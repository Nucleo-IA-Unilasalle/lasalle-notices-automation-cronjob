"""Shared contract for independently auditable structured-source discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StructuredDiscoveryResult:
    """Keep authoritative inventory separate from accepted opportunities.

    ``inventory`` is produced from the source's canonical records before
    acceptance policy and submission caps are applied. ``opportunities`` is
    the independently produced set eligible for discovery/submission.
    """

    stats: dict[str, int]
    inventory: list[dict[str, Any]]
    opportunities: list[dict[str, Any]]
    policy_rejections: list[dict[str, Any]] = field(default_factory=list)
    parser_failures: list[dict[str, Any]] = field(default_factory=list)

    def __iter__(self):
        """Preserve the historical ``stats, opportunities = result`` API."""
        yield self.stats
        yield self.opportunities


def normalize_audit_status(value: Any) -> str:
    """Map source-native status labels to the fidelity contract."""
    status = str(value or "").strip().casefold()
    if status in {"aberta", "aberto", "open"}:
        return "open"
    if status in {
        "closed",
        "encerrada",
        "encerrado",
        "expired",
        "fechada",
        "fechado",
    }:
        return "closed"
    return "unknown"


def opportunity_to_fidelity_record(
    opportunity: dict[str, Any],
) -> dict[str, Any]:
    """Project an accepted opportunity into the Plan-01 discovery schema."""
    documents = opportunity.get("documents") or []
    return {
        "source_key": opportunity.get("source_key"),
        "source_record_id": opportunity.get("source_record_id"),
        "canonical_url": opportunity.get("canonical_url"),
        "title": opportunity.get("title"),
        "status": normalize_audit_status(
            opportunity.get("authoritative_status")
        ),
        "published_at": opportunity.get("source_published_at"),
        "deadline": opportunity.get("application_deadline"),
        "document_urls": [
            document.get("url")
            for document in documents
            if document.get("url")
        ],
        "document_hashes": [
            document.get("content_hash")
            for document in documents
            if document.get("content_hash")
        ],
    }


def policy_rejection(
    inventory_record: dict[str, Any],
    *,
    policy: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Return an auditable non-blocking disposition for one source record."""
    disposition = dict(inventory_record)
    disposition["reason_code"] = "out_of_scope"
    disposition["evidence"] = {"policy": policy, **evidence}
    return disposition


def parser_failure(
    source_key: str,
    *,
    stage: str,
    error: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build stable parser-failure evidence for workflow verification."""
    return {
        "source_key": source_key,
        "stage": stage,
        "error": error,
        "evidence": evidence or {},
    }
