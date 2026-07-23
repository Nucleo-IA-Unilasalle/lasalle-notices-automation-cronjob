"""GOVBR-MMA participation-social public-call discoverer for the cronjob.

Plan 03 (``plans/opportunity-sources/03-mma-source-expansion.md``) adds the
MMA *public-calls* participation-social index as a SEPARATE, explicitly
selectable source (``govbr_mma_public_calls``) that must NOT change the
existing ``govbr_mma`` procurement discoverer.

The source is a Plone-backed listing whose ``#content-core
#parent-fieldname-text`` (falling back to ``#content-core``) editorial body
associates year headings (``<h2>2026</h2>``) with the edital links that
follow them. The discoverer:

* restricts parsing to that editorial body (so cross-section navigation /
  footer links are excluded);
* walks the body tracking the most-recent year heading so every edital link
  carries its source year context;
* extracts direct listing PDFs AND follows internal detail pages for the
  principal edital PDFs;
* treats ``resultado`` / ``retificacao`` / ``errata`` / historical support
  documents as RELATED documents of the parent opportunity, never as new
  opportunity identities (they are attached to the parent inventory record's
  ``document_urls`` and must NOT create a separate candidate or inventory
  entry);
* emits a Plan-01-compatible inventory for deterministic fidelity checks.

``source_record_id`` uses the canonical detail URL (or a normalized
edital title + year when the source supplies no explicit ID). Status is never
inferred as ``open`` solely from the current year: when no deadline/status is
stated it is ``"unknown"``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    log_source_failure,
    looks_like_pdf_url,
)


GOVBR_MMA_PUBLIC_CALLS_LISTING_URL = (
    "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
    "3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico"
)

GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR = int(
    os.environ.get("GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR", "2026"),
)

GOVBR_MMA_PUBLIC_CALLS_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("GOVBR_MMA_PUBLIC_CALLS_MAX_CANDIDATES_PER_RUN", "50"),
)
GOVBR_MMA_PUBLIC_CALLS_MAX_DETAILS_PER_RUN = int(
    os.environ.get("GOVBR_MMA_PUBLIC_CALLS_MAX_DETAILS_PER_RUN", "20"),
)

SOURCE_KEY = "govbr_mma_public_calls"

# Documents that are supporting material of a parent edital, never an
# opportunity identity of their own (Plan 03 / Plan 01).
RELATED_DOCUMENT_PATTERNS = [
    r"resultado",
    r"retificacao",
    r"errata",
    r"historico",
    r"anexo",
    r"termo.?de.?referencia",
]

_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")

_HEADING_TAGS = ("h1", "h2", "h3", "h4")

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _extract_year_from_url(url: str) -> int | None:
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


def _passes_year_guard(
    url: str, *, min_year: int, source_year: int | None = None,
) -> bool:
    year = source_year if source_year is not None else _extract_year_from_url(url)
    if year is None:
        return True
    return year >= min_year


def _fold_text(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value).lower()
        if not unicodedata.combining(character)
    )


def _is_related_document(url: str, title: str = "") -> bool:
    folded_title = _fold_text(title).strip()
    if folded_title and re.match(
        r"^(?:resultado|retificacao|errata|historico|anexo|termo.?de.?referencia)\b",
        folded_title,
    ):
        return True
    filename = _fold_text(urlsplit(url).path.rsplit("/", 1)[-1])
    return bool(re.match(
        r"^(?:resultado|retificacao|errata|historico|anexo|termo.?de.?referencia)(?:[-_.]|$)",
        filename,
    ))


def _canonical(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""),
    )


def _normalize_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold_text(title).strip())
    return slug.strip("-")


def _make_source_record_id(*, detail_url: str | None, title: str, year: int | None) -> str:
    if detail_url:
        return _canonical(detail_url)
    year_token = str(year) if year else "nd"
    return f"{year_token}-{_normalize_title(title) or 'edital'}"


def _content_root(soup: BeautifulSoup) -> Tag | None:
    root = soup.select_one("#content-core #parent-fieldname-text")
    if not isinstance(root, Tag):
        root = soup.select_one("#content-core")
    if not isinstance(root, Tag):
        root = soup.select_one("#content")
    if not isinstance(root, Tag):
        return None
    return root


def _extract_date(text: str, *, year: int | None) -> str | None:
    folded = _fold_text(text)
    numeric = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-]((?:19|20)\d{2}))?\b", folded,
    )
    if numeric:
        resolved_year = int(numeric.group(3)) if numeric.group(3) else year
        if resolved_year is not None:
            try:
                return datetime(
                    resolved_year, int(numeric.group(2)), int(numeric.group(1)),
                    tzinfo=timezone.utc,
                ).date().isoformat()
            except ValueError:
                pass
    named = re.search(
        r"\b(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+((?:19|20)\d{2}))?\b",
        folded,
    )
    if named:
        resolved_year = int(named.group(3)) if named.group(3) else year
        month = _MONTHS.get(named.group(2))
        if resolved_year is not None and month is not None:
            try:
                return datetime(
                    resolved_year, month, int(named.group(1)), tzinfo=timezone.utc,
                ).date().isoformat()
            except ValueError:
                pass
    return None


def _extract_record_metadata(html: str, *, year: int | None) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    root = _content_root(soup)
    if isinstance(root, Tag):
        for link in root.select("a"):
            if _is_related_document(
                str(link.get("href") or ""), link.get_text(" ", strip=True),
            ):
                link.decompose()
    text = root.get_text(" ", strip=True) if isinstance(root, Tag) else ""
    folded = _fold_text(text)

    status = "unknown"
    # "Resultado" is often part of the opportunity's subject (for example,
    # results-based payments) and is not, by itself, an explicit closed state.
    if re.search(r"\b(encerrad|homologad|finalizad)", folded):
        status = "closed"
    elif re.search(r"\b(abert|prorrogad)\w*", folded) or re.search(
        r"(?:inscricoes|propostas).{0,80}\bate\b", folded,
    ):
        status = "open"

    deadline: str | None = None
    deadline_match = re.search(
        r"(?:prazo|inscricoes|propostas).{0,160}?\bate\b.{0,80}",
        folded,
    )
    if deadline_match:
        deadline = _extract_date(deadline_match.group(0), year=year)

    published_at: str | None = None
    published = soup.select_one(
        'meta[property="article:published_time"], meta[name="DC.date.created"]',
    )
    if isinstance(published, Tag) and isinstance(published.get("content"), str):
        published_at = published["content"]
    if published_at is None:
        time_element = soup.select_one("time[datetime]")
        if isinstance(time_element, Tag) and isinstance(time_element.get("datetime"), str):
            published_at = time_element["datetime"]
    if published_at is None:
        publication_match = re.search(r"publicad[oa]\s+em\s+(.{0,60})", folded)
        if publication_match:
            published_at = _extract_date(publication_match.group(1), year=year)

    return {
        "status": status,
        "deadline": deadline,
        "published_at": published_at,
    }


def extract_public_calls_links(
    soup: BeautifulSoup, page_url: str,
) -> list[dict[str, Any]]:
    """Walk the editorial body, associating year headings with links.

    Returns a list of ``{"url", "title", "year", "kind"}`` entries where
    ``kind`` is ``"detail"`` for internal detail pages or ``"pdf"`` for direct
    PDF anchors. Only anchors inside ``#content-core`` are considered; links
    outside it (navigation / footer) are dropped.
    """
    root = _content_root(soup)
    if not isinstance(root, Tag):
        return []

    parsed_listing = urlsplit(page_url)
    listing_base = urlunsplit(
        (parsed_listing.scheme, parsed_listing.netloc, parsed_listing.path.rstrip("/") + "/", "", ""),
    )
    listing_prefix = listing_base.rstrip("/")

    entries: list[dict[str, Any]] = []
    current_year: int | None = None
    seen_urls: set[str] = set()

    for element in root.find_all(["a", "p", "div", *_HEADING_TAGS]):
        if not isinstance(element, Tag):
            continue

        if element.name in _HEADING_TAGS or element.name in ("p", "div"):
            text = element.get_text(strip=True)
            is_year_marker = (
                element.name in _HEADING_TAGS
                or "callout" in (element.get("class") or [])
                or bool(re.fullmatch(r"(?:edital\s+)?(?:19|20)\d{2}.*", text, re.IGNORECASE))
            )
            m = _YEAR_PATTERN.search(text or "") if is_year_marker and len(text) < 200 else None
            if m:
                y = int(m.group(0))
                if 1900 <= y <= 2099:
                    current_year = y
            if element.name != "a":
                continue

        href = element.get("href")
        if not isinstance(href, str) or not href:
            continue
        resolved = _canonical(urljoin(listing_base, href))
        if resolved in seen_urls:
            continue
        # Skip self-links and external sites. Gov.br detail/news pages may live
        # elsewhere under the MMA tree, not below the listing path.
        if resolved == listing_prefix:
            continue
        parsed_resolved = urlsplit(resolved)
        if (
            parsed_resolved.netloc != parsed_listing.netloc
            or not parsed_resolved.path.startswith("/mma/")
        ):
            continue
        if looks_like_pdf_url(resolved):
            seen_urls.add(resolved)
            entries.append(
                {
                    "url": resolved,
                    "title": element.get_text(strip=True) or resolved.rsplit("/", 1)[-1],
                    "year": current_year,
                    "kind": "pdf",
                    "related": _is_related_document(
                        resolved, element.get_text(" ", strip=True),
                    ),
                }
            )
        else:
            seen_urls.add(resolved)
            entries.append(
                {
                    "url": resolved,
                    "title": element.get_text(strip=True) or resolved.rsplit("/", 1)[-1],
                    "year": current_year,
                    "kind": "detail",
                    "related": _is_related_document(
                        resolved, element.get_text(" ", strip=True),
                    ),
                }
            )

    return entries


def _candidate_passes_edital_prefilter(
    url: str, filter_policy: FilterPolicy = "default",
) -> bool:
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    return is_likely_edital(filename, url, filter_policy=filter_policy)


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR,
    origin: str | None = None,
    source_record_id: str | None = None,
    year: int | None = None,
    title: str | None = None,
) -> dict[str, Any] | None:
    if not _passes_year_guard(url, min_year=min_year, source_year=year):
        return None
    if not _candidate_passes_edital_prefilter(url, filter_policy=filter_policy):
        return None

    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "detail_page"

    extracted_year = year if year is not None else _extract_year_from_url(url)
    if extracted_year is None and detail_url:
        extracted_year = _extract_year_from_url(detail_url)

    metadata: dict[str, Any] = {
        "source": SOURCE_KEY,
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if title is not None:
        metadata["title"] = title
    if detail_url is not None:
        metadata["detail_url"] = detail_url
    if source_record_id is not None:
        metadata["source_record_id"] = source_record_id

    return {"url": url, "kind": "pdf", "metadata": metadata}


def build_inventory(
    *,
    listing_html: str,
    detail_responses: dict[str, str],
    listing_url: str = GOVBR_MMA_PUBLIC_CALLS_LISTING_URL,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR,
) -> tuple[list[dict[str, Any]], bool]:
    """Build a Plan-01 compatible inventory from the parsed listing.

    Returns ``(inventory, content_present)``. ``content_present`` is False
    when the editorial body is absent. Each record carries the principal
    edital PDF plus any related (result/retification/annex) PDFs in
    ``document_urls`` — related docs are NOT separate records.
    """
    root = _content_root(BeautifulSoup(listing_html, "html.parser"))
    if not isinstance(root, Tag):
        return [], False

    listing_entries = extract_public_calls_links(
        BeautifulSoup(listing_html, "html.parser"), listing_url,
    )
    if not listing_entries:
        return [], True

    inventory: list[dict[str, Any]] = []
    records_by_id: dict[str, dict[str, Any]] = {}
    last_record_by_year: dict[int | None, dict[str, Any]] = {}
    pending_related_by_year: dict[int | None, list[str]] = {}

    def add_record(record: dict[str, Any]) -> dict[str, Any]:
        """Merge repeated direct-PDF identities and retain related documents.

        A listing can place a result/retification before its edital, or repeat
        the same edital title with a replacement PDF.  Keep those files on the
        single stable source record instead of losing them or creating a
        duplicate opportunity identity.
        """
        record_id = record["source_record_id"]
        existing = records_by_id.get(record_id)
        if existing is None:
            records_by_id[record_id] = record
            inventory.append(record)
            existing = record
        for document_url in record["document_urls"]:
            if document_url not in existing["document_urls"]:
                existing["document_urls"].append(document_url)
        year = existing["source_year"]
        last_record_by_year[year] = existing
        for document_url in pending_related_by_year.pop(year, []):
            if document_url not in existing["document_urls"]:
                existing["document_urls"].append(document_url)
        return existing

    def add_related_document(year: int | None, document_url: str) -> None:
        parent = last_record_by_year.get(year)
        if parent is None:
            pending_related_by_year.setdefault(year, []).append(document_url)
        elif document_url not in parent["document_urls"]:
            parent["document_urls"].append(document_url)

    for entry in listing_entries:
        title = entry["title"]
        year = entry["year"]
        if entry["kind"] == "pdf":
            if entry.get("related"):
                add_related_document(year, entry["url"])
                continue
            candidate = build_candidate(
                entry["url"],
                listing_url=listing_url,
                filter_policy=filter_policy,
                min_year=min_year,
                origin="listing_pdf",
                year=year,
                source_record_id=None,
            )
            if candidate is None:
                continue
            record_id = _make_source_record_id(
                detail_url=None, title=title, year=year,
            )
            add_record(
                {
                    "source_key": SOURCE_KEY,
                    "source_record_id": record_id,
                    "canonical_url": entry["url"],
                    "title": title,
                    "status": "unknown",
                    "published_at": None,
                    "deadline": None,
                    "source_year": year,
                    "document_urls": [entry["url"]],
                    "document_hashes": [],
                },
            )
            continue

        detail_url = entry["url"]
        if entry.get("related") or not _passes_year_guard(
            detail_url, min_year=min_year, source_year=year,
        ):
            continue
        detail_html = detail_responses.get(detail_url, "")
        doc_urls: list[str] = []
        principal_urls: list[str] = []
        if detail_html:
            for pdf_url, pdf_title in _extract_detail_pdf_entries(detail_html, detail_url):
                if _is_related_document(pdf_url, pdf_title):
                    if pdf_url not in doc_urls:
                        doc_urls.append(pdf_url)
                    continue
                if not _candidate_passes_edital_prefilter(pdf_url, filter_policy=filter_policy):
                    continue
                if pdf_url not in principal_urls:
                    principal_urls.append(pdf_url)
                    if pdf_url not in doc_urls:
                        doc_urls.append(pdf_url)

        if principal_urls:
            record_id = _make_source_record_id(
                detail_url=detail_url, title=title, year=year,
            )
            metadata = _extract_record_metadata(detail_html, year=year)
            add_record(
                {
                    "source_key": SOURCE_KEY,
                    "source_record_id": record_id,
                    "canonical_url": detail_url,
                    "title": title,
                    "status": metadata["status"],
                    "published_at": metadata["published_at"],
                    "deadline": metadata["deadline"],
                    "source_year": year,
                    "document_urls": doc_urls,
                    "document_hashes": [],
                },
            )
        elif detail_html:
            metadata = _extract_record_metadata(detail_html, year=year)
            add_record(
                {
                    "source_key": SOURCE_KEY,
                    "source_record_id": _make_source_record_id(
                        detail_url=detail_url, title=title, year=year,
                    ),
                    "canonical_url": detail_url,
                    "title": title,
                    "status": metadata["status"],
                    "published_at": metadata["published_at"],
                    "deadline": metadata["deadline"],
                    "source_year": year,
                    "document_urls": doc_urls,
                    "document_hashes": [],
                    "reason_code": "unresolved_news_lead",
                    "evidence": {"detail_url": detail_url, "principal_pdf_found": False},
                },
            )

    return inventory, True


def _extract_detail_pdf_entries(
    detail_html: str, detail_url: str,
) -> list[tuple[str, str]]:
    soup = BeautifulSoup(detail_html, "html.parser")
    root = _content_root(soup)
    if not isinstance(root, Tag):
        return []
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in root.select("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        resolved = _canonical(urljoin(detail_url, href))
        if looks_like_pdf_url(resolved) and resolved not in seen:
            seen.add(resolved)
            found.append((resolved, link.get_text(" ", strip=True)))
    return found


def _extract_detail_pdfs(detail_html: str, detail_url: str) -> list[str]:
    return [url for url, _title in _extract_detail_pdf_entries(detail_html, detail_url)]


def _discover_candidates_and_inventory(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR,
    seen_ids: set[str] | None = None,
    seen_pdfs: set[str] | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    """Discover public-call edital PDF candidates.

    Returns ``(stats, candidates)`` — the same contract as every other
    source. The inventory (audit mode / fidelity checks) is produced by the
    separate ``build_inventory`` helper. ``seen_ids`` / ``seen_pdfs``
    (defaulting to fresh local sets) let the orchestrator dedup opportunity
    identities AND pdf URLs across the MMA feeds.
    """
    if seen_ids is None:
        seen_ids = set()
    if seen_pdfs is None:
        seen_pdfs = set()

    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "prefilter_rejected": 0,
        "year_rejected": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
        "inventory_parse_failed": 0,
    }
    candidates: list[dict[str, Any]] = []
    details_fetched = 0

    try:
        from scraper_transport import fetch_html_with_retry

        listing_html = fetch_html_with_retry(
            GOVBR_MMA_PUBLIC_CALLS_LISTING_URL,
            timeout=30,
        )
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch public-calls listing %s: %s",
            GOVBR_MMA_PUBLIC_CALLS_LISTING_URL,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        stats["inventory_parse_failed"] = 1
        return stats, candidates, []

    root = _content_root(BeautifulSoup(listing_html, "html.parser"))
    if not isinstance(root, Tag):
        stats["inventory_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates, []

    listing_entries = extract_public_calls_links(
        BeautifulSoup(listing_html, "html.parser"), GOVBR_MMA_PUBLIC_CALLS_LISTING_URL,
    )
    if not listing_entries:
        stats["inventory_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates, []

    inventory: list[dict[str, Any]] = []
    inventory_by_id: dict[str, dict[str, Any]] = {}
    last_record_by_year: dict[int | None, dict[str, Any]] = {}
    pending_related_by_year: dict[int | None, list[str]] = {}
    cap_reached = False

    def add_record(record: dict[str, Any]) -> dict[str, Any]:
        record_id = record["source_record_id"]
        existing = inventory_by_id.get(record_id)
        if existing is None:
            inventory_by_id[record_id] = record
            inventory.append(record)
            existing = record
        for document_url in record["document_urls"]:
            if document_url not in existing["document_urls"]:
                existing["document_urls"].append(document_url)
        year = existing["source_year"]
        last_record_by_year[year] = existing
        for document_url in pending_related_by_year.pop(year, []):
            if document_url not in existing["document_urls"]:
                existing["document_urls"].append(document_url)
        return existing

    def add_related_document(year: int | None, document_url: str) -> None:
        parent = last_record_by_year.get(year)
        if parent is None:
            pending_related_by_year.setdefault(year, []).append(document_url)
        elif document_url not in parent["document_urls"]:
            parent["document_urls"].append(document_url)

    for entry in listing_entries:
        title = entry["title"]
        year = entry["year"]

        if entry["kind"] == "pdf":
            if entry.get("related"):
                add_related_document(year, entry["url"])
                continue
            record_id = _make_source_record_id(detail_url=None, title=title, year=year)
            candidate = build_candidate(
                entry["url"],
                listing_url=GOVBR_MMA_PUBLIC_CALLS_LISTING_URL,
                filter_policy=filter_policy,
                min_year=min_year,
                origin="listing_pdf",
                year=year,
                source_record_id=record_id,
                title=title,
            )
            if candidate is None:
                if not _passes_year_guard(
                    entry["url"], min_year=min_year, source_year=year,
                ):
                    stats["year_rejected"] += 1
                else:
                    stats["prefilter_rejected"] += 1
                continue
            add_record(
                {
                    "source_key": SOURCE_KEY,
                    "source_record_id": record_id,
                    "canonical_url": entry["url"],
                    "title": title,
                    "status": "unknown",
                    "published_at": None,
                    "deadline": None,
                    "source_year": year,
                    "document_urls": [entry["url"]],
                    "document_hashes": [],
                },
            )
            if record_id in seen_ids:
                continue
            if entry["url"] in seen_pdfs:
                continue
            seen_ids.add(record_id)
            seen_pdfs.add(entry["url"])
            candidates.append(candidate)
            if len(candidates) >= GOVBR_MMA_PUBLIC_CALLS_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                cap_reached = True
                break
            continue

        detail_url = entry["url"]
        if entry.get("related"):
            continue
        if not _passes_year_guard(detail_url, min_year=min_year, source_year=year):
            stats["year_rejected"] += 1
            continue
        if details_fetched >= GOVBR_MMA_PUBLIC_CALLS_MAX_DETAILS_PER_RUN:
            break
        try:
            detail_html = fetch_html_with_retry(detail_url, timeout=30)
        except Exception as exc:
            log_source_failure(
                "Failed to fetch public-calls detail %s: %s", detail_url, exc, exc=exc,
            )
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        details_fetched += 1
        stats["details_fetched"] += 1

        doc_urls: list[str] = []
        principal_urls: list[str] = []
        for pdf_url, pdf_title in _extract_detail_pdf_entries(detail_html, detail_url):
            # Related documents (result/retification/annex) attach to the
            # parent record regardless of the edital prefilter; they are never
            # standalone opportunities.
            if _is_related_document(pdf_url, pdf_title):
                if pdf_url not in doc_urls:
                    doc_urls.append(pdf_url)
                continue
            if not _candidate_passes_edital_prefilter(pdf_url, filter_policy=filter_policy):
                continue
            if pdf_url not in principal_urls:
                principal_urls.append(pdf_url)
                if pdf_url not in doc_urls:
                    doc_urls.append(pdf_url)

        # A detail page is the opportunity identity. Multiple principal files
        # remain documents of that one record rather than duplicate editais.
        if principal_urls:
            record_id = _make_source_record_id(
                detail_url=detail_url, title=title, year=year,
            )
            metadata = _extract_record_metadata(detail_html, year=year)
            add_record(
                {
                    "source_key": SOURCE_KEY,
                    "source_record_id": record_id,
                    "canonical_url": detail_url,
                    "title": title,
                    "status": metadata["status"],
                    "published_at": metadata["published_at"],
                    "deadline": metadata["deadline"],
                    "source_year": year,
                    "document_urls": doc_urls,
                    "document_hashes": [],
                },
            )

            principal_url = next(
                (url for url in principal_urls if url not in seen_pdfs), None,
            )
            if record_id in seen_ids or principal_url is None:
                continue
            candidate = build_candidate(
                principal_url,
                listing_url=GOVBR_MMA_PUBLIC_CALLS_LISTING_URL,
                detail_url=detail_url,
                filter_policy=filter_policy,
                min_year=min_year,
                origin="detail_page",
                year=year,
                source_record_id=record_id,
                title=title,
            )
            if candidate is None:
                if not _passes_year_guard(
                    principal_url, min_year=min_year, source_year=year,
                ):
                    stats["year_rejected"] += 1
                else:
                    stats["prefilter_rejected"] += 1
                continue
            candidate["metadata"].update(metadata)
            seen_ids.add(record_id)
            seen_pdfs.add(principal_url)
            candidates.append(candidate)
            if len(candidates) >= GOVBR_MMA_PUBLIC_CALLS_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                cap_reached = True
                break
        else:
            metadata = _extract_record_metadata(detail_html, year=year)
            add_record(
                {
                    "source_key": SOURCE_KEY,
                    "source_record_id": _make_source_record_id(
                        detail_url=detail_url, title=title, year=year,
                    ),
                    "canonical_url": detail_url,
                    "title": title,
                    "status": metadata["status"],
                    "published_at": metadata["published_at"],
                    "deadline": metadata["deadline"],
                    "source_year": year,
                    "document_urls": doc_urls,
                    "document_hashes": [],
                    "reason_code": "unresolved_news_lead",
                    "evidence": {"detail_url": detail_url, "principal_pdf_found": False},
                },
            )

        if cap_reached:
            break

    stats["candidates"] = len(candidates)
    if stats["candidates"] == 0 and not inventory:
        stats["inventory_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
    return stats, candidates, inventory


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR,
    seen_ids: set[str] | None = None,
    seen_pdfs: set[str] | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    stats, candidates, _inventory = _discover_candidates_and_inventory(
        filter_policy=filter_policy,
        min_year=min_year,
        seen_ids=seen_ids,
        seen_pdfs=seen_pdfs,
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
    discovery: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for candidate in candidates:
        record_id = candidate.get("metadata", {}).get("source_record_id")
        record = records_by_id.get(record_id)
        if isinstance(record_id, str) and record is not None and record_id not in emitted:
            discovery.append({**record, "document_urls": [candidate["url"]]})
            emitted.add(record_id)
    payloads = {
        "source_inventory.json": inventory,
        "discovery.json": discovery,
        "candidates.json": candidates,
        "stats.json": stats,
    }
    for filename, payload in payloads.items():
        (output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover MMA public-call editais")
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
        print(f"GOVBR-MMA public-calls audit stats: {stats}")
        print(f"GOVBR-MMA public-calls audit artifacts: {args.audit_dir}")
        return 1 if stats.get("inventory_parse_failed", 0) else 0

    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"GOVBR-MMA public-calls discovery stats: {stats}")
    print(f"GOVBR-MMA public-calls candidates discovered: {len(candidates)}")

    if stats.get("inventory_parse_failed", 0):
        print("error: public-calls discovery reported a parser failure", file=sys.stderr)
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
    print(f"GOVBR-MMA public-calls processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered public-call candidates failed download/OCR; "
            "nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source=SOURCE_KEY)
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered public-call candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
