"""WWF BeautifulSoup source discoverer for the cronjob pipeline.

Phase 3 port of
``lasalle-notices-automation/app/services/scraper/sources/wwf.py``.
The original function took ``self: ScrapperService`` and called
``self.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="wwf")`` for
download / OCR / submit.

The WWF source fans out from a single listing page at
``https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/`` that
organises opportunities into two structural sections:

* ``EDITAIS ABERTOS`` — open editais (``status="open"``).
* ``EDITAIS ENCERRADOS`` — closed editais (``status="closed"``).

Plan 02 ("WWF Discovery Precision Repair") requires that we parse those
sections **structurally** rather than scanning every anchor on the page.
Only detail URLs belonging to parsed edital rows are followed, and PDFs
are extracted only from the detail content area. Generic supplier
documents (``documentos-necessarios``, ``requisitos-basicos``,
proposal-model, supplier-portal) are rejected even when they look like
PDFs.

The discoverer emits two ADDITIVE outputs:

* ``(stats, candidates)`` — the unchanged kind="pdf" candidate flow that
  ``main()`` feeds into the download/OCR/submit pipeline.
* ``build_inventory(...)`` — a Plan-01 compatible list of normalized
  records (one per parsed edital row) used by audit mode.

If the listing HTML does not contain both edital section headings or yields
no structural rows, discovery records a failure and does NOT report a healthy
zero-result run.

Filter pipeline (per plan §9):
- ``WWF_MIN_NOTICE_YEAR`` (default ``2026``) drops URLs whose
  extracted year is older than the threshold. URLs without a
  discoverable year pass through with no extracted_year (recorded in
  the candidate metadata so operators can audit it).
- ``scraper_filters.is_likely_edital`` drops URLs whose filename
  matches an EDITAL exclusion pattern. ``filter_policy="default"``
  matches the FastAPI source's behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)


WWF_LISTING_URL = "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/"

WWF_MIN_NOTICE_YEAR = int(os.environ.get("WWF_MIN_NOTICE_YEAR", "2026"))

WWF_MAX_CANDIDATES_PER_RUN = int(os.environ.get("WWF_MAX_CANDIDATES_PER_RUN", "50"))
WWF_MAX_DETAILS_PER_RUN = int(os.environ.get("WWF_MAX_DETAILS_PER_RUN", "20"))
WWF_FETCH_MAX_ATTEMPTS = int(os.environ.get("WWF_FETCH_MAX_ATTEMPTS", "3"))
WWF_FETCH_BACKOFF_SECONDS = float(os.environ.get("WWF_FETCH_BACKOFF_SECONDS", "2"))
WWF_FETCH_TIMEOUT_SECONDS = int(os.environ.get("WWF_FETCH_TIMEOUT_SECONDS", "30"))


# Matches a 4-digit year token bounded by non-digit boundaries.
_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")

# Section headings that delimit the open/closed edital tables. Anchored
# against a normalized (whitespace-collapsed, trimmed) heading so a
# substring like "Veja os EDITAIS ABERTOS abaixo" does not falsely start a
# section.
_OPEN_HEADING = re.compile(r"^\s*edit\s*a\s*is\s+abertos\s*$", re.IGNORECASE)
_CLOSED_HEADING = re.compile(r"^\s*edit\s*a\s*is\s+encerrados\s*$", re.IGNORECASE)

# Stable process-number patterns used by both recorded and current WWF rows.
_PROCESS_NUMBER_PATTERN = re.compile(
    r"processo(?:\s+de\s+contrata[cç][aã]o)?\s*(?:n[ºo°.]?\s*)?(\d{4,})",
    re.IGNORECASE,
)

# Best-effort publication date like "Publicado em 16/07/2026".
_PUBLISHED_AT_PATTERN = re.compile(
    r"publicad[oa]\s+em\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE,
)
_PUBLISHED_AT_TEXT_PATTERN = re.compile(
    r"(?:^|\s)(\d{1,2})\s+"
    r"(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\s+"
    r"(\d{4})(?:\s|$)",
    re.IGNORECASE,
)
_PORTUGUESE_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

# Additional generic supplier-asset rejections layered on top of the
# edital prefilter (Plan 02 §"Reject listing-level ...").
_GENERIC_SUPPLIER_PATTERNS = [
    r"documentos[-_ ]?necessarios",
    r"requisitos[-_ ]?basicos",
    r"modelo.*proposta|proposta.*modelo",
    r"portal.*fornecedor|fornecedor.*portal",
]

# Edital-component documents that Plan 02 requires us to retain even
# though the base edital prefilter lists them as exclusions. They are
# reached only through a parsed edital row's detail page, so they belong
# to the edital.
_EDITAL_COMPONENT_PATTERNS = [
    r"retificacao",
    r"errata",
    r"anexo",
]


StatusValue = Literal["open", "closed"]


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
    """Apply the WWF year guard per plan §9."""
    year = _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def extract_wwf_detail_urls(listing_html: str, listing_url: str) -> list[str]:
    """Discover detail-page URLs from the WWF listing HTML.

    Verbatim port of ``extract_wwf_detail_urls`` from the FastAPI
    repo. The extractor matches same-host anchors whose path lives
    under ``/sobrenos/aquisicoesecontratacoes`` and whose query carries
    either a current numeric content ID or a legacy numeric ``uNewsID``.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()
    listing_host = (urlsplit(listing_url).hostname or "").lower()
    allowed_path = "/sobrenos/aquisicoesecontratacoes"

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)

        if (normalized.hostname or "").lower() != listing_host:
            continue

        path = normalized.path
        path_no_slash = path.rstrip("/")
        if path_no_slash != allowed_path and not path_no_slash.startswith(f"{allowed_path}/"):
            continue

        if _extract_detail_id(normalized.geturl()) is None:
            continue

        detail_url = urlunsplit((normalized.scheme, normalized.netloc, path, normalized.query, ""))
        if detail_url in seen:
            continue

        seen.add(detail_url)
        discovered.append(detail_url)

    return discovered


def _is_generic_supplier_asset(url: str) -> bool:
    """Return True for generic supplier assets that Plan 02 rejects."""
    text = url.lower()
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _GENERIC_SUPPLIER_PATTERNS)


def _candidate_passes_edital_prefilter(
    url: str, filter_policy: FilterPolicy = "default",
) -> bool:
    """Apply the EDITAL inclusion/exclusion patterns to a candidate URL.

    Generic supplier assets are rejected first. Edital-component documents
    (retificacao / errata / anexo) reached via a parsed edital row's detail
    page are always retained, overriding the base prefilter's exclusions.
    Everything else defers to ``is_likely_edital``.
    """
    if _is_generic_supplier_asset(url):
        return False
    text = url.lower()
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _EDITAL_COMPONENT_PATTERNS):
        return True
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    return is_likely_edital(filename, url, filter_policy=filter_policy)


def _collect_section_tags(
    start_heading: Tag,
    stop_headings: tuple[re.Pattern[str], ...],
) -> list[Tag]:
    """Return the tags belonging to one section: the heading itself plus its
    following siblings until the next section heading (or end of parent).

    Walking siblings (not ``next_elements``) avoids re-emitting nested
    descendants, so each edital row anchor is seen exactly once.
    """
    collected: list[Tag] = [start_heading]
    for sibling in start_heading.next_siblings:
        if not isinstance(sibling, Tag):
            continue
        text = sibling.get_text(" ", strip=True)
        if any(pattern.match(text) for pattern in stop_headings):
            break
        collected.append(sibling)
    return collected


def _split_sections(listing_html: str) -> tuple[list[Tag], list[Tag]] | None:
    """Split the listing into (open_section_tags, closed_section_tags).

    Returns ``None`` when either edital heading is absent (selector
    drift) so the caller can record a failure instead of a silent
    zero-result run.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    open_string = next(
        (
            h for h in soup.find_all(string=True)
            if isinstance(h, str) and _OPEN_HEADING.match(h)
        ),
        None,
    )
    closed_string = next(
        (
            h for h in soup.find_all(string=True)
            if isinstance(h, str) and _CLOSED_HEADING.match(h)
        ),
        None,
    )
    if open_string is None or closed_string is None:
        return None

    open_tags: list[Tag] = []
    if isinstance(open_string, NavigableString) and isinstance(open_string.parent, Tag):
        open_tags = _collect_section_tags(open_string.parent, (_CLOSED_HEADING, _OPEN_HEADING))
    closed_tags: list[Tag] = []
    if isinstance(closed_string, NavigableString) and isinstance(closed_string.parent, Tag):
        closed_tags = _collect_section_tags(closed_string.parent, (_OPEN_HEADING, _CLOSED_HEADING))
    return open_tags, closed_tags


def _extract_detail_id(url: str) -> str | None:
    """Return the WWF content id from legacy or current detail URLs."""
    parsed = urlsplit(url)
    legacy_ids = parse_qs(parsed.query).get("uNewsID")
    if legacy_ids and len(legacy_ids) == 1 and legacy_ids[0].isdigit():
        return legacy_ids[0]
    current_match = re.match(r"^(\d+)(?:/|$)", parsed.query)
    return current_match.group(1) if current_match else None


def _extract_published_at(text: str) -> str | None:
    numeric_match = _PUBLISHED_AT_PATTERN.search(text)
    if numeric_match is not None:
        day, month, year = numeric_match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}T00:00:00Z"
    text_match = _PUBLISHED_AT_TEXT_PATTERN.search(text)
    if text_match is None:
        return None
    day, month_name, year = text_match.groups()
    month = _PORTUGUESE_MONTHS[month_name.lower()]
    return f"{year}-{month:02d}-{int(day):02d}T00:00:00Z"


def _parse_edital_rows(
    section_tags: list[Tag],
    status: StatusValue,
    *,
    listing_url: str,
) -> list[dict[str, Any]]:
    """Parse edital rows from one section's tag list into row dicts."""
    if not section_tags:
        return []
    rows: list[dict[str, Any]] = []
    wrapper = BeautifulSoup("<div></div>", "html.parser").div
    assert isinstance(wrapper, Tag)
    for container in section_tags:
        if isinstance(container, Tag):
            wrapper.append(container)
    for anchor in wrapper.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str) or not href:
            continue
        normalized = urlsplit(urljoin(listing_url, href))
        listing = urlsplit(listing_url)
        if normalized.hostname != listing.hostname or normalized.path.rstrip("/") != listing.path.rstrip("/"):
            continue
        detail_id = _extract_detail_id(normalized.geturl())
        if detail_id is None:
            continue
        detail_url = urlunsplit((normalized.scheme, normalized.netloc, normalized.path, normalized.query, ""))
        text = anchor.get_text(" ", strip=True)
        process_match = _PROCESS_NUMBER_PATTERN.search(text)
        if process_match:
            source_record_id = process_match.group(1)
        else:
            source_record_id = detail_id
        published = _extract_published_at(text)
        if published is None:
            published = _extract_published_at(anchor.parent.get_text(" ", strip=True))
        rows.append(
            {
                "source_record_id": source_record_id,
                "title": text,
                "status": status,
                "canonical_url": detail_url,
                "listing_url": listing_url,
                "published_at": published,
                "deadline": None,
                "document_urls": [],
                "document_hashes": [],
            }
        )
    return rows


def parse_listing_sections(
    listing_html: str,
    listing_url: str = WWF_LISTING_URL,
) -> list[dict[str, Any]] | None:
    """Parse both edital sections into a list of row dicts.

    Returns ``None`` when the listing lacks either edital heading (selector
    drift). Otherwise returns the combined open + closed rows.
    """
    sections = _split_sections(listing_html)
    if sections is None:
        return None
    open_tags, closed_tags = sections
    open_rows = _parse_edital_rows(open_tags, "open", listing_url=listing_url)
    closed_rows = _parse_edital_rows(closed_tags, "closed", listing_url=listing_url)
    return open_rows + closed_rows


def _extract_detail_pdf_urls(page_html: str, detail_url: str) -> list[str]:
    """Extract PDF URLs only from the detail content area.

    Filtering is applied by the inventory/candidate callers after extraction.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    content_area = soup.select_one("div.template433, div.page-content")
    if content_area is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for link in content_area.find_all("a", href=lambda h: bool(h and looks_like_pdf_url(h))):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        pdf_url = urljoin(detail_url, href)
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        found.append(pdf_url)
    return found


def build_inventory(
    *,
    listing_html: str,
    detail_responses: dict[str, str],
    listing_url: str = WWF_LISTING_URL,
) -> tuple[list[dict[str, Any]], bool]:
    """Build a Plan-01 compatible inventory list from parsed edital rows.

    Returns ``(inventory, sections_present)``. Each inventory record is a
    normalized dict with ``source_key`` plus the Plan-01 fields. PDFs are
    extracted per-detail via ``_extract_detail_pdf_urls`` and the edital
    prefilter + generic-supplier rejection are applied.

    When the listing lacks either edital heading, ``sections_present`` is False
    and an empty inventory is returned (caller decides how to record the
    failure).
    """
    rows = parse_listing_sections(listing_html, listing_url)
    if rows is None:
        return [], False

    inventory: list[dict[str, Any]] = []
    for row in rows:
        detail_url = row["canonical_url"]
        doc_urls: list[str] = []
        if detail_url in detail_responses:
            for pdf_url in _extract_detail_pdf_urls(detail_responses[detail_url], detail_url):
                if not _candidate_passes_edital_prefilter(pdf_url):
                    continue
                if pdf_url not in doc_urls:
                    doc_urls.append(pdf_url)
        record: dict[str, Any] = {
            "source_key": "wwf",
            "source_record_id": row["source_record_id"],
            "canonical_url": row["canonical_url"],
            "title": row["title"],
            "status": row["status"],
            "published_at": row["published_at"],
            "deadline": row["deadline"],
            "document_urls": doc_urls,
            "document_hashes": row["document_hashes"],
        }
        inventory.append(record)
    return inventory, True


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    filter_policy: FilterPolicy = "default",
    min_year: int = WWF_MIN_NOTICE_YEAR,
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
        "source": "wwf",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url

    return {"url": url, "kind": "pdf", "metadata": metadata}


def _discover_candidates_and_inventory(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = WWF_MIN_NOTICE_YEAR,
    listing_url: str = WWF_LISTING_URL,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    """Discover WWF edital PDF candidates from the listing + detail pages.

    Returns ``(stats, candidates, inventory)``. The candidate flow
    (download/OCR/submit) is unchanged; the inventory supports audit mode.
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "prefilter_rejected": 0,
        "year_rejected": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
        "section_parse_failed": 0,
        "detail_parse_failed": 0,
    }
    candidates: list[dict[str, Any]] = []
    seen_pdfs: set[str] = set()
    details_fetched = 0

    try:
        listing_html = fetch_html_with_retry(
            listing_url,
            timeout=WWF_FETCH_TIMEOUT_SECONDS,
            max_attempts=WWF_FETCH_MAX_ATTEMPTS,
            backoff_seconds=WWF_FETCH_BACKOFF_SECONDS,
            allowed_status_codes=(401, 403, 404, 410),
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch WWF listing %s: %s",
            listing_url,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates, []

    rows = parse_listing_sections(listing_html, listing_url)
    if rows is None or not rows:
        log_source_failure(
            "WWF listing %s has missing edital sections or no parsed rows; selector drift suspected",
            listing_url,
            exc=ValueError("WWF listing missing edital sections or parsed rows"),
        )
        stats["section_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
        stats["candidates"] = 0
        return stats, candidates, []

    detail_pdf_records: list[tuple[str, str, dict[str, Any]]] = []
    detail_responses: dict[str, str] = {}
    for row in rows:
        detail_url = row["canonical_url"]
        if details_fetched >= WWF_MAX_DETAILS_PER_RUN:
            print(
                f"Stopping after detail fetch cap {WWF_MAX_DETAILS_PER_RUN}",
                file=sys.stderr,
            )
            break
        try:
            page_html = fetch_html_with_retry(
                detail_url,
                timeout=WWF_FETCH_TIMEOUT_SECONDS,
                max_attempts=WWF_FETCH_MAX_ATTEMPTS,
                backoff_seconds=WWF_FETCH_BACKOFF_SECONDS,
                allowed_status_codes=(401, 403, 404, 410),
            )
        except Exception as exc:
            log_source_failure(
                "Failed to fetch WWF detail %s: %s",
                detail_url,
                exc,
                exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        details_fetched += 1
        stats["details_fetched"] += 1
        content_area = BeautifulSoup(page_html, "html.parser").select_one(
            "div.template433, div.page-content",
        )
        if content_area is None:
            log_source_failure(
                "WWF detail %s missing record content area; selector drift suspected",
                detail_url,
                exc=ValueError("WWF detail missing record content area"),
            )
            stats["detail_parse_failed"] += 1
            stats["errors"] += 1
            continue
        detail_responses[detail_url] = page_html
        for pdf_url in _extract_detail_pdf_urls(page_html, detail_url):
            detail_pdf_records.append((pdf_url, detail_url, row))

    inventory, _sections_present = build_inventory(
        listing_html=listing_html,
        detail_responses=detail_responses,
        listing_url=listing_url,
    )

    for pdf_url, detail_url, row in detail_pdf_records:
        if pdf_url in seen_pdfs:
            continue
        seen_pdfs.add(pdf_url)
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
        candidate["metadata"]["source_record_id"] = row["source_record_id"]
        candidate["metadata"]["status"] = row["status"]
        candidate["metadata"]["title"] = row["title"]
        candidate["metadata"]["published_at"] = row["published_at"]
        candidates.append(candidate)
        if len(candidates) >= WWF_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(
                f"Stopping after candidate cap {WWF_MAX_CANDIDATES_PER_RUN}",
                file=sys.stderr,
            )
            stats["candidates"] = len(candidates)
            return stats, candidates, inventory

    stats["candidates"] = len(candidates)
    return stats, candidates, inventory


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = WWF_MIN_NOTICE_YEAR,
    listing_url: str = WWF_LISTING_URL,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover WWF candidates for the existing processing pipeline."""
    stats, candidates, _inventory = _discover_candidates_and_inventory(
        filter_policy=filter_policy,
        min_year=min_year,
        listing_url=listing_url,
    )
    return stats, candidates


def _write_audit_artifacts(
    output_dir: Path,
    *,
    inventory: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    stats: dict[str, int],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records_by_id = {record["source_record_id"]: record for record in inventory}
    discovery_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        metadata = candidate.get("metadata", {})
        record_id = metadata.get("source_record_id")
        inventory_record = records_by_id.get(record_id)
        if not isinstance(record_id, str) or inventory_record is None:
            continue
        record = discovery_by_id.setdefault(
            record_id,
            {**inventory_record, "document_urls": [], "document_hashes": []},
        )
        if candidate["url"] not in record["document_urls"]:
            record["document_urls"].append(candidate["url"])

    payloads = {
        "source_inventory.json": inventory,
        "discovery.json": list(discovery_by_id.values()),
        "candidates.json": candidates,
        "stats.json": stats,
    }
    for filename, payload in payloads.items():
        (output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover WWF edital documents")
    parser.add_argument(
        "--audit-dir",
        type=Path,
        help="Run without OCR/submission and write inventory/discovery JSON artifacts",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or [])
    if args.audit_dir is not None:
        stats, candidates, inventory = _discover_candidates_and_inventory()
        _write_audit_artifacts(
            args.audit_dir,
            inventory=inventory,
            candidates=candidates,
            stats=stats,
        )
        print(f"WWF audit stats: {stats}")
        print(f"WWF audit artifacts: {args.audit_dir}")
        return 1 if stats.get("errors", 0) or stats.get("section_parse_failed", 0) else 0

    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"WWF discovery stats: {stats}")
    print(f"WWF candidates discovered: {len(candidates)}")

    if stats.get("errors", 0) or stats.get("section_parse_failed", 0):
        print("error: WWF discovery reported source/parser failures", file=sys.stderr)
        return 1

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
    print(f"WWF processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered WWF candidates failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source="wwf")
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered WWF candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
