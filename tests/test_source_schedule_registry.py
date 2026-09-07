"""Registry coverage tests for config/source_schedule.json (Plan 01).

Validates the declarative execution registry against the orchestrator's
SOURCE_MODULES, the group topology (7/7/8), and the group workflow crons.
The builder must fail closed on unknown/duplicate keys and invalid modes.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys

import pytest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import build_source_matrix as builder  # noqa: E402


def _registry() -> dict:
    return builder.load_registry()


def test_registry_covers_exactly_the_23_operational_keys() -> None:
    from discover_all_candidates import SOURCE_MODULES

    sources = {s["source_key"] for s in _registry()["sources"]}
    assert sources == set(SOURCE_MODULES) | {"pncp"}
    assert len(sources) == 23


def test_groups_hold_7_7_8_non_pncp_entries_with_single_ownership() -> None:
    sources = _registry()["sources"]
    per_group: dict[str, int] = {"a": 0, "b": 0, "c": 0}
    owners: dict[str, str] = {}
    for entry in sources:
        key = entry["source_key"]
        if key == "pncp":
            assert entry["group"] == "pncp"
            continue
        assert entry["group"] in per_group, key
        assert key not in owners, f"{key} has more than one owner: {owners.get(key)}, {entry['group']}"
        owners[key] = entry["group"]
        per_group[entry["group"]] += 1
    assert per_group == {"a": 7, "b": 7, "c": 8}


def test_every_registry_module_matches_the_orchestrator() -> None:
    from discover_all_candidates import SOURCE_MODULES

    for entry in _registry()["sources"]:
        assert entry["module"] == SOURCE_MODULES.get(entry["source_key"], "discover_pncp_candidates"), entry


def test_group_workflow_crons_match_registry_primary_crons() -> None:
    registry = _registry()
    for group_id in ("a", "b", "c"):
        path = PROJECT_ROOT / ".github" / "workflows" / f"pipeline-discovery-group-{group_id}.yml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        trigger = document.get("on", document.get(True, {}))
        assert trigger["schedule"] == [{"cron": registry["groups"][group_id]["primary_cron"]}], path.name


def test_group_crons_are_distinct_and_off_peak() -> None:
    crons = [_registry()["groups"][g]["primary_cron"].split()[0] for g in ("a", "b", "c")]
    assert len(set(crons)) == 3
    pncp = [s for s in _registry()["sources"] if s["source_key"] == "pncp"]
    assert pncp[0]["group"] == "pncp"


def test_builder_matrices_cover_all_executable_entries_and_omit_paused() -> None:
    registry = _registry()
    executable: set[str] = set()
    for group_id in ("a", "b", "c"):
        matrix = builder.build_matrix(registry, group_id)
        keys = [entry["source"] for entry in matrix["includes"]]
        assert len(keys) == len(set(keys))
        executable |= set(keys)
        for entry in matrix["includes"]:
            assert entry["rollout_mode"] in {"ingest", "audit"}
            if entry["rollout_mode"] == "audit":
                # audit entries execute; the reusable workflow enforces no-ingestion
                assert entry["source"] in {s["source_key"] for s in registry["sources"]}
    expected = {
        s["source_key"] for s in registry["sources"]
        if s["source_key"] != "pncp" and s["rollout_mode"] != "paused"
    }
    assert executable == expected
    paused = {s["source_key"] for s in registry["sources"] if s["rollout_mode"] == "paused"}
    assert paused == {"canoas", "dopa", "fbds", "finep", "ibama"}


def test_builder_fails_closed_on_duplicate_key(tmp_path) -> None:
    registry = _registry()
    registry["sources"].append(dict(registry["sources"][0]))
    with pytest.raises(SystemExit):
        builder.build_matrix(registry, "a")


def test_builder_fails_closed_on_unknown_key() -> None:
    registry = _registry()
    registry["sources"][0]["source_key"] = "not_a_real_source"
    with pytest.raises(SystemExit):
        builder.build_matrix(registry, "a")


def test_builder_fails_closed_on_invalid_rollout_mode() -> None:
    registry = _registry()
    registry["sources"][0]["rollout_mode"] = "silent_ingest"
    with pytest.raises(SystemExit):
        builder.build_matrix(registry, "a")


def test_builder_cli_emits_github_format(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_source_matrix.py"), "--group", "a", "--format", "github"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    includes = json.loads(result.stdout.strip())
    assert {e["source"] for e in includes} == {"bndes", "brde", "fao", "fapergs", "govbr_mma_fnma", "iis_rio"}
    assert {e["rollout_mode"] for e in includes} == {"ingest", "audit"}
