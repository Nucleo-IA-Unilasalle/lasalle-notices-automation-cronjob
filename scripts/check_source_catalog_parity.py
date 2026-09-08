"""Fail closed on pinned/live A catalog drift; never modifies A or dispatches jobs."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path

import requests
from build_source_matrix import load_registry, validate_registry

PIN = Path(__file__).resolve().parents[1] / "config/source_catalog_contract.json"

PIN_MAX_AGE_DAYS = 14
EXPECTED_MAX_CONCURRENT_SOURCE_RUNS = 3
REQUIRED_ITEM_FIELDS = ("source_key", "catalog_status", "expected_interval_minutes", "max_run_minutes")
ARCHIVED_SOURCE_KEYS = frozenset({
    "cnpq", "floresta_mais_amazonia", "fundacao_cargill", "fundo_amazonia",
    "govbr_mcti", "govbr_mma_cop17", "govbr_sfb", "iadb", "thegef",
})


def _require_contract_items(contract):
    if not isinstance(contract, dict):
        raise ValueError("Unsupported A catalog contract")
    if contract.get("contract_version") != 1:
        raise ValueError("Unsupported A catalog contract")
    items = contract.get("items")
    if not isinstance(items, list):
        raise ValueError("Unsupported A catalog contract")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Malformed catalog item: expected an object")
        for field in REQUIRED_ITEM_FIELDS:
            if field not in item:
                raise ValueError(f"Malformed catalog item: missing {field}")
        if not isinstance(item["source_key"], str) or not item["source_key"]:
            raise ValueError("Malformed catalog item: invalid source_key")
        if not isinstance(item["catalog_status"], str):
            raise ValueError(f"Malformed catalog item: invalid catalog_status for {item['source_key']}")
    return items


def pin_exported_at(pin):
    if not isinstance(pin, dict) or not isinstance(pin.get("exported_at"), str):
        raise ValueError("Pinned export is missing exported_at")
    try:
        moment = datetime.fromisoformat(pin["exported_at"])
    except ValueError:
        raise ValueError("Pinned export has an invalid exported_at timestamp")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def is_pin_stale(pin, now=None):
    moment = pin_exported_at(pin)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return moment < current - timedelta(days=PIN_MAX_AGE_DAYS)


def compare_pinned_to_live(pin, live):
    pinned_items = _require_contract_items(pin)
    observed_items = _require_contract_items(live)
    pinned = {item["source_key"]: item for item in pinned_items}
    observed = {item["source_key"]: item for item in observed_items}
    # A dict build silently collapses duplicate keys; fail closed instead.
    if len(pinned) != len(pinned_items) or len(observed) != len(observed_items):
        raise ValueError("Duplicate catalog identities in pinned or live exports")
    # The operational pin covers 23 sources; A also returns nine historical
    # identities. Only the exact unchanged archived rows are outside that pin.
    for key in ARCHIVED_SOURCE_KEYS - pinned.keys():
        if observed.get(key) == {
            "source_key": key, "catalog_status": "archived",
            "expected_interval_minutes": None, "max_run_minutes": None,
        }:
            observed.pop(key)
    if set(observed) != set(pinned):
        missing = sorted(set(pinned) - set(observed))
        extra = sorted(set(observed) - set(pinned))
        raise ValueError(f"Live catalog keys differ from pin (missing={missing} extra={extra})")
    for key, item in pinned.items():
        if observed.get(key) != item:
            raise ValueError(f"Live catalog differs from the reviewed A manifest export: {key}")


def validate_parity(registry, contract):
    items = _require_contract_items(contract)
    catalog = {item["source_key"]: item for item in items}
    if len(catalog) != len(items):
        raise ValueError("Duplicate catalog identities")
    entries = validate_registry(registry)
    registry_keys = {entry["source_key"] for entry in entries}
    if any(key not in registry_keys and item["catalog_status"] in {"active", "audit"} for key, item in catalog.items()):
        raise ValueError("A has operational sources without a B execution owner")
    for entry in entries:
        key = entry["source_key"]
        item = catalog.get(key)
        if item is None:
            raise ValueError(f"Missing A catalog identity: {key}")
        if entry["rollout_mode"] == "paused":
            # Execution holds do not mutate A lifecycle. They remain outside
            # the healthy coverage gate even when the bootstrap manifest is active.
            continue
        allowed = {"active"} if entry["rollout_mode"] == "ingest" else {"active", "audit"}
        if item["catalog_status"] not in allowed:
            raise ValueError(f"Lifecycle mismatch: {key}")
        if type(item["expected_interval_minutes"]) is not int or item["expected_interval_minutes"] != entry["interval_minutes"]:
            raise ValueError(f"Cadence mismatch: {key}")
        if type(item["max_run_minutes"]) is not int or item["max_run_minutes"] < registry["defaults"]["run_timeout_minutes"]:
            raise ValueError(f"A run timeout is shorter than B job timeout: {key}")


def fetch_catalog():
    response = requests.get(os.environ["RENDER_APP_URL"].rstrip("/") + "/api/pipeline/source-schedule/catalog",
                            headers={"Authorization": "Bearer " + os.environ["PIPELINE_SECRET"]},
                            timeout=(5, 20), allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f"Live catalog unavailable: HTTP {response.status_code}")
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Live catalog returned a malformed body")
    if result.get("max_concurrent_source_runs") != EXPECTED_MAX_CONCURRENT_SOURCE_RUNS:
        raise ValueError("Live aggregate capacity differs from the reviewed three-slot policy")
    _require_contract_items(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        registry = load_registry()
        pin = json.loads(PIN.read_text(encoding="utf-8"))
        validate_parity(registry, pin)
        if args.live:
            if is_pin_stale(pin):
                raise ValueError("Pinned A catalog export is older than 14 days; refresh and review it")
            live = fetch_catalog()
            validate_parity(registry, live)
            compare_pinned_to_live(pin, live)
            if args.output:
                args.output.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
        paused = [s["source_key"] for s in registry["sources"] if s["rollout_mode"] == "paused"]
        print("Locally paused (not covered): " + ", ".join(paused))
        print("A catalog parity passed" + (" (live and pinned)" if args.live else " (pinned only)"))
        return 0
    except (ValueError, KeyError, OSError, requests.RequestException):
        print("A catalog parity failed; inspect identity, lifecycle, cadence, capacity, credentials and pin age")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
