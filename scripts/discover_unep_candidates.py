"""UNEP BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/unep.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="unep")`` for
download / OCR / submit.

The UNEP source is a single listing page at
``https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding``
that hosts ``.pdf`` anchors on the listing itself. The Cloudflare
anti-bot challenge is bypassed because the shared
``scraper_transport.request_with_safe_redirects`` (which
``fetch_html_with_retry`` calls through) sends a browser-style
``User-Agent`` header (the Mozilla/Chrome string defined in
``scraper_transport.DEFAULT_HEADERS``) on every request.

Signal pattern matches ``call[s_-]*for[s_-]*proposals?``,
``concept[\s_-]*note``, ``gfc[\s_-]*fund``,
``applying[\s_-]*for[\s_-]*funding``, ``request[\s_-]*for[\s_-]*proposals?``
(case-insensitive, tolerant of hyphen/underscore/space separators).
PDF anchors whose href / path / text / title / aria-label does not
carry one of those tokens are dropped. Tracking query parameters
(``utm_*``, ``fbclid``, ``gclid``, ``mc_cid``, ``mc_eid``) are
stripped before the URL is canonicalised.

Filter pipeline (per plan §9):
- ``UNEP_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
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
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)


UNEP_LISTING_URL = (
    "https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding"
)

UNEP_MIN_NOTICE_YEAR = int(os.environ.get("UNEP_MIN_NOTICE_YEAR", "2026"))

UNEP_MAX_CANDIDATES_PER_RUN = int(os.environ.get("UNEP_MAX_CANDIDATES_PER_RUN", "50"))
UNEP_FETCH_MAX_ATTEMPTS = int(os.environ.get("UNEP_FETCH_MAX_ATTEMPTS", "3"))
UNEP_FETCH_BACKOFF_SECONDS = float(os.environ.get("UNEP_FETCH_BACKOFF_SECONDS", "2"))
UNEP_FETCH_TIMEOUT_SECONDS = int(os.environ.get("UNEP_FETCH_TIMEOUT_SECONDS", "30"))


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
    """Apply the UNEP year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_unep_pdf_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover PDF URLs from the UNEP listing HTML.

    Verbatim port of ``extract_unep_pdf_urls`` from the FastAPI repo.
    The extractor keeps only ``.pdf`` anchors on the ``unep.org``
    host (and subdomains) that carry one of the UNEP signal tokens
    (``call for proposals``, ``concept note``, ``gfc fund``,
    ``applying for funding``, ``request for proposals``), strips
    tracking query parameters (``utm_*``, ``fbclid``, ``gclid``,
    ``mc_cid``, ``mc_eid``), and canonicalises the netloc to
    ``www.unep.org`` when the host is bare ``unep.org``.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(
        r"(call[\s_-]*for[\s_-]*proposals?|concept[\s_-]*note|gfc[\s_-]*fund|applying[\s_-]*for[\s_-]*funding|request[\s_-]*for[\s_-]*proposals?)",
        re.IGNORECASE,
    )
    tracking_prefixes = ("utm_",)
    tracking_keys = {"fbclid", "gclid", "mc_cid", "mc_eid"}

    def _sanitize_query(raw_query: str) -> str:
        if not raw_query:
            return ""

        query_pairs: list[tuple[str, str]] = []
        for key, values in parse_qs(raw_query, keep_blank_values=True).items():
            key_lower = key.lower()
            if key_lower.startswith(tracking_prefixes) or key_lower in tracking_keys:
                continue
            for value in values:
                query_pairs.append((key, value))

        if not query_pairs:
            return ""

        query_pairs.sort()
        return urlencode(query_pairs, doseq=True)

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
        if host.startswith("www."):
            host = host[4:]
        if host != "unep.org" and not host.endswith(".unep.org"):
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

        sanitized_query = _sanitize_query(normalized.query)
        canonical_netloc = normalized.netloc
        if host == "unep.org" or host == "www.unep.org":
            canonical_netloc = "www.unep.org"
        canonical = urlunsplit((normalized.scheme, canonical_netloc, normalized.path, sanitized_query, ""))
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
    min_year: int = UNEP_MIN_NOTICE_YEAR,
) -> dict[str, Any] | None:
    """Build a ``kind="pdf"`` candidate or return ``None`` if filtered out."""
    if not _passes_year_guard(url, min_year=min_year):
        return None
    if not _candidate_passes_edital_prefilter(url, filter_policy=filter_policy):
        return None

    extracted_year = _extract_year_from_url(url)
    metadata: dict[str, Any] = {
        "source": "unep",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": "listing_pdf",
        "extracted_year": extracted_year,
    }

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = UNEP_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover UNEP edital PDF candidates from the listing page.

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

    try:
        listing_html = fetch_html_with_retry(
            UNEP_LISTING_URL,
            timeout=UNEP_FETCH_TIMEOUT_SECONDS,
            max_attempts=UNEP_FETCH_MAX_ATTEMPTS,
            backoff_seconds=UNEP_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch UNEP listing %s: %s",
            UNEP_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates

    pdf_urls = extract_unep_pdf_urls(listing_html, UNEP_LISTING_URL)
    for pdf_url in pdf_urls:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
        candidate = build_candidate(
            pdf_url,
            listing_url=UNEP_LISTING_URL,
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
        if len(candidates) >= UNEP_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {UNEP_MAX_CANDIDATES_PER_RUN}",
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
    print(f"UNEP discovery stats: {stats}")
    print(f"UNEP candidates discovered: {len(candidates)}")

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
    print(f"UNEP processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered UNEP candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="unep")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered UNEP candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())