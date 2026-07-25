"""GOVBR-MMA FNMA (Fundo Nacional do Meio Ambiente) discoverer for the cronjob.

Plan 03 (``plans/opportunity-sources/03-mma-source-expansion.md``) adds the
MMA FNMA editais / terms-of-reference page as a SEPARATE, explicitly
selectable source (``govbr_mma_fnma``) that must NOT change the existing
``govbr_mma`` procurement discoverer.

The FNMA page hosts edital PDFs and (under a separate policy) terms of
reference (``termo de referencia``). Per Plan 03 the default policy is
``default``: TDR documents are treated as RELATED metadata of a parent edital,
never as a standalone opportunity. An operator may opt in to surfacing TDR as
principal candidates via the ``GOVBR_MMA_FNMA_INCLUDE_TDR`` env var / the
module-level ``include_tdr`` flag — but this is a SOURCE-SPECIFIC switch and
must NOT mutate the global ``scraper_filters`` default (the global
``FILTER_POLICY`` is still forwarded by the orchestrator untouched).

Sharing the public-calls contract:

* parsing is restricted to ``#content-core #parent-fieldname-text`` (falling
  back to ``#content-core``) so navigation / footer links are excluded;
* year headings (``<h2>2026</h2>``) are associated with the edital links that
  follow them;
* ``resultado`` / ``retificacao`` / ``errata`` / historical support docs are
  RELATED documents of the parent opportunity, attached to the inventory
  record's ``document_urls`` and never a separate candidate/entry;
* a Plan-01-compatible inventory is emitted for deterministic fidelity checks;
* ``source_record_id`` uses the canonical detail URL (or a normalized title +
  year) and status is ``"unknown"`` unless a deadline/status is explicitly
  stated.
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
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)


GOVBR_MMA_FNMA_LISTING_URL = (
    "https://www.gov.br/mma/pt-br/composicao/secex/dfre/"
    "fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1"
)

GOVBR_MMA_FNMA_MIN_NOTICE_YEAR = int(
    os.environ.get("GOVBR_MMA_FNMA_MIN_NOTICE_YEAR", "2026"),
)

GOVBR_MMA_FNMA_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("GOVBR_MMA_FNMA_MAX_CANDIDATES_PER_RUN", "50"),
)

SOURCE_KEY = "govbr_mma_fnma"

# Source-specific opt-in only; never alters the global scraper_filters default.
FNMA_INCLUDE_TDR = os.environ.get("GOVBR_MMA_FNMA_INCLUDE_TDR", "0") in ("1", "true", "True")

RELATED_DOCUMENT_PATTERNS = [
    r"resultado",
    r"retificacao",
    r"errata",
    r"historico",
    r"anexo",
]

_YEAR_PATTERN = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")

_HEADING_TAGS = ("h1", "h2", "h3", "h4")

_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
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
        r"^(?:resultado|retificacao|errata|historico|anexo)\b", folded_title,
    ):
        return True
    filename = _fold_text(urlsplit(url).path.rsplit("/", 1)[-1])
    return bool(re.match(
        r"^(?:resultado|retificacao|errata|historico|anexo)(?:[-_.]|$)", filename,
    ))


def _is_tdr(url: str, title: str = "") -> bool:
    return bool(re.search(r"termo.?de.?referencia", _fold_text(f"{url} {title}")))


def _canonical(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""),
    )


def _normalize_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold_text(title).strip())
    return slug.strip("-")


def _fnma_record_id(url: str, *, year: int | None, title: str) -> str:
    """Stable candidate/inventory identity for a single FNMA edital.

    Must be UNIQUE PER EDITAL (not per year) so two principal PDFs in the
    same year are not collapsed into one opportunity identity. Per Plan 03,
    normalized title + source year is authoritative when no explicit ID or
    detail URL exists; canonical PDF URL is only the last-resort fallback.
    """
    year_token = str(year) if year else "nd"
    title_token = _normalize_title(title)
    if title_token:
        return f"fnma-{year_token}-{title_token}"
    canonical = _canonical(url)
    return f"fnma-{canonical}" if canonical else f"fnma-{year_token}-edital"


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
    match = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-]((?:19|20)\d{2}))?\b", folded,
    )
    if match:
        resolved_year = int(match.group(3)) if match.group(3) else year
        if resolved_year is not None:
            try:
                return datetime(
                    resolved_year, int(match.group(2)), int(match.group(1)),
                    tzinfo=timezone.utc,
                ).date().isoformat()
            except ValueError:
                pass
    match = re.search(
        r"\b(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+((?:19|20)\d{2}))?\b",
        folded,
    )
    if match:
        resolved_year = int(match.group(3)) if match.group(3) else year
        month = _MONTHS.get(match.group(2))
        if resolved_year is not None and month is not None:
            try:
                return datetime(
                    resolved_year, month, int(match.group(1)), tzinfo=timezone.utc,
                ).date().isoformat()
            except ValueError:
                pass
    return None


def _extract_listing_metadata(
    root: Tag,
    *,
    year: int | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    text = root.get_text(" ", strip=True)
    folded = _fold_text(text)
    status = "unknown"
    # Do not treat a subject containing "resultado" as an explicit closed
    # status. Result/retification documents are classified separately.
    if re.search(r"\b(encerrad|homologad|finalizad)", folded):
        status = "closed"
    elif re.search(r"\b(abert|prorrogad)\w*", folded) or re.search(
        r"(?:inscricoes|propostas).{0,80}\bate\b", folded,
    ):
        status = "open"

    deadline = None
    matches = list(re.finditer(r"\bate\b.{0,80}", folded))
    for match in matches:
        parsed = _extract_date(match.group(0), year=year)
        if parsed is not None:
            deadline = parsed
    current_date = (now or datetime.now(timezone.utc)).date()
    if (
        status == "open"
        and deadline is not None
        and datetime.fromisoformat(deadline).date() < current_date
    ):
        status = "expired"

    published_at = None
    document = root.find_parent("html") or root
    published = document.select_one(
        'meta[property="article:published_time"], meta[name="DC.date.created"]',
    )
    if isinstance(published, Tag) and isinstance(published.get("content"), str):
        published_at = published["content"]
    if published_at is None:
        time_element = document.select_one("time[datetime]")
        if isinstance(time_element, Tag) and isinstance(time_element.get("datetime"), str):
            published_at = time_element["datetime"]
    return {"status": status, "deadline": deadline, "published_at": published_at}


def extract_fnma_links(soup: BeautifulSoup, page_url: str) -> list[dict[str, Any]]:
    """Walk the editorial body, associating year headings with PDF links.

    Returns ``{"url", "title", "year"}`` entries for every PDF anchor inside
    ``#content-core``. Links outside the editorial body are dropped.
    """
    root = _content_root(soup)
    if not isinstance(root, Tag):
        return []

    parsed_listing = urlsplit(page_url)
    listing_base = urlunsplit(
        (parsed_listing.scheme, parsed_listing.netloc, parsed_listing.path.rstrip("/") + "/", "", ""),
    )

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
        if not looks_like_pdf_url(resolved):
            continue
        if resolved in seen_urls:
            continue
        seen_urls.add(resolved)
        entries.append(
            {
                "url": resolved,
                "title": element.get_text(strip=True) or resolved.rsplit("/", 1)[-1],
                "year": current_year,
                "related": _is_related_document(
                    resolved, element.get_text(" ", strip=True),
                ),
                "tdr": _is_tdr(resolved, element.get_text(" ", strip=True)),
            }
        )

    return entries


def _candidate_passes_edital_prefilter(
    url: str,
    filter_policy: FilterPolicy = "default",
    *,
    include_tdr: bool = False,
    title: str = "",
) -> bool:
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    # FNMA TDR is only allowed under the source-specific opt-in; otherwise it
    # is handled as a related document by the caller. When the opt-in is active
    # AND this is a TDR, use the source-local "include_tdr" policy so the
    # global default exclusion is overridden without mutating scraper_filters.
    effective_policy: FilterPolicy = filter_policy
    if _is_tdr(url, title) and include_tdr:
        effective_policy = "include_tdr"
    elif _is_tdr(url, title) and not include_tdr:
        return False
    return is_likely_edital(filename, url, filter_policy=effective_policy)


def build_candidate(
    url: str,
    *,
    listing_url: str,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_FNMA_MIN_NOTICE_YEAR,
    origin: str | None = None,
    source_record_id: str | None = None,
    year: int | None = None,
    include_tdr: bool = False,
    title: str = "",
) -> dict[str, Any] | None:
    if not _passes_year_guard(url, min_year=min_year, source_year=year):
        return None
    if not _candidate_passes_edital_prefilter(
        url, filter_policy=filter_policy, include_tdr=include_tdr, title=title,
    ):
        return None

    if origin is None:
        origin = "listing_pdf"

    extracted_year = year if year is not None else _extract_year_from_url(url)

    metadata: dict[str, Any] = {
        "source": SOURCE_KEY,
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "extracted_year": extracted_year,
    }
    if source_record_id is not None:
        metadata["source_record_id"] = source_record_id
    if title:
        metadata["title"] = title

    return {"url": url, "kind": "pdf", "metadata": metadata}


def build_inventory(
    *,
    listing_html: str,
    listing_url: str = GOVBR_MMA_FNMA_LISTING_URL,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_FNMA_MIN_NOTICE_YEAR,
    include_tdr: bool | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Build a Plan-01 compatible inventory from the parsed FNMA page.

    Returns ``(inventory, content_present)``. ``content_present`` is False
    when the editorial body is absent. Each record carries the principal edital
    PDF plus any related (result/retification/annex) PDFs in ``document_urls``.

    ``include_tdr`` mirrors the candidate opt-in (defaulting to the module-level
    ``FNMA_INCLUDE_TDR``). When ``True``, a TDR PDF becomes its OWN principal
    inventory record (matching the candidate's ``source_record_id``) instead of
    being attached as related metadata. The default (opt-out) behavior is
    unchanged: TDR is related metadata only.
    """
    if include_tdr is None:
        include_tdr = FNMA_INCLUDE_TDR

    root = _content_root(BeautifulSoup(listing_html, "html.parser"))
    if not isinstance(root, Tag):
        return [], False

    entries = extract_fnma_links(
        BeautifulSoup(listing_html, "html.parser"), listing_url,
    )
    if not entries:
        return [], True

    inventory = _build_fnma_inventory_records(
        entries,
        filter_policy=filter_policy,
        include_tdr=include_tdr,
        min_year=min_year,
        listing_metadata=_extract_listing_metadata(
            root,
            year=max(
                (entry["year"] for entry in entries if entry["year"] is not None),
                default=None,
            ),
        ),
    )
    return inventory, True


def _build_fnma_inventory_records(
    entries: list[dict[str, Any]],
    *,
    filter_policy: FilterPolicy = "default",
    include_tdr: bool = False,
    min_year: int = GOVBR_MMA_FNMA_MIN_NOTICE_YEAR,
    listing_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Emit per-edital inventory records whose ID matches the candidate ID.

    Principal edital PDFs each become their own record. Related documents
    (result/retification/annex/TDR) are attached as related metadata to the
    principal edital record of the SAME year (falling back to the first
    principal overall) and never form a standalone record. When a related doc
    has no principal to attach to it is still recorded as related metadata on a
    synthetic year-group record so it remains auditable.
    """
    principals: list[dict[str, Any]] = []
    related_by_year: dict[int | None, list[dict[str, Any]]] = {}

    for entry in entries:
        url = entry["url"]
        if not _passes_year_guard(url, min_year=min_year, source_year=entry["year"]):
            continue
        # A TDR URL is treated as a principal (own record) when the source-
        # specific opt-in is enabled, so its inventory record_id matches the
        # candidate's source_record_id. Otherwise it is related metadata.
        if entry.get("related") or (entry.get("tdr") and not include_tdr):
            related_by_year.setdefault(entry["year"], []).append(entry)
        else:
            principals.append(entry)

    inventory: list[dict[str, Any]] = []
    record_by_id: dict[str, dict[str, Any]] = {}

    def _ensure_record(url: str, year: int | None, title: str) -> dict[str, Any]:
        record_id = _fnma_record_id(url, year=year, title=title)
        year_token = str(year) if year else "nd"
        if record_id not in record_by_id:
            record_by_id[record_id] = {
                "source_key": SOURCE_KEY,
                "source_record_id": record_id,
                "canonical_url": url,
                "title": title or f"FNMA edital {year_token}",
                "status": (listing_metadata or {}).get("status", "unknown"),
                "published_at": (listing_metadata or {}).get("published_at"),
                "deadline": (listing_metadata or {}).get("deadline"),
                "source_year": year,
                "document_urls": [],
                "document_hashes": [],
            }
            inventory.append(record_by_id[record_id])
        return record_by_id[record_id]

    # Principals first so related docs can attach to them.
    for entry in principals:
        rec = _ensure_record(entry["url"], entry["year"], entry["title"])
        if entry["url"] not in rec["document_urls"]:
            rec["document_urls"].append(entry["url"])

    # Attach related docs to a principal of the same year (else first principal).
    fallback = principals[0] if principals else None
    for year, related in related_by_year.items():
        anchor = next(
            (p for p in principals if p["year"] == year), fallback,
        )
        if anchor is None:
            # No principal exists at all; keep related docs auditable on a
            # synthetic year-group record (still not a standalone opportunity).
            anchor = {"url": GOVBR_MMA_FNMA_LISTING_URL, "year": year, "title": f"FNMA {year if year else 'nd'}"}
        rec = _ensure_record(anchor["url"], anchor["year"], anchor["title"])
        for entry in related:
            if entry["url"] not in rec["document_urls"]:
                rec["document_urls"].append(entry["url"])

    return inventory


def _discover_candidates_and_inventory(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_FNMA_MIN_NOTICE_YEAR,
    include_tdr: bool | None = None,
    seen_ids: set[str] | None = None,
    seen_pdfs: set[str] | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    """Discover FNMA edital PDF candidates.

    Returns ``(stats, candidates)`` — the same contract as every other
    source. The inventory (audit mode / fidelity checks) is produced by the
    separate ``build_inventory`` helper. ``include_tdr`` overrides the
    module-level ``FNMA_INCLUDE_TDR`` opt-in for the duration of the call only
    (it never mutates the global ``scraper_filters`` default). ``seen_ids`` /
    ``seen_pdfs`` (defaulting to fresh local sets) let the orchestrator dedup
    opportunity identities AND pdf URLs across the MMA feeds.
    """
    if seen_ids is None:
        seen_ids = set()
    if seen_pdfs is None:
        seen_pdfs = set()
    if include_tdr is None:
        include_tdr = FNMA_INCLUDE_TDR

    stats: dict[str, int] = {
        "listings_fetched": 0,
        "candidates": 0,
        "prefilter_rejected": 0,
        "year_rejected": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
        "inventory_parse_failed": 0,
    }
    candidates: list[dict[str, Any]] = []

    try:
        listing_html = fetch_html_with_retry(GOVBR_MMA_FNMA_LISTING_URL, timeout=30)
        stats["listings_fetched"] += 1
    except Exception as exc:
        log_source_failure(
            "Failed to fetch FNMA listing %s: %s", GOVBR_MMA_FNMA_LISTING_URL, exc, exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        stats["inventory_parse_failed"] = 1
        return stats, candidates, []

    root = _content_root(BeautifulSoup(listing_html, "html.parser"))
    if not isinstance(root, Tag):
        stats["inventory_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates, []

    entries = extract_fnma_links(
        BeautifulSoup(listing_html, "html.parser"), GOVBR_MMA_FNMA_LISTING_URL,
    )
    if not entries:
        stats["inventory_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
        return stats, candidates, []

    inventory = _build_fnma_inventory_records(
        entries,
        filter_policy=filter_policy,
        include_tdr=include_tdr,
        min_year=min_year,
        listing_metadata=_extract_listing_metadata(
            root,
            year=max(
                (entry["year"] for entry in entries if entry["year"] is not None),
                default=None,
            ),
        ),
    )
    inventory_by_id = {record["source_record_id"]: record for record in inventory}

    # Principal edital PDFs become candidates; related non-TDR docs (result /
    # retification / annex) are excluded as standalone opportunities. TDR
    # becomes a candidate only under the source-specific opt-in (does not change
    # the global default policy).
    for entry in entries:
        url = entry["url"]
        year = entry["year"]
        if entry.get("related"):
            continue
        treat_as_tdr = entry.get("tdr") and not include_tdr
        if treat_as_tdr:
            continue

        record_id = _fnma_record_id(url, year=year, title=entry["title"])
        if record_id in seen_ids:
            continue
        if url in seen_pdfs:
            continue

        candidate = build_candidate(
            url,
            listing_url=GOVBR_MMA_FNMA_LISTING_URL,
            filter_policy=filter_policy,
            min_year=min_year,
            origin="listing_pdf",
            year=year,
            source_record_id=record_id,
            include_tdr=include_tdr,
            title=entry["title"],
        )
        if candidate is None:
            if not _passes_year_guard(url, min_year=min_year, source_year=year):
                stats["year_rejected"] += 1
            else:
                stats["prefilter_rejected"] += 1
            continue
        record = inventory_by_id.get(record_id)
        if record is not None:
            candidate["metadata"].update(
                {
                    "status": record["status"],
                    "published_at": record["published_at"],
                    "deadline": record["deadline"],
                }
            )
        seen_ids.add(record_id)
        seen_pdfs.add(url)
        candidates.append(candidate)
        if len(candidates) >= GOVBR_MMA_FNMA_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            break

    stats["candidates"] = len(candidates)
    if stats["candidates"] == 0 and not inventory:
        stats["inventory_parse_failed"] = 1
        stats["errors"] = stats.get("errors", 0) + 1
    return stats, candidates, inventory


def discover_candidates(
    *,
    filter_policy: FilterPolicy = "default",
    min_year: int = GOVBR_MMA_FNMA_MIN_NOTICE_YEAR,
    include_tdr: bool | None = None,
    seen_ids: set[str] | None = None,
    seen_pdfs: set[str] | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    stats, candidates, _inventory = _discover_candidates_and_inventory(
        filter_policy=filter_policy,
        min_year=min_year,
        include_tdr=include_tdr,
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
    for candidate in candidates:
        record_id = candidate.get("metadata", {}).get("source_record_id")
        record = records_by_id.get(record_id)
        if isinstance(record_id, str) and record is not None:
            discovery.append({**record, "document_urls": [candidate["url"]]})
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
    parser = argparse.ArgumentParser(description="Discover MMA FNMA editais")
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
        print(f"GOVBR-MMA FNMA audit stats: {stats}")
        print(f"GOVBR-MMA FNMA audit artifacts: {args.audit_dir}")
        return 1 if stats.get("inventory_parse_failed", 0) else 0

    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"GOVBR-MMA FNMA discovery stats: {stats}")
    print(f"GOVBR-MMA FNMA candidates discovered: {len(candidates)}")

    if stats.get("inventory_parse_failed", 0):
        print("error: FNMA discovery reported a parser failure", file=sys.stderr)
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
    print(f"GOVBR-MMA FNMA processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered FNMA candidates failed download/OCR; "
            "nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(processed, source=SOURCE_KEY)
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered FNMA candidates produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
