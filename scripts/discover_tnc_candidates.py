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
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_filters import FilterPolicy, is_likely_edital
from scraper_transport import (
    discover_pdf_urls_on_page,
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)
from structured_discovery import (
    StructuredDiscoveryResult,
    parser_failure,
    policy_rejection,
)


TNC_LISTING_URL = "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"
TNC_OPPORTUNITIES_URL = "https://www.tnc.org.br/conecte-se/trabalhe-conosco/"

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


def _consultancy_content(listing_html: str) -> Tag | None:
    soup = BeautifulSoup(listing_html, "html.parser")
    heading = next(
        (
            node
            for node in soup.find_all(["h1", "h2", "h3"])
            if re.search(
                r"oportunidades para consultoria e presta(?:cao|ção) de servi(?:cos|ços)",
                node.get_text(" ", strip=True),
                re.I,
            )
        ),
        None,
    )
    if not isinstance(heading, Tag):
        return None
    current = heading.find_next()
    while isinstance(current, Tag):
        if "rich-text-editor" in (current.get("class") or []):
            return current
        current = current.find_next()
    return None


def extract_consultancy_blocks(listing_html: str) -> list[list[Tag]]:
    """Split the official consultancy section on its visible separators."""
    content = _consultancy_content(listing_html)
    if content is None:
        return []
    blocks: list[list[Tag]] = []
    current: list[Tag] = []
    for paragraph in content.find_all("p"):
        if not isinstance(paragraph, Tag):
            continue
        text = paragraph.get_text(" ", strip=True)
        if re.fullmatch(r"[-–—\s]{10,}", text):
            if current:
                blocks.append(current)
                current = []
            continue
        if text or paragraph.find("a"):
            current.append(paragraph)
    if current:
        blocks.append(current)
    return blocks


def _parse_tnc_deadline(text: str) -> datetime | None:
    matches = list(
        re.finditer(
            r"(?:(NOVO)\s+)?PRAZO\s*:\s*(\d{2}/\d{2}/\d{4})(?:\s+at[eé]\s+(\d{1,2})h)?",
            text,
            re.I,
        )
    )
    if not matches:
        return None
    preferred = next((match for match in reversed(matches) if match.group(1)), matches[-1])
    hour = int(preferred.group(3) or 23)
    minute = 59 if preferred.group(3) is None else 0
    return datetime.strptime(preferred.group(2), "%d/%m/%Y").replace(
        hour=hour,
        minute=minute,
        tzinfo=ZoneInfo("America/Sao_Paulo"),
    )


def parse_consultancy_block(
    paragraphs: list[Tag],
    *,
    now: datetime | None = None,
    snapshot_at: datetime | None = None,
) -> dict[str, Any] | None:
    text_parts = [paragraph.get_text(" ", strip=True) for paragraph in paragraphs]
    full_text = "\n".join(part for part in text_parts if part)
    deadline = _parse_tnc_deadline(full_text)
    title = next(
        (
            part
            for part in text_parts
            if part
            and not re.match(r"^(NOVO\s+)?PRAZO\s*:", part, re.I)
            and not re.match(r"^CONTATO\s*:", part, re.I)
        ),
        "",
    )
    if not title or deadline is None:
        return None
    tdr_url = None
    for paragraph in paragraphs:
        for link in paragraph.find_all("a"):
            href = link.get("href") if isinstance(link, Tag) else None
            if isinstance(href, str) and re.search(r"\.(pdf|docx)($|[?#])", href, re.I):
                tdr_url = urljoin(TNC_OPPORTUNITIES_URL, href)
                break
        if tdr_url:
            break
    if tdr_url and len(tdr_url) <= 255:
        source_record_id = tdr_url
    else:
        source_record_id = _fallback_consultancy_id(title, deadline.isoformat())
    current = now or datetime.now(ZoneInfo("America/Sao_Paulo"))
    status = "open" if deadline >= current else "expired"
    documents = []
    if tdr_url:
        kind = "pdf" if re.search(r"\.pdf($|[?#])", tdr_url, re.I) else "docx"
        documents.append(
            {
                "source_document_id": tdr_url,
                "document_kind": kind,
                "url": tdr_url,
                "filename": urlsplit(tdr_url).path.rsplit("/", 1)[-1],
                "mime_type": (
                    "application/pdf"
                    if kind == "pdf"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                "is_principal": False,
                "is_renderable": False,
            }
        )
    source_markdown = (
        f"# {title}\n\n## Prazo\n\n{deadline.isoformat()}"
        f"\n\n## Instrucoes e contato\n\n{full_text}"
    )
    snapshot = snapshot_at or datetime.now(timezone.utc)
    return {
        "source_key": "tnc",
        "source_record_id": source_record_id,
        "source_kind": "web",
        "opportunity_type": "consultancy",
        "canonical_url": tdr_url or TNC_OPPORTUNITIES_URL,
        "title": title,
        "description": full_text,
        "authoritative_status": status,
        "source_published_at": None,
        "source_updated_at": None,
        "proposal_opens_at": None,
        "application_deadline": deadline.astimezone(timezone.utc).isoformat(),
        "source_snapshot_at": snapshot.astimezone(timezone.utc).isoformat(),
        "source_markdown": source_markdown,
        "source_content_hash": "",
        "documents": documents,
    }


def parse_consultancy_inventory_block(
    paragraphs: list[Tag],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Parse a canonical consultancy block directly into audit inventory."""
    text_parts = [paragraph.get_text(" ", strip=True) for paragraph in paragraphs]
    full_text = "\n".join(part for part in text_parts if part)
    deadline = _parse_tnc_deadline(full_text)
    title = next(
        (
            part
            for part in text_parts
            if part
            and not re.match(r"^(NOVO\s+)?PRAZO\s*:", part, re.I)
            and not re.match(r"^CONTATO\s*:", part, re.I)
        ),
        "",
    )
    if not title or deadline is None:
        return None
    tdr_url = next(
        (
            urljoin(TNC_OPPORTUNITIES_URL, href)
            for paragraph in paragraphs
            for link in paragraph.find_all("a")
            if isinstance(link, Tag)
            if isinstance((href := link.get("href")), str)
            if re.search(r"\.(pdf|docx)($|[?#])", href, re.I)
        ),
        None,
    )
    source_record_id = (
        tdr_url
        if tdr_url and len(tdr_url) <= 255
        else _fallback_consultancy_id(title, deadline.isoformat())
    )
    current = now or datetime.now(ZoneInfo("America/Sao_Paulo"))
    return {
        "source_key": "tnc",
        "source_record_id": source_record_id,
        "canonical_url": tdr_url or TNC_OPPORTUNITIES_URL,
        "title": title,
        "status": "open" if deadline >= current else "closed",
        "published_at": None,
        "deadline": deadline.astimezone(timezone.utc).isoformat(),
        "document_urls": [tdr_url] if tdr_url else [],
        "document_hashes": [],
    }


def _fallback_consultancy_id(title: str, deadline: str) -> str:
    identity = f"{TNC_OPPORTUNITIES_URL}|{title.casefold()}|{deadline}"
    return f"consultancy:{hashlib.sha256(identity.encode()).hexdigest()}"


def _extract_document_text(url: str) -> str:
    """Read a duplicated official PDF so its owner can be verified."""
    if not re.search(r"\.pdf($|[?#])", url, re.I):
        return ""
    from pypdf import PdfReader

    content = pipeline_core._download_attachment(
        url,
        max_bytes=pipeline_core.SCRAPE_MAX_PDF_BYTES,
    )
    return "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(content)).pages
    )


def _association_markers(opportunity: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return exact public deadline/contact markers from one source block."""
    description = str(opportunity.get("description") or "")
    deadlines = {
        match.group(1)
        for match in re.finditer(r"\b(\d{2}/\d{2}/\d{4})\b", description)
    }
    contacts = {
        match.group(0).casefold()
        for match in re.finditer(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            description,
            re.I,
        )
    }
    return deadlines, contacts


def _resolve_duplicate_documents(
    opportunities: list[dict[str, Any]],
    *,
    fetch_document_text: Any,
) -> list[dict[str, Any]]:
    """Assign a reused link only when PDF metadata proves a unique owner.

    TNC occasionally publishes the same anchor under adjacent consultancy
    blocks. Stable IDs remain block-derived in that case. The attachment is
    retained only when its text contains both the exact deadline and a public
    contact from exactly one block; otherwise it is quarantined from every
    opportunity and returned as blocking audit evidence.
    """
    owners_by_url: dict[str, list[dict[str, Any]]] = {}
    for opportunity in opportunities:
        for document in opportunity.get("documents", []):
            url = str(document.get("url") or "")
            if url:
                owners_by_url.setdefault(url, []).append(opportunity)

    conflicts: list[dict[str, Any]] = []
    for url, possible_owners in owners_by_url.items():
        if len(possible_owners) <= 1:
            continue
        document_text = ""
        inspection_error = None
        try:
            document_text = str(fetch_document_text(url) or "")
        except Exception as exc:
            inspection_error = type(exc).__name__
        normalized_text = document_text.casefold()
        proven_owners: list[dict[str, Any]] = []
        for opportunity in possible_owners:
            deadlines, contacts = _association_markers(opportunity)
            deadline_match = bool(deadlines) and any(
                deadline in normalized_text for deadline in deadlines
            )
            contact_match = bool(contacts) and any(
                contact in normalized_text for contact in contacts
            )
            if deadline_match and contact_match:
                proven_owners.append(opportunity)

        retained_owner = proven_owners[0] if len(proven_owners) == 1 else None
        for opportunity in possible_owners:
            if opportunity is retained_owner:
                continue
            opportunity["documents"] = [
                document
                for document in opportunity.get("documents", [])
                if document.get("url") != url
            ]

        if retained_owner is None:
            evidence: dict[str, Any] = {
                "reason_code": "identity_mismatch",
                "document_url": url,
                "source_record_ids": [
                    opportunity["source_record_id"]
                    for opportunity in possible_owners
                ],
                "resolution": "attachment_quarantined",
            }
            if inspection_error:
                evidence["inspection_error"] = inspection_error
            conflicts.append(evidence)
    return conflicts


def _disambiguate_shared_source_ids(records: list[dict[str, Any]]) -> None:
    """Give distinct blocks stable IDs without discarding shared TDR evidence."""
    source_id_counts: dict[str, int] = {}
    for record in records:
        source_id = record["source_record_id"]
        source_id_counts[source_id] = source_id_counts.get(source_id, 0) + 1
    for record in records:
        if source_id_counts[record["source_record_id"]] <= 1:
            continue
        deadline = record.get("application_deadline") or record.get("deadline")
        fallback_id = _fallback_consultancy_id(record["title"], deadline)
        record["source_record_id"] = fallback_id
        record["canonical_url"] = (
            f"{TNC_OPPORTUNITIES_URL}?consultancy="
            f"{fallback_id.removeprefix('consultancy:')}"
        )


def discover_opportunities(
    *,
    fetch_html: Any = None,
    fetch_document_text: Any = None,
    now: datetime | None = None,
    snapshot_at: datetime | None = None,
    min_year: int | None = None,
) -> StructuredDiscoveryResult:
    """Discover only official consultancy blocks, never general news."""
    del min_year
    fetch = fetch_html or (
        lambda url: fetch_html_with_retry(
            url,
            timeout=TNC_FETCH_TIMEOUT_SECONDS,
            max_attempts=TNC_FETCH_MAX_ATTEMPTS,
            backoff_seconds=TNC_FETCH_BACKOFF_SECONDS,
        )
    )
    html = fetch(TNC_OPPORTUNITIES_URL)
    if _consultancy_content(html) is None:
        failure = parser_failure(
            "tnc",
            stage="consultancy_section",
            error="canonical consultancy section was not found",
        )
        return StructuredDiscoveryResult(
            stats={
                "section_parse_failed": 1,
                "blocks": 0,
                "inventory_records": 0,
                "opportunities": 0,
                "parser_failures": 1,
            },
            inventory=[],
            opportunities=[],
            parser_failures=[failure],
        )
    blocks = extract_consultancy_blocks(html)
    if not blocks:
        failure = parser_failure(
            "tnc",
            stage="consultancy_inventory",
            error="canonical consultancy section contained no blocks",
        )
        return StructuredDiscoveryResult(
            stats={
                "inventory_parse_failed": 1,
                "blocks": 0,
                "inventory_records": 0,
                "opportunities": 0,
                "parser_failures": 1,
            },
            inventory=[],
            opportunities=[],
            parser_failures=[failure],
        )
    raw_inventory: list[dict[str, Any]] = []
    raw_opportunities: list[dict[str, Any]] = []
    parser_failures: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        inventory_record = parse_consultancy_inventory_block(block, now=now)
        opportunity = parse_consultancy_block(
            block,
            now=now,
            snapshot_at=snapshot_at,
        )
        if inventory_record is None or opportunity is None:
            parser_failures.append(
                parser_failure(
                    "tnc",
                    stage="consultancy_block",
                    error="block is missing a stable title or deadline",
                    evidence={
                        "block_index": index,
                        "text": " ".join(
                            paragraph.get_text(" ", strip=True)
                            for paragraph in block
                        )[:500],
                    },
                )
            )
            continue
        raw_inventory.append(inventory_record)
        raw_opportunities.append(opportunity)
    _disambiguate_shared_source_ids(raw_inventory)
    _disambiguate_shared_source_ids(raw_opportunities)

    conflicts = _resolve_duplicate_documents(
        raw_opportunities,
        fetch_document_text=fetch_document_text or _extract_document_text,
    )
    opportunity_documents = {
        opportunity["source_record_id"]: [
            document["url"]
            for document in opportunity.get("documents", [])
            if document.get("url")
        ]
        for opportunity in raw_opportunities
    }
    for inventory_record in raw_inventory:
        inventory_record["document_urls"] = opportunity_documents.get(
            inventory_record["source_record_id"],
            [],
        )
    parser_failures.extend(
        parser_failure(
            "tnc",
            stage="document_association",
            error="shared attachment ownership could not be proven",
            evidence=conflict,
        )
        for conflict in conflicts
    )

    inventory: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for inventory_record, opportunity in zip(
        raw_inventory,
        raw_opportunities,
        strict=True,
    ):
        if inventory_record["status"] == "closed":
            rejected = policy_rejection(
                inventory_record,
                policy="open_status_only",
                evidence={"authoritative_status": "expired"},
            )
            inventory.append(rejected)
            rejections.append(rejected)
        else:
            inventory.append(inventory_record)
            opportunities.append(opportunity)
    stats = {
        "blocks": len(blocks),
        "inventory_records": len(inventory),
        "opportunities": len(opportunities),
        "malformed_blocks": len(parser_failures),
        "policy_rejected": len(rejections),
        "parser_failures": len(parser_failures),
    }
    if conflicts:
        stats["ambiguous_document_conflicts"] = len(conflicts)
        stats["document_conflicts"] = conflicts
    if parser_failures:
        stats["inventory_parse_failed"] = 1
    return StructuredDiscoveryResult(
        stats=stats,
        inventory=inventory,
        opportunities=opportunities,
        policy_rejections=rejections,
        parser_failures=parser_failures,
    )


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
