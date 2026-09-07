"""Regression tests for source-reliability review fixes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import build_source_matrix as builder
from discover_all_candidates import normalize_stats


def test_normalize_stats_includes_processing_and_submittable_caps():
    stats = {"processing_cap_reached": 1}
    assert normalize_stats(stats)["cap_reached"] is True
    stats = {"submittable_cap_reached": 1}
    assert normalize_stats(stats)["cap_reached"] is True
    stats = {"candidate_cap_reached": 0, "pdf_download_cap_reached": 0,
             "search_result_cap_reached": 0, "detail_cap_reached": 0,
             "processing_cap_reached": 0, "submittable_cap_reached": 0}
    assert normalize_stats(stats)["cap_reached"] is False


def test_registry_has_schedule_owner_filter_and_limits():
    registry = builder.load_registry()
    for entry in registry["sources"]:
        assert entry["schedule_owner"], entry["source_key"]
        assert entry["interval_minutes"] == 60, entry["source_key"]
        assert entry["filter_policy"] in {"default", "include_tdr", "no_prefilter"}
        assert entry["detail_limit"] > 0
        assert entry["page_limit"] > 0
        assert entry["attachment_limit"] > 0
    # Structured routes per Plan 05
    by_key = {s["source_key"]: s for s in registry["sources"]}
    assert by_key["tnc"]["submission_contract"] == "opportunity"
    assert by_key["funbio"]["submission_contract"] == "opportunity"
    assert by_key["tnc"]["rollout_mode"] == "audit"
    assert by_key["funbio"]["rollout_mode"] == "audit"


def test_registry_rejects_bad_schedule_owner():
    registry = builder.load_registry()
    registry["sources"][0]["schedule_owner"] = "wrong.yml"
    try:
        builder.validate_registry(registry)
    except SystemExit:
        return
    raise AssertionError("expected SystemExit for bad schedule_owner")


def test_submission_contract_opportunity_rejects_candidate_fallback():
    from discover_all_candidates import main

    discoverer = MagicMock()
    # Has only candidate path, no structured path
    discoverer.__dict__["discover_candidates"] = MagicMock(return_value=({"candidates": 1}, []))
    if "discover_opportunities" in discoverer.__dict__:
        del discoverer.__dict__["discover_opportunities"]

    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": "bndes",
        "SUBMISSION_CONTRACT": "opportunity",
        "DISCOVERY_AUDIT_ONLY": "false",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
    }
    with patch.dict(os.environ, env, clear=True), \
        patch("discover_all_candidates.load_discoverer", return_value=discoverer), \
        patch("discover_all_candidates.discover_source", return_value=({"candidates": 1}, [])):
        # Should fail (no silent fallback) rather than succeed via candidate
        assert main() == 1


def test_multi_source_ingest_is_rejected():
    from discover_all_candidates import main

    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": "bndes,brde",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
    }
    with patch.dict(os.environ, env, clear=True), \
        patch("discover_all_candidates.discover_source", return_value=({"candidates": 0}, [])), \
        patch("discover_all_candidates.load_discoverer", return_value=MagicMock()):
        # Recovery must use independently fenced single-source jobs too.
        assert main() == 2
