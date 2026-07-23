"""Offline, deterministic CLI for source-fidelity audits.

Usage:

    python scripts/audit_source_fidelity.py \
        --source-inventory inv.json \
        --discovery disc.json \
        --dashboard dash.json \
        --out ./report

Writes ``summary.json``, ``matches.json``, ``exceptions.json`` and
``report.md`` into ``--out`` (default ``./report``).

Exit codes:

* ``0`` — no blocking exceptions
* ``1`` — fidelity failures (blocking exceptions present)
* ``2`` — invalid input or configuration
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from source_fidelity import (
    AuditResult,
    render_markdown,
    render_summary,
    run_audit,
    validate_records,
)


EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_INVALID = 2


def _load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid JSON in {path}: {exc}")
    if not isinstance(data, list):
        raise CliError(f"{path} must contain a JSON array of records")
    return data


class CliError(Exception):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="audit_source_fidelity",
        description="Deterministic, offline source-fidelity audit (no LLM/network).",
    )
    parser.add_argument(
        "--source-inventory",
        required=True,
        type=Path,
        help="JSON file: authoritative open opportunities (array of records).",
    )
    parser.add_argument(
        "--discovery",
        required=True,
        type=Path,
        help="JSON file: discovery candidates (array of records).",
    )
    parser.add_argument(
        "--dashboard",
        required=False,
        type=Path,
        default=None,
        help="JSON file: optional dashboard export (array of records).",
    )
    parser.add_argument(
        "--out",
        required=False,
        type=Path,
        default=Path("./report"),
        help="Output directory for summary.json, matches.json, exceptions.json, report.md.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        inventory = validate_records(_load_json(args.source_inventory), "inventory")
        discovery = validate_records(_load_json(args.discovery), "discovery")
        dashboard = (
            validate_records(_load_json(args.dashboard), "dashboard")
            if args.dashboard is not None
            else None
        )
    except (CliError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INVALID

    try:
        result = run_audit(inventory, discovery, dashboard)
    except (TypeError, ValueError) as exc:
        print(f"error: invalid audit input: {exc}", file=sys.stderr)
        return EXIT_INVALID

    out_dir = args.out
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create output dir {out_dir}: {exc}", file=sys.stderr)
        return EXIT_INVALID

    summary = render_summary(result)
    matches = [m.to_dict() for m in result.matches]
    exceptions = [e.to_dict() for e in result.exceptions]

    try:
        _write_json(out_dir / "summary.json", summary)
        _write_json(out_dir / "matches.json", matches)
        _write_json(out_dir / "exceptions.json", exceptions)
        (out_dir / "report.md").write_text(
            render_markdown(result), encoding="utf-8"
        )
    except OSError as exc:
        print(f"error: cannot write reports to {out_dir}: {exc}", file=sys.stderr)
        return EXIT_INVALID

    blocking = summary["total_blocking_exceptions"]
    if blocking > 0:
        print(f"fidelity failures: {blocking} blocking exception(s)", file=sys.stderr)
        return EXIT_FAILURE
    print("source fidelity OK: no blocking exceptions")
    return EXIT_OK


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
