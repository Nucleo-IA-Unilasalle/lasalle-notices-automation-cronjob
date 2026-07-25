"""Fail closed when a structured-source audit bundle is incomplete."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from structured_discovery import opportunity_to_fidelity_record


REQUIRED_FILES = (
    "audit_manifest.json",
    "source_inventory.json",
    "discovery.json",
    "opportunities.json",
    "policy_rejections.json",
    "parser_failures.json",
    "stats.json",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_bundle(source_dir: Path) -> list[str]:
    errors = [
        f"missing required artifact: {name}"
        for name in REQUIRED_FILES
        if not (source_dir / name).is_file()
    ]
    if errors:
        return errors

    manifest = _load(source_dir / "audit_manifest.json")
    inventory = _load(source_dir / "source_inventory.json")
    discovery = _load(source_dir / "discovery.json")
    opportunities = _load(source_dir / "opportunities.json")
    rejections = _load(source_dir / "policy_rejections.json")
    parser_failures = _load(source_dir / "parser_failures.json")
    stats = _load(source_dir / "stats.json")

    for name, value in (
        ("source_inventory.json", inventory),
        ("discovery.json", discovery),
        ("opportunities.json", opportunities),
        ("policy_rejections.json", rejections),
        ("parser_failures.json", parser_failures),
    ):
        if not isinstance(value, list):
            errors.append(f"{name} must contain a JSON array")

    if errors:
        return errors
    if manifest.get("contract_version") != 2:
        errors.append("audit manifest contract_version must be 2")
    if manifest.get("inventory_origin") != "authoritative_source_records":
        errors.append("audit manifest does not declare authoritative inventory")
    if manifest.get("discovery_origin") != "accepted_opportunity_projections":
        errors.append("audit manifest does not declare accepted discovery origin")
    if not inventory:
        errors.append("authoritative inventory is empty")
    if parser_failures:
        errors.append(
            f"parser_failures.json contains {len(parser_failures)} failure(s)"
        )
    for flag in ("inventory_parse_failed", "section_parse_failed", "parser_failures"):
        if stats.get(flag, 0):
            errors.append(f"stats.json reports {flag}={stats[flag]}")

    projected = [
        opportunity_to_fidelity_record(opportunity)
        for opportunity in opportunities
    ]
    if discovery != projected:
        errors.append("discovery.json is not the accepted opportunity projection")
    if len(discovery) != manifest.get("discovery_records"):
        errors.append("manifest discovery count does not match discovery.json")
    if len(inventory) != manifest.get("inventory_records"):
        errors.append("manifest inventory count does not match source_inventory.json")

    inventory_ids = {
        (record.get("source_key"), record.get("source_record_id"))
        for record in inventory
    }
    for index, record in enumerate(discovery):
        stable_id = (record.get("source_key"), record.get("source_record_id"))
        if stable_id not in inventory_ids:
            errors.append(
                f"discovery[{index}] has no authoritative inventory identity"
            )
    for index, record in enumerate(rejections):
        if not record.get("reason_code") or not isinstance(
            record.get("evidence"), dict
        ):
            errors.append(
                f"policy_rejections[{index}] lacks reason_code or evidence"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        errors = verify_bundle(args.source_dir)
    except (OSError, ValueError, TypeError) as exc:
        print(f"invalid structured audit bundle: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"structured audit bundle OK: {args.source_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
