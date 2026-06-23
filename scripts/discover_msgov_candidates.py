"""MSGOV source discoverer for the cronjob pipeline.

Phase 4 port of
``lasalle-notices-automation/app/services/scraper/playwright/msgov.py``.
The original function took a Playwright ``Page`` and called
``ctx.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="msgov")`` for
download / OCR / submit.

MSGOV is the only Phase 4 source that needs Playwright as the
**primary** path because the listing (``editaisms.prosas.com.br``) is
JS-rendered via a ``prosas-listagem-editais`` web component and detail
pages contain a dropdown that lazy-loads anexos. A few ``.doc`` annexes
leak through discovery; the cronjob relies on the magic-byte check in
``pncp_http.validate_pdf`` (which checks both the ``b"%PDF"`` header
and ``application/pdf`` MIME via ``python-magic``) to reject them at
download time, so no manual classification is needed here.

The discoverer has two Playwright stages:

1. **Listing stage** — navigate to the base URL, wait for the
   ``prosas-listagem-editais`` component to settle, then try
   ``a[href*='edital?id=']`` and ``a[href*='edital.html?id=']``
   selectors. If those yield nothing, run a shadow-DOM walker via
   ``page.evaluate`` to enumerate every anchor's ``href`` in the
   document tree. Filter hrefs down to ``/edital`` / ``/edital.html``
   paths with an ``id=`` query parameter on the base host.

2. **Detail stage** — for each detail URL, navigate, expand the
   ``prosas-box-container-dropdown`` / ``dropdown`` triggers via a
   second shadow-DOM walker, then collect ``.pdf`` hrefs and
   ``amazonaws.com`` URLs (the prosas CDN host).

Playwright is imported lazily so the cronjob can no-op on runners
that do not bundle Chromium.

Message shape matches the existing PNCP contract so the Render submit
endpoint can ingest it unchanged.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import pipeline_core
from scraper_transport import log_source_failure, looks_like_pdf_url


MSGOV_LISTING_URL = "https://editaisms.prosas.com.br"


MSGOV_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("MSGOV_MAX_CANDIDATES_PER_RUN", "50"),
)
MSGOV_MAX_DETAILS_PER_RUN = int(
    os.environ.get("MSGOV_MAX_DETAILS_PER_RUN", "40"),
)


_COLLECT_LISTING_HREFS_SCRIPT = """
(() => {
  const hrefs = [];
  const seen = new Set();
  const stack = [document.documentElement];

  const pushHref = (value) => {
    if (!value) return;
    if (seen.has(value)) return;
    seen.add(value);
    hrefs.push(value);
  };

  while (stack.length) {
    const node = stack.pop();
    if (!node) continue;

    if (node instanceof Element) {
      if (node.tagName === 'A') {
        pushHref(node.getAttribute('href'));
      }
      if (node.shadowRoot) {
        stack.push(node.shadowRoot);
      }
      for (const child of Array.from(node.children || [])) {
        stack.push(child);
      }
      continue;
    }

    if (node instanceof ShadowRoot || node instanceof DocumentFragment) {
      for (const child of Array.from(node.children || [])) {
        stack.push(child);
      }
    }
  }

  return hrefs;
})()
""".strip()


_EXPAND_DROPDOWN_SCRIPT = """
(() => {
  const clicked = [];
  const seen = new Set();
  const stack = [document.documentElement];

  const shouldClick = (el) => {
    if (!el || !el.tagName) return false;
    const id = (el.id || '').toLowerCase();
    const cls = (el.className || '').toString().toLowerCase();
    const txt = (el.textContent || '').toLowerCase();
    if (id === 'prosas-box-container-dropdown') return true;
    if (id.includes('dropdown') && (txt.includes('complement') || txt.includes('anex'))) return true;
    if (cls.includes('dropdown') && (txt.includes('complement') || txt.includes('anex'))) return true;
    if ((el.getAttribute && (el.getAttribute('role') || '').toLowerCase() === 'button') && txt.includes('complement')) return true;
    return false;
  };

  while (stack.length) {
    const node = stack.pop();
    if (!node) continue;

    if (node instanceof Element) {
      if (shouldClick(node)) {
        const key = `${node.tagName}#${node.id}.${node.className}`;
        if (!seen.has(key)) {
          seen.add(key);
          try { node.click(); clicked.push(key); } catch (e) { /* ignore */ }
        }
      }

      if (node.shadowRoot) {
        stack.push(node.shadowRoot);
      }
      for (const child of Array.from(node.children || [])) {
        stack.push(child);
      }
      continue;
    }

    if (node instanceof ShadowRoot || node instanceof DocumentFragment) {
      for (const child of Array.from(node.children || [])) {
        stack.push(child);
      }
    }
  }

  return clicked.length;
})()
""".strip()


async def _collect_listing_detail_urls(page: Any, listing_url: str) -> list[str]:
    """Drive the listing page through Playwright and return the
    canonical detail URLs.

    Mirrors the FastAPI source: waits for ``prosas-listagem-editais``
    to render, tries the ``edital?id=`` selectors first, falls back
    to a shadow-DOM walk via ``page.evaluate``. Filters out non-base
    hosts and hrefs that are not ``/edital`` / ``/edital.html`` with
    an ``id=`` query parameter.
    """
    base_parts = urlsplit(listing_url)

    candidate_hrefs: list[str] = []
    for selector in (
        "a[href*='edital?id=']",
        'a[href*="edital?id="]',
        "a[href*='edital.html?id=']",
        'a[href*="edital.html?id="]',
    ):
        try:
            found = await page.query_selector_all(selector)
        except Exception:
            found = []
        if found:
            for anchor in found:
                href = await anchor.get_attribute("href")
                if isinstance(href, str) and href:
                    candidate_hrefs.append(href)

    if not candidate_hrefs:
        try:
            evaluated = await page.evaluate(_COLLECT_LISTING_HREFS_SCRIPT)
            if isinstance(evaluated, list):
                for item in evaluated:
                    if isinstance(item, str) and item:
                        candidate_hrefs.append(item)
        except Exception as exc:
            print(f"warning: MSGOV listing evaluate() failed: {exc}", file=sys.stderr)

    detail_urls: list[str] = []
    seen_details: set[str] = set()
    for href in candidate_hrefs:
        detail_url = urljoin(listing_url, href)
        detail_parts = urlsplit(detail_url)
        if (detail_parts.hostname or "").lower() != (base_parts.hostname or "").lower():
            continue
        if detail_parts.path not in {"/edital", "/edital.html"}:
            continue
        detail_query = parse_qs(detail_parts.query)
        if not detail_query.get("id"):
            continue
        canonical = urlunsplit(
            (
                detail_parts.scheme,
                detail_parts.netloc,
                detail_parts.path,
                detail_parts.query,
                "",
            )
        )
        if canonical in seen_details:
            continue
        seen_details.add(canonical)
        detail_urls.append(canonical)

    return detail_urls


async def _collect_detail_pdfs(page: Any, detail_url: str) -> list[str]:
    """Drive one detail page through Playwright and return PDF URLs.

    Mirrors the FastAPI source: waits for ``networkidle`` and a
    generic ``a`` selector, expands the prosas dropdown via shadow-DOM
    walker, then collects ``looks_like_pdf_url(href)`` and
    ``amazonaws.com`` anchors.
    """
    pdf_candidates: list[str] = []
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    try:
        await page.wait_for_selector("a", timeout=5000)
    except Exception:
        pass

    deep_hrefs: list[str] = []
    try:
        await page.evaluate(_EXPAND_DROPDOWN_SCRIPT)
        for _ in range(2):
            evaluated = await page.evaluate(_COLLECT_LISTING_HREFS_SCRIPT)
            if isinstance(evaluated, list):
                for item in evaluated:
                    if isinstance(item, str) and item:
                        deep_hrefs.append(item)
            if deep_hrefs:
                break
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                break
    except Exception as exc:
        print(f"warning: MSGOV detail shadow-dom probe failed: {exc}", file=sys.stderr)

    detail_links = await page.query_selector_all("a")
    light_hrefs: list[str] = []
    for link in detail_links:
        href = await link.get_attribute("href")
        if isinstance(href, str) and href:
            light_hrefs.append(href)

    for href in [*light_hrefs, *deep_hrefs]:
        if not (looks_like_pdf_url(href) or "amazonaws.com" in href):
            continue
        pdf_candidates.append(urljoin(detail_url, href))

    return pdf_candidates


async def _scrape_msgov(stats: dict[str, int]) -> tuple[list[str], list[dict[str, Any]]]:
    """Run the full MSGOV discovery flow.

    Returns ``(detail_urls, pdf_candidates)``. Increments
    ``stats["errors"]`` on failure.
    """
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    detail_urls: list[str] = []
    pdf_candidates: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(MSGOV_LISTING_URL)
            except Exception as exc:
                log_source_failure(
                    "Failed to navigate to MSGOV listing %s: %s",
                    MSGOV_LISTING_URL,
                    exc,
                    exc=exc,
                )
                stats["errors"] = stats.get("errors", 0) + 1
                return detail_urls, pdf_candidates

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            try:
                await page.wait_for_selector("a", timeout=5000)
            except Exception:
                pass
            try:
                await page.wait_for_selector(
                    "prosas-listagem-editais", timeout=10000,
                )
            except Exception:
                pass
            await page.wait_for_timeout(2000)

            detail_urls = await _collect_listing_detail_urls(page, MSGOV_LISTING_URL)
            stats["listings_fetched"] = stats.get("listings_fetched", 0) + 1

            for detail_url in detail_urls[:MSGOV_MAX_DETAILS_PER_RUN]:
                try:
                    await page.goto(detail_url)
                except Exception as exc:
                    log_source_failure(
                        "Failed to navigate to MSGOV detail %s: %s",
                        detail_url,
                        exc,
                        exc=exc,
                    )
                    stats["errors"] = stats.get("errors", 0) + 1
                    continue
                detail_pdfs = await _collect_detail_pdfs(page, detail_url)
                stats["details_fetched"] = stats.get("details_fetched", 0) + 1
                pdf_candidates.extend(detail_pdfs)
        finally:
            await browser.close()

    return detail_urls, pdf_candidates


def _run_playwright_discovery(stats: dict[str, int]) -> tuple[list[str], list[str]]:
    """Run the Playwright discovery flow synchronously via
    ``asyncio.run``. Returns ``(detail_urls, pdf_candidates)``.
    """
    try:
        return asyncio.run(_scrape_msgov(stats))
    except ImportError:
        log_source_failure(
            "Playwright is not installed; skipping MSGOV discovery",
            exc=ImportError("playwright"),
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return [], []
    except Exception as exc:
        log_source_failure(
            "Failed processing MSGOV listing page %s: %s",
            MSGOV_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return [], []


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
) -> dict[str, Any]:
    """Build a ``kind="pdf"`` candidate for the MSGOV source."""
    metadata: dict[str, Any] = {
        "source": "msgov",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": "playwright_listing",
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover MSGOV edital PDF candidates.

    Returns ``(stats, candidates)``. The MSGOV source is pure
    Playwright because the listing is JS-rendered; ``.doc`` annexes
    that leak through discovery are filtered by the magic-byte
    check in ``pipeline_core.process_candidate`` (via
    ``download_pncp_pdf`` → ``validate_pdf``).
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
    }
    candidates: list[dict[str, Any]] = []
    seen_pdfs: set[str] = set()

    detail_urls, pdf_urls = _run_playwright_discovery(stats)

    for pdf_url in pdf_urls:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
        candidate = build_candidate(
            pdf_url,
            listing_url=MSGOV_LISTING_URL,
        )
        candidates.append(candidate)
        if len(candidates) >= MSGOV_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {MSGOV_MAX_CANDIDATES_PER_RUN}",
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
    print(f"MSGOV discovery stats: {stats}")
    print(f"MSGOV candidates discovered: {len(candidates)}")

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
    print(f"MSGOV processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered MSGOV candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="msgov")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered MSGOV candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
