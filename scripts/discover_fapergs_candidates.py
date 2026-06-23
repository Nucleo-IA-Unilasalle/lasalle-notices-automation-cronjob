"""FAPERGS BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/fapergs.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="fapergs")`` for
download / OCR / submit.

FAPERGS exposes two ways to enumerate edital URLs:

1. The static listing at
   ``https://fapergs.rs.gov.br/abertos?classificacao=3242`` (HTML
   anchors to detail pages).
2. An AJAX endpoint at
   ``https://fapergs.rs.gov.br/_service/conteudo/pagedlistfilho?id=2042&currentPage=1&pageSize=50``
   that returns a JSON ``body`` HTML fragment with additional detail
   anchors. The AJAX call is best-effort: a failure is logged at
   DEBUG and the discoverer falls back to the static listing.

Detail pages are fetched via ``scraper_transport.discover_pdf_urls_on_page``
to enumerate PDF anchors.

Filter pipeline (per plan §9):
- ``FAPERGS_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
  extracted year is older than the threshold. URLs without a
  discoverable year pass through with no extracted_year (recorded
  in the candidate metadata so operators can audit it).
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
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    DEFAULT_HEADERS,
    discover_pdf_urls_on_page,
    log_source_failure,
    looks_like_pdf_url,
)


logger = logging.getLogger(__name__)


FAPERGS_LISTING_URL = "https://fapergs.rs.gov.br/abertos?classificacao=3242"
FAPERGS_AJAX_URL = (
    "https://fapergs.rs.gov.br/_service/conteudo/pagedlistfilho"
    "?id=2042&currentPage=1&pageSize=50"
)

FAPERGS_MIN_NOTICE_YEAR = int(os.environ.get("FAPERGS_MIN_NOTICE_YEAR", "2026"))

FAPERGS_MAX_CANDIDATES_PER_RUN = int(os.environ.get("FAPERGS_MAX_CANDIDATES_PER_RUN", "50"))
FAPERGS_MAX_DETAILS_PER_RUN = int(os.environ.get("FAPERGS_MAX_DETAILS_PER_RUN", "20"))
FAPERGS_FETCH_MAX_ATTEMPTS = int(os.environ.get("FAPERGS_FETCH_MAX_ATTEMPTS", "3"))
FAPERGS_FETCH_BACKOFF_SECONDS = float(os.environ.get("FAPERGS_FETCH_BACKOFF_SECONDS", "2"))
FAPERGS_FETCH_TIMEOUT_SECONDS = int(os.environ.get("FAPERGS_FETCH_TIMEOUT_SECONDS", "30"))


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
    """Apply the FAPERGS year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_fapergs_detail_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover detail-page URLs from the FAPERGS listing HTML.

    Verbatim port of ``extract_fapergs_detail_urls`` from the FastAPI
    repo. The extractor matches anchors that carry a signal token
    (``edital``, ``chamada``, ``centelha``, ``programa``) and dedupes
    canonicalised URLs on the listing host. Direct PDF URLs are
    skipped (those go through the detail-page stage).
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    listing_host = (urlsplit(listing_url).hostname or "").lower()
    signal = re.compile(r"\b(edital|chamada|centelha|programa)\b", re.IGNORECASE)

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        text = " ".join([href, link.get_text(" ", strip=True)])
        if not signal.search(text):
            continue

        resolved = urljoin(listing_url, href)
        parts = urlsplit(resolved)
        if (parts.hostname or "").lower() != listing_host:
            continue

        canonical = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path.rstrip("/"),
                parts.query,
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
    min_year: int = FAPERGS_MIN_NOTICE_YEAR,
    origin: str | None = None,
) -> dict[str, Any] | None:
    """Build a ``kind="pdf"`` candidate or return ``None`` if filtered out."""
    if not _passes_year_guard(url, min_year=min_year):
        return None
    if not _candidate_passes_edital_prefilter(url, filter_policy=filter_policy):
        return None

    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "listing_detail"

    extracted_year = _extract_year_from_url(url)
    if extracted_year is None and detail_url:
        extracted_year = _extract_year_from_url(detail_url)

    metadata: dict[str, Any] = {
        "source": "fapergs",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def _merge_detail_urls(static_urls: list[str], ajax_urls: list[str]) -> list[str]:
    """Merge static + AJAX URL lists preserving order and dedup."""
    merged: list[str] = []
    seen: set[str] = set()
    for url in list(static_urls) + list(ajax_urls):
        if url in seen:
            continue
        seen.add(url)
        merged.append(url)
    return merged


def _fetch_ajax_detail_urls(stats: dict[str, int]) -> list[str]:
    """Fetch the FAPERGS AJAX endpoint and extract detail URLs.

    Failures are logged at DEBUG and return ``[]``; the discoverer
    falls back to the static listing only.
    """
    from scraper_transport import request_with_safe_redirects
    try:
        response = request_with_safe_redirects(
            method="GET",
            url=FAPERGS_AJAX_URL,
            timeout=FAPERGS_FETCH_TIMEOUT_SECONDS,
            extra_headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": FAPERGS_LISTING_URL,
            },
        )
    except Exception as exc:
        logger.debug("FAPERGS AJAX endpoint failed: %s", exc, exc_info=True)
        return []
    try:
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.debug("FAPERGS AJAX decode failed: %s", exc, exc_info=True)
        return []
    body = payload.get("body", "")
    if not body:
        return []
    return extract_fapergs_detail_urls(body, FAPERGS_LISTING_URL)


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = FAPERGS_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover FAPERGS edital PDF candidates from the static listing
    + AJAX endpoint, then enumerate PDFs on each detail page.

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

    from scraper_transport import request_with_safe_redirects

    try:
        response = request_with_safe_redirects(
            method="GET",
            url=FAPERGS_LISTING_URL,
            timeout=FAPERGS_FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        static_urls = extract_fapergs_detail_urls(response.text, FAPERGS_LISTING_URL)
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch FAPERGS listing %s: %s",
            FAPERGS_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        static_urls = []

    ajax_urls = _fetch_ajax_detail_urls(stats)
    detail_urls = _merge_detail_urls(static_urls, ajax_urls)

    for detail_url in detail_urls:
        if details_fetched >= FAPERGS_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {FAPERGS_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            detail_pdfs = discover_pdf_urls_on_page(detail_url, stats=stats)
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on FAPERGS detail %s: %s",
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
                listing_url=FAPERGS_LISTING_URL,
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
            if len(candidates) >= FAPERGS_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {FAPERGS_MAX_CANDIDATES_PER_RUN}",
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
    print(f"FAPERGS discovery stats: {stats}")
    print(f"FAPERGS candidates discovered: {len(candidates)}")

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
    print(f"FAPERGS processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered FAPERGS candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="fapergs")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered FAPERGS candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
