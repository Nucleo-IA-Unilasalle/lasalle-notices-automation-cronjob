"""Structured FINEP opportunity discovery through the public Liferay API."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from scraper_transport import request_with_safe_redirects


FINEP_API_URL = "https://www.finep.gov.br/o/c/chamadapublicas"
FINEP_DETAIL_BASE_URL = "https://www.finep.gov.br/chamada-publica/222684"
FINEP_PAGE_SIZE = int(os.environ.get("FINEP_PAGE_SIZE", "20"))
FINEP_MAX_PAGES_PER_RUN = int(os.environ.get("FINEP_MAX_PAGES_PER_RUN", "5"))
FINEP_MAX_OPPORTUNITIES_PER_RUN = int(
    os.environ.get("FINEP_MAX_OPPORTUNITIES_PER_RUN", "10")
)
FINEP_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("FINEP_FETCH_TIMEOUT_SECONDS", "30")
)

_BLOCKED_DOCUMENT = re.compile(
    r"\b(organograma|manual|tutorial|politica|privacidade|formulario|apresentacao)\b",
    re.IGNORECASE,
)
_OWNED_DOCUMENT = re.compile(
    r"\b(edital|chamada|regulamento|termo|anexo)\b", re.IGNORECASE
)


def _choice_name(value: Any) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("name") or value.get("label") or value.get("key")
        return str(candidate).strip() if candidate else None
    if value is None:
        return None
    return str(value).strip() or None


def _list_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for item in value if (name := _choice_name(item))]


def _iso(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def extract_record_documents(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep only call-owned documents from the record description."""
    soup = BeautifulSoup(str(record.get("descricao") or ""), "html.parser")
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not re.search(r"\.pdf($|[?#])", href, re.I):
            continue
        url = urljoin("https://www.finep.gov.br/", href)
        evidence = f"{link.get_text(' ', strip=True)} {url}"
        if _BLOCKED_DOCUMENT.search(evidence) or not _OWNED_DOCUMENT.search(evidence):
            continue
        if url in seen:
            continue
        seen.add(url)
        documents.append(
            {
                "source_document_id": str(len(documents) + 1),
                "document_kind": "pdf",
                "url": url,
                "filename": url.split("?", 1)[0].rsplit("/", 1)[-1],
                "mime_type": "application/pdf",
                "is_principal": not documents,
                "is_renderable": False,
            }
        )
    return documents


def build_source_markdown(record: dict[str, Any]) -> str:
    """Render authoritative API fields in a fixed, hash-stable order."""
    fields: list[tuple[str, str | None]] = [
        ("Titulo", str(record.get("titulo") or "").strip() or None),
        ("Descricao", str(record.get("descricaoRawText") or "").strip() or None),
        ("Situacao", _choice_name(record.get("situacao"))),
        ("Publicacao", _iso(record.get("dataDePublicacao"))),
        ("Prazo", _iso(record.get("prazoProposto"))),
        ("Publico-alvo", ", ".join(_list_names(record.get("publicoAlvo"))) or None),
        ("Regiao", _choice_name(record.get("regiao"))),
        ("Tipo", _choice_name(record.get("tipoDeOportunidade"))),
        ("Tema", str(record.get("tema") or "").strip() or None),
    ]
    title = fields[0][1] or f"Chamada FINEP {record.get('id')}"
    lines = [f"# {title}"]
    for label, value in fields[1:]:
        if value:
            lines.extend(("", f"## {label}", "", value))
    return "\n".join(lines).strip()


def record_to_inventory(record: dict[str, Any]) -> dict[str, Any]:
    record_id = str(record["id"])
    documents = extract_record_documents(record)
    return {
        "source_key": "finep",
        "source_record_id": record_id,
        "canonical_url": f"{FINEP_DETAIL_BASE_URL}/{record_id}",
        "title": str(record.get("titulo") or "").strip(),
        "status": (_choice_name(record.get("situacao")) or "unknown").lower(),
        "published_at": _iso(record.get("dataDePublicacao")),
        "deadline": _iso(record.get("prazoProposto")),
        "document_urls": [document["url"] for document in documents],
        "document_hashes": [],
    }


def record_to_opportunity(
    record: dict[str, Any], *, snapshot_at: datetime | None = None
) -> dict[str, Any]:
    record_id = str(record["id"])
    markdown = build_source_markdown(record)
    snapshot = snapshot_at or datetime.now(timezone.utc)
    return {
        "source_key": "finep",
        "source_record_id": record_id,
        "source_kind": "api",
        "opportunity_type": "funding",
        "canonical_url": f"{FINEP_DETAIL_BASE_URL}/{record_id}",
        "title": str(record.get("titulo") or "").strip(),
        "description": str(record.get("descricaoRawText") or "").strip() or None,
        "authoritative_status": _choice_name(record.get("situacao")),
        "source_published_at": _iso(record.get("dataDePublicacao")),
        "source_updated_at": _iso(record.get("dateModified")),
        "proposal_opens_at": _iso(record.get("vigenciaInicio")),
        "application_deadline": _iso(record.get("prazoProposto")),
        "source_snapshot_at": snapshot.astimezone(timezone.utc).isoformat(),
        "source_markdown": markdown,
        "source_content_hash": "",
        "documents": extract_record_documents(record),
    }


def fetch_api_pages(
    *,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch bounded, explicitly paginated API records."""
    if fetch_json is None:
        def fetch_json(url: str) -> dict[str, Any]:
            response = request_with_safe_redirects(
                method="GET",
                url=url,
                timeout=FINEP_FETCH_TIMEOUT_SECONDS,
                extra_headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("FINEP API response must be an object")
            return payload

    records: list[dict[str, Any]] = []
    for page in range(1, FINEP_MAX_PAGES_PER_RUN + 1):
        url = (
            f"{FINEP_API_URL}?sort=dataDePublicacao:desc"
            f"&pageSize={FINEP_PAGE_SIZE}&page={page}"
        )
        payload = fetch_json(url)
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("FINEP API response is missing items")
        records.extend(item for item in items if isinstance(item, dict))
        if page >= int(payload.get("lastPage") or page):
            break
    return records


def discover_opportunities(
    *,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
    snapshot_at: datetime | None = None,
    min_year: int | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    records = fetch_api_pages(fetch_json=fetch_json)
    if not records:
        return {"inventory_parse_failed": 1, "records": 0, "opportunities": 0}, []

    opportunities: list[dict[str, Any]] = []
    rejected = 0
    for record in records:
        if not record.get("id") or not str(record.get("titulo") or "").strip():
            rejected += 1
            continue
        published = _iso(record.get("dataDePublicacao"))
        if min_year and published and int(published[:4]) < min_year:
            rejected += 1
            continue
        status = (_choice_name(record.get("situacao")) or "").lower()
        if status not in {"aberta", "open"}:
            rejected += 1
            continue
        opportunities.append(
            record_to_opportunity(record, snapshot_at=snapshot_at)
        )
        if len(opportunities) >= FINEP_MAX_OPPORTUNITIES_PER_RUN:
            break
    return {
        "records": len(records),
        "opportunities": len(opportunities),
        "policy_rejected": rejected,
    }, opportunities

