"""IIS-Rio BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/iis_rio.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="iis_rio")`` for
download / OCR / submit.

The IIS-Rio source fans out across up to 10 paginated listing pages
at ``https://www.iis-rio.org/noticias/`` (subsequent pages use
``?tipo-de-noticia=noticia&paged=N``). Detail-page URLs match
``/noticias/<slug>`` on the listing host and require one of the signal
tokens (``edital``, ``chamada``, ``consultoria``, ``tdr``). Each
detail page is then fetched via
``scraper_transport.discover_pdf_urls_on_page`` to enumerate the
PDF anchors hosted on it.

Filter pipeline (per plan §9):
- ``IIS_RIO_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
  extracted year is older than the threshold. URLs without a
  discoverable year pass through with no extracted_year (recorded in
  the candidate metadata so operators can audit it).
- ``scraper_filters.is_likely_edital`` with
  ``filter_policy="include_tdr"`` keeps ``termo-de-referencia``
  filenames (the default policy would drop them). This matches the
  FastAPI source's behaviour (``ctx.ingest_pdf_url(...,
  filter_policy="include_tdr")``).

Message shape matches the existing PNCP contract so the Render submit
endpoint can ingest it unchanged.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    discover_pdf_urls_on_page,
    log_source_failure,
    looks_like_pdf_url,
)


IIS_RIO_LISTING_URL = "https://www.iis-rio.org/noticias/"
IIS_RIO_MAX_PAGES = 10

IIS_RIO_MIN_NOTICE_YEAR = int(os.environ.get("IIS_RIO_MIN_NOTICE_YEAR", "2026"))

IIS_RIO_MAX_CANDIDATES_PER_RUN = int(os.environ.get("IIS_RIO_MAX_CANDIDATES_PER_RUN", "50"))
IIS_RIO_MAX_DETAILS_PER_RUN = int(os.environ.get("IIS_RIO_MAX_DETAILS_PER_RUN", "30"))
IIS_RIO_FETCH_MAX_ATTEMPTS = int(os.environ.get("IIS_RIO_FETCH_MAX_ATTEMPTS", "3"))
IIS_RIO_FETCH_BACKOFF_SECONDS = float(os.environ.get("IIS_RIO_FETCH_BACKOFF_SECONDS", "2"))
IIS_RIO_FETCH_TIMEOUT_SECONDS = int(os.environ.get("IIS_RIO_FETCH_TIMEOUT_SECONDS", "30"))


# Matches a 4-digit year token bounded by non-digit boundaries.
_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _extract_year_from_url(url: str) -> int | None:
    """Return the first 4-digit year found in the URL, or ``None``.

    Searches the URL path and query string for any year in the 1900-2099
    range. Returns the most recent year if multiple are present.
    """
    parsed = urlsplit(url)
    haystack = f"{parsed.path} {parsed.query}"
    candidates: list[int] = []
    for match in _YEAR_PATTERN.finditer(haystack):
        year = int(match.group(0))
        if 1900 <= year <= 2099:
            candidates.append(year)
    if not candidates:
        return None
    return max(candidates)


def _passes_year_guard(url: str, *, min_year: int) -> bool:
    """Apply the IIS-Rio year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_iis_rio_detail_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover detail-page URLs from an IIS-Rio listing page.

    Verbatim port of ``extract_iis_rio_detail_urls`` from the FastAPI
    repo. The extractor matches same-host anchors whose path starts
    with ``/noticias/`` (single slug segment), then requires one of
    the IIS-Rio signal tokens (``edital``, ``chamada``,
    ``consultoria``, ``tdr``) in the href/path/text/title/aria-label.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(r"\b(edital|chamada|consultoria|tdr)\b", re.IGNORECASE)

    def _normalize_host(host: str) -> str:
        normalized = host.lower()
        if normalized.startswith("www."):
            return normalized[4:]
        return normalized

    listing_parts = urlsplit(listing_url)
    listing_host = _normalize_host(listing_parts.hostname or "")
    listing_scheme = listing_parts.scheme
    listing_netloc = listing_parts.netloc

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)

        if _normalize_host(normalized.hostname or "") != listing_host:
            continue

        path = normalized.path.rstrip("/")
        if not path.startswith("/noticias/"):
            continue
        if not re.fullmatch(r"/noticias/[^/]+", path):
            continue

        signal_text = " ".join(
            [
                href,
                path,
                link.get_text(" ", strip=True),
                str(link.get("title") or ""),
                str(link.get("aria-label") or ""),
            ]
        )
        if not signal_pattern.search(signal_text):
            continue

        canonical = urlunsplit((listing_scheme, listing_netloc, path, "", ""))
        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def _candidate_passes_edital_prefilter(
    url: str, filter_policy: FilterPolicy = "include_tdr",
) -> bool:
    """Apply the EDITAL inclusion/exclusion patterns to a candidate URL.

    The IIS-Rio source uses ``filter_policy="include_tdr"`` because the
    default policy excludes ``termo-de-referencia`` filenames, and TDRs
    are a valid edital document type for this source.
    """
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    return is_likely_edital(filename, url, filter_policy=filter_policy)


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    filter_policy: FilterPolicy = "include_tdr",
    min_year: int = IIS_RIO_MIN_NOTICE_YEAR,
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
        "source": "iis_rio",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def _page_url_for(page_num: int) -> str:
    """Return the IIS-Rio listing URL for ``page_num`` (1-indexed)."""
    if page_num == 1:
        return IIS_RIO_LISTING_URL
    return f"{IIS_RIO_LISTING_URL}?tipo-de-noticia=noticia&paged={page_num}"


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "include_tdr",
    min_year: int = IIS_RIO_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover IIS-Rio edital PDF candidates from the paginated listing.

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
    seen_details: set[str] = set()
    details_fetched = 0

    from scraper_transport import request_with_safe_redirects

    all_detail_urls: list[str] = []
    for page_num in range(1, IIS_RIO_MAX_PAGES + 1):
        page_url = _page_url_for(page_num)
        try:
            response = request_with_safe_redirects(
                method="GET", url=page_url, timeout=IIS_RIO_FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            listing_html = response.text
        except Exception as exc:
            log_source_failure(
                "Failed to fetch IIS-Rio listing page %s: %s",
                page_url,
                exc,
                exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            if page_num == 1:
                return stats, candidates
            break

        stats["listings_fetched"] += 1
        page_detail_urls = extract_iis_rio_detail_urls(listing_html, page_url)

        new_urls = [u for u in page_detail_urls if u not in seen_details]
        if not new_urls and page_num > 1:
            break

        for url in new_urls:
            seen_details.add(url)
            all_detail_urls.append(url)

    for detail_url in all_detail_urls:
        if details_fetched >= IIS_RIO_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {IIS_RIO_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            detail_pdfs = discover_pdf_urls_on_page(detail_url, stats=stats)
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on IIS-Rio detail %s: %s",
                detail_url,
                exc,
                exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        details_fetched += 1
        stats["details_fetched"] += 1
        for pdf_url in detail_pdfs:
            if pdf_url in seen_pdfs:
                continue
            seen_pdfs.add(pdf_url)
            candidate = build_candidate(
                pdf_url,
                listing_url=IIS_RIO_LISTING_URL,
                detail_url=detail_url,
                filter_policy=filter_policy,
                min_year=min_year,
                origin="detail_page",
            )
            if candidate is None:
                if not _passes_year_guard(pdf_url, min_year=min_year):
                    stats["year_rejected"] += 1
                else:
                    stats["prefilter_rejected"] += 1
                continue
            candidates.append(candidate)
            if len(candidates) >= IIS_RIO_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {IIS_RIO_MAX_CANDIDATES_PER_RUN}",
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
    print(f"IIS-Rio discovery stats: {stats}")
    print(f"IIS-Rio candidates discovered: {len(candidates)}")

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
    print(f"IIS-Rio processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered IIS-Rio candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="iis_rio")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered IIS-Rio candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())