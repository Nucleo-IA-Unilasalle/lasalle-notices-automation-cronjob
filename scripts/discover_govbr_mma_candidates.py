"""GOVBR-MMA BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/govbr.py``
(``scrape_govbr_mma`` at line 85; the ``scrape_govbr_mcti`` variant
at line 115 is intentionally NOT ported because it is degraded —
listing now redirects to a Plone ``credentials_cookie_auth`` page).
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="govbr_mma")``
for download / OCR / submit.

The GOVBR-MMA source is a Plone-backed listing at
``https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais``
that hosts a ``#content-core #parent-fieldname-text`` (or ``#content-core``)
content node with internal anchor links to detail pages. The detail
pages are fetched via ``scraper_transport.discover_pdf_urls_on_page``
(using the default PDF extractor that matches ``.pdf`` anchors) to
enumerate the PDF anchors hosted on each detail page.

Filter pipeline (per plan §9):
- ``GOVBR_MMA_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
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
    log_source_failure,
    looks_like_pdf_url,
)


GOVBR_MMA_LISTING_URL = (
    "https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais"
)

GOVBR_MMA_MIN_NOTICE_YEAR = int(os.environ.get("GOVBR_MMA_MIN_NOTICE_YEAR", "2026"))

GOVBR_MMA_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("GOVBR_MMA_MAX_CANDIDATES_PER_RUN", "50"),
)
GOVBR_MMA_MAX_DETAILS_PER_RUN = int(
    os.environ.get("GOVBR_MMA_MAX_DETAILS_PER_RUN", "20"),
)


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
    """Apply the GOVBR-MMA year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_govbr_mma_detail_urls(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Discover internal detail-page URLs from the GOVBR-MMA listing.

    Verbatim port of ``extract_govbr_mma_detail_urls`` from the FastAPI
    repo. The extractor pins to the ``#content-core #parent-fieldname-text``
    (falling back to ``#content-core``) content node, then keeps only
    internal anchors whose canonical path lives under the listing's
    prefix. Direct PDF anchors are skipped.
    """
    discovered: list[str] = []
    parsed_listing = urlsplit(page_url)
    listing_base = urlunsplit(
        (parsed_listing.scheme, parsed_listing.netloc, parsed_listing.path.rstrip("/") + "/", "", ""),
    )
    listing_prefix = listing_base.rstrip("/")
    seen: set[str] = set()

    root = soup.select_one("#content-core #parent-fieldname-text")
    if not isinstance(root, Tag):
        root = soup.select_one("#content-core")
    if not isinstance(root, Tag):
        return discovered

    for link in root.select("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_base, href)
        normalized = urlsplit(resolved)
        canonical = urlunsplit(
            (
                normalized.scheme,
                normalized.netloc,
                normalized.path.rstrip("/"),
                "",
                "",
            )
        )

        if looks_like_pdf_url(canonical):
            continue
        if canonical == listing_prefix:
            continue
        if not canonical.startswith(f"{listing_prefix}/"):
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
    min_year: int = GOVBR_MMA_MIN_NOTICE_YEAR,
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
        "source": "govbr_mma",
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
    min_year: int = GOVBR_MMA_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover GOVBR-MMA edital PDF candidates from the listing + detail pages.

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

    try:
        detail_urls = discover_pdf_urls_on_page(
            GOVBR_MMA_LISTING_URL,
            stats=stats,
            extractor=lambda soup, page_url: extract_govbr_mma_detail_urls(soup, page_url),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch GOVBR-MMA listing %s: %s",
            GOVBR_MMA_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates

    for detail_url in detail_urls:
        if details_fetched >= GOVBR_MMA_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {GOVBR_MMA_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            detail_pdfs = discover_pdf_urls_on_page(detail_url, stats=stats)
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on GOVBR-MMA detail %s: %s",
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
                listing_url=GOVBR_MMA_LISTING_URL,
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
            if len(candidates) >= GOVBR_MMA_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {GOVBR_MMA_MAX_CANDIDATES_PER_RUN}",
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
    print(f"GOVBR-MMA discovery stats: {stats}")
    print(f"GOVBR-MMA candidates discovered: {len(candidates)}")

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
    print(f"GOVBR-MMA processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered GOVBR-MMA candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="govbr_mma")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered GOVBR-MMA candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())