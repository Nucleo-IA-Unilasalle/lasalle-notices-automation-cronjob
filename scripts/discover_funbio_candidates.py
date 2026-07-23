"""FUNBIO BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/funbio.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="funbio")`` for
download / OCR / submit.

The FUNBIO listing at ``https://chamadas.funbio.org.br/`` carries
same-host anchors to detail pages (e.g. ``/floresta-viva-piaui``) that
match one of the signal tokens (``chamada``, ``projeto``, ``edital``,
``floresta``, ``selecao``). Each detail page is then fetched via
``scraper_transport.discover_pdf_urls_on_page`` with a custom
``extract_funbio_pdf_urls`` helper that recognises FUNBIO's two
document conventions:

1. ``/download/regulamento?id=...`` anchors that resolve to the
   regulation PDF.
2. Direct ``.pdf`` anchors whose text/path matches the same signal
   tokens.

Documents whose anchor carries the privacy/politica/cookie blocks are
ignored.

Filter pipeline (per plan §9):
- ``FUNBIO_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
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
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)
from discover_funbio_news_leads import (
    FUNBIO_NEWS_URL,
    parse_news_inventory,
    resolve_news_leads,
)


FUNBIO_LISTING_URL = "https://chamadas.funbio.org.br/"

FUNBIO_MIN_NOTICE_YEAR = int(os.environ.get("FUNBIO_MIN_NOTICE_YEAR", "2026"))

FUNBIO_MAX_CANDIDATES_PER_RUN = int(os.environ.get("FUNBIO_MAX_CANDIDATES_PER_RUN", "50"))
FUNBIO_MAX_DETAILS_PER_RUN = int(os.environ.get("FUNBIO_MAX_DETAILS_PER_RUN", "20"))
FUNBIO_FETCH_MAX_ATTEMPTS = int(os.environ.get("FUNBIO_FETCH_MAX_ATTEMPTS", "3"))
FUNBIO_FETCH_BACKOFF_SECONDS = float(os.environ.get("FUNBIO_FETCH_BACKOFF_SECONDS", "2"))
FUNBIO_FETCH_TIMEOUT_SECONDS = int(os.environ.get("FUNBIO_FETCH_TIMEOUT_SECONDS", "30"))
FUNBIO_NEWS_ENABLED = os.environ.get("FUNBIO_NEWS_ENABLED", "false").lower() == "true"


# Matches a 4-digit year token bounded by non-digit boundaries. The
# FUNBIO detail paths typically carry the year in English
# (``/floresta-viva-piaui`` doesn't, but ``/edital-2026-...`` does),
# so this regex is sufficient for FUNBIO today.
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
    """Apply the FUNBIO year guard per plan §9.

    URLs without a discoverable year pass through (recorded in
    candidate metadata for operator audit). URLs with a year older
    than ``min_year`` are rejected.
    """
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_funbio_detail_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover detail-page URLs from the FUNBIO listing HTML.

    Verbatim port of ``extract_funbio_detail_urls`` from the FastAPI
    repo. The extractor matches anchors whose path conforms to
    ``/<slug>`` (single segment) on the listing host, filters out a
    blocklist of well-known paths, and requires one of the FUNBIO
    signal tokens (``chamada``, ``projeto``, ``edital``, ``floresta``,
    ``selecao``) in the href/text/title/aria-label.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    listing_host = (urlsplit(listing_url).hostname or "").lower()
    blocked_paths = {
        "", "/", "/calendario-chamadas", "/noticias", "/quem-somos", "/receba-informacoes",
    }

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        if (normalized.hostname or "").lower() != listing_host:
            continue

        path = normalized.path.rstrip("/")
        if not re.fullmatch(r"/[a-z0-9-]+", path):
            continue
        if path in blocked_paths:
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
        if not re.search(r"\b(chamada|projeto|edital|floresta|selecao)\b", signal_text, re.IGNORECASE):
            continue

        canonical = urlunsplit((normalized.scheme, normalized.netloc, path, "", ""))
        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def extract_funbio_pdf_urls(soup: BeautifulSoup, _page_url: str) -> list[str]:
    """Extract FUNBIO PDF anchors from a detail page.

    Verbatim port of ``extract_funbio_pdf_urls`` from the FastAPI
    repo. Returns ``/download/regulamento`` anchors as-is and adds
    direct ``.pdf`` anchors whose text/path matches the signal
    pattern (``regulamento``, ``edital``, ``chamada``, ``anexo``,
    ``termo``). Privacy / politica / cookie anchors are blocked.
    """
    discovered: list[str] = []
    signal_pattern = re.compile(r"\b(regulamento|edital|chamada|anexo|termo)\b", re.IGNORECASE)
    blocked_pattern = re.compile(r"\b(privacidade|politica|cookie)\b", re.IGNORECASE)

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        href_lower = href.lower()
        text = link.get_text(" ", strip=True)
        signal_text = " ".join(
            [
                href,
                text,
                str(link.get("title") or ""),
                str(link.get("aria-label") or ""),
            ]
        )

        if blocked_pattern.search(signal_text):
            continue

        if "/download/regulamento" in href_lower:
            discovered.append(href)
            continue

        if looks_like_pdf_url(href) and signal_pattern.search(signal_text):
            discovered.append(href)

    return discovered


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
    min_year: int = FUNBIO_MIN_NOTICE_YEAR,
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
        "source": "funbio",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = FUNBIO_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover FUNBIO edital PDF candidates from the listing + detail pages.

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
    details_fetched = 0

    from scraper_transport import fetch_html_with_retry

    try:
        listing_html = fetch_html_with_retry(
            FUNBIO_LISTING_URL,
            timeout=FUNBIO_FETCH_TIMEOUT_SECONDS,
            max_attempts=FUNBIO_FETCH_MAX_ATTEMPTS,
            backoff_seconds=FUNBIO_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch FUNBIO listing %s: %s",
            FUNBIO_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates

    detail_urls = extract_funbio_detail_urls(listing_html, FUNBIO_LISTING_URL)

    for detail_url in detail_urls:
        if details_fetched >= FUNBIO_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {FUNBIO_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            detail_pdfs = discover_pdf_urls_on_page(
                detail_url,
                stats=stats,
                extractor=extract_funbio_pdf_urls,
            )
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on FUNBIO detail %s: %s",
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
                listing_url=FUNBIO_LISTING_URL,
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
            if len(candidates) >= FUNBIO_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {FUNBIO_MAX_CANDIDATES_PER_RUN}",
                    file=sys.stderr,
                )
                stats["candidates"] = len(candidates)
                return stats, candidates

    stats["candidates"] = len(candidates)
    return stats, candidates


def parse_funbio_opportunity(
    detail_url: str,
    detail_html: str,
    *,
    snapshot_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Build a canonical call record; news text never supplies these fields."""
    soup = BeautifulSoup(detail_html, "html.parser")
    content = soup.select_one("main, #content-core, article")
    if content is None:
        next_root = soup.select_one("#__next")
        heading = next_root.find("h1") if isinstance(next_root, Tag) else None
        if isinstance(heading, Tag):
            content = heading
            while (
                isinstance(content.parent, Tag)
                and content.parent is not next_root
            ):
                content = content.parent
    if content is None:
        return None
    heading = content.find(["h1", "h2"])
    title = heading.get_text(" ", strip=True) if isinstance(heading, Tag) else ""
    text = re.sub(r"\s+", " ", content.get_text(" ", strip=True)).strip()
    if not title or not text:
        return None
    deadline = None
    deadline_match = re.search(
        r"(?:at[eé]|prazo|aberta\s+at[eé]).{0,50}?(\d{2}/\d{2}/\d{4})",
        text,
        re.I,
    )
    if deadline_match:
        deadline = datetime.strptime(deadline_match.group(1), "%d/%m/%Y").replace(
            hour=23, minute=59, tzinfo=timezone.utc
        )
    now = datetime.now(timezone.utc)
    status = "open" if deadline and deadline >= now else ("closed" if deadline else "unknown")
    documents = []
    for index, href in enumerate(extract_funbio_pdf_urls(BeautifulSoup(detail_html, "html.parser"), detail_url), start=1):
        url = urljoin(detail_url, href)
        documents.append(
            {
                "source_document_id": str(index),
                "document_kind": "pdf",
                "url": url,
                "filename": urlsplit(url).path.rsplit("/", 1)[-1] or "regulamento.pdf",
                "mime_type": "application/pdf",
                "is_principal": False,
                "is_renderable": False,
            }
        )
    canonical = urlunsplit((*urlsplit(detail_url)[:3], "", ""))
    source_record_id = urlsplit(canonical).path.strip("/")
    markdown = f"# {title}\n\n## Fonte oficial\n\n{canonical}\n\n## Conteudo\n\n{text}"
    snapshot = snapshot_at or datetime.now(timezone.utc)
    return {
        "source_key": "funbio",
        "source_record_id": source_record_id,
        "source_kind": "web",
        "opportunity_type": "funding",
        "canonical_url": canonical,
        "title": title,
        "description": text,
        "authoritative_status": status,
        "source_published_at": None,
        "source_updated_at": None,
        "proposal_opens_at": None,
        "application_deadline": deadline.isoformat() if deadline else None,
        "source_snapshot_at": snapshot.astimezone(timezone.utc).isoformat(),
        "source_markdown": markdown,
        "source_content_hash": "",
        "documents": documents,
    }


def discover_opportunities(
    *,
    fetch_html: Any = None,
    snapshot_at: datetime | None = None,
    include_news: bool = FUNBIO_NEWS_ENABLED,
    min_year: int | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover canonical calls and optionally resolve the bounded news feed."""
    del min_year
    fetch = fetch_html or (
        lambda url: fetch_html_with_retry(
            url,
            timeout=FUNBIO_FETCH_TIMEOUT_SECONDS,
            max_attempts=FUNBIO_FETCH_MAX_ATTEMPTS,
            backoff_seconds=FUNBIO_FETCH_BACKOFF_SECONDS,
        )
    )
    listing_html = fetch(FUNBIO_LISTING_URL)
    detail_urls = extract_funbio_detail_urls(listing_html, FUNBIO_LISTING_URL)
    if not detail_urls:
        return {"inventory_parse_failed": 1, "records": 0, "opportunities": 0}, []
    opportunities: list[dict[str, Any]] = []
    errors = 0
    for detail_url in detail_urls[:FUNBIO_MAX_DETAILS_PER_RUN]:
        try:
            parsed = parse_funbio_opportunity(
                detail_url, fetch(detail_url), snapshot_at=snapshot_at
            )
        except Exception:
            parsed = None
        if parsed is None:
            errors += 1
        else:
            opportunities.append(parsed)

    resolutions: list[dict[str, Any]] = []
    if include_news:
        news = parse_news_inventory(fetch(FUNBIO_NEWS_URL))
        resolutions = resolve_news_leads(news, opportunities)
        by_id = {item["source_record_id"]: item for item in opportunities}
        for resolution in resolutions:
            if resolution["resolution"] == "resolved":
                target = by_id.get(resolution["source_record_id"])
                if target is not None:
                    target.setdefault("_related_news", []).append(
                        resolution["article_url"]
                    )
            elif resolution["resolution"] == "explicit_new_call":
                canonical = resolution["canonical_url"]
                if canonical in {item["canonical_url"] for item in opportunities}:
                    continue
                try:
                    parsed = parse_funbio_opportunity(
                        canonical, fetch(canonical), snapshot_at=snapshot_at
                    )
                except Exception:
                    parsed = None
                if parsed is not None:
                    parsed["_related_news"] = [resolution["article_url"]]
                    opportunities.append(parsed)
    return {
        "records": len(detail_urls),
        "opportunities": len(opportunities),
        "errors": errors,
        "news_resolved": sum(
            item["resolution"] == "resolved" for item in resolutions
        ),
        "news_unresolved": sum(
            item["resolution"] == "unresolved_lead" for item in resolutions
        ),
    }, opportunities


def main() -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"FUNBIO discovery stats: {stats}")
    print(f"FUNBIO candidates discovered: {len(candidates)}")

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
    print(f"FUNBIO processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered FUNBIO candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="funbio")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered FUNBIO candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
