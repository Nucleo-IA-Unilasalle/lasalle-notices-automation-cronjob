"""Unified discovery orchestrator for non-PNCP cronjob sources (Phase 5).

Reads a ``SOURCES`` env var (e.g. ``SOURCES=bndes,brde,fapergs,funbio,
iis_rio,sema_rs,tnc,wwf``) and runs the per-source discoverer for each
listed source, then funnels the candidates through the shared
``pipeline_core.process_candidate`` / ``pipeline_core.submit_candidates``
flow. The per-run cap (``SCRAPE_MAX_PDFS_PER_RUN``) is shared across
sources so the run cannot exceed the Actions budget.

Per plan §5 the PNCP discoverer is intentionally NOT folded into this
orchestrator in the first cut; PNCP keeps its own
``pipeline-pncp-discovery.yml`` workflow because its source-specific
guardrails (``PNCP_MIN_NOTICE_YEAR``, ``PNCP_MAX_CANDIDATES_PER_RUN``,
modality filtering, document-type priorities, the
``/atualizacao`` checkpoint) are not directly applicable to other
sources. Folding PNCP in is a follow-up PR after this lands.

Per plan §9 the orchestrator carries a generic ``MIN_NOTICE_YEAR``
env var (default 2026) instead of borrowing the ``PNCP_MIN_NOTICE_YEAR``
name. The orchestrator passes ``min_year`` only to discoverers whose
``discover_candidates`` signature accepts it; Playwright sources
(``fao``, ``fundacao_grupo_boticario``, ``kfw``, ``msgov``) do not
take that argument and run with their own internal filtering.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

import pipeline_core
from scraper_filters import FilterPolicy, VALID_FILTER_POLICIES


SOURCE_MODULES: dict[str, str] = {
    "bndes": "discover_bndes_candidates",
    "brde": "discover_brde_candidates",
    "fapergs": "discover_fapergs_candidates",
    "fbds": "discover_fbds_opportunities",
    "finep": "discover_finep_opportunities",
    "funbio": "discover_funbio_candidates",
    "govbr_mma": "discover_govbr_mma_candidates",
    "govbr_mma_public_calls": "discover_govbr_mma_public_calls_candidates",
    "govbr_mma_fnma": "discover_govbr_mma_fnma_candidates",
    "iis_rio": "discover_iis_rio_candidates",
    "sema_rs": "discover_sema_rs_candidates",
    "tnc": "discover_tnc_candidates",
    "unep": "discover_unep_candidates",
    "worldbank": "discover_worldbank_candidates",
    "wwf": "discover_wwf_candidates",
    "fao": "discover_fao_candidates",
    "fundacao_grupo_boticario": "discover_fundacao_grupo_boticario_candidates",
    "kfw": "discover_kfw_candidates",
    "msgov": "discover_msgov_candidates",
}


DEFAULT_MIN_NOTICE_YEAR = 2026
DEFAULT_FILTER_POLICY: FilterPolicy = "default"


class UnknownSourceError(ValueError):
    """Raised when a source name is not registered in ``SOURCE_MODULES``."""


def parse_sources(sources_env: str | None) -> list[str]:
    """Parse the ``SOURCES`` env var into a deduplicated, ordered list.

    Tolerates whitespace around entries and ignores empty entries. An
    empty / missing input returns an empty list. Order is preserved so
    per-source output is deterministic across runs.
    """
    if not sources_env:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for entry in sources_env.split(","):
        name = entry.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def load_discoverer(source: str) -> Any:
    """Dynamically import the ``discover_<source>_candidates`` module."""
    module_name = SOURCE_MODULES.get(source)
    if module_name is None:
        raise UnknownSourceError(f"Unknown source: {source!r}")
    return importlib.import_module(module_name)


def discover_source(
    discoverer: Any,
    *,
    filter_policy: FilterPolicy,
    min_year: int,
    seen_pdfs: set[str] | None = None,
    seen_ids: set[str] | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Call ``discoverer.discover_candidates`` with the params it accepts.

    BS4 discoverers accept ``filter_policy`` and ``min_year`` as
    keyword-only arguments; Playwright discoverers (``fao``,
    ``fundacao_grupo_boticario``, ``kfw``, ``msgov``) accept neither
    and run with their own internal filtering. We inspect the signature
    rather than forcing a uniform contract on the per-source modules.

    ``seen_pdfs`` / ``seen_ids`` are threaded through to discoverers that
    accept them (the two MMA feeds), giving stable cross-feed dedup so the
    same PDF URL / opportunity identity is not double-submitted in one run.
    """
    signature = inspect.signature(discoverer.discover_candidates)
    kwargs: dict[str, Any] = {}
    if "filter_policy" in signature.parameters:
        kwargs["filter_policy"] = filter_policy
    if "min_year" in signature.parameters:
        kwargs["min_year"] = min_year
    if "seen_pdfs" in signature.parameters and seen_pdfs is not None:
        kwargs["seen_pdfs"] = seen_pdfs
    if "seen_ids" in signature.parameters and seen_ids is not None:
        kwargs["seen_ids"] = seen_ids
    return discoverer.discover_candidates(**kwargs)


def discover_source_opportunities(
    discoverer: Any,
    *,
    min_year: int,
) -> tuple[dict[str, int], list[dict[str, Any]]] | None:
    """Use the structured opportunity contract when a source exposes it."""
    # Read the concrete module namespace so MagicMock-based legacy tests (and
    # dynamic objects in operators' tooling) are not mistaken for structured
    # sources merely because ``getattr`` fabricates a callable attribute.
    discover = getattr(discoverer, "__dict__", {}).get("discover_opportunities")
    if not callable(discover):
        return None
    signature = inspect.signature(discover)
    kwargs: dict[str, Any] = {}
    if "min_year" in signature.parameters:
        kwargs["min_year"] = min_year
    result = discover(**kwargs)
    # PNCP also returns its checkpoint timestamp. The all-sources runner only
    # needs the shared stats and opportunity payloads.
    if isinstance(result, tuple) and len(result) == 3:
        stats, opportunities, _checkpoint = result
        return stats, opportunities
    return result


def process_source_candidates(
    candidates: list[dict[str, Any]],
    *,
    extractor: Any,
    stats: dict[str, int],
) -> list[dict[str, Any]]:
    """Download + OCR each candidate, respecting the shared cap.

    The ``stats`` dict is shared across sources so the per-run
    ``SCRAPE_MAX_PDFS_PER_RUN`` cap is enforced once for the whole
    orchestrator run. Each successful download increments the counter
    via ``pipeline_core.record_pdf_download``; the next iteration
    short-circuits via ``pipeline_core.pdf_download_limit_reached``.
    """
    processed: list[dict[str, Any]] = []
    max_pdf_bytes = pipeline_core.SCRAPE_MAX_PDF_BYTES

    for candidate in candidates:
        if pipeline_core.pdf_download_limit_reached(stats):
            stats["pdf_download_cap_reached"] = 1
            print(
                f"Stopping after PDF download cap "
                f"{pipeline_core.SCRAPE_MAX_PDFS_PER_RUN}",
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

    return processed


def write_opportunity_audit(
    source: str,
    stats: dict[str, int],
    opportunities: list[dict[str, Any]],
) -> None:
    """Write Plan-01-compatible inventory/discovery artifacts when configured."""
    root_value = os.environ.get("DISCOVERY_AUDIT_DIR")
    if not root_value:
        return
    target = Path(root_value) / source
    target.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "source_key": item.get("source_key"),
            "source_record_id": item.get("source_record_id"),
            "canonical_url": item.get("canonical_url"),
            "title": item.get("title"),
            "status": item.get("authoritative_status"),
            "published_at": item.get("source_published_at"),
            "deadline": item.get("application_deadline"),
            "document_urls": [
                document.get("url")
                for document in item.get("documents", [])
                if document.get("url")
            ],
            "document_hashes": [
                document.get("content_hash")
                for document in item.get("documents", [])
                if document.get("content_hash")
            ],
        }
        for item in opportunities
    ]
    stable_json = lambda value: json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=True, default=str
    ) + "\n"
    (target / "source_inventory.json").write_text(
        stable_json(records), encoding="utf-8"
    )
    (target / "discovery.json").write_text(
        stable_json(records), encoding="utf-8"
    )
    (target / "opportunities.json").write_text(
        stable_json(opportunities), encoding="utf-8"
    )
    (target / "stats.json").write_text(stable_json(stats), encoding="utf-8")


def write_candidate_audit(
    source: str,
    stats: dict[str, int],
    candidates: list[dict[str, Any]],
) -> None:
    """Write no-submit audit artifacts for PDF-backed discoverers."""
    root_value = os.environ.get("DISCOVERY_AUDIT_DIR")
    if not root_value:
        return
    target = Path(root_value) / source
    target.mkdir(parents=True, exist_ok=True)
    records = []
    for candidate in candidates:
        metadata = candidate.get("metadata") or {}
        url = candidate.get("url")
        records.append(
            {
                "source_key": metadata.get("source_key")
                or metadata.get("source")
                or source,
                "source_record_id": metadata.get("source_record_id")
                or metadata.get("external_id")
                or url,
                "canonical_url": metadata.get("detail_url")
                or metadata.get("canonical_url")
                or url,
                "title": metadata.get("title") or candidate.get("title"),
                "status": metadata.get("status")
                or metadata.get("authoritative_status"),
                "published_at": metadata.get("published_at"),
                "deadline": metadata.get("application_deadline")
                or metadata.get("deadline"),
                "document_urls": [url] if url else [],
                "document_hashes": [],
            }
        )
    stable_json = lambda value: json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=True, default=str
    ) + "\n"
    (target / "source_inventory.json").write_text(
        stable_json(records), encoding="utf-8"
    )
    (target / "discovery.json").write_text(
        stable_json(records), encoding="utf-8"
    )
    (target / "candidates.json").write_text(
        stable_json(candidates), encoding="utf-8"
    )
    (target / "stats.json").write_text(stable_json(stats), encoding="utf-8")


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_min_year() -> int:
    raw = os.environ.get("MIN_NOTICE_YEAR", str(DEFAULT_MIN_NOTICE_YEAR))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"MIN_NOTICE_YEAR must be an integer; got {raw!r}",
        ) from exc


def _resolve_filter_policy() -> FilterPolicy:
    policy = os.environ.get("FILTER_POLICY", DEFAULT_FILTER_POLICY)
    if policy not in VALID_FILTER_POLICIES:
        raise ValueError(
            f"FILTER_POLICY must be one of {sorted(VALID_FILTER_POLICIES)}; "
            f"got {policy!r}",
        )
    return policy  # type: ignore[return-value]


def main() -> int:
    audit_only = _env_flag("DISCOVERY_AUDIT_ONLY")
    if not audit_only and not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not audit_only and not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2
    if audit_only and not os.environ.get("DISCOVERY_AUDIT_DIR"):
        print(
            "error: DISCOVERY_AUDIT_DIR is required in audit-only mode",
            file=sys.stderr,
        )
        return 2

    sources = parse_sources(os.environ.get("SOURCES"))
    if not sources:
        print(
            "error: SOURCES is required (e.g. SOURCES=bndes,brde,wwf)",
            file=sys.stderr,
        )
        return 2

    unknown = [s for s in sources if s not in SOURCE_MODULES]
    if unknown:
        print(
            f"error: unknown source(s): {','.join(unknown)}. "
            f"Valid: {','.join(sorted(SOURCE_MODULES))}",
            file=sys.stderr,
        )
        return 2

    try:
        min_year = _resolve_min_year()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        filter_policy = _resolve_filter_policy()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"discover_all_candidates: sources={sources} "
        f"min_year={min_year} filter_policy={filter_policy} "
        f"pdf_cap={pipeline_core.SCRAPE_MAX_PDFS_PER_RUN} "
        f"audit_only={audit_only}",
    )

    extractor = None
    if not audit_only:
        _, extractor = pipeline_core.make_default_ocr_extractor()
    opportunity_sources = set(
        parse_sources(os.environ.get("OPPORTUNITY_SOURCES"))
    )

    # Shared across feeds so a PDF that appears in more than one MMA source is
    # not double-submitted within a single run.
    shared_seen_pdfs: set[str] = set()
    shared_seen_ids: set[str] = set()

    shared_stats: dict[str, int] = {}
    per_source_stats: dict[str, dict[str, int]] = {}
    per_source_processed: dict[str, int] = {}
    per_source_submitted: dict[str, int] = {}
    exit_code = 0

    for source in sources:
        if pipeline_core.pdf_download_limit_reached(shared_stats):
            print(
                f"Stopping before source {source}: shared PDF cap "
                f"{pipeline_core.SCRAPE_MAX_PDFS_PER_RUN} already reached",
                file=sys.stderr,
            )
            break

        try:
            discoverer = load_discoverer(source)
        except UnknownSourceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        except ImportError as exc:
            print(
                f"error: failed to import discoverer for source {source!r}: {exc}",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        try:
            opportunity_result = (
                discover_source_opportunities(discoverer, min_year=min_year)
                if audit_only or source in opportunity_sources
                else None
            )
            if opportunity_result is None:
                source_stats, candidates = discover_source(
                    discoverer,
                    filter_policy=filter_policy,
                    min_year=min_year,
                    seen_pdfs=shared_seen_pdfs,
                    seen_ids=shared_seen_ids,
                )
                opportunities: list[dict[str, Any]] | None = None
            else:
                source_stats, opportunities = opportunity_result
                candidates = []
        except Exception as exc:
            print(
                f"error: discovery failed for source {source!r}: {exc}",
                file=sys.stderr,
            )
            per_source_stats[source] = {"errors": 1}
            exit_code = 1
            continue

        per_source_stats[source] = source_stats
        if opportunities is not None:
            write_opportunity_audit(source, source_stats, opportunities)
        elif audit_only:
            write_candidate_audit(source, source_stats, candidates)
        print(
            f"{source}: discovered "
            f"{len(opportunities) if opportunities is not None else len(candidates)} "
            f"{'opportunities' if opportunities is not None else 'candidates'} "
            f"(stats={source_stats})",
        )

        if (
            source_stats.get("section_parse_failed", 0)
            or source_stats.get("inventory_parse_failed", 0)
            or source_stats.get("ambiguous_document_conflicts", 0)
        ):
            print(
                f"error: discovery reported source/parser/identity failures "
                f"for {source!r}",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        if audit_only:
            per_source_processed[source] = 0
            per_source_submitted[source] = 0
            continue

        if opportunities is not None:
            processed_opportunities = [
                pipeline_core.process_opportunity(
                    opportunity,
                    extractor=extractor,
                    stats=shared_stats,
                )
                for opportunity in opportunities
            ]
            per_source_processed[source] = len(processed_opportunities)
            try:
                submit_result = pipeline_core.submit_opportunities(
                    processed_opportunities
                )
            except Exception as exc:
                print(
                    f"error: opportunity submission failed for {source!r}: {exc}",
                    file=sys.stderr,
                )
                exit_code = 1
                continue
            per_source_submitted[source] = submit_result.get("submitted", 0)
            print(f"{source}: opportunity submission: {submit_result}")
            if opportunities and submit_result.get("submitted", 0) == 0:
                exit_code = 1
            continue

        if not candidates:
            continue

        processed = process_source_candidates(
            candidates,
            extractor=extractor,
            stats=shared_stats,
        )
        per_source_processed[source] = sum(
            1 for r in processed if r.get("worker_result")
        )

        ocr_successes = per_source_processed[source]
        if candidates and ocr_successes == 0:
            print(
                f"error: all {source} candidates failed download/OCR; "
                "nothing will be submitted for this source",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        try:
            submit_result = pipeline_core.submit_candidates(
                processed, source=source,
            )
        except Exception as exc:
            print(
                f"error: submission failed for source {source!r}: {exc}",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        per_source_submitted[source] = submit_result.get("submitted", 0)
        print(f"{source}: render submission: {submit_result}")

        if candidates and submit_result.get("submitted", 0) == 0:
            print(
                f"error: discovered {source} candidates produced no "
                "Render submissions",
                file=sys.stderr,
            )
            exit_code = 1

    print(f"shared_stats={shared_stats}")
    print(f"per_source_stats={per_source_stats}")
    print(f"per_source_processed={per_source_processed}")
    print(f"per_source_submitted={per_source_submitted}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
