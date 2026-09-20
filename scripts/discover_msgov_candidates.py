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
import re
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
# Registry ``page_limit`` for msgov is 5; the Prosas listing web component
# renders 20 editais per page and the open set can exceed one page.
MSGOV_MAX_LISTING_PAGES = int(
    os.environ.get("MSGOV_MAX_LISTING_PAGES", "5"),
)


def _stable_pdf_identity(url: str) -> str:
    """Normalize a Prosas PDF href to a stable cross-request identity.

    Detail-page anchors carry Oracle Cloud preauthenticated ``/p/<token>/``
    path segments and signed query strings that change on every page load.
    Strip the token segment and the query so discovery metadata
    (``canonical_url`` / ``source_record_id``) stays comparable across the
    independent inventory and discovery runs. The original signed URL is
    still used for download via ``candidate["url"]``.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path or ""
    host = (parts.hostname or "").lower()
    if "objectstorage" in host:
        path = re.sub(r"^/p/[^/]+", "", path)
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


# Office/archive annexes ride the same Prosas S3/objectstorage hosts as
# PDFs. The historical ``or "amazonaws.com" in href`` catch-all admitted
# them as candidates (later rejected by magic-byte validation), which
# both polluted the candidate set and pushed real PDFs past the run cap
# once a detail page exposed many annexes. Keep extensionless S3 objects
# but drop explicit non-PDF suffixes at discovery time.
_NON_PDF_SUFFIX_RE = re.compile(
    r"\.(?:doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|csv|txt|odt|ods|odp|rtf)"
    r"($|[?#])",
    re.IGNORECASE,
)


def _is_pdf_candidate_href(href: str) -> bool:
    """Whether a detail-page href should be emitted as a PDF candidate."""
    if not href:
        return False
    if _NON_PDF_SUFFIX_RE.search(href):
        return False
    return looks_like_pdf_url(href) or "amazonaws.com" in href or "objectstorage" in href


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


_CLICK_NEXT_PAGE_SCRIPT = """
(() => {
  const host = document.querySelector('prosas-listagem-editais');
  if (!host || !host.shadowRoot) return 'no-host';

  // Pagination row is a div with exactly four button children:
  // [first, prev, next, last]. Click "next" when enabled.
  const groups = [];
  const walk = (node) => {
    if (!node) return;
    if (node instanceof Element) {
      if (node.tagName === 'DIV') {
        const btns = Array.from(node.children || []).filter(
          (c) => c.tagName === 'BUTTON',
        );
        if (btns.length === 4) groups.push(btns);
      }
      if (node.shadowRoot) walk(node.shadowRoot);
      for (const child of Array.from(node.children || [])) walk(child);
      return;
    }
    if (node instanceof ShadowRoot || node instanceof DocumentFragment) {
      for (const child of Array.from(node.children || [])) walk(child);
    }
  };
  walk(host.shadowRoot);
  if (!groups.length) return 'no-pagination';
  const btns = groups[groups.length - 1];
  const next = btns[2];
  if (!next || next.disabled) return 'next-disabled';
  try {
    next.click();
  } catch (e) {
    return 'click-failed';
  }
  return 'clicked-next';
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
        if not _is_pdf_candidate_href(href):
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
    # Each entry is (pdf_url, detail_url) so candidate identity can carry
    # the owning detail page.
    pdf_candidates: list[tuple[str, str]] = []

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

            # Paginate the open listing. The Prosas web component renders
            # 20 editais per page; without walking the next-page control
            # the open set beyond the first page is silently dropped.
            seen_detail_urls: set[str] = set()
            for page_index in range(MSGOV_MAX_LISTING_PAGES):
                page_urls = await _collect_listing_detail_urls(page, MSGOV_LISTING_URL)
                if page_index == 0:
                    stats["listings_fetched"] = stats.get("listings_fetched", 0) + 1
                new_urls = [u for u in page_urls if u not in seen_detail_urls]
                if not new_urls and page_index > 0:
                    break
                for url in new_urls:
                    seen_detail_urls.add(url)
                    detail_urls.append(url)
                if page_index >= MSGOV_MAX_LISTING_PAGES - 1:
                    break
                try:
                    click_result = await page.evaluate(_CLICK_NEXT_PAGE_SCRIPT)
                except Exception as exc:
                    print(
                        f"warning: MSGOV listing next-page click failed: {exc}",
                        file=sys.stderr,
                    )
                    break
                if click_result != "clicked-next":
                    break
                await page.wait_for_timeout(2000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass

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
                for pdf_url in detail_pdfs:
                    pdf_candidates.append((pdf_url, detail_url))
        finally:
            await browser.close()

    return detail_urls, pdf_candidates


def _run_playwright_discovery(
    stats: dict[str, int],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Run the Playwright discovery flow synchronously via
    ``asyncio.run``. Returns ``(detail_urls, pdf_candidates)`` where
    each pdf candidate is ``(pdf_url, detail_url)``.
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
    """Build a ``kind="pdf"`` candidate for the MSGOV source.

    ``metadata.canonical_url`` / ``metadata.source_record_id`` carry the
    stable (token-stripped) PDF identity so audit artifacts remain
    comparable across runs; ``candidate["url"]`` keeps the original
    signed href for download.
    """
    stable = _stable_pdf_identity(url)
    metadata: dict[str, Any] = {
        "source": "msgov",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": "playwright_listing",
        "canonical_url": stable,
        "source_record_id": stable,
        # The listing only enumerates the open (inscrições abertas) tab.
        "status": "open",
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

    detail_urls, pdf_entries = _run_playwright_discovery(stats)

    for pdf_url, detail_url in pdf_entries:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
        candidate = build_candidate(
            pdf_url,
            listing_url=MSGOV_LISTING_URL,
            detail_url=detail_url,
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
