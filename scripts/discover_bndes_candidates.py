"""BNDES BeautifulSoup source discoverer for the cronjob pipeline.

Phase 2 port of
``lasalle-notices-automation/app/services/scraper/sources/bndes.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="bndes")`` for
download / OCR / submit.

Listing pages (BNDES Fundo Socioambiental + Chamada de Inovação) are
fetched with ``scraper_transport.request_with_safe_redirects``. Direct
PDF anchors on the listing pages become candidates directly; non-PDF
detail anchors trigger a second ``scraper_transport.discover_pdf_urls_on_page``
call to find PDFs hosted on the detail page.

Filter pipeline (per plan §9):
- ``BNDES_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
  extracted year is older than the threshold. URLs without a
  discoverable year pass through with no extracted_year (plan §9
  allows this for sources without reliable date metadata; recorded
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
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import is_likely_edital
from scraper_transport import (
    discover_pdf_urls_on_page,
    log_source_failure,
    looks_like_pdf_url,
    request_with_safe_redirects,
)


BNDES_LISTING_URLS = [
    "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental",
    "https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao",
]

BNDES_MIN_NOTICE_YEAR = int(os.environ.get("BNDES_MIN_NOTICE_YEAR", "2026"))

BNDES_MAX_CANDIDATES_PER_RUN = int(os.environ.get("BNDES_MAX_CANDIDATES_PER_RUN", "50"))
BNDES_MAX_DETAILS_PER_RUN = int(os.environ.get("BNDES_MAX_DETAILS_PER_RUN", "20"))
BNDES_FETCH_MAX_ATTEMPTS = int(os.environ.get("BNDES_FETCH_MAX_ATTEMPTS", "3"))
BNDES_FETCH_BACKOFF_SECONDS = float(os.environ.get("BNDES_FETCH_BACKOFF_SECONDS", "2"))
BNDES_FETCH_TIMEOUT_SECONDS = int(os.environ.get("BNDES_FETCH_TIMEOUT_SECONDS", "30"))


_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _extract_year_from_url(url: str) -> int | None:
    """Return the first 4-digit year found in the URL, or ``None``.

    Searches the URL path and query string for any year in the 1900-2099
    range. Returns the most recent year if multiple are present, since
    the BNDE listing slugs typically carry the edital year in the
    trailing segment (e.g. ``chamada-publica-periferias-2026``).
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
    """Apply the BNDE year guard per plan §9.

    URLs without a discoverable year pass through (recorded in
    candidate metadata for operator audit). URLs with a year older
    than ``min_year`` are rejected.
    """
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


# ---------------------------------------------------------------------------
# Verbatim port of FastAPI ``extract_bndes_detail_and_pdf_urls``.
# ---------------------------------------------------------------------------

def extract_bndes_detail_and_pdf_urls(listing_html: str, listing_url: str) -> list[str]:
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(
        r"\b(edital|chamada|cpsi|inovacao|fundo-socioambiental|periferias|corais|sertao)\b",
        re.IGNORECASE,
    )
    allowed_urile_segments = frozenset({"bndes-periferias", "bndes-corais", "sertao-mais-produtivo"})

    def _normalize_host(host: str) -> str:
        normalized = host.lower()
        if normalized.startswith("www."):
            return normalized[4:]
        return normalized

    def _normalize_urile_value(urile_value: str) -> str:
        return urile_value.strip().lower().rstrip("/")

    def _is_allowed_urile_route(urile_value: str) -> bool:
        normalized_urile = _normalize_urile_value(urile_value)
        urile_path = normalized_urile
        if ":" in urile_path:
            urile_path = urile_path.split(":", maxsplit=1)[1]
        path_segments = [segment for segment in urile_path.split("/") if segment]
        return any(segment in allowed_urile_segments for segment in path_segments)

    def _canonical_query_route(query_values: dict[str, list[str]]) -> str:
        urile_values = sorted(
            {
                _normalize_urile_value(urile_value)
                for urile_value in query_values.get("urile", [])
                if isinstance(urile_value, str)
                and urile_value.strip()
                and _is_allowed_urile_route(urile_value)
            }
        )
        return "&".join(f"urile={urile_value}" for urile_value in urile_values)

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        if _normalize_host(normalized.hostname or "") != "bndes.gov.br":
            continue

        path = normalized.path.rstrip("/")
        if not path:
            continue

        query_values = parse_qs(normalized.query)
        urile_values = query_values.get("urile", [])
        is_query_route = bool(urile_values)
        allow_query_route = any(
            _is_allowed_urile_route(urile_value)
            for urile_value in urile_values
            if isinstance(urile_value, str)
        )
        if is_query_route and not allow_query_route:
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

        if re.search(r"/(imprensa|noticias|quem-somos)\b", path, re.IGNORECASE):
            continue

        if looks_like_pdf_url(resolved):
            canonical = urlunsplit((normalized.scheme, normalized.netloc, path, normalized.query, ""))
        elif allow_query_route:
            canonical_query = _canonical_query_route(query_values)
            if not canonical_query:
                continue
            canonical = urlunsplit((normalized.scheme, normalized.netloc, path, canonical_query, ""))
        else:
            canonical = urlunsplit((normalized.scheme, normalized.netloc, path, "", ""))

        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def _candidate_passes_edital_prefilter(
    url: str, filter_policy: str = "default"
) -> bool:
    """Apply the EDITAL inclusion/exclusion patterns to a candidate URL."""
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    return is_likely_edital(filename, url, filter_policy=filter_policy)  # type: ignore[arg-type]


def _fetch_listing_html(listing_url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, BNDES_FETCH_MAX_ATTEMPTS + 1):
        try:
            response = request_with_safe_redirects(
                method="GET", url=listing_url, timeout=BNDES_FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_error = exc
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {401, 403, 404, 410}:
                raise
            if attempt < BNDES_FETCH_MAX_ATTEMPTS:
                time.sleep(BNDES_FETCH_BACKOFF_SECONDS * attempt)
    assert last_error is not None
    raise last_error


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    filter_policy: str = "default",
    min_year: int = BNDES_MIN_NOTICE_YEAR,
    origin: str | None = None,
) -> dict[str, Any] | None:
    """Build a ``kind="pdf"`` candidate or return ``None`` if filtered out."""
    if not _passes_year_guard(url, min_year=min_year):
        return None
    if not _candidate_passes_edital_prefilter(url, filter_policy=filter_policy):
        return None

    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "listing_detail"

    pdf_year = _extract_year_from_url(url)
    inherited_year = _extract_year_from_url(detail_url) if detail_url else None
    extracted_year = pdf_year if pdf_year is not None else inherited_year

    metadata: dict[str, Any] = {
        "source": "bndes",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
        "pdf_year": pdf_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url
        metadata["inherited_year_from_detail_url"] = inherited_year

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates(
    *,
    filter_policy: str = "default",
    min_year: int = BNDES_MIN_NOTICE_YEAR,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover BNDE edital PDF candidates from the two BNDE listing pages.

    Returns ``(stats, candidates)``. The shape matches
    ``discover_pncp_candidates.discover_candidates``'s contract minus
    the discovery timestamp (the cronjob does not need a checkpoint).
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
    seen_urls: set[str] = set()
    details_fetched = 0

    for listing_url in BNDES_LISTING_URLS:
        try:
            listing_html = _fetch_listing_html(listing_url)
        except Exception as exc:
            log_source_failure(
                "Failed to fetch BNDE listing %s: %s", listing_url, exc, exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            continue

        stats["listings_fetched"] += 1
        discovered_urls = extract_bndes_detail_and_pdf_urls(listing_html, listing_url)

        direct_pdfs: list[str] = []
        detail_urls: list[str] = []
        for discovered_url in discovered_urls:
            if looks_like_pdf_url(discovered_url):
                direct_pdfs.append(discovered_url)
            elif discovered_url not in detail_urls:
                detail_urls.append(discovered_url)

        for pdf_url in direct_pdfs:
            if pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)
            candidate = build_candidate(
                pdf_url,
                listing_url=listing_url,
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
            if len(candidates) >= BNDES_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {BNDES_MAX_CANDIDATES_PER_RUN}",
                    file=sys.stderr,
                )
                return stats, candidates

        for detail_url in detail_urls:
            if details_fetched >= BNDES_MAX_DETAILS_PER_RUN:
                print(
                    f"Stopping after detail fetch cap {BNDES_MAX_DETAILS_PER_RUN}",
                    file=sys.stderr,
                )
                break
            try:
                detail_pdfs = discover_pdf_urls_on_page(detail_url, stats=stats)
            except Exception as exc:
                log_source_failure(
                    "Failed to discover PDFs on BNDE detail %s: %s", detail_url, exc, exc=exc,
                )
                stats["errors"] = stats.get("errors", 0) + 1
                continue
            details_fetched += 1
            stats["details_fetched"] += 1
            for pdf_url in detail_pdfs:
                if pdf_url in seen_urls:
                    continue
                seen_urls.add(pdf_url)
                candidate = build_candidate(
                    pdf_url,
                    listing_url=listing_url,
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
                if len(candidates) >= BNDES_MAX_CANDIDATES_PER_RUN:
                    stats["candidate_cap_reached"] = 1
                    print(
                        f"Stopping after candidate cap {BNDES_MAX_CANDIDATES_PER_RUN}",
                        file=sys.stderr,
                    )
                    stats["candidates"] = len(candidates)
                    return stats, candidates

    stats["candidates"] = len(candidates)
    return stats, candidates


def submit_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Backwards-compatible wrapper around :func:`pipeline_core.submit_candidates`.

    Pins ``source="bndes"`` so existing cronjob code that imports
    ``discover_bndes_candidates.submit_candidates`` keeps the same
    surface as the PNCP discoverer.
    """
    return pipeline_core.submit_candidates(candidates, source="bndes")


def main() -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"BNDES discovery stats: {stats}")
    print(f"BNDES candidates discovered: {len(candidates)}")

    if not candidates:
        print("No new candidates to submit")
        return 0

    from ocr_worker.ocr_extraction_config import OCRExtractionConfig
    from ocr_worker.pdf_markdown_extractor import PDFMarkdownExtractor

    ocr_config = OCRExtractionConfig(
        language=os.getenv("KREUZBERG_PADDLE_LANGUAGE", "latin"),
        model_tier=os.getenv("KREUZBERG_PADDLE_MODEL_TIER", "tiny"),
        use_gpu=os.getenv("KREUZBERG_USE_GPU", "false").lower() == "true",
        force_ocr=os.getenv("KREUZBERG_FORCE_OCR_DEFAULT", "false").lower() == "true",
        extraction_timeout_seconds=int(os.getenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", "300")),
    )
    extractor = PDFMarkdownExtractor(ocr_config=ocr_config)
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
    print(f"BNDES processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered BNDE candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = submit_candidates(processed)
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered BNDE candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
