"""WorldBank source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/playwright/worldbank.py``.
The original function took a Playwright ``Page`` and called
``ctx.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="worldbank")``
for download / OCR / submit.

The WorldBank source uses two paths:

1. **Primary BS4 path** — the shared ``scraper_transport.discover_pdf_urls_on_page``
   fetches the listing at
   ``https://www.worldbank.org/en/programs/sief-trust-fund/brief/sief-call-for-proposals-8-edtech-for-foundational-learning``
   and extracts ``.pdf`` anchors on the ``worldbank.org`` host whose
   href/path/text/title/aria-label carries one of the WorldBank signal
   tokens (``call for proposals``, ``request for proposals``,
   ``expression of interest``, ``procurement``, ``funding strategy``,
   ``resolution``). Tracking query parameters and URL fragments are
   stripped before the URL is canonicalised.

2. **Playwright fallback** — only triggered when the BS4 path yields
   no PDF candidates. The Playwright path queries all ``<a>``
   elements on the listing page and rebuilds an HTML fragment to
   feed back into ``extract_worldbank_pdf_urls``. Playwright is
   imported lazily so the cronjob can run the BS4 path on runners
   that do not bundle Chromium.

Filter pipeline (per plan §9):
- ``WORLDBANK_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
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


WORLDBANK_LISTING_URL = (
    "https://www.worldbank.org/en/programs/sief-trust-fund/brief/"
    "sief-call-for-proposals-8-edtech-for-foundational-learning"
)

WORLDBANK_MIN_NOTICE_YEAR = int(os.environ.get("WORLDBANK_MIN_NOTICE_YEAR", "2026"))

WORLDBANK_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("WORLDBANK_MAX_CANDIDATES_PER_RUN", "50"),
)
WORLDBANK_FETCH_MAX_ATTEMPTS = int(os.environ.get("WORLDBANK_FETCH_MAX_ATTEMPTS", "3"))
WORLDBANK_FETCH_BACKOFF_SECONDS = float(
    os.environ.get("WORLDBANK_FETCH_BACKOFF_SECONDS", "2"),
)
WORLDBANK_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("WORLDBANK_FETCH_TIMEOUT_SECONDS", "30"),
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
    """Apply the WorldBank year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_worldbank_pdf_urls(listing_doc: BeautifulSoup | str, listing_url: str) -> list[str]:
    """Discover PDF URLs from the WorldBank listing HTML.

    Verbatim port of ``extract_worldbank_pdf_urls`` from the FastAPI
    repo. The extractor keeps only ``.pdf`` anchors on the
    ``worldbank.org`` host (and subdomains) that carry one of the
    WorldBank signal tokens (``call for proposals``,
    ``request for proposals``, ``expression of interest``,
    ``procurement``, ``funding strategy``, ``resolution``).
    URL fragments are stripped before the URL is canonicalised.
    """
    if isinstance(listing_doc, BeautifulSoup):
        soup = listing_doc
    else:
        soup = BeautifulSoup(listing_doc, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(
        r"(call[\s_-]*for[\s_-]*proposals?|request[\s_-]*for[\s_-]*proposals?|expression[\s_-]*of[\s_-]*interest|\beoi\b|procurement|funding[\s_-]*strategy|resolution)",
        re.IGNORECASE,
    )

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        if not looks_like_pdf_url(href):
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        host = (normalized.hostname or "").lower()
        if host != "worldbank.org" and not host.endswith(".worldbank.org"):
            continue

        signal_text = " ".join(
            [
                href,
                normalized.path,
                link.get_text(" ", strip=True),
                str(link.get("title") or ""),
                str(link.get("aria-label") or ""),
            ]
        )
        if not signal_pattern.search(signal_text):
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
    filter_policy: FilterPolicy = "default",
    min_year: int = WORLDBANK_MIN_NOTICE_YEAR,
    origin: str | None = None,
) -> dict[str, Any] | None:
    """Build a ``kind="pdf"`` candidate or return ``None`` if filtered out."""
    if not _passes_year_guard(url, min_year=min_year):
        return None
    if not _candidate_passes_edital_prefilter(url, filter_policy=filter_policy):
        return None

    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "playwright_fallback"

    extracted_year = _extract_year_from_url(url)
    metadata: dict[str, Any] = {
        "source": "worldbank",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }

    return {"url": url, "kind": "pdf", "metadata": metadata}


def _run_playwright_fallback(listing_url: str, *, stats: dict[str, int]) -> list[str]:
    """Run the Playwright fallback against ``listing_url``.

    Returns the discovered PDF URLs (possibly empty). Increments
    ``stats["errors"]`` if Playwright is unavailable or the
    navigation fails.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        log_source_failure(
            "Playwright is not installed; skipping WorldBank fallback for %s",
            listing_url,
            exc=ImportError("playwright"),
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    listing_html = "<html><body>"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto(listing_url)
                links = page.query_selector_all("a")
                for link in links:
                    href = link.get_attribute("href")
                    if not href:
                        continue
                    link_text = link.inner_text() or ""
                    title = link.get_attribute("title") or ""
                    aria_label = link.get_attribute("aria-label") or ""
                    safe_href = href.replace('"', "&quot;")
                    safe_text = link_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    safe_title = title.replace('"', "&quot;")
                    safe_aria_label = aria_label.replace('"', "&quot;")
                    listing_html += (
                        f'<a href="{safe_href}" title="{safe_title}" '
                        f'aria-label="{safe_aria_label}">{safe_text}</a>'
                    )
            finally:
                browser.close()
    except Exception as exc:
        log_source_failure(
            "Failed processing World Bank listing page %s: %s",
            listing_url,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    listing_html += "</body></html>"
    return extract_worldbank_pdf_urls(listing_html, listing_url)


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = WORLDBANK_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover WorldBank edital PDF candidates from the listing page.

    Returns ``(stats, candidates)``. The primary BS4 path is tried
    first; if it yields no PDFs, the Playwright fallback runs only if
    Playwright is importable in the current environment.
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "prefilter_rejected": 0,
        "year_rejected": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
        "playwright_fallback_used": 0,
    }
    candidates: list[dict[str, Any]] = []
    seen_pdfs: set[str] = set()

    from scraper_transport import fetch_html_with_retry

    listing_html: str | None = None
    try:
        listing_html = fetch_html_with_retry(
            WORLDBANK_LISTING_URL,
            timeout=WORLDBANK_FETCH_TIMEOUT_SECONDS,
            max_attempts=WORLDBANK_FETCH_MAX_ATTEMPTS,
            backoff_seconds=WORLDBANK_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch WorldBank listing %s: %s",
            WORLDBANK_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1

    pdf_urls: list[str] = []
    if listing_html is not None:
        pdf_urls = extract_worldbank_pdf_urls(listing_html, WORLDBANK_LISTING_URL)
        stats["details_fetched"] += 1

    if not pdf_urls:
        stats["playwright_fallback_used"] = 1
        pdf_urls = _run_playwright_fallback(WORLDBANK_LISTING_URL, stats=stats)

    for pdf_url in pdf_urls:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
        candidate = build_candidate(
            pdf_url,
            listing_url=WORLDBANK_LISTING_URL,
            filter_policy=filter_policy,
            min_year=min_year,
        )
        if candidate is None:
            if not _passes_year_guard(pdf_url, min_year=min_year):
                stats["year_rejected"] += 1
            else:
                stats["prefilter_rejected"] += 1
            continue
        candidates.append(candidate)
        if len(candidates) >= WORLDBANK_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {WORLDBANK_MAX_CANDIDATES_PER_RUN}",
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
    print(f"WorldBank discovery stats: {stats}")
    print(f"WorldBank candidates discovered: {len(candidates)}")

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
    print(f"WorldBank processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered WorldBank candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="worldbank")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered WorldBank candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())