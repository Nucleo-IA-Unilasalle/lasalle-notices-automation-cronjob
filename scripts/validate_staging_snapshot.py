"""Offline structural check for a staging evidence snapshot directory.

Reads only local files. Performs no network I/O, never touches production,
and never fabricates audit/soak results: placeholder TODO values are accepted
as structurally valid but reported as outstanding.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_source_matrix import ORCHESTRATOR_MODULES

KNOWN_SOURCES = set(ORCHESTRATOR_MODULES) | {"pncp"}
REQUIRED_TOP_FIELDS = ("source_key", "observed_at", "registry_ref", "pin_ref", "runs", "audits", "notes")
REQUIRED_RUN_FIELDS = ("run_id", "started_at", "status")
VALID_RUN_STATUS = {"pending", "success", "failed", "warning", "skipped", "TODO"}
VALID_AUDIT_RESULT = {"TODO", "pass", "fail"}
FORBIDDEN_SUBSTRINGS = ("Authorization", "Bearer ey", "PIPELINE_SECRET", "BEGIN PRIVATE KEY")


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_snapshot_dir(snapshot_dir: Path) -> tuple[int, list[str]]:
    errors: list[str] = []
    outstanding: list[str] = []
    snapshot_file = snapshot_dir / "snapshot.json"
    checklist_file = snapshot_dir / "checklist.md"
    if not snapshot_file.is_file():
        _fail(errors, f"missing required file: {snapshot_file.name}")
        return 1, errors
    if not checklist_file.is_file():
        _fail(errors, f"missing required file: {checklist_file.name}")
    try:
        raw = snapshot_file.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(errors, f"unreadable snapshot.json: {exc}")
        return 1, errors
    for token in FORBIDDEN_SUBSTRINGS:
        if token in raw:
            _fail(errors, f"snapshot.json may contain credentials (found {token!r}); redact before storing")
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(errors, f"snapshot.json is not valid JSON: {exc}")
        return 1, errors
    if not isinstance(snapshot, dict):
        _fail(errors, "snapshot.json must be a JSON object")
        return 1, errors
    for field in REQUIRED_TOP_FIELDS:
        if field not in snapshot:
            _fail(errors, f"snapshot.json is missing required field: {field}")
    if errors:
        return 1, errors
    if snapshot["source_key"] not in KNOWN_SOURCES:
        _fail(errors, f"unknown source_key: {snapshot['source_key']!r}")
    try:
        datetime.fromisoformat(str(snapshot["observed_at"]))
    except ValueError:
        _fail(errors, "observed_at must be an ISO-8601 timestamp")
    if not isinstance(snapshot["runs"], list):
        _fail(errors, "runs must be a list")
    else:
        for run in snapshot["runs"]:
            if not isinstance(run, dict):
                _fail(errors, "each run must be an object")
                continue
            for field in REQUIRED_RUN_FIELDS:
                if field not in run:
                    _fail(errors, f"run is missing required field: {field}")
            if run.get("status") not in VALID_RUN_STATUS:
                _fail(errors, f"run has invalid status: {run.get('status')!r}")
            try:
                datetime.fromisoformat(str(run.get("started_at", "")))
            except ValueError:
                _fail(errors, f"run has invalid started_at: {run.get('run_id', '?')}")
    if not isinstance(snapshot["audits"], list) or len(snapshot["audits"]) > 2:
        _fail(errors, "audits must be a list of at most 2 entries")
    else:
        for audit in snapshot["audits"]:
            if not isinstance(audit, dict):
                _fail(errors, "each audit must be an object")
                continue
            if audit.get("result") not in VALID_AUDIT_RESULT:
                _fail(errors, f"audit has invalid result: {audit.get('result')!r}")
            if audit.get("result") in {"pass", "fail"} and not audit.get("report_path"):
                _fail(errors, "a concluded audit must reference its report_path")
            if audit.get("result") == "TODO":
                outstanding.append("audit result TODO")
    if snapshot.get("notes") == "TODO":
        outstanding.append("notes TODO")
    if not snapshot["runs"]:
        outstanding.append("no runs recorded yet")
    if errors:
        return 1, errors
    return 0, outstanding


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.snapshot_dir.is_dir():
        print(f"error: not a directory: {args.snapshot_dir}", file=sys.stderr)
        return 2
    try:
        code, details = validate_snapshot_dir(args.snapshot_dir)
    except Exception as exc:  # fail closed on unexpected input shapes
        print(f"error: invalid snapshot directory: {exc}", file=sys.stderr)
        return 2
    if code == 0:
        if details:
            print("Snapshot structure OK; outstanding placeholders: " + ", ".join(details))
        else:
            print("Snapshot structure OK; no placeholders outstanding")
        return 0
    for detail in details:
        print(f"error: {detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
