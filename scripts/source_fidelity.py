"""Deterministic source-fidelity schemas, normalization, matching, and reporting.

This module compares a source inventory (the authoritative set of open
opportunities), discovery candidates, and an optional dashboard export
without any LLM or network calls. It produces a JSON + Markdown report
describing how the three inputs agree or disagree.

The matching ladder is, in descending authority:

1. ``(source_key, source_record_id)``
2. canonical URL after fragment removal and safe normalization
3. exact document SHA-256
4. exact normalized document URL

Title similarity never establishes identity; it may only add a human-review
suggestion to an exception.

All blocking reason codes are enumerated in ``BLOCKING_REASON_CODES``. Every
exception carries a ``severity``, a ``reason_code``, and ``evidence``. There is
no generic ignored bucket: the only non-blocking reason codes are
``missing_optional_metadata``, ``out_of_scope``, and ``unresolved_news_lead``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


UNKNOWN = "unknown"

BLOCKING_REASON_CODES = frozenset(
    {
        "missing_open",
        "extra_submission",
        "duplicate_identity",
        "identity_mismatch",
        "authoritative_status_mismatch",
        "authoritative_deadline_mismatch",
        "renderability_mismatch",
        "parser_failure",
    }
)

NON_BLOCKING_REASON_CODES = frozenset(
    {
        "missing_optional_metadata",
        "out_of_scope",
        "unresolved_news_lead",
    }
)

EXPLICIT_DISPOSITION_CODES = frozenset({"out_of_scope", "unresolved_news_lead"})

SEVERITY_BLOCKING = "blocking"
SEVERITY_NON_BLOCKING = "non_blocking"


@dataclass
class NormalizedRecord:
    source_key: Optional[str] = None
    source_record_id: Optional[str] = None
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    published_at: Optional[str] = None
    deadline: Optional[str] = None
    document_urls: list[str] = field(default_factory=list)
    document_hashes: list[str] = field(default_factory=list)
    reason_code: Optional[str] = None
    origin: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            s = _as_str(item)
            if s is not None:
                out.append(s)
        return out
    s = _as_str(value)
    return [s] if s is not None else []


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Remove the fragment and normalize the query string without dropping params.

    Meaningful query parameters are preserved (sorted for determinism). The
    scheme and host are lower-cased and the default port is stripped. The
    path is collapsed of duplicate slashes but not otherwise rewritten.
    """
    if url is None:
        return None
    s = str(url).strip()
    if not s:
        return None
    try:
        parts = urlsplit(s)
    except (ValueError, AttributeError):
        return s
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if host and host.endswith(":80") and scheme == "http":
        host = host[:-3]
    if host and host.endswith(":443") and scheme == "https":
        host = host[:-4]
    path = re.sub(r"/{2,}", "/", parts.path)
    if path and not path.startswith("/"):
        path = "/" + path
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    # Sort keys for stable output without reordering repeated values, whose
    # order can be meaningful to the origin server.
    query = urlencode(sorted(query_pairs, key=lambda item: item[0]))
    return urlunsplit((scheme, host, path, query, ""))


def normalize_timestamp(value: Any) -> tuple[Optional[str], Optional[str]]:
    """Return (normalized_utc_iso, original_value) or (None, None) for empty.

    The original textual value is preserved in the returned pair so it can be
    attached to evidence. Parsing is deliberately strict: only ISO-8601
    variants (with optional trailing ``Z``) are accepted. Anything else is a
    ``parser_failure`` candidate surfaced by the caller.
    """
    original = _as_str(value)
    if original is None:
        return None, None
    text = original
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None, original
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z"), original


def normalize_record(raw: dict[str, Any], origin: str) -> NormalizedRecord:
    canonical = normalize_url(_as_str(raw.get("canonical_url")))
    published_norm, _ = normalize_timestamp(raw.get("published_at"))
    deadline_norm, _ = normalize_timestamp(raw.get("deadline"))
    return NormalizedRecord(
        source_key=_as_str(raw.get("source_key")),
        source_record_id=_as_str(raw.get("source_record_id")),
        canonical_url=canonical,
        title=_as_str(raw.get("title")),
        status=_as_str(raw.get("status")),
        published_at=published_norm,
        deadline=deadline_norm,
        document_urls=[u for u in (_norm_doc(u) for u in _as_list(raw.get("document_urls"))) if u],
        document_hashes=[h.lower() for h in _as_list(raw.get("document_hashes"))],
        reason_code=_as_str(raw.get("reason_code")),
        origin=origin,
        raw=raw,
    )


def validate_records(records: Any, origin: str) -> list[dict[str, Any]]:
    """Validate the external JSON schema before the audit starts."""
    if not isinstance(records, list):
        raise ValueError(f"{origin} must contain a JSON array of records")

    string_fields = (
        "source_key",
        "source_record_id",
        "canonical_url",
        "title",
        "status",
        "published_at",
        "deadline",
    )
    bool_fields = ("renderable", "content_type_validated", "hash_validated")
    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        prefix = f"{origin}[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{prefix} must be a JSON object")
        for name in string_fields:
            value = raw.get(name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{prefix}.{name} must be a string or null")
        for name in ("document_urls", "document_hashes"):
            value = raw.get(name)
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
            ):
                raise ValueError(f"{prefix}.{name} must be an array of strings")
        for name in bool_fields:
            value = raw.get(name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{prefix}.{name} must be a boolean or null")
        reason_code = raw.get("reason_code")
        if reason_code is not None and reason_code not in EXPLICIT_DISPOSITION_CODES:
            raise ValueError(
                f"{prefix}.reason_code must be one of "
                f"{', '.join(sorted(EXPLICIT_DISPOSITION_CODES))}"
            )
        evidence = raw.get("evidence")
        if evidence is not None and not isinstance(evidence, dict):
            raise ValueError(f"{prefix}.evidence must be an object or null")
        for hash_index, value in enumerate(raw.get("document_hashes") or []):
            if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
                raise ValueError(
                    f"{prefix}.document_hashes[{hash_index}] must be a SHA-256 hex digest"
                )
        validated.append(raw)
    return validated


def _norm_doc(url: str) -> Optional[str]:
    return normalize_url(url)


def record_stable_id(rec: NormalizedRecord) -> Optional[tuple[str, str]]:
    if rec.source_key and rec.source_record_id:
        return (rec.source_key, rec.source_record_id)
    return None


def empty_record_without_id(rec: NormalizedRecord) -> bool:
    if record_stable_id(rec) is not None:
        return False
    if rec.canonical_url:
        return False
    if rec.document_urls or rec.document_hashes:
        return False
    return True


def is_open_in_scope(rec: NormalizedRecord) -> bool:
    """Whether an inventory record belongs in the missing-open gate.

    Sources such as WWF intentionally inventory closed rows alongside open
    rows. Closed (and status-unknown) records remain useful provenance, but
    are not required to have a current candidate/submission. Explicit policy
    dispositions are similarly outside the in-scope denominator.
    """
    return rec.status == "open" and rec.reason_code not in EXPLICIT_DISPOSITION_CODES


@dataclass
class ExceptionRecord:
    severity: str
    reason_code: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "reason_code": self.reason_code,
            "evidence": _redact_value(self.evidence),
        }

    @property
    def blocking(self) -> bool:
        return self.reason_code in BLOCKING_REASON_CODES


@dataclass
class MatchRecord:
    match_key: str
    match_method: str
    discovery_match_method: Optional[str]
    dashboard_match_method: Optional[str]
    inventory: Optional[dict[str, Any]]
    discovery: Optional[dict[str, Any]]
    dashboard: Optional[dict[str, Any]]
    field_comparison: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(
            {
                "match_key": self.match_key,
                "match_method": self.match_method,
                "discovery_match_method": self.discovery_match_method,
                "dashboard_match_method": self.dashboard_match_method,
                "inventory": self.inventory,
                "discovery": self.discovery,
                "dashboard": self.dashboard,
                "field_comparison": self.field_comparison,
            }
        )


@dataclass
class AuditResult:
    matches: list[MatchRecord]
    exceptions: list[ExceptionRecord]
    gates: dict[str, Any]

    def blocking_exceptions(self) -> list[ExceptionRecord]:
        return [e for e in self.exceptions if e.blocking]

    def non_blocking_exceptions(self) -> list[ExceptionRecord]:
        return [e for e in self.exceptions if not e.blocking]


def _identity_key(rec: NormalizedRecord, method: str) -> Optional[Any]:
    if method == "stable_id":
        return record_stable_id(rec)
    if method == "canonical_url":
        return rec.canonical_url
    if method == "document_hash":
        return frozenset(rec.document_hashes) or None
    if method == "document_url":
        return frozenset(rec.document_urls) or None
    return None


def _matching_identity(
    left: NormalizedRecord, right: NormalizedRecord, method: str
) -> Optional[Any]:
    left_key = _identity_key(left, method)
    right_key = _identity_key(right, method)
    if left_key is None or right_key is None:
        return None
    if method in ("document_hash", "document_url"):
        shared = sorted(left_key.intersection(right_key))
        return shared[0] if shared else None
    return left_key if left_key == right_key else None


def detect_internal_duplicates(
    records: list[NormalizedRecord], origin: str
) -> list[ExceptionRecord]:
    """Flag duplicate (source_key, source_record_id), canonical URL, and hash."""
    out: list[ExceptionRecord] = []
    seen: dict[str, list[tuple[int, NormalizedRecord]]] = {}

    for idx, rec in enumerate(records):
        sid = record_stable_id(rec)
        if sid is not None:
            seen.setdefault("sid:" + str(sid), []).append((idx, rec))
        if rec.canonical_url:
            seen.setdefault("url:" + rec.canonical_url, []).append((idx, rec))
        for h in rec.document_hashes:
            seen.setdefault("hash:" + h, []).append((idx, rec))

    for key, group in seen.items():
        if len(group) < 2:
            continue
        kind, _, value = key.partition(":")
        indices = [g[0] for g in group]
        out.append(
            ExceptionRecord(
                severity=SEVERITY_BLOCKING,
                reason_code="duplicate_identity",
                evidence={
                    "type": kind,
                    "value": value,
                    "origin": origin,
                    "record_indices": sorted(indices),
                },
            )
        )
    return out


def _compare_field(
    name: str,
    inv: Optional[str],
    other: Optional[str],
    *,
    authoritative_mismatch: str,
    origin: str,
) -> Optional[ExceptionRecord]:
    inv_val = inv if inv is not None else UNKNOWN
    other_val = other if other is not None else UNKNOWN
    if inv_val == UNKNOWN or other_val == UNKNOWN:
        if inv_val == UNKNOWN and other_val != UNKNOWN:
            return ExceptionRecord(
                severity=SEVERITY_NON_BLOCKING,
                reason_code="missing_optional_metadata",
                evidence={"field": name, "inventory": inv, origin: other, "origin": origin},
            )
        if other_val == UNKNOWN and inv_val != UNKNOWN:
            return ExceptionRecord(
                severity=SEVERITY_NON_BLOCKING,
                reason_code="missing_optional_metadata",
                evidence={"field": name, "inventory": inv, origin: other, "origin": origin},
            )
        return None
    if inv_val != other_val:
        return ExceptionRecord(
            severity=SEVERITY_BLOCKING,
            reason_code=authoritative_mismatch,
            evidence={
                "field": name,
                "inventory_value": inv,
                "other_value": other,
                "origin": origin,
            },
        )
    return None


_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "authorisation",
        "proxy_authorization",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "secret",
        "client_secret",
        "credential",
        "credentials",
        "signature",
        "private_key",
        "api_key",
        "apikey",
        "auth",
        "authentication",
        "bearer",
        "jwt",
        "session",
        "session_id",
        "sig",
        "password",
        "passwd",
        "cookie",
        "set_cookie",
    }
)


def _sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(f"_{needle}") for needle in _SENSITIVE_KEYS
    )


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"[REDACTED]@{netloc.rsplit('@', 1)[1]}"
    query = urlencode(
        [
            (key, "[REDACTED]" if _sensitive_key(key) else item_value)
            for key, item_value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _sensitive_key(key) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, str):
        return _redact_url(value)
    return value


def _redact(raw: dict[str, Any]) -> dict[str, Any]:
    return _redact_value(raw)


def _detect_identity_mismatch(
    inv: NormalizedRecord, other: NormalizedRecord
) -> Optional[ExceptionRecord]:
    if record_stable_id(inv) is None or record_stable_id(inv) != record_stable_id(other):
        return None
    inv_urls = set(inv.document_urls)
    other_urls = set(other.document_urls)
    inv_hashes = set(inv.document_hashes)
    other_hashes = set(other.document_hashes)
    if inv_urls and other_urls and inv_urls.isdisjoint(other_urls):
        if inv_hashes and other_hashes and inv_hashes.isdisjoint(other_hashes):
            return ExceptionRecord(
                severity=SEVERITY_BLOCKING,
                reason_code="identity_mismatch",
                evidence={
                    "stable_id": record_stable_id(inv),
                    "inventory_canonical_url": inv.canonical_url,
                    "other_canonical_url": other.canonical_url,
                    "inventory_document_urls": inv.document_urls,
                    "other_document_urls": other.document_urls,
                    "inventory_document_hashes": inv.document_hashes,
                    "other_document_hashes": other.document_hashes,
                    "other_origin": other.origin,
                },
            )
    return None


def _detect_conflicting_stable_ids(
    inv: NormalizedRecord, other: NormalizedRecord
) -> Optional[ExceptionRecord]:
    """Reject a lower-authority match that contradicts both stable IDs."""
    inv_stable_id = record_stable_id(inv)
    other_stable_id = record_stable_id(other)
    if (
        inv_stable_id is None
        or other_stable_id is None
        or inv_stable_id == other_stable_id
    ):
        return None

    for method in ("canonical_url", "document_hash", "document_url"):
        shared_identity = _matching_identity(inv, other, method)
        if shared_identity is None:
            continue
        return ExceptionRecord(
            severity=SEVERITY_BLOCKING,
            reason_code="identity_mismatch",
            evidence={
                "inventory_stable_id": inv_stable_id,
                "other_stable_id": other_stable_id,
                "shared_lower_authority_method": method,
                "shared_lower_authority_identity": shared_identity,
                "other_origin": other.origin,
            },
        )
    return None


def _title_suggestion(inv: NormalizedRecord, other: NormalizedRecord) -> Optional[str]:
    if inv.title and other.title and inv.title.strip().lower() == other.title.strip().lower():
        return f"title matches between {inv.origin} and {other.origin}; human review suggested (not used for identity)"
    return None


def run_audit(
    inventory: list[dict[str, Any]],
    discovery: list[dict[str, Any]],
    dashboard: Optional[list[dict[str, Any]]] = None,
) -> AuditResult:
    inv_recs = [normalize_record(r, "inventory") for r in inventory]
    disc_recs = [normalize_record(r, "discovery") for r in discovery]
    dash_recs = (
        [normalize_record(r, "dashboard") for r in dashboard]
        if dashboard is not None
        else []
    )

    exceptions: list[ExceptionRecord] = []
    exceptions.extend(detect_internal_duplicates(inv_recs, "inventory"))
    exceptions.extend(detect_internal_duplicates(disc_recs, "discovery"))
    exceptions.extend(detect_internal_duplicates(dash_recs, "dashboard"))

    conflicting_stable_id_pairs: set[tuple[int, str, int]] = set()
    for inv_idx, inv in enumerate(inv_recs):
        for origin, records in (("discovery", disc_recs), ("dashboard", dash_recs)):
            for other_idx, other in enumerate(records):
                conflict = _detect_conflicting_stable_ids(inv, other)
                if conflict is None:
                    continue
                exceptions.append(conflict)
                conflicting_stable_id_pairs.add((inv_idx, origin, other_idx))

    for rec in inv_recs + disc_recs + dash_recs:
        pub_dt, pub_orig = normalize_timestamp(rec.raw.get("published_at"))
        dl_dt, dl_orig = normalize_timestamp(rec.raw.get("deadline"))
        bad = []
        if rec.raw.get("published_at") is not None and pub_dt is None:
            bad.append(("published_at", pub_orig))
        if rec.raw.get("deadline") is not None and dl_dt is None:
            bad.append(("deadline", dl_orig))
        for field_name, original in bad:
            exceptions.append(
                ExceptionRecord(
                    severity=SEVERITY_BLOCKING,
                    reason_code="parser_failure",
                    evidence={
                        "origin": rec.origin,
                        "field": field_name,
                        "value": original,
                        "error": "unparseable timestamp",
                    },
                )
            )
        validation_exception = _renderability_validation_exception(rec)
        if validation_exception is not None:
            exceptions.append(validation_exception)

    matched_indices: set[tuple[str, int]] = set()
    matches: list[MatchRecord] = []
    methods = ("stable_id", "canonical_url", "document_hash", "document_url")

    def find_match(
        inv: NormalizedRecord,
        inv_index: int,
        records: list[NormalizedRecord],
        origin: str,
    ) -> tuple[Optional[int], Optional[str], Optional[Any]]:
        for method in methods:
            for index, candidate in enumerate(records):
                if (origin, index) in matched_indices:
                    continue
                if (inv_index, origin, index) in conflicting_stable_id_pairs:
                    continue
                identity = _matching_identity(inv, candidate, method)
                if identity is not None:
                    return index, method, identity
        return None, None, None

    def policy_exception(rec: NormalizedRecord) -> Optional[ExceptionRecord]:
        if rec.reason_code not in EXPLICIT_DISPOSITION_CODES:
            return None
        supplied_evidence = rec.raw.get("evidence") or {}
        return ExceptionRecord(
            severity=SEVERITY_NON_BLOCKING,
            reason_code=rec.reason_code,
            evidence={
                "origin": rec.origin,
                "record": _redact(rec.raw),
                **_redact(supplied_evidence),
            },
        )

    for inv_idx, inv in enumerate(inv_recs):
        best_disc, disc_method, disc_identity = find_match(
            inv, inv_idx, disc_recs, "discovery"
        )
        best_dash, dash_method, dash_identity = find_match(
            inv, inv_idx, dash_recs, "dashboard"
        )

        if best_disc is None and best_dash is None:
            explicit_policy = policy_exception(inv)
            if explicit_policy is not None:
                exceptions.append(explicit_policy)
            elif is_open_in_scope(inv):
                exceptions.append(
                    ExceptionRecord(
                        severity=SEVERITY_BLOCKING,
                        reason_code="missing_open",
                        evidence={
                            "inventory": _redact(inv.raw),
                            "stable_id": record_stable_id(inv),
                            "canonical_url": inv.canonical_url,
                            "title": inv.title,
                        },
                    )
                )
            matched_indices.add(("inventory", inv_idx))
            continue

        disc = disc_recs[best_disc] if best_disc is not None else None
        dash = dash_recs[best_dash] if best_dash is not None else None
        comparison: dict[str, Any] = {}

        for field_name, mismatch_code in (
            ("status", "authoritative_status_mismatch"),
            ("deadline", "authoritative_deadline_mismatch"),
        ):
            inv_value = getattr(inv, field_name)
            values: dict[str, Any] = {
                "inventory": inv_value if inv_value is not None else UNKNOWN,
                "discovery": UNKNOWN,
                "dashboard": UNKNOWN,
            }
            field_matches = True
            for origin, other in (("discovery", disc), ("dashboard", dash)):
                if other is None:
                    continue
                other_value = getattr(other, field_name)
                values[origin] = other_value if other_value is not None else UNKNOWN
                field_exception = _compare_field(
                    field_name,
                    inv_value,
                    other_value,
                    authoritative_mismatch=mismatch_code,
                    origin=origin,
                )
                if field_exception is not None:
                    exceptions.append(field_exception)
                    if field_exception.blocking:
                        field_matches = False
            values["match"] = field_matches
            comparison[field_name] = values

        inv_renderable = _is_renderable(inv)
        render_values: dict[str, Any] = {
            "inventory": inv_renderable if inv_renderable is not None else UNKNOWN,
            "discovery": UNKNOWN,
            "dashboard": UNKNOWN,
        }
        render_match = True
        for origin, other in (("discovery", disc), ("dashboard", dash)):
            if other is None:
                continue
            other_renderable = _is_renderable(other)
            render_values[origin] = (
                other_renderable if other_renderable is not None else UNKNOWN
            )
            if (
                inv_renderable is not None
                and other_renderable is not None
                and inv_renderable != other_renderable
            ):
                render_match = False
                exceptions.append(
                    ExceptionRecord(
                        severity=SEVERITY_BLOCKING,
                        reason_code="renderability_mismatch",
                        evidence={
                            "field": "renderable",
                            "origin": origin,
                            "inventory_value": inv_renderable,
                            "other_value": other_renderable,
                        },
                    )
                )
        render_values["match"] = render_match
        comparison["renderable"] = render_values

        suggestions = [
            suggestion
            for other in (disc, dash)
            if other is not None
            for suggestion in [_title_suggestion(inv, other)]
            if suggestion is not None
        ]
        if suggestions:
            comparison["title_suggestions"] = suggestions

        for other in (disc, dash):
            if other is None:
                continue
            identity_exc = _detect_identity_mismatch(inv, other)
            if identity_exc is not None:
                exceptions.append(identity_exc)

        matched_indices.add(("inventory", inv_idx))
        if best_disc is not None:
            matched_indices.add(("discovery", best_disc))
        if best_dash is not None:
            matched_indices.add(("dashboard", best_dash))

        primary_method = disc_method or dash_method
        primary_identity = disc_identity if disc_method is not None else dash_identity
        assert primary_method is not None and primary_identity is not None
        matches.append(
            MatchRecord(
                match_key=str(primary_identity),
                match_method=primary_method,
                discovery_match_method=disc_method,
                dashboard_match_method=dash_method,
                inventory=_redact(inv.raw),
                discovery=_redact(disc.raw) if disc is not None else None,
                dashboard=_redact(dash.raw) if dash is not None else None,
                field_comparison=comparison,
            )
        )

    for d_idx, d in enumerate(disc_recs):
        if ("discovery", d_idx) in matched_indices:
            continue
        explicit_policy = policy_exception(d)
        if empty_record_without_id(d):
            exceptions.append(
                explicit_policy
                or ExceptionRecord(
                    severity=SEVERITY_BLOCKING,
                    reason_code="parser_failure",
                    evidence={
                        "origin": "discovery",
                        "record": _redact(d.raw),
                        "error": "record has no deterministic identity",
                    },
                )
            )
            matched_indices.add(("discovery", d_idx))
            continue
        exceptions.append(
            explicit_policy
            or ExceptionRecord(
                severity=SEVERITY_BLOCKING,
                reason_code="extra_submission",
                evidence={
                    "origin": "discovery",
                    "record": _redact(d.raw),
                    "stable_id": record_stable_id(d),
                    "canonical_url": d.canonical_url,
                    "document_urls": d.document_urls,
                },
            )
        )
        matched_indices.add(("discovery", d_idx))

    for dash_idx, dsh in enumerate(dash_recs):
        if ("dashboard", dash_idx) in matched_indices:
            continue
        explicit_policy = policy_exception(dsh)
        if empty_record_without_id(dsh):
            exceptions.append(
                explicit_policy
                or ExceptionRecord(
                    severity=SEVERITY_BLOCKING,
                    reason_code="parser_failure",
                    evidence={
                        "origin": "dashboard",
                        "record": _redact(dsh.raw),
                        "error": "record has no deterministic identity",
                    },
                )
            )
            matched_indices.add(("dashboard", dash_idx))
            continue
        exceptions.append(
            explicit_policy
            or ExceptionRecord(
                severity=SEVERITY_BLOCKING,
                reason_code="extra_submission",
                evidence={
                    "origin": "dashboard",
                    "record": _redact(dsh.raw),
                    "stable_id": record_stable_id(dsh),
                    "canonical_url": dsh.canonical_url,
                    "document_urls": dsh.document_urls,
                },
            )
        )
        matched_indices.add(("dashboard", dash_idx))

    gates = compute_gates(inv_recs, disc_recs, dash_recs, matches, exceptions)

    matches.sort(key=lambda item: (item.match_key, item.match_method))
    exceptions.sort(
        key=lambda item: (
            item.severity,
            item.reason_code,
            json.dumps(item.evidence, sort_keys=True, ensure_ascii=False, default=str),
        )
    )
    return AuditResult(matches=matches, exceptions=exceptions, gates=gates)


def _is_renderable(rec: NormalizedRecord) -> Optional[bool]:
    value = rec.raw.get("renderable")
    return value if isinstance(value, bool) else None


def _renderability_validation_exception(
    rec: NormalizedRecord,
) -> Optional[ExceptionRecord]:
    if _is_renderable(rec) is not True:
        return None
    content_type_validated = rec.raw.get("content_type_validated") is True
    hash_validated = rec.raw.get("hash_validated") is True
    if content_type_validated and hash_validated:
        return None
    return ExceptionRecord(
        severity=SEVERITY_BLOCKING,
        reason_code="renderability_mismatch",
        evidence={
            "origin": rec.origin,
            "stable_id": record_stable_id(rec),
            "canonical_url": rec.canonical_url,
            "renderable": True,
            "content_type_validated": content_type_validated,
            "hash_validated": hash_validated,
            "error": "renderable document lacks successful type/hash validation",
        },
    )


def compute_gates(
    inv_recs: list[NormalizedRecord],
    disc_recs: list[NormalizedRecord],
    dash_recs: list[NormalizedRecord],
    matches: list[MatchRecord],
    exceptions: list[ExceptionRecord],
) -> dict[str, Any]:
    open_in_scope_inventory = sum(1 for rec in inv_recs if is_open_in_scope(rec))
    missing_open = sum(1 for e in exceptions if e.reason_code == "missing_open")
    traced_candidates = sum(
        int(
            match.discovery is not None
            and match.discovery.get("reason_code") not in EXPLICIT_DISPOSITION_CODES
        )
        + int(
            match.dashboard is not None
            and match.dashboard.get("reason_code") not in EXPLICIT_DISPOSITION_CODES
        )
        for match in matches
    )
    excluded_candidates = sum(
        1
        for rec in disc_recs + dash_recs
        if rec.reason_code in EXPLICIT_DISPOSITION_CODES
    )
    candidate_denominator = len(disc_recs) + len(dash_recs) - excluded_candidates
    accounts = {
        "inventory_total": len(inv_recs),
        "inventory_open_in_scope_total": open_in_scope_inventory,
        "inventory_accounted": open_in_scope_inventory - missing_open,
        "inventory_accounted_numerator": open_in_scope_inventory - missing_open,
        "inventory_accounted_denominator": open_in_scope_inventory,
        "candidates_total": candidate_denominator,
        "candidates_traced": traced_candidates,
        "candidates_traced_numerator": traced_candidates,
        "candidates_traced_denominator": candidate_denominator,
        "missing_open": missing_open,
        "extra_submission": sum(1 for e in exceptions if e.reason_code == "extra_submission"),
        "duplicate_identity": sum(1 for e in exceptions if e.reason_code == "duplicate_identity"),
        "identity_mismatch": sum(1 for e in exceptions if e.reason_code == "identity_mismatch"),
        "authoritative_status_mismatch": sum(1 for e in exceptions if e.reason_code == "authoritative_status_mismatch"),
        "authoritative_deadline_mismatch": sum(1 for e in exceptions if e.reason_code == "authoritative_deadline_mismatch"),
        "renderability_mismatch": sum(1 for e in exceptions if e.reason_code == "renderability_mismatch"),
        "parser_failure": sum(1 for e in exceptions if e.reason_code == "parser_failure"),
    }
    return {
        "inventory_accounting_pct": _pct(
            accounts["inventory_accounted_numerator"],
            accounts["inventory_accounted_denominator"],
            total=accounts["inventory_open_in_scope_total"],
        ),
        "candidate_traceability_pct": _pct(
            accounts["candidates_traced_numerator"],
            accounts["candidates_traced_denominator"],
            total=accounts["candidates_total"],
        ),
        "counts": accounts,
    }


def _pct(num: int, den: int, *, total: int) -> float:
    if den == 0:
        # When there is genuinely nothing to do (no records at all), report a
        # healthy 100%. Otherwise an empty/failed run (records exist but none
        # were accounted or traced) is degraded and must report 0%, not 100%.
        return 100.0 if total == 0 else 0.0
    return round((num / den) * 100.0, 2)


def render_markdown(result: AuditResult) -> str:
    lines: list[str] = []
    lines.append("# Source Fidelity Report")
    lines.append("")
    gates = result.gates
    counts = gates["counts"]
    lines.append("## Quantitative Gates")
    lines.append("")
    lines.append(f"- Inventory accounting: {gates['inventory_accounting_pct']}% "
                 f"({counts['inventory_accounted_numerator']}/{counts['inventory_accounted_denominator']})")
    lines.append(f"- Candidate traceability: {gates['candidate_traceability_pct']}% "
                 f"({counts['candidates_traced_numerator']}/{counts['candidates_traced_denominator']})")
    lines.append("")
    lines.append("### Blocking exception counts")
    for code in sorted(BLOCKING_REASON_CODES):
        lines.append(f"- {code}: {counts.get(code, 0)}")
    lines.append("")
    lines.append(f"Total blocking exceptions: {len(result.blocking_exceptions())}")
    lines.append("")
    lines.append("## Matches")
    lines.append("")
    if not result.matches:
        lines.append("_No matches._")
    for m in sorted(result.matches, key=lambda x: x.match_key):
        lines.append(
            f"- key={_redact_value(m.match_key)} method={m.match_method}"
        )
        comp = m.field_comparison
        for field_name in ("status", "deadline", "renderable"):
            fc = comp.get(field_name)
            if fc:
                lines.append(
                    f"  - {field_name}: inv={fc['inventory']} "
                    f"discovery={fc['discovery']} dashboard={fc['dashboard']} "
                    f"match={fc['match']}"
                )
        for suggestion in comp.get("title_suggestions", []):
            lines.append(f"  - suggestion: {suggestion}")
    lines.append("")
    lines.append("## Exceptions")
    lines.append("")
    if not result.exceptions:
        lines.append("_No exceptions._")
    for e in sorted(result.exceptions, key=lambda x: (x.severity, x.reason_code)):
        lines.append(f"- [{e.severity}] {e.reason_code}")
        for k, v in sorted(_redact_value(e.evidence).items()):
            lines.append(f"  - {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def render_summary(result: AuditResult) -> dict[str, Any]:
    counts = result.gates["counts"]
    blocking = result.blocking_exceptions()
    return {
        "inventory_accounting_pct": result.gates["inventory_accounting_pct"],
        "inventory_accounted_numerator": counts["inventory_accounted_numerator"],
        "inventory_accounted_denominator": counts["inventory_accounted_denominator"],
        "inventory_open_in_scope_total": counts["inventory_open_in_scope_total"],
        "candidate_traceability_pct": result.gates["candidate_traceability_pct"],
        "candidates_traced_numerator": counts["candidates_traced_numerator"],
        "candidates_traced_denominator": counts["candidates_traced_denominator"],
        "blocking_reason_counts": {
            code: counts.get(code, 0) for code in sorted(BLOCKING_REASON_CODES)
        },
        "non_blocking_exception_count": len(result.non_blocking_exceptions()),
        "total_blocking_exceptions": len(blocking),
        "pass": len(blocking) == 0,
    }
