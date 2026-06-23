"""TNC BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/tnc.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="tnc")`` for
download / OCR / submit.

The TNC source fans out from a single listing page at
``https://www.tnc.org.br/conecte-se/comunicacao/noticias/`` that
exposes detail-page anchors both as direct ``<a>`` elements and as
JSON-encoded payloads inside ``<span class="articleAggregationDetailsStr"
data-details="...">`` elements (a WordPress-style aggregation
convention). Detail URLs match ``/conecte-se/comunicacao/noticias/<slug>``
on the listing host and require one of the signal tokens (``edital``,
``chamada``, ``tdr``, ``consultoria``, ``documento``). Each detail
page is then fetched via
``scraper_transport.discover_pdf_urls_on_page`` to enumerate the PDF
anchors hosted on it.

Filter pipeline (per plan §9):
- ``TNC_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
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


TNC_LISTING_URL = "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"

TNC_MIN_NOTICE_YEAR = int(os.environ.get("TNC_MIN_NOTICE_YEAR", "2026"))

TNC_MAX_CANDIDATES_PER_RUN = int(os.environ.get("TNC_MAX_CANDIDATES_PER_RUN", "50"))
TNC_MAX_DETAILS_PER_RUN = int(os.environ.get("TNC_MAX_DETAILS_PER_RUN", "20"))
TNC_FETCH_MAX_ATTEMPTS = int(os.environ.get("TNC_FETCH_MAX_ATTEMPTS", "3"))
TNC_FETCH_BACKOFF_SECONDS = float(os.environ.get("TNC_FETCH_BACKOFF_SECONDS", "2"))
TNC_FETCH_TIMEOUT_SECONDS = int(os.environ.get("TNC_FETCH_TIMEOUT_SECONDS", "30"))


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
    """Apply the TNC year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_tnc_detail_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover detail-page URLs from the TNC listing HTML.

    Verbatim port of ``extract_tnc_detail_urls`` from the FastAPI
    repo. The extractor checks both:

    * direct ``<a>`` anchors whose href / text / title / aria-label
      carries one of the signal tokens (``edital``, ``chamada``,
      ``tdr``, ``consultoria``, ``documento``), AND
    * ``<span class="articleAggregationDetailsStr" data-details="...">``
      nodes whose JSON payload has ``{link, title, description}``
      entries that match the same signal.

    Detail URLs are filtered to ``/conecte-se/comunicacao/noticias/<slug>``
    on the listing host.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(r"\b(edital|chamada|tdr|consultoria|documento)\b", re.IGNORECASE)

    def _normalize_host(host: str) -> str:
        normalized = host.lower()
        if normalized.startswith("www."):
            return normalized[4:]
        return normalized

    listing_parts = urlsplit(listing_url)
    listing_host = _normalize_host(listing_parts.hostname or "")
    canonical_scheme = listing_parts.scheme
    canonical_netloc = listing_parts.netloc

    def add_candidate_link(href: str, signal_text: str) -> None:
        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        if _normalize_host(normalized.hostname or "") != listing_host:
            return

        path = normalized.path.rstrip("/")
        if not re.fullmatch(r"/conecte-se/comunicacao/noticias/[^/]+", path):
            return

        if not signal_pattern.search(signal_text):
            return

        canonical = urlunsplit((canonical_scheme, canonical_netloc, path, "", ""))
        if canonical in seen:
            return

        seen.add(canonical)
        discovered.append(canonical)

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
        add_candidate_link(href, signal_text)

    for payload_node in soup.find_all("span", class_="articleAggregationDetailsStr"):
        if not isinstance(payload_node, Tag):
            continue

        payload_text = payload_node.get("data-details")
        if not isinstance(payload_text, str) or not payload_text.strip():
            payload_text = payload_node.get_text(strip=True)
        if not isinstance(payload_text, str) or not payload_text:
            continue

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue

        if not isinstance(payload, list):
            continue

        for payload_item in payload:
            if not isinstance(payload_item, dict):
                continue

            payload_link = payload_item.get("link")
            if not isinstance(payload_link, str) or not payload_link:
                continue

            payload_signal_text = " ".join(
                [
                    payload_link,
                    str(payload_item.get("title") or ""),
                    str(payload_item.get("description") or ""),
                ]
            )
            add_candidate_link(payload_link, payload_signal_text)

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
    min_year: int = TNC_MIN_NOTICE_YEAR,
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
        "source": "tnc",
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
    min_year: int = TNC_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover TNC edital PDF candidates from the listing + detail pages.

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
        listing_html = fetch_html_with_retry(
            TNC_LISTING_URL,
            timeout=TNC_FETCH_TIMEOUT_SECONDS,
            max_attempts=TNC_FETCH_MAX_ATTEMPTS,
            backoff_seconds=TNC_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch TNC listing %s: %s",
            TNC_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates

    detail_urls = extract_tnc_detail_urls(listing_html, TNC_LISTING_URL)

    for detail_url in detail_urls:
        if details_fetched >= TNC_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {TNC_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            detail_pdfs = discover_pdf_urls_on_page(detail_url, stats=stats)
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on TNC detail %s: %s",
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
                listing_url=TNC_LISTING_URL,
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
            if len(candidates) >= TNC_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {TNC_MAX_CANDIDATES_PER_RUN}",
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
    print(f"TNC discovery stats: {stats}")
    print(f"TNC candidates discovered: {len(candidates)}")

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
    print(f"TNC processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered TNC candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="tnc")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered TNC candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())