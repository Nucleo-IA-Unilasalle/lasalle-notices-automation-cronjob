"""BRDE BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/brde.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="brde")`` for
download / OCR / submit.

The BRDE source fans out across two listings:

1. ``https://www.brde.com.br/palacete/editais/`` — ``Palacete`` page
   with direct PDF anchors grouped under explicit lifecycle headings.
2. ``https://www.brde.com.br/producao/?tab=ci`` — the current FSA
   Production listing. Each current detail page is checked for an active
   application period before its principal edital PDF is admitted.

Filter pipeline (per plan §9):
- ``BRDE_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
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

import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)


BRDE_PALACETE_LISTING_URL = "https://www.brde.com.br/palacete/editais/"
BRDE_FSA_LISTING_URL = "https://www.brde.com.br/producao/?tab=ci"

BRDE_MIN_NOTICE_YEAR = int(os.environ.get("BRDE_MIN_NOTICE_YEAR", "2026"))

BRDE_MAX_CANDIDATES_PER_RUN = int(os.environ.get("BRDE_MAX_CANDIDATES_PER_RUN", "50"))
BRDE_MAX_DETAILS_PER_RUN = int(os.environ.get("BRDE_MAX_DETAILS_PER_RUN", "20"))
BRDE_FETCH_MAX_ATTEMPTS = int(os.environ.get("BRDE_FETCH_MAX_ATTEMPTS", "3"))
BRDE_FETCH_BACKOFF_SECONDS = float(os.environ.get("BRDE_FETCH_BACKOFF_SECONDS", "2"))
BRDE_FETCH_TIMEOUT_SECONDS = int(os.environ.get("BRDE_FETCH_TIMEOUT_SECONDS", "30"))


# Matches a 4-digit year token bounded by non-digit boundaries. The BRDE
# PDF slugs and detail slugs carry the year in English (e.g.
# ``edital-de-patrocinio-brde-cultural-2026-1.pdf``, ``errata-edital-de-ocupacao-2024-2025-1.pdf``),
# so this regex is sufficient for BRDE today.
_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_APPLICATION_PERIOD_PATTERN = re.compile(
    r"periodo\s+de\s+inscricoes\s*:\s*"
    r"(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return " ".join(
        normalized.encode("ascii", "ignore").decode("ascii").lower().split()
    )


def _normalized_brde_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _is_official_brde_url(url: str) -> bool:
    return _normalized_brde_host(url) == "brde.com.br"


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
    """Apply the BRDE year guard per plan §9.

    URLs without a discoverable year pass through (recorded in
    candidate metadata for operator audit). URLs with a year older
    than ``min_year`` are rejected.
    """
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_brde_palacete_open_pdf_urls(
    listing_html: str,
    listing_url: str,
    *,
    min_year: int,
) -> tuple[list[str], int]:
    """Return PDFs from non-closed Palacete edital sections.

    The page keeps closed editions online. A year guard alone therefore cannot
    establish eligibility; the section heading is the lifecycle authority.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    closed_sections = 0

    for heading in soup.find_all(["h2", "h3", "h4"]):
        if not isinstance(heading, Tag):
            continue
        heading_text = _normalized_text(heading.get_text(" ", strip=True))
        years = [int(match.group(0)) for match in _YEAR_PATTERN.finditer(heading_text)]
        if not years or max(years) < min_year or not heading_text.startswith("edital"):
            continue
        is_closed = "encerrad" in heading_text
        if is_closed:
            closed_sections += 1

        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4"}:
                break
            if not isinstance(sibling, Tag):
                continue
            for link in sibling.find_all("a"):
                if not isinstance(link, Tag):
                    continue
                href = link.get("href")
                if not isinstance(href, str) or not href.strip():
                    continue
                resolved = urljoin(listing_url, href.strip())
                if (
                    not looks_like_pdf_url(resolved)
                    or not _is_official_brde_url(resolved)
                    or is_closed
                ):
                    continue
                if resolved not in seen:
                    seen.add(resolved)
                    discovered.append(resolved)

    return discovered, closed_sections


def extract_brde_fsa_detail_urls(
    listing_html: str,
    listing_url: str,
    *,
    min_year: int | None = None,
) -> list[str]:
    """Discover detail-page URLs from the BRDE FSA listing.

    BRDE moved current calls from ``/fsa/chamada-publica-...`` to root-level
    ``/chamada-publica-...`` pages and occasionally publishes whitespace in
    an absolute href. Both official path forms are accepted, while unrelated
    BRDE pages and cross-host links remain excluded.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    listing_host = _normalized_brde_host(listing_url)

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue

        resolved = urljoin(listing_url, href.strip())
        normalized = urlsplit(resolved)
        if _normalized_brde_host(resolved) != listing_host:
            continue

        # The live Portugal 2026 link contains one erroneous space after the
        # host slash. Repair only that bounded leading-path defect.
        path = re.sub(r"^/\s+", "/", normalized.path).rstrip("/")
        if not re.match(r"^/(?:fsa/)?chamada-publica-brde-fsa-", path):
            continue
        if min_year is not None and not _passes_year_guard(
            resolved, min_year=min_year,
        ):
            continue

        canonical = urlunsplit(("https", normalized.netloc, path, "", ""))
        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def extract_brde_application_period(detail_html: str) -> tuple[date, date] | None:
    """Extract the official application period from an FSA detail page."""
    text = _normalized_text(
        BeautifulSoup(detail_html, "html.parser").get_text(" ", strip=True)
    )
    match = _APPLICATION_PERIOD_PATTERN.search(text)
    if not match:
        return None
    try:
        start = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        end = datetime.strptime(match.group(2), "%d/%m/%Y").date()
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def extract_brde_principal_edital_pdf_urls(
    detail_html: str,
    detail_url: str,
) -> list[str]:
    """Return only principal edital PDFs, excluding FAQs, results and annexes."""
    soup = BeautifulSoup(detail_html, "html.parser")
    exact: list[str] = []
    complete: list[str] = []
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        resolved = urljoin(detail_url, href.strip())
        if not looks_like_pdf_url(resolved) or not _is_official_brde_url(resolved):
            continue
        label = _normalized_text(link.get_text(" ", strip=True))
        if label == "edital":
            exact.append(resolved)
        elif label.startswith("edital completo"):
            complete.append(resolved)
    return list(dict.fromkeys(exact or complete))


def _fsa_listing_looks_valid(listing_html: str) -> bool:
    soup = BeautifulSoup(listing_html, "html.parser")
    content = soup.select_one(".page-content")
    if content is None:
        return False
    text = _normalized_text(content.get_text(" ", strip=True))
    return "producao" in text and "chamadas publicas" in text


def _palacete_listing_looks_valid(listing_html: str) -> bool:
    soup = BeautifulSoup(listing_html, "html.parser")
    content = soup.select_one(".page-content")
    if content is None:
        return False
    return any(
        _normalized_text(heading.get_text(" ", strip=True)).startswith("edital")
        for heading in content.find_all(["h1", "h2", "h3", "h4"])
    )


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
    min_year: int = BRDE_MIN_NOTICE_YEAR,
    origin: str | None = None,
    application_start: date | None = None,
    application_deadline: date | None = None,
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
        "source": "brde",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url
    if application_start is not None:
        metadata["application_start"] = application_start.isoformat()
    if application_deadline is not None:
        metadata["application_deadline"] = application_deadline.isoformat()
        metadata["status"] = "open"

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = BRDE_MIN_NOTICE_YEAR,
    as_of_date: date | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover BRDE edital PDF candidates from the Palacete + FSA listings.

    Returns ``(stats, candidates)``.
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "prefilter_rejected": 0,
        "year_rejected": 0,
        "errors": 0,
        "partial_inventory": 0,
        "candidate_cap_reached": 0,
        "detail_cap_reached": 0,
        "open_details": 0,
        "closed_details": 0,
        "upcoming_details": 0,
        "missing_lifecycle": 0,
        "palacete_closed_sections": 0,
    }
    if as_of_date is None:
        as_of_date = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    details_fetched = 0

    def _ingest_pdf(
        pdf_url: str,
        *,
        listing_url: str,
        detail_url: str | None,
        origin: str,
        application_period: tuple[date, date] | None = None,
    ) -> bool:
        if pdf_url in seen_urls:
            return True
        seen_urls.add(pdf_url)
        candidate = build_candidate(
            pdf_url,
            listing_url=listing_url,
            detail_url=detail_url,
            filter_policy=filter_policy,
            min_year=min_year,
            origin=origin,
            application_start=application_period[0] if application_period else None,
            application_deadline=application_period[1] if application_period else None,
        )
        if candidate is None:
            if not _passes_year_guard(pdf_url, min_year=min_year):
                stats["year_rejected"] += 1
            else:
                stats["prefilter_rejected"] += 1
            return True
        candidates.append(candidate)
        return False

    def _hit_candidate_cap() -> bool:
        if len(candidates) < BRDE_MAX_CANDIDATES_PER_RUN:
            return False
        stats["candidate_cap_reached"] = 1
        print(
            f"Stopping after candidate cap {BRDE_MAX_CANDIDATES_PER_RUN}",
            file=sys.stderr,
        )
        return True

    def _record_discovery_error() -> None:
        stats["errors"] = stats.get("errors", 0) + 1
        stats["partial_inventory"] = 1

    def _mark_partial_inventory() -> None:
        if stats.get("errors"):
            stats["partial_inventory"] = 1

    palacete_pdfs: list[str] = []
    try:
        palacete_html = fetch_html_with_retry(
            BRDE_PALACETE_LISTING_URL,
            timeout=BRDE_FETCH_TIMEOUT_SECONDS,
            max_attempts=BRDE_FETCH_MAX_ATTEMPTS,
            backoff_seconds=BRDE_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
        if not _palacete_listing_looks_valid(palacete_html):
            raise RuntimeError("BRDE Palacete listing structure is unrecognized")
        palacete_pdfs, closed_sections = extract_brde_palacete_open_pdf_urls(
            palacete_html,
            BRDE_PALACETE_LISTING_URL,
            min_year=min_year,
        )
        stats["palacete_closed_sections"] = closed_sections
    except Exception as exc:
        log_source_failure(
            "Failed to fetch BRDE Palacete listing %s: %s",
            BRDE_PALACETE_LISTING_URL,
            exc,
            exc=exc,
        )
        _record_discovery_error()

    for pdf_url in palacete_pdfs:
        if _ingest_pdf(
            pdf_url,
            listing_url=BRDE_PALACETE_LISTING_URL,
            detail_url=None,
            origin="listing_pdf",
        ):
            continue
        if _hit_candidate_cap():
            _mark_partial_inventory()
            stats["candidates"] = len(candidates)
            return stats, candidates

    fsa_detail_urls: list[str] = []
    try:
        fsa_html = fetch_html_with_retry(
            BRDE_FSA_LISTING_URL,
            timeout=BRDE_FETCH_TIMEOUT_SECONDS,
            max_attempts=BRDE_FETCH_MAX_ATTEMPTS,
            backoff_seconds=BRDE_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
        if not _fsa_listing_looks_valid(fsa_html):
            raise RuntimeError("BRDE FSA Production listing structure is unrecognized")
        fsa_detail_urls = extract_brde_fsa_detail_urls(
            fsa_html,
            BRDE_FSA_LISTING_URL,
            min_year=min_year,
        )
    except Exception as exc:
        log_source_failure(
            "Failed to fetch BRDE FSA listing %s: %s",
            BRDE_FSA_LISTING_URL,
            exc,
            exc=exc,
        )
        _record_discovery_error()

    for detail_url in fsa_detail_urls:
        if details_fetched >= BRDE_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {BRDE_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            stats["detail_cap_reached"] = 1
            stats["partial_inventory"] = 1
            break
        try:
            detail_html = fetch_html_with_retry(
                detail_url,
                timeout=BRDE_FETCH_TIMEOUT_SECONDS,
                max_attempts=BRDE_FETCH_MAX_ATTEMPTS,
                backoff_seconds=BRDE_FETCH_BACKOFF_SECONDS,
                allowed_status_codes=(401, 403, 404, 410),
            )
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on BRDE FSA detail %s: %s",
                detail_url,
                exc,
                exc=exc,
            )
            _record_discovery_error()
            continue
        details_fetched += 1
        stats["details_fetched"] += 1
        application_period = extract_brde_application_period(detail_html)
        if application_period is None:
            stats["missing_lifecycle"] += 1
            _record_discovery_error()
            continue
        application_start, application_deadline = application_period
        if as_of_date < application_start:
            stats["upcoming_details"] += 1
            continue
        if as_of_date >= application_deadline:
            stats["closed_details"] += 1
            continue
        stats["open_details"] += 1
        detail_pdfs = extract_brde_principal_edital_pdf_urls(
            detail_html, detail_url,
        )
        if not detail_pdfs:
            _record_discovery_error()
            continue
        for pdf_url in detail_pdfs:
            if _ingest_pdf(
                pdf_url,
                listing_url=BRDE_FSA_LISTING_URL,
                detail_url=detail_url,
                origin="detail_page",
                application_period=application_period,
            ):
                continue
            if _hit_candidate_cap():
                _mark_partial_inventory()
                stats["candidates"] = len(candidates)
                return stats, candidates

    _mark_partial_inventory()
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
    print(f"BRDE discovery stats: {stats}")
    print(f"BRDE candidates discovered: {len(candidates)}")
    discovery_incomplete = bool(stats.get("errors") or stats.get("partial_inventory"))
    if discovery_incomplete:
        print(
            "error: BRDE discovery reported errors; inventory is partial",
            file=sys.stderr,
        )

    if not candidates:
        print("No new candidates to submit")
        return 1 if discovery_incomplete else 0

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
    print(f"BRDE processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered BRDE candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="brde")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered BRDE candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 1 if discovery_incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
