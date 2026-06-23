"""Fundação Grupo Boticário source discoverer for the cronjob pipeline.

Phase 4 port of
``lasalle-notices-automation/app/services/scraper/playwright/fundacao_grupo_boticario.py``.
The original function took a Playwright ``Page`` and called
``ctx.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="fundacao_grupo_boticario")``
for download / OCR / submit.

The Fundação Grupo Boticário source uses two paths and two stages:

1. **Listing stage** — pull the listing at
   ``https://fundacaogrupoboticario.org.br/`` and extract the set of
   detail page URLs (kept on either ``fundacaogrupoboticario.org.br``
   or ``goias.gov.br`` under ``/fapeg/`` and tagged with one of the
   ``chamada`` / ``edital`` / ``sprint`` / ``bolsa`` signal tokens).

2. **Detail stage** — for each detail URL, fetch the page and extract
   ``.pdf`` anchors via the shared ``scraper_transport.discover_pdf_urls_on_page``.
   Hosts other than ``fundacaogrupoboticario.org.br`` (e.g. ``goias.gov.br``
   FAPEG) carry the actual editais.

When the listing BS4 path yields no detail URLs, a Playwright fallback
rebuilds an HTML fragment from the listing's ``<a>`` elements and feeds
it back into the BS4 detail extractor. Detail pages keep the BS4
path because the FastAPI source itself only falls back to Playwright
for the detail page when the BS4 fetch yields no PDFs — a case the
cronjob keeps simple by reporting the fallback as the origin.

The detail-URL helpers are inlined from the FastAPI helper-only module
``app/services/scraper/sources/fundacao_grupo_boticario.py``. That
helper module is intentionally not registered as a discoverer in the
cronjob (it is consumed only by this Playwright source per the FastAPI
``sources/AGENTS.md`` and ``scraper/AGENTS.md`` docs).

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


FUNDACAO_GRUPO_BOTICARIO_LISTING_URL = "https://fundacaogrupoboticario.org.br/"


FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN", "50"),
)
FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN", "20"),
)
FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS", "3"),
)
FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS = float(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS", "2"),
)
FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS", "30"),
)


def is_fundacao_grupo_boticario_host(url: str) -> bool:
    """Return ``True`` if ``url`` is on the foundation's host.

    Inlined verbatim from
    ``app/services/scraper/sources/fundacao_grupo_boticario.py`` so
    the cronjob can reuse the helper without importing the
    FastAPI package.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host == "fundacaogrupoboticario.org.br"


def extract_fundacao_grupo_boticario_detail_urls_from_soup(
    soup: BeautifulSoup, listing_url: str,
) -> list[str]:
    """Discover detail-URL links from the Fundação Grupo Boticário
    listing HTML.

    Inlined verbatim from
    ``app/services/scraper/sources/fundacao_grupo_boticario.py``.
    Keeps only anchors on ``fundacaogrupoboticario.org.br`` /
    ``goias.gov.br`` (the latter gated to ``/fapeg/`` paths) whose
    href / path / text / title / aria-label carries one of the
    ``chamada`` / ``edital`` / ``sprint`` / ``bolsa`` signal tokens.
    """
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(r"\b(chamada|edital|sprint|bolsa)\b", re.IGNORECASE)
    allowed_hosts = {"fundacaogrupoboticario.org.br", "goias.gov.br"}

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        host = (normalized.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host not in allowed_hosts:
            continue

        path = normalized.path.rstrip("/")
        if not path or path == "/":
            continue

        if host == "goias.gov.br" and not path.startswith("/fapeg/"):
            continue

        if host == "fundacaogrupoboticario.org.br" and path in {
            "/noticias",
            "/quem-somos",
            "/nossa-atuacao",
            "/fale-conosco",
        }:
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

        canonical = urlunsplit((normalized.scheme, normalized.netloc, path, "", ""))
        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def extract_fundacao_grupo_boticario_detail_urls(
    listing_html: str, listing_url: str,
) -> list[str]:
    soup = BeautifulSoup(listing_html, "html.parser")
    return extract_fundacao_grupo_boticario_detail_urls_from_soup(soup, listing_url)


async def _collect_listing_anchors(listing_url: str) -> str:
    """Navigate to ``listing_url`` with Playwright and rebuild an HTML
    fragment containing every ``<a>`` element's href. The fragment is
    fed back into ``extract_fundacao_grupo_boticario_detail_urls``
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
            listing_links = await page.query_selector_all("a")
            for link in listing_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                safe_href = href.replace('"', "&quot;")
                listing_html += f'<a href="{safe_href}"></a>'
        finally:
            await browser.close()
    listing_html += "</body></html>"
    return listing_html


def _run_playwright_fallback(
    listing_url: str, *, stats: dict[str, int],
) -> list[str]:
    """Run the Playwright fallback against ``listing_url``.

    Returns the discovered detail URLs (possibly empty). Increments
    ``stats["errors"]`` if Playwright is unavailable or the
    navigation fails.
    """
    try:
        listing_html = asyncio.run(_collect_listing_anchors(listing_url))
    except ImportError:
        log_source_failure(
            "Playwright is not installed; skipping "
            "Fundação Grupo Boticário fallback for %s",
            listing_url,
            exc=ImportError("playwright"),
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []
    except Exception as exc:
        log_source_failure(
            "Failed processing Fundação Grupo Boticário listing page %s: %s",
            listing_url,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    return extract_fundacao_grupo_boticario_detail_urls(listing_html, listing_url)


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    """Build a ``kind="pdf"`` candidate for the Fundação Grupo
    Boticário source."""
    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "playwright_fallback"

    metadata: dict[str, Any] = {
        "source": "fundacao_grupo_boticario",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover Fundação Grupo Boticário edital PDF candidates.

    Returns ``(stats, candidates)``. The listing BS4 path is tried
    first; if it yields no detail URLs, the Playwright fallback runs
    only if Playwright is importable in the current environment.
    Each detail URL is then resolved through the shared BS4 PDF
    discovery.
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
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
            timeout=FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS,
            max_attempts=FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS,
            backoff_seconds=FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch Fundação Grupo Boticário listing %s: %s",
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1

    detail_urls: list[str] = []
    if listing_html is not None:
        soup = BeautifulSoup(listing_html, "html.parser")
        detail_urls = extract_fundacao_grupo_boticario_detail_urls_from_soup(
            soup, FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
        )

    if not detail_urls:
        stats["playwright_fallback_used"] = 1
        detail_urls = _run_playwright_fallback(
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URL, stats=stats,
        )

    for detail_url in detail_urls[:FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN]:
        pdf_urls = discover_pdf_urls_on_page(
            detail_url, stats=stats,
        )
        stats["details_fetched"] += 1
        for pdf_url in pdf_urls:
            if pdf_url in seen_pdfs:
                continue
            seen_pdfs.add(pdf_url)
            candidate = build_candidate(
                pdf_url,
                listing_url=FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
                detail_url=detail_url,
            )
            candidates.append(candidate)
            if len(candidates) >= FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    "Stopping after candidate cap "
                    f"{FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN}",
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
    print(f"Fundação Grupo Boticário discovery stats: {stats}")
    print(f"Fundação Grupo Boticário candidates discovered: {len(candidates)}")

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
    print(f"Fundação Grupo Boticário processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered Fundação Grupo Boticário candidates "
            "failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(
        processed, source="fundacao_grupo_boticario",
    )
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered Fundação Grupo Boticário candidates "
            "produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
