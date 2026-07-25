"""FBDS Restaura Amazonia opportunity and ZIP attachment discovery."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from scraper_transport import fetch_html_with_retry
from structured_discovery import (
    StructuredDiscoveryResult,
    normalize_audit_status,
    parser_failure,
    policy_rejection,
)


FBDS_LISTING_URL = "https://restaura-amazonia.fbds.org.br/Editais"
FBDS_MAX_DETAILS_PER_RUN = int(os.environ.get("FBDS_MAX_DETAILS_PER_RUN", "20"))
FBDS_FETCH_TIMEOUT_SECONDS = int(os.environ.get("FBDS_FETCH_TIMEOUT_SECONDS", "30"))


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def extract_fbds_records(listing_html: str, listing_url: str) -> list[dict[str, str]]:
    """Parse only anchors in the canonical edital listing content."""
    soup = BeautifulSoup(listing_html, "html.parser")
    body = soup.select_one("#content-core, #Principal, main, .editais, .content")
    if body is None:
        return []
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    host = (urlsplit(listing_url).hostname or "").lower()
    for link in body.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        title = link.get_text(" ", strip=True)
        if not isinstance(href, str) or not title:
            continue
        resolved = canonical_url(urljoin(listing_url, href))
        parts = urlsplit(resolved)
        if (parts.hostname or "").lower() != host or parts.path.rstrip("/") == "/Editais":
            continue
        evidence = f"{title} {parts.path}"
        if not re.search(r"\b(edital|restaura|restauracao|apoio)\b", evidence, re.I):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        match = re.search(r"(?:-|/)(\d+)$", parts.path)
        record_id = match.group(1) if match else parts.path.strip("/").lower()
        records.append(
            {
                "source_record_id": record_id,
                "canonical_url": resolved,
                "title": title,
            }
        )
    return records


def parse_fbds_detail(
    record: dict[str, str],
    detail_html: str,
    *,
    snapshot_at: datetime | None = None,
) -> dict[str, object]:
    soup = BeautifulSoup(detail_html, "html.parser")
    content = soup.select_one("#content-core, #Principal, main, article, .content")
    if content is None:
        raise ValueError("FBDS detail content area not found")
    heading = content.find(["h1", "h2"])
    title = heading.get_text(" ", strip=True) if isinstance(heading, Tag) else record["title"]
    text = re.sub(r"\s+", " ", content.get_text(" ", strip=True)).strip()
    deadline_match = re.search(
        r"(?:prazo|encerramento|inscri(?:cao|ções|coes)).{0,40}?(\d{2}/\d{2}/\d{4})",
        text,
        re.I,
    )
    deadline = None
    if deadline_match:
        deadline = datetime.strptime(deadline_match.group(1), "%d/%m/%Y").replace(
            hour=23, minute=59, tzinfo=timezone.utc
        ).isoformat()
    status_match = re.search(r"\b(aberto|aberta|encerrado|encerrada)\b", text, re.I)
    status = status_match.group(1).lower() if status_match else "unknown"
    documents: list[dict[str, object]] = []
    seen: set[str] = set()
    for link in content.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        url = canonical_url(urljoin(record["canonical_url"], href))
        path = urlsplit(url).path.lower()
        if not path.endswith((".pdf", ".zip")) or url in seen:
            continue
        seen.add(url)
        kind = "zip" if path.endswith(".zip") else "pdf"
        documents.append(
            {
                "source_document_id": str(len(documents) + 1),
                "document_kind": kind,
                "url": url,
                "filename": urlsplit(url).path.rsplit("/", 1)[-1],
                "mime_type": "application/zip" if kind == "zip" else "application/pdf",
                "is_principal": False,
                "is_renderable": False,
            }
        )
    markdown = f"# {title}\n\n## Fonte oficial\n\n{record['canonical_url']}\n\n## Conteudo\n\n{text}"
    snapshot = snapshot_at or datetime.now(timezone.utc)
    return {
        "source_key": "fbds",
        "source_record_id": record["source_record_id"],
        "source_kind": "web",
        "opportunity_type": "funding",
        "canonical_url": record["canonical_url"],
        "title": title,
        "description": text or None,
        "authoritative_status": status,
        "source_published_at": None,
        "source_updated_at": None,
        "proposal_opens_at": None,
        "application_deadline": deadline,
        "source_snapshot_at": snapshot.astimezone(timezone.utc).isoformat(),
        "source_markdown": markdown,
        "source_content_hash": "",
        "documents": documents,
    }


def parse_fbds_inventory_record(
    record: dict[str, str],
    detail_html: str,
) -> dict[str, object]:
    """Parse the canonical detail page directly into the audit schema."""
    soup = BeautifulSoup(detail_html, "html.parser")
    content = soup.select_one("#content-core, #Principal, main, article, .content")
    if content is None:
        raise ValueError("FBDS detail content area not found")
    heading = content.find(["h1", "h2"])
    title = (
        heading.get_text(" ", strip=True)
        if isinstance(heading, Tag)
        else record["title"]
    )
    text = re.sub(r"\s+", " ", content.get_text(" ", strip=True)).strip()
    deadline_match = re.search(
        r"(?:prazo|encerramento|inscri(?:cao|ções|coes)).{0,40}?(\d{2}/\d{2}/\d{4})",
        text,
        re.I,
    )
    deadline = (
        datetime.strptime(deadline_match.group(1), "%d/%m/%Y")
        .replace(hour=23, minute=59, tzinfo=timezone.utc)
        .isoformat()
        if deadline_match
        else None
    )
    status_match = re.search(
        r"\b(aberto|aberta|encerrado|encerrada)\b", text, re.I
    )
    document_urls: list[str] = []
    for link in content.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        url = canonical_url(urljoin(record["canonical_url"], href))
        if (
            urlsplit(url).path.lower().endswith((".pdf", ".zip"))
            and url not in document_urls
        ):
            document_urls.append(url)
    return {
        "source_key": "fbds",
        "source_record_id": record["source_record_id"],
        "canonical_url": record["canonical_url"],
        "title": title,
        "status": normalize_audit_status(
            status_match.group(1) if status_match else None
        ),
        "published_at": None,
        "deadline": deadline,
        "document_urls": document_urls,
        "document_hashes": [],
    }


def discover_opportunities(
    *,
    fetch_html: Callable[[str], str] | None = None,
    snapshot_at: datetime | None = None,
    min_year: int | None = None,
) -> StructuredDiscoveryResult:
    del min_year
    if fetch_html is None:
        fetch_html = lambda url: fetch_html_with_retry(
            url, timeout=FBDS_FETCH_TIMEOUT_SECONDS
        )
    listing = fetch_html(FBDS_LISTING_URL)
    records = extract_fbds_records(listing, FBDS_LISTING_URL)
    if not records:
        failure = parser_failure(
            "fbds",
            stage="listing_inventory",
            error="canonical listing returned no edital records",
        )
        return StructuredDiscoveryResult(
            stats={
                "inventory_parse_failed": 1,
                "records": 0,
                "inventory_records": 0,
                "opportunities": 0,
                "parser_failures": 1,
            },
            inventory=[],
            opportunities=[],
            parser_failures=[failure],
        )
    inventory: list[dict[str, object]] = []
    opportunities: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    parser_failures: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if index >= FBDS_MAX_DETAILS_PER_RUN:
            parser_failures.append(
                parser_failure(
                    "fbds",
                    stage="detail_inventory",
                    error="detail fetch cap left an authoritative record unresolved",
                    evidence={
                        "source_record_id": record["source_record_id"],
                        "canonical_url": record["canonical_url"],
                        "detail_cap": FBDS_MAX_DETAILS_PER_RUN,
                    },
                )
            )
            continue
        try:
            detail_html = fetch_html(record["canonical_url"])
            inventory_record = parse_fbds_inventory_record(record, detail_html)
        except Exception as exc:
            parser_failures.append(
                parser_failure(
                    "fbds",
                    stage="detail_inventory",
                    error=str(exc),
                    evidence={
                        "source_record_id": record["source_record_id"],
                        "canonical_url": record["canonical_url"],
                    },
                )
            )
            continue
        if inventory_record["status"] == "closed":
            rejected = policy_rejection(
                inventory_record,
                policy="open_status_only",
                evidence={
                    "authoritative_status": inventory_record["status"],
                },
            )
            inventory.append(rejected)
            rejections.append(rejected)
            continue
        inventory.append(inventory_record)
        try:
            opportunities.append(
                parse_fbds_detail(
                    record,
                    detail_html,
                    snapshot_at=snapshot_at,
                )
            )
        except Exception as exc:
            parser_failures.append(
                parser_failure(
                    "fbds",
                    stage="opportunity_projection",
                    error=str(exc),
                    evidence={
                        "source_record_id": record["source_record_id"],
                        "canonical_url": record["canonical_url"],
                    },
                )
            )
    stats = {
        "records": len(records),
        "details_fetched": len(opportunities),
        "inventory_records": len(inventory),
        "opportunities": len(opportunities),
        "errors": len(parser_failures),
        "policy_rejected": len(rejections),
        "parser_failures": len(parser_failures),
    }
    if parser_failures:
        stats["inventory_parse_failed"] = 1
    return StructuredDiscoveryResult(
        stats=stats,
        inventory=inventory,
        opportunities=opportunities,
        policy_rejections=rejections,
        parser_failures=parser_failures,
    )
