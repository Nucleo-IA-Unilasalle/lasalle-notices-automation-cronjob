"""FAO source discoverer for the cronjob pipeline.

Phase 4 port of
``lasalle-notices-automation/app/services/scraper/playwright/fao.py``.
The original function took a Playwright ``Page`` and called
``ctx.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="fao")`` for
download / OCR / submit.

The FAO source uses two paths:

1. **Primary BS4 path** — ``extract_fao_pdf_urls`` scans the listing
   at ``https://www.fao.org/plant-treaty/areas-of-work/funding/`` for
   ``.pdf`` anchors on the ``fao.org`` host whose href / path / text /
   title / aria-label carries one of the FAO signal tokens
   (``call for proposals``, ``request for proposals``, ``expression of
   interest``, ``procurement``, ``funding strategy``, ``resolution``).

2. **Playwright fallback** — only triggered when the BS4 path yields
   no PDF candidates. The Playwright path queries all ``<a>``
   elements on the listing page and rebuilds an HTML fragment to
   feed back into ``extract_fao_pdf_urls``. Playwright is imported
   lazily so the cronjob can run the BS4 path on runners that do not
   bundle Chromium.

Message shape matches the existing PNCP contract so the Render submit
endpoint can ingest it unchanged.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_transport import (
    discover_pdf_urls_on_page,
    log_source_failure,
    looks_like_pdf_url,
)


FAO_LISTING_URL = "https://www.fao.org/plant-treaty/areas-of-work/funding/"


FAO_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("FAO_MAX_CANDIDATES_PER_RUN", "50"),
)
FAO_FETCH_MAX_ATTEMPTS = int(os.environ.get("FAO_FETCH_MAX_ATTEMPTS", "3"))
FAO_FETCH_BACKOFF_SECONDS = float(os.environ.get("FAO_FETCH_BACKOFF_SECONDS", "2"))
FAO_FETCH_TIMEOUT_SECONDS = int(os.environ.get("FAO_FETCH_TIMEOUT_SECONDS", "30"))


def extract_fao_pdf_urls(listing_doc: BeautifulSoup | str, listing_url: str) -> list[str]:
    """Discover PDF URLs from the FAO listing HTML.

    Verbatim port of ``extract_fao_pdf_urls`` from the FastAPI repo.
    The extractor keeps only ``.pdf`` anchors on the ``fao.org`` host
    (and subdomains) that carry one of the FAO signal tokens
    (``call for proposals``, ``request for proposals``,
    ``expression of interest``, ``procurement``, ``funding strategy``,
    ``resolution``). URL fragments are stripped before the URL is
    canonicalised.
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
        if host != "fao.org" and not host.endswith(".fao.org"):
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


async def _collect_listing_anchors(listing_url: str) -> str:
    """Navigate to ``listing_url`` with Playwright and rebuild an HTML
    fragment containing every ``<a>`` element's href / text / title /
    aria-label. The fragment is fed back into ``extract_fao_pdf_urls``
    so the BS4 extractor stays the source of truth for filtering.

    Returns an empty string when no anchors are found.
    """
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    listing_html = "<html><body>"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(listing_url)
            links = await page.query_selector_all("a")
            for link in links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                link_text = await link.inner_text()
                title = await link.get_attribute("title")
                aria_label = await link.get_attribute("aria-label")
                safe_href = href.replace('"', "&quot;")
                safe_text = (link_text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                safe_title = (title or "").replace('"', "&quot;")
                safe_aria_label = (aria_label or "").replace('"', "&quot;")
                listing_html += (
                    f'<a href="{safe_href}" title="{safe_title}" aria-label="{safe_aria_label}">'
                    f"{safe_text}</a>"
                )
        finally:
            await browser.close()
    listing_html += "</body></html>"
    return listing_html


def _run_playwright_fallback(listing_url: str, *, stats: dict[str, int]) -> list[str]:
    """Run the Playwright fallback against ``listing_url``.

    Returns the discovered PDF URLs (possibly empty). Increments
    ``stats["errors"]`` if Playwright is unavailable or the
    navigation fails.
    """
    try:
        listing_html = asyncio.run(_collect_listing_anchors(listing_url))
    except ImportError:
        log_source_failure(
            "Playwright is not installed; skipping FAO fallback for %s",
            listing_url,
            exc=ImportError("playwright"),
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []
    except Exception as exc:
        log_source_failure(
            "Failed processing FAO listing page %s: %s",
            listing_url,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    return extract_fao_pdf_urls(listing_html, listing_url)


def build_candidate(
    url: str,
    *,
    listing_url: str,
    origin: str | None = None,
) -> dict[str, Any]:
    """Build a ``kind="pdf"`` candidate for the FAO source."""
    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "playwright_fallback"

    metadata: dict[str, Any] = {
        "source": "fao",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
    }

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover FAO edital PDF candidates from the listing page.

    Returns ``(stats, candidates)``. The primary BS4 path is tried
    first; if it yields no PDFs, the Playwright fallback runs only if
    Playwright is importable in the current environment.
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
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
            FAO_LISTING_URL,
            timeout=FAO_FETCH_TIMEOUT_SECONDS,
            max_attempts=FAO_FETCH_MAX_ATTEMPTS,
            backoff_seconds=FAO_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch FAO listing %s: %s",
            FAO_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1

    pdf_urls: list[str] = []
    if listing_html is not None:
        pdf_urls = discover_pdf_urls_on_page(
            FAO_LISTING_URL,
            stats=stats,
            extractor=extract_fao_pdf_urls,
        )
        stats["details_fetched"] += 1

    if not pdf_urls:
        stats["playwright_fallback_used"] = 1
        pdf_urls = _run_playwright_fallback(FAO_LISTING_URL, stats=stats)

    for pdf_url in pdf_urls:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
        candidate = build_candidate(pdf_url, listing_url=FAO_LISTING_URL)
        candidates.append(candidate)
        if len(candidates) >= FAO_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {FAO_MAX_CANDIDATES_PER_RUN}",
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
    print(f"FAO discovery stats: {stats}")
    print(f"FAO candidates discovered: {len(candidates)}")

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
    print(f"FAO processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered FAO candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="fao")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered FAO candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
