"""Offline checks for the staging snapshot validator (no network, no registry writes)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import validate_staging_snapshot as validator


PLACEHOLDER = {
    "source_key": "bndes",
    "observed_at": "TODO",
    "registry_ref": "TODO: config/source_schedule.json commit",
    "pin_ref": "TODO: config/source_catalog_contract.json exported_at",
    "runs": [],
    "audits": [{"result": "TODO", "report_path": ""}],
    "notes": "TODO",
}


def _write_snapshot(tmp_path: Path, snapshot: dict, checklist: str = "# Checklist\n\n- [ ] TODO\n") -> Path:
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (folder / "checklist.md").write_text(checklist, encoding="utf-8")
    return folder


def test_placeholder_snapshot_is_structurally_valid_with_outstanding(tmp_path):
    snapshot = copy.deepcopy(PLACEHOLDER)
    snapshot["observed_at"] = "2026-09-06T00:00:00+00:00"
    folder = _write_snapshot(tmp_path, snapshot)
    code, outstanding = validator.validate_snapshot_dir(folder)
    assert code == 0
    assert outstanding


def test_missing_snapshot_file_fails(tmp_path):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "checklist.md").write_text("# Checklist\n", encoding="utf-8")
    code, errors = validator.validate_snapshot_dir(folder)
    assert code == 1
    assert any("snapshot.json" in error for error in errors)


def test_unknown_source_key_rejected(tmp_path):
    snapshot = copy.deepcopy(PLACEHOLDER)
    snapshot.update(source_key="ghost_source", observed_at="2026-09-06T00:00:00+00:00")
    folder = _write_snapshot(tmp_path, snapshot)
    code, errors = validator.validate_snapshot_dir(folder)
    assert code == 1
    assert any("unknown source_key" in error for error in errors)


def test_invalid_timestamp_rejected(tmp_path):
    snapshot = copy.deepcopy(PLACEHOLDER)
    snapshot["observed_at"] = "not-a-timestamp"
    folder = _write_snapshot(tmp_path, snapshot)
    code, errors = validator.validate_snapshot_dir(folder)
    assert code == 1
    assert any("observed_at" in error for error in errors)


def test_credential_leak_rejected(tmp_path):
    snapshot = copy.deepcopy(PLACEHOLDER)
    snapshot.update(
        source_key="bndes",
        observed_at="2026-09-06T00:00:00+00:00",
        notes="Authorization: Bearer eyJhbGciOiJIUzI1NiJ9",
    )
    folder = _write_snapshot(tmp_path, snapshot)
    code, errors = validator.validate_snapshot_dir(folder)
    assert code == 1
    assert any("credentials" in error for error in errors)


def test_concluded_audit_without_report_rejected(tmp_path):
    snapshot = copy.deepcopy(PLACEHOLDER)
    snapshot.update(
        observed_at="2026-09-06T00:00:00+00:00",
        audits=[{"result": "pass", "report_path": ""}],
    )
    folder = _write_snapshot(tmp_path, snapshot)
    code, errors = validator.validate_snapshot_dir(folder)
    assert code == 1
    assert any("report_path" in error for error in errors)
