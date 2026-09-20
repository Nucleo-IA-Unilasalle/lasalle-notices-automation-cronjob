"""SEMA-RS BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/sema_rs.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="sema_rs")`` for
download / OCR / submit.

SEMA-RS exposes two ways to enumerate edital URLs:

1. The JSON-backed AJAX endpoint at
   ``https://www.sema.rs.gov.br/busca/lista-data-table`` that returns
   a ``{"body": "<html>...</html>", "pagecount": N}`` envelope. Two
   keywords are swept: ``edital`` and ``chamada``. The endpoint is a
   full-text search whose early pages can contain many articles with
   no signal-matched anchors, so pagination must not stop on the
   first page without matches. The discoverer stops when (a) the
   reported ``pagecount`` is reached, (b) a page contains no article
   items at all (end of results), (c) no new URLs are seen for
   ``MAX_STALE_PAGES`` pages in a row, (d) three consecutive fetch
   failures are observed, or (e) the per-keyword cap
   (``MAX_SEMA_RS_PAGES``) is reached.
2. A static service page at ``https://www.sema.rs.gov.br/residuos-solidos``
   whose PDF anchors are enumerated with a source-local extractor:
   same-host anchors only, an edital-signal token in the anchor
   context, and panels that also carry a closure marker (for example
   "Resultado Final") are skipped as concluded calls.

Detail pages are fetched via ``scraper_transport.discover_pdf_urls_on_page``
to enumerate the PDF anchors hosted on them.

Filter pipeline (per plan §9):
- ``SEMA_RS_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
  extracted year is older than the threshold. URLs without a
  discoverable year pass through with no extracted_year (recorded in
  the candidate metadata so operators can audit it).
- ``scraper_filters.is_likely_edital`` drops URLs whose filename
  matches an EDITAL exclusion pattern. ``filter_policy="default"``
  matches the FastAPI source's behaviour.

Message shape matches the existing PNCP contract so the Render submit
endpoint can ingest it unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
import scraper_transport
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    DEFAULT_HEADERS,
    discover_pdf_urls_on_page,
    log_source_failure,
    looks_like_pdf_url,
)


logger = logging.getLogger(__name__)


SEMA_RS_LISTING_ORIGIN = "https://www.sema.rs.gov.br"
SEMA_RS_LISTING_URL_TEMPLATE = (
    "https://www.sema.rs.gov.br/busca/lista-data-table"
    "?currentPage={current_page}&pageSize=20"
    "&form%5Bpalavraschave%5D={keyword}"
    "&form%5Bordem%5D=RECENTES"
)
SEMA_RS_STATIC_SERVICE_PAGES: tuple[str, ...] = (
    "https://www.sema.rs.gov.br/residuos-solidos",
)

SEMA_RS_KEYWORDS: tuple[str, ...] = ("edital", "chamada")
SEMA_RS_MAX_PAGES_PER_KEYWORD = 200
SEMA_RS_MAX_STALE_PAGES = 5

SEMA_RS_MIN_NOTICE_YEAR = int(os.environ.get("SEMA_RS_MIN_NOTICE_YEAR", "2026"))

SEMA_RS_MAX_CANDIDATES_PER_RUN = int(os.environ.get("SEMA_RS_MAX_CANDIDATES_PER_RUN", "50"))
SEMA_RS_MAX_DETAILS_PER_RUN = int(os.environ.get("SEMA_RS_MAX_DETAILS_PER_RUN", "40"))
SEMA_RS_FETCH_MAX_ATTEMPTS = int(os.environ.get("SEMA_RS_FETCH_MAX_ATTEMPTS", "3"))
SEMA_RS_FETCH_BACKOFF_SECONDS = float(os.environ.get("SEMA_RS_FETCH_BACKOFF_SECONDS", "2"))
SEMA_RS_FETCH_TIMEOUT_SECONDS = int(os.environ.get("SEMA_RS_FETCH_TIMEOUT_SECONDS", "30"))


# Matches a 4-digit year token bounded by non-digit boundaries.
_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
# Matches a ``/YYYYMM/`` upload-folder segment (SEMA-RS stores PDFs under
# ``/upload/arquivos/202605/...``); the folder year is authoritative even
# when the filename carries no year token.
_UPLOAD_MONTH_PATTERN = re.compile(r"/((?:19|20)\d{2})(0[1-9]|1[0-2])/")
# Concluded-call markers used by static service-page panels (for example
# the Comunidade de Prática panel lists "Resultado Final" next to the
# edital PDF once the selection has finished).
_CLOSURE_MARKER_PATTERN = re.compile(r"resultado\s*final|encerrad", re.IGNORECASE)
# Shared signal tokens for SEMA-RS anchors (detail listings and static
# service pages alike).
_SIGNAL_PATTERN = re.compile(r"\b(edital|chamada|chamamento)\b", re.IGNORECASE)


def _extract_year_from_url(url: str) -> int | None:
    """Return the most recent year discoverable in the URL, or ``None``.

    Scans the percent-decoded path and query for any 4-digit year in the
    1900-2099 range (decoding first prevents ``%2009.921``-style false
    matches across percent-encoding boundaries) and also recognises
    ``/YYYYMM/`` upload-folder segments.
    """
    decoded = unquote(url)
    parsed = urlsplit(decoded)
    haystack = f"{parsed.path} {parsed.query}"
    candidates: list[int] = []
    for match in _YEAR_PATTERN.finditer(haystack):
        year = int(match.group(0))
        if 1900 <= year <= 2099:
            candidates.append(year)
    for match in _UPLOAD_MONTH_PATTERN.finditer(parsed.path):
        candidates.append(int(match.group(1)))
    if not candidates:
        return None
    return max(candidates)


def _passes_year_guard(url: str, *, min_year: int) -> bool:
    """Apply the SEMA-RS year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_sema_rs_detail_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover detail-page URLs from a SEMA-RS listing HTML fragment.

    Verbatim port of ``extract_sema_rs_detail_urls`` from the FastAPI
    repo. The extractor matches same-host anchors whose href / text /
    title / aria-label contains one of the SEMA-RS signal tokens
    (``edital``, ``chamada``, ``chamamento``) and dedupes canonicalised
    URLs. Direct PDF anchors are skipped.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = _SIGNAL_PATTERN
    listing_host = (urlsplit(listing_url).hostname or "").lower()

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        signal_text = " ".join(
            [
                href,
                link.get_text(" ", strip=True),
                str(link.get("title") or ""),
                str(link.get("aria-label") or ""),
            ]
        )
        if not signal_pattern.search(signal_text):
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        if (normalized.hostname or "").lower() != listing_host:
            continue

        canonical = urlunsplit(
            (
                normalized.scheme,
                normalized.netloc,
                normalized.path.rstrip("/"),
                normalized.query,
                "",
            )
        )

        if not canonical:
            continue
        if looks_like_pdf_url(canonical):
            continue
        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def extract_static_service_pdf_urls(page_html: str, page_url: str) -> list[str]:
    """Discover edital PDF anchors on a SEMA-RS static service page.

    The residuos-solidos page mixes call documents with guidance reports
    and off-host statute PDFs. Only same-host PDF anchors whose
    href / text / title / aria-label carries a SEMA-RS signal token are
    kept, and anchors inside a panel that also contains a closure marker
    ("Resultado Final" / "encerrad…") are skipped as concluded calls.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    return _extract_static_service_pdf_urls_from_soup(soup, page_url)


def _extract_static_service_pdf_urls_from_soup(
    soup: BeautifulSoup, page_url: str,
) -> list[str]:
    page_host = (urlsplit(page_url).hostname or "").lower()
    discovered: list[str] = []
    seen: set[str] = set()

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(page_url, href)
        normalized = urlsplit(resolved)
        if (normalized.hostname or "").lower() != page_host:
            continue
        if not looks_like_pdf_url(resolved):
            continue

        signal_text = " ".join(
            [
                href,
                link.get_text(" ", strip=True),
                str(link.get("title") or ""),
                str(link.get("aria-label") or ""),
            ]
        )
        if not _SIGNAL_PATTERN.search(signal_text):
            continue

        # Skip concluded calls: if the enclosing panel also advertises a
        # final result / closed period, the edital is no longer open.
        panel = link.find_parent("div", class_="panel-body")
        if panel is not None and _CLOSURE_MARKER_PATTERN.search(
            panel.get_text(" ", strip=True),
        ):
            continue

        canonical = urlunsplit(
            (
                normalized.scheme,
                normalized.netloc,
                normalized.path,
                normalized.query,
                "",
            )
        )
        if canonical in seen:
            continue
        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def _listing_body_has_articles(listing_html: str) -> bool:
    """Whether a listing body fragment contains result articles.

    The AJAX endpoint returns a short "Nenhuma informação a ser exibida."
    placeholder body once results are exhausted; article-bearing pages
    (even ones whose anchors carry no signal tokens) are not the end of
    the listing.
    """
    return "<article" in listing_html


def _candidate_passes_edital_prefilter(
    url: str, filter_policy: FilterPolicy = "default",
) -> bool:
    """Apply the EDITAL inclusion/exclusion patterns to a candidate URL."""
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    return is_likely_edital(filename, url, filter_policy=filter_policy)


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    filter_policy: FilterPolicy = "default",
    min_year: int = SEMA_RS_MIN_NOTICE_YEAR,
    origin: str | None = None,
) -> dict[str, Any] | None:
    """Build a ``kind="pdf"`` candidate or return ``None`` if filtered out."""
    if not _passes_year_guard(url, min_year=min_year):
        return None
    if not _candidate_passes_edital_prefilter(url, filter_policy=filter_policy):
        return None

    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "detail_page"

    extracted_year = _extract_year_from_url(url)
    if extracted_year is None and detail_url:
        extracted_year = _extract_year_from_url(detail_url)

    metadata: dict[str, Any] = {
        "source": "sema_rs",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def _fetch_keyword_listing_html(
    keyword: str, current_page: int, *, stats: dict[str, int],
) -> tuple[str, int | None] | None:
    """Fetch a SEMA-RS JSON listing page for ``keyword``.

    Returns ``(body_html, pagecount)`` where ``pagecount`` is the
    server-reported total page count (or ``None`` when absent), or
    ``None`` if every retry attempt fails (caller is expected to count
    failures).
    """
    url = SEMA_RS_LISTING_URL_TEMPLATE.format(current_page=current_page, keyword=keyword)
    last_error: Exception | None = None
    for attempt in range(SEMA_RS_FETCH_MAX_ATTEMPTS):
        try:
            response = scraper_transport.request_with_safe_redirects(
                method="GET",
                url=url,
                timeout=SEMA_RS_FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            body = payload.get("body", "") if isinstance(payload, dict) else ""
            raw_pagecount = payload.get("pagecount") if isinstance(payload, dict) else None
            pagecount = raw_pagecount if isinstance(raw_pagecount, int) else None
            return (body if isinstance(body, str) else "", pagecount)
        except Exception as exc:
            last_error = exc
            if attempt < SEMA_RS_FETCH_MAX_ATTEMPTS - 1:
                wait = SEMA_RS_FETCH_BACKOFF_SECONDS ** attempt
                logger.warning(
                    "Retrying SEMA-RS page %s for keyword '%s' in %ss (attempt %s/%s): %s",
                    current_page,
                    keyword,
                    wait,
                    attempt + 1,
                    SEMA_RS_FETCH_MAX_ATTEMPTS,
                    exc,
                )
                time.sleep(wait)
            else:
                log_source_failure(
                    "Error while paginating SEMA-RS listings for keyword '%s' at page %s after %s attempts: %s",
                    keyword,
                    current_page,
                    SEMA_RS_FETCH_MAX_ATTEMPTS,
                    exc,
                    exc=exc,
                )
                stats["errors"] = stats.get("errors", 0) + 1
    _ = last_error
    return None


def _paginate_keyword(
    keyword: str,
    *,
    seen_detail_urls: set[str],
    detail_urls_out: list[str],
    stats: dict[str, int],
) -> bool:
    """Paginate the SEMA-RS listing for ``keyword``.

    Returns ``True`` if pagination yielded at least one detail URL for
    this keyword, otherwise ``False``. The AJAX endpoint is a full-text
    search: early pages can carry many articles whose anchors do not
    contain the signal tokens, so an empty extraction is not the end of
    the listing. Stops when the server-reported ``pagecount`` is
    exhausted, when a page carries no article items at all, on stale
    pages, on consecutive failures, or when
    ``SEMA_RS_MAX_PAGES_PER_KEYWORD`` is reached.
    """
    current_page = 1
    stale_pages = 0
    consecutive_failures = 0
    known_pagecount: int | None = None
    yielded_details = False

    while True:
        if current_page > SEMA_RS_MAX_PAGES_PER_KEYWORD:
            logger.warning(
                "Stopping SEMA-RS pagination after exceeding max pages (%s)",
                SEMA_RS_MAX_PAGES_PER_KEYWORD,
            )
            break
        if known_pagecount is not None and current_page > known_pagecount:
            break

        fetched = _fetch_keyword_listing_html(keyword, current_page, stats=stats)
        if fetched is None:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.warning(
                    "Stopping SEMA-RS pagination after %s consecutive failures",
                    consecutive_failures,
                )
                break
            current_page += 1
            continue

        consecutive_failures = 0
        listing_html, pagecount = fetched
        if pagecount is not None:
            known_pagecount = pagecount
        if not listing_html:
            listing_html = ""

        # End of results: the endpoint returns a placeholder body with no
        # article items once pages are exhausted.
        if not _listing_body_has_articles(listing_html):
            break

        page_detail_urls = extract_sema_rs_detail_urls(listing_html, SEMA_RS_LISTING_ORIGIN)

        new_detail_urls: list[str] = []
        for detail_url in page_detail_urls:
            if detail_url in seen_detail_urls:
                continue
            seen_detail_urls.add(detail_url)
            new_detail_urls.append(detail_url)

        if new_detail_urls:
            stale_pages = 0
            detail_urls_out.extend(new_detail_urls)
            yielded_details = True
        else:
            stale_pages += 1
            if stale_pages >= SEMA_RS_MAX_STALE_PAGES:
                logger.warning(
                    "Stopping SEMA-RS pagination after %s stale pages",
                    stale_pages,
                )
                break

        current_page += 1

    return yielded_details


def _ingest_pdfs(
    pdf_urls: list[str],
    *,
    listing_url: str,
    detail_url: str | None,
    origin: str,
    stats: dict[str, int],
    candidates: list[dict[str, Any]],
    seen_pdfs: set[str],
    filter_policy: FilterPolicy,
    min_year: int,
) -> None:
    for pdf_url in pdf_urls:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
        candidate = build_candidate(
            pdf_url,
            listing_url=listing_url,
            detail_url=detail_url,
            filter_policy=filter_policy,
            min_year=min_year,
            origin=origin,
        )
        if candidate is None:
            if not _passes_year_guard(pdf_url, min_year=min_year):
                stats["year_rejected"] += 1
            else:
                stats["prefilter_rejected"] += 1
            continue
        candidates.append(candidate)


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = SEMA_RS_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover SEMA-RS edital PDF candidates.

    Returns ``(stats, candidates)``.
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "prefilter_rejected": 0,
        "year_rejected": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
    }
    candidates: list[dict[str, Any]] = []
    seen_pdfs: set[str] = set()
    seen_detail_urls: set[str] = set()
    all_detail_urls: list[str] = []

    for keyword in SEMA_RS_KEYWORDS:
        yielded = _paginate_keyword(
            keyword,
            seen_detail_urls=seen_detail_urls,
            detail_urls_out=all_detail_urls,
            stats=stats,
        )
        if yielded:
            stats["listings_fetched"] += 1

    details_fetched = 0
    for detail_url in all_detail_urls:
        if details_fetched >= SEMA_RS_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {SEMA_RS_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            detail_pdfs = discover_pdf_urls_on_page(detail_url, stats=stats)
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on SEMA-RS detail %s: %s",
                detail_url,
                exc,
                exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        details_fetched += 1
        stats["details_fetched"] += 1
        _ingest_pdfs(
            detail_pdfs,
            listing_url=SEMA_RS_LISTING_ORIGIN,
            detail_url=detail_url,
            origin="detail_page",
            stats=stats,
            candidates=candidates,
            seen_pdfs=seen_pdfs,
            filter_policy=filter_policy,
            min_year=min_year,
        )
        if len(candidates) >= SEMA_RS_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {SEMA_RS_MAX_CANDIDATES_PER_RUN}",
                file=sys.stderr,
            )
            stats["candidates"] = len(candidates)
            return stats, candidates

    for static_page_url in SEMA_RS_STATIC_SERVICE_PAGES:
        try:
            static_pdfs = discover_pdf_urls_on_page(
                static_page_url,
                stats=stats,
                extractor=_extract_static_service_pdf_urls_from_soup,
            )
        except Exception as exc:
            log_source_failure(
                "Failed to fetch SEMA-RS static page %s: %s",
                static_page_url,
                exc,
                exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        stats["details_fetched"] += 1
        _ingest_pdfs(
            static_pdfs,
            listing_url=static_page_url,
            detail_url=None,
            origin="listing_pdf",
            stats=stats,
            candidates=candidates,
            seen_pdfs=seen_pdfs,
            filter_policy=filter_policy,
            min_year=min_year,
        )
        if len(candidates) >= SEMA_RS_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {SEMA_RS_MAX_CANDIDATES_PER_RUN}",
                file=sys.stderr,
            )
            stats["candidates"] = len(candidates)
            return stats, candidates

    stats["candidates"] = len(candidates)
    return stats, candidates


def main() -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"SEMA-RS discovery stats: {stats}")
    print(f"SEMA-RS candidates discovered: {len(candidates)}")

    if not candidates:
        print("No new candidates to submit")
        return 0

    _ocr_config, extractor = pipeline_core.make_default_ocr_extractor()
    max_pdf_bytes = pipeline_core.SCRAPE_MAX_PDF_BYTES

    processed: list[dict[str, Any]] = []
    for candidate in candidates:
        if pipeline_core.pdf_download_limit_reached(stats):
            stats["pdf_download_cap_reached"] = 1
            print(
                f"Stopping after PDF download cap {pipeline_core.SCRAPE_MAX_PDFS_PER_RUN}",
                file=sys.stderr,
            )
            break

        result = pipeline_core.process_candidate(
            candidate,
            extractor=extractor,
            max_bytes=max_pdf_bytes,
        )
        processed.append(result)
        if result.get("worker_result"):
            pipeline_core.record_pdf_download(stats)

    stats["processed"] = len(processed)
    stats["ocr_successes"] = sum(1 for r in processed if r.get("worker_result"))
    stats["ocr_failures"] = sum(1 for r in processed if r.get("error"))
    print(f"SEMA-RS processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered SEMA-RS candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="sema_rs")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered SEMA-RS candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())