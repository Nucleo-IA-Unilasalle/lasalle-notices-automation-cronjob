"""Build the strict single-source execution matrix for a discovery group.

The registry (``config/source_schedule.json``) is the only place source
execution configuration lives. This builder validates it fail-closed and
emits the GitHub Actions matrix for one group. Paused entries remain visible
in the registry but are omitted from the executable matrix; audit entries are
emitted and the workflow runs them without ingestion (``DISCOVERY_AUDIT_ONLY``).

Exit codes:
  0 - matrix emitted
  1 - registry invalid (unknown/duplicate keys, invalid groups, bad modes,
      modules that do not match the orchestrator registry, or a group that is
      not exactly 7/7/8 non-PNCP entries)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "source_schedule.json"

NON_PNCP_GROUP_SIZES = {"a": 7, "b": 7, "c": 8}
VALID_ROLLOUT_MODES = {"audit", "ingest", "paused"}
VALID_SUBMISSION_CONTRACTS = {"candidate", "opportunity"}
VALID_GROUPS = {"a", "b", "c", "pncp"}
VALID_FILTER_POLICIES = {"default", "include_tdr", "no_prefilter"}

# Mirrors scripts/discover_all_candidates.py SOURCE_MODULES; kept as a literal
# list of module stems so validation never imports heavy source dependencies.
ORCHESTRATOR_MODULES = {
    "bndes": "discover_bndes_candidates",
    "brde": "discover_brde_candidates",
    "fapergs": "discover_fapergs_candidates",
    "fbds": "discover_fbds_opportunities",
    "finep": "discover_finep_opportunities",
    "dopa": "discover_dopa_opportunities",
    "canoas": "discover_canoas_opportunities",
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
    "ibama": "discover_ibama_candidates",
}


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        registry = json.load(handle)
    if not isinstance(registry, dict) or not isinstance(registry.get("sources"), list):
        raise ValueError("registry must be an object with a 'sources' list")
    return registry


def validate_registry(registry: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[str] = []
    sources = registry["sources"]
    seen: set[str] = set()
    per_group: dict[str, int] = {"a": 0, "b": 0, "c": 0}

    defaults = registry.get("defaults", {})
    for key in ("interval_minutes", "run_timeout_minutes", "application_budget_seconds", "pdf_limit"):
        if not isinstance(defaults.get(key), int) or defaults[key] <= 0:
            _fail(errors, f"defaults.{key} must be a positive integer")

    groups = registry.get("groups", {})
    for group_id in ("a", "b", "c"):
        entry = groups.get(group_id)
        if not isinstance(entry, dict):
            _fail(errors, f"missing group '{group_id}'")
            continue
        primary = entry.get("primary_cron")
        if not isinstance(primary, str) or not primary.endswith("* * * *"):
            _fail(errors, f"group {group_id} primary_cron must be an hourly cron")

    for entry in sources:
        if not isinstance(entry, dict):
            _fail(errors, "source entry must be an object")
            continue
        key = entry.get("source_key")
        if not isinstance(key, str) or not key:
            _fail(errors, f"source entry missing source_key: {entry!r}")
            continue
        if key in seen:
            _fail(errors, f"duplicate source key: {key}")
            continue
        seen.add(key)

        module = entry.get("module")
        expected_module = ORCHESTRATOR_MODULES.get(key, "discover_pncp_candidates" if key == "pncp" else None)
        if expected_module is None:
            _fail(errors, f"unknown source key not present in the orchestrator registry or A manifest: {key}")
            continue
        if module != expected_module:
            _fail(errors, f"module mismatch for {key}: registry={module!r} orchestrator={expected_module!r}")

        if entry.get("submission_contract") not in VALID_SUBMISSION_CONTRACTS:
            _fail(errors, f"invalid submission_contract for {key}: {entry.get('submission_contract')!r}")
        if entry.get("rollout_mode") not in VALID_ROLLOUT_MODES:
            _fail(errors, f"invalid rollout_mode for {key}: {entry.get('rollout_mode')!r}")
        group = entry.get("group")
        if group not in VALID_GROUPS:
            _fail(errors, f"invalid group for {key}: {group!r}")
            continue
        if not isinstance(entry.get("browser_required"), bool):
            _fail(errors, f"browser_required must be boolean for {key}")

        # Plan 01 registry contract: execution ownership + bounded limits.
        expected_owner = f"pipeline-discovery-group-{group}.yml" if group in ("a", "b", "c") else "pipeline-pncp-discovery.yml" if group == "pncp" else None
        if expected_owner is not None and entry.get("schedule_owner") != expected_owner:
            _fail(errors, f"schedule_owner for {key} must be {expected_owner!r}, got {entry.get('schedule_owner')!r}")
        if entry.get("filter_policy") not in VALID_FILTER_POLICIES:
            _fail(errors, f"invalid filter_policy for {key}: {entry.get('filter_policy')!r}")
        for limit_key in ("detail_limit", "page_limit", "attachment_limit"):
            limit_value = entry.get(limit_key)
            if not isinstance(limit_value, int) or limit_value <= 0:
                _fail(errors, f"{limit_key} for {key} must be a positive integer")

        interval = entry.get("interval_minutes", defaults.get("interval_minutes"))
        if interval != 60:
            _fail(errors, f"interval_minutes for {key} must be 60 initially, got {interval!r}")

        if group in per_group and key != "pncp":
            per_group[group] += 1

    missing = set(ORCHESTRATOR_MODULES) - seen
    if missing:
        _fail(errors, f"missing source keys from the registry: {sorted(missing)}")
    if "pncp" not in seen:
        _fail(errors, "missing dedicated pncp entry")
    for group_id, expected in NON_PNCP_GROUP_SIZES.items():
        if per_group[group_id] != expected:
            _fail(errors, f"group {group_id} must contain exactly {expected} non-PNCP entries, got {per_group[group_id]}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    return sources


def build_matrix(registry: dict[str, Any], group: str) -> dict[str, Any]:
    """Return the executable matrix for one group plus a paused-by-mode report."""
    defaults = registry["defaults"]
    includes: list[dict[str, Any]] = []
    paused: list[str] = []
    for entry in validate_registry(registry):
        if entry["group"] != group or entry["source_key"] == "pncp":
            continue
        if entry["rollout_mode"] == "paused":
            paused.append(entry["source_key"])
            continue
        includes.append(
            {
                "source": entry["source_key"],
                "module": entry["module"],
                "browser_required": entry["browser_required"],
                "rollout_mode": entry["rollout_mode"],
                "submission_contract": entry["submission_contract"],
                "schedule_owner": entry.get("schedule_owner"),
                "filter_policy": entry.get("filter_policy", "default"),
                "detail_limit": entry.get("detail_limit"),
                "page_limit": entry.get("page_limit"),
                "attachment_limit": entry.get("attachment_limit"),
                "run_timeout_minutes": defaults["run_timeout_minutes"],
                "application_budget_seconds": defaults["application_budget_seconds"],
                "pdf_limit": defaults["pdf_limit"],
            }
        )
    if not includes:
        print(f"error: group {group} has no executable entries", file=sys.stderr)
        raise SystemExit(1)
    return {"group": group, "includes": includes, "paused": paused}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", required=True, choices=("a", "b", "c"))
    parser.add_argument("--format", choices=("json", "github"), default="json")
    args = parser.parse_args()

    matrix = build_matrix(load_registry(), args.group)
    if args.format == "github":
        # Compact single-line JSON for a GitHub Actions `fromJSON(...)` output.
        print(json.dumps(matrix["includes"], separators=(",", ":")))
    else:
        print(json.dumps(matrix, indent=2))
    if matrix["paused"]:
        print(f"paused entries visible in registry but omitted from execution: {','.join(matrix['paused'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
