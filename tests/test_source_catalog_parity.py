"""Offline fail-closed checks for the A catalog parity gate.

No test here performs live network I/O. Live-authenticated validation is
documented in docs/OPERATIONS.md ("Catalog parity: pinned/live CI") and must be
run manually via the source-catalog-parity workflow; these tests cover the same
failure classes with local fixtures and mocked HTTP responses.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import requests

import check_source_catalog_parity
from build_source_matrix import load_registry
from check_source_catalog_parity import (
    PIN,
    compare_pinned_to_live,
    fetch_catalog,
    is_pin_stale,
    pin_exported_at,
    validate_parity,
)


@pytest.fixture
def registry():
    return load_registry()


@pytest.fixture
def pin():
    return json.loads(PIN.read_text(encoding="utf-8"))


def _item(pin, key):
    for item in pin["items"]:
        if item["source_key"] == key:
            return item
    raise AssertionError(f"missing pin item: {key}")


def test_pinned_parity_passes(registry, pin):
    validate_parity(registry, pin)


def test_duplicate_catalog_identities_rejected(registry, pin):
    pin["items"].append(copy.deepcopy(pin["items"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        validate_parity(registry, pin)


def test_duplicate_registry_keys_fail_closed(registry):
    registry["sources"].append(copy.deepcopy(registry["sources"][0]))
    with pytest.raises(SystemExit):
        validate_parity(registry, {"contract_version": 1, "items": []})


def test_missing_a_identity_rejected(registry, pin):
    pin["items"] = [item for item in pin["items"] if item["source_key"] != "bndes"]
    with pytest.raises(ValueError, match="Missing A catalog identity: bndes"):
        validate_parity(registry, pin)


def test_lifecycle_mismatch_rejected(registry, pin):
    for item in pin["items"]:
        if item["source_key"] == "bndes":
            item["catalog_status"] = "paused"
    with pytest.raises(ValueError, match="Lifecycle mismatch"):
        validate_parity(registry, pin)


def test_ingest_source_rejects_audit_status(registry, pin):
    # bndes runs with rollout_mode=ingest, so only active is allowed.
    _item(pin, "bndes")["catalog_status"] = "audit"
    with pytest.raises(ValueError, match="Lifecycle mismatch: bndes"):
        validate_parity(registry, pin)


def test_audit_source_accepts_active_and_audit(registry, pin):
    # funbio runs with rollout_mode=audit, so active and audit both pass.
    validate_parity(registry, pin)
    _item(pin, "funbio")["catalog_status"] = "audit"
    validate_parity(registry, pin)


def test_paused_entries_skip_lifecycle_cadence_timeout(registry, pin):
    # canoas is rollout_mode=paused in the registry: lifecycle, cadence and
    # timeout drift must not fail parity. Paused rows stay outside the healthy
    # coverage gate and never authorize ingestion.
    paused = _item(pin, "canoas")
    paused["catalog_status"] = "paused"
    paused["expected_interval_minutes"] = 9999
    paused["max_run_minutes"] = 1
    validate_parity(registry, pin)


def test_cadence_mismatch_rejected(registry, pin):
    for item in pin["items"]:
        if item["source_key"] == "bndes":
            item["expected_interval_minutes"] = 9999
    with pytest.raises(ValueError, match="Cadence mismatch"):
        validate_parity(registry, pin)


def test_non_integer_interval_rejected(registry, pin):
    _item(pin, "bndes")["expected_interval_minutes"] = "60"
    with pytest.raises(ValueError, match="Cadence mismatch: bndes"):
        validate_parity(registry, pin)


def test_short_run_timeout_rejected(registry, pin):
    for item in pin["items"]:
        if item["source_key"] == "bndes":
            item["max_run_minutes"] = 1
    with pytest.raises(ValueError, match="run timeout"):
        validate_parity(registry, pin)


def test_non_integer_run_timeout_rejected(registry, pin):
    _item(pin, "bndes")["max_run_minutes"] = "30"
    with pytest.raises(ValueError, match="run timeout"):
        validate_parity(registry, pin)


def test_run_timeout_at_job_bound_passes(registry, pin):
    bound = registry["defaults"]["run_timeout_minutes"]
    _item(pin, "bndes")["max_run_minutes"] = bound
    validate_parity(registry, pin)


def test_missing_timeout_field_rejected(registry, pin):
    del _item(pin, "bndes")["max_run_minutes"]
    with pytest.raises(ValueError, match="missing max_run_minutes"):
        validate_parity(registry, pin)


def test_missing_interval_field_rejected(registry, pin):
    del _item(pin, "bndes")["expected_interval_minutes"]
    with pytest.raises(ValueError, match="missing expected_interval_minutes"):
        validate_parity(registry, pin)


def test_unsupported_contract_rejected(registry, pin):
    pin["contract_version"] = 999
    with pytest.raises(ValueError, match="Unsupported"):
        validate_parity(registry, pin)


def test_items_not_list_rejected(registry):
    with pytest.raises(ValueError, match="Unsupported"):
        validate_parity(registry, {"contract_version": 1, "items": {}})


def test_contract_not_object_rejected(registry):
    with pytest.raises(ValueError, match="Unsupported"):
        validate_parity(registry, ["not", "a", "dict"])


def test_item_not_object_rejected(registry, pin):
    pin["items"][0] = "bndes"
    with pytest.raises(ValueError, match="Malformed catalog item"):
        validate_parity(registry, pin)


def test_item_missing_source_key_rejected(registry, pin):
    del pin["items"][0]["source_key"]
    with pytest.raises(ValueError, match="missing source_key"):
        validate_parity(registry, pin)


def test_item_invalid_status_type_rejected(registry, pin):
    _item(pin, "bndes")["catalog_status"] = 42
    with pytest.raises(ValueError, match="invalid catalog_status"):
        validate_parity(registry, pin)


def test_operational_source_without_b_owner_rejected(registry, pin):
    pin["items"].append({
        "source_key": "ghost_source",
        "catalog_status": "active",
        "expected_interval_minutes": 60,
        "max_run_minutes": 30,
    })
    with pytest.raises(ValueError, match="without a B execution owner"):
        validate_parity(registry, pin)


def test_paused_extra_pin_key_does_not_require_owner(registry, pin):
    pin["items"].append({
        "source_key": "ghost_paused",
        "catalog_status": "paused",
        "expected_interval_minutes": 60,
        "max_run_minutes": 30,
    })
    validate_parity(registry, pin)


def test_pin_exported_at_parses(pin):
    assert pin_exported_at(pin).tzinfo is not None


def test_pin_exported_at_missing_rejected(pin):
    del pin["exported_at"]
    with pytest.raises(ValueError, match="exported_at"):
        pin_exported_at(pin)


def test_pin_exported_at_invalid_rejected(pin):
    pin["exported_at"] = "not-a-timestamp"
    with pytest.raises(ValueError, match="exported_at"):
        pin_exported_at(pin)


def test_pin_age_gate_boundaries(pin):
    exported = pin_exported_at(pin)
    assert is_pin_stale(pin, now=exported + timedelta(days=13)) is False
    assert is_pin_stale(pin, now=exported + timedelta(days=15)) is True


def test_compare_pinned_to_live_identical_passes(pin):
    compare_pinned_to_live(pin, copy.deepcopy(pin))


def test_compare_pinned_to_live_duplicate_live_keys_rejected(pin):
    # A duplicated live key must not silently collapse to a single row and
    # then compare equal against the pin.
    live = copy.deepcopy(pin)
    live["items"].append(copy.deepcopy(live["items"][0]))
    with pytest.raises(ValueError, match="Duplicate catalog identities"):
        compare_pinned_to_live(pin, live)


def test_compare_pinned_to_live_duplicate_pinned_keys_rejected(pin):
    duplicated = copy.deepcopy(pin)
    duplicated["items"].append(copy.deepcopy(duplicated["items"][0]))
    with pytest.raises(ValueError, match="Duplicate catalog identities"):
        compare_pinned_to_live(duplicated, copy.deepcopy(pin))


def test_compare_pinned_to_live_interval_drift_rejected(pin):
    live = copy.deepcopy(pin)
    _item(live, "bndes")["expected_interval_minutes"] = 9999
    with pytest.raises(ValueError, match="Live catalog differs.*bndes"):
        compare_pinned_to_live(pin, live)


def test_compare_pinned_to_live_status_drift_rejected(pin):
    live = copy.deepcopy(pin)
    _item(live, "bndes")["catalog_status"] = "audit"
    with pytest.raises(ValueError, match="Live catalog differs.*bndes"):
        compare_pinned_to_live(pin, live)


def test_compare_pinned_to_live_missing_key_rejected(pin):
    live = copy.deepcopy(pin)
    live["items"] = [item for item in live["items"] if item["source_key"] != "bndes"]
    with pytest.raises(ValueError, match="Live catalog keys differ"):
        compare_pinned_to_live(pin, live)


def test_compare_pinned_to_live_extra_key_rejected(pin, registry):
    live = copy.deepcopy(pin)
    live["items"].append({
        "source_key": "ghost_source",
        "catalog_status": "active",
        "expected_interval_minutes": 60,
        "max_run_minutes": 30,
    })
    with pytest.raises(ValueError, match="Live catalog keys differ"):
        compare_pinned_to_live(pin, live)


class _FakeResponse:
    def __init__(self, status_code=200, body=None, exc=None):
        self.status_code = status_code
        self._body = body
        self._exc = exc

    def json(self):
        if self._exc is not None:
            raise self._exc
        return self._body


def _patch_get(monkeypatch, response=None, exc=None):
    def fake_get(*args, **kwargs):
        if exc is not None:
            raise exc
        assert kwargs.get("allow_redirects") is False
        assert kwargs.get("timeout") == (5, 20)
        return response

    monkeypatch.setattr("check_source_catalog_parity.requests.get", fake_get)
    monkeypatch.setenv("RENDER_APP_URL", "https://render.example.com/")
    monkeypatch.setenv("PIPELINE_SECRET", "test-secret")


def test_fetch_catalog_auth_failure_rejected(monkeypatch):
    _patch_get(monkeypatch, response=_FakeResponse(status_code=401, body={}))
    with pytest.raises(ValueError, match="HTTP 401"):
        fetch_catalog()


def test_fetch_catalog_server_failure_rejected(monkeypatch):
    _patch_get(monkeypatch, response=_FakeResponse(status_code=500, body={}))
    with pytest.raises(ValueError, match="HTTP 500"):
        fetch_catalog()


def test_fetch_catalog_network_failure_surfaces(monkeypatch):
    _patch_get(monkeypatch, exc=requests.ConnectionError("dns down"))
    with pytest.raises(requests.RequestException):
        fetch_catalog()


def test_fetch_catalog_capacity_drift_rejected(monkeypatch, pin):
    body = copy.deepcopy(pin)
    body["max_concurrent_source_runs"] = 9
    _patch_get(monkeypatch, response=_FakeResponse(status_code=200, body=body))
    with pytest.raises(ValueError, match="aggregate capacity"):
        fetch_catalog()


def test_fetch_catalog_malformed_body_rejected(monkeypatch):
    _patch_get(monkeypatch, response=_FakeResponse(status_code=200, body=["not", "a", "dict"]))
    with pytest.raises(ValueError, match="malformed"):
        fetch_catalog()


def test_fetch_catalog_malformed_items_rejected(monkeypatch, pin):
    body = copy.deepcopy(pin)
    body["max_concurrent_source_runs"] = 3
    body["items"] = "not-a-list"
    _patch_get(monkeypatch, response=_FakeResponse(status_code=200, body=body))
    with pytest.raises(ValueError, match="Unsupported"):
        fetch_catalog()


def test_fetch_catalog_valid_body_passes(monkeypatch, pin):
    body = copy.deepcopy(pin)
    body["max_concurrent_source_runs"] = 3
    _patch_get(monkeypatch, response=_FakeResponse(status_code=200, body=body))
    assert fetch_catalog() == body


def test_fetch_catalog_invalid_json_body_rejected(monkeypatch):
    # A 200 whose body is not JSON at all must fail closed, not surface a
    # raw decoder traceback to the caller.
    _patch_get(monkeypatch, response=_FakeResponse(
        status_code=200, exc=json.JSONDecodeError("Expecting value", "<html>", 0)))
    with pytest.raises(ValueError):
        fetch_catalog()


def test_fetch_catalog_timeout_surfaces(monkeypatch):
    _patch_get(monkeypatch, exc=requests.Timeout("connect timed out"))
    with pytest.raises(requests.RequestException):
        fetch_catalog()


def test_fetch_catalog_sends_no_redirects_with_bounded_timeout(monkeypatch, pin):
    # The transport contract itself: auth header present, redirects refused,
    # (5, 20) connect/read timeouts. Asserted in _patch_get for every fake.
    body = copy.deepcopy(pin)
    body["max_concurrent_source_runs"] = 3
    seen: dict = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        return _FakeResponse(status_code=200, body=body)

    monkeypatch.setattr("check_source_catalog_parity.requests.get", fake_get)
    monkeypatch.setenv("RENDER_APP_URL", "https://render.example.com/")
    monkeypatch.setenv("PIPELINE_SECRET", "test-secret")
    fetch_catalog()
    assert seen["url"] == "https://render.example.com/api/pipeline/source-schedule/catalog"
    assert seen["headers"]["Authorization"] == "Bearer test-secret"


# --- Live-mode orchestration in main(): stale-pin ordering, output artifact,
# --- and failure surfacing. All offline; no production endpoints are touched.


def _argv(*extra):
    return ["check_source_catalog_parity.py", *extra]


def _use_fresh_pin(monkeypatch, tmp_path, pin):
    """Point main() at a fresh-exported pin so tests never depend on real age."""
    fresh = copy.deepcopy(pin)
    fresh["exported_at"] = datetime.now(timezone.utc).isoformat()
    temp_pin = tmp_path / "fresh-pin.json"
    temp_pin.write_text(json.dumps(fresh), encoding="utf-8")
    monkeypatch.setattr(check_source_catalog_parity, "PIN", temp_pin)


def test_main_pinned_only_passes_and_reports_paused_holds(monkeypatch, registry, pin, capsys):
    monkeypatch.setattr("sys.argv", _argv())
    assert check_source_catalog_parity.main() == 0
    out = capsys.readouterr().out
    assert "Locally paused (not covered): canoas, dopa, fbds, finep, ibama" in out
    assert "A catalog parity passed (pinned only)" in out


def test_main_live_rejects_stale_pin_before_any_live_request(monkeypatch, registry, pin, tmp_path, capsys):
    # Pin age is checked before the live fetch: a stale pin must fail even
    # when the network is unreachable, and must not perform the live request.
    stale = copy.deepcopy(pin)
    stale["exported_at"] = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    temp_pin = tmp_path / "stale-pin.json"
    temp_pin.write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(check_source_catalog_parity, "PIN", temp_pin)
    requested = []

    def _refused(*args, **kwargs):
        requested.append(args)
        raise requests.ConnectionError("network refused")

    monkeypatch.setattr("check_source_catalog_parity.requests.get", _refused)
    monkeypatch.setenv("RENDER_APP_URL", "https://render.example.com/")
    monkeypatch.setenv("PIPELINE_SECRET", "test-secret")
    monkeypatch.setattr("sys.argv", _argv("--live"))
    assert check_source_catalog_parity.main() == 1
    assert requested == [], "stale-pin rejection must precede any live fetch"
    assert "parity failed" in capsys.readouterr().out


def test_main_live_failure_surfaces_safe_message(monkeypatch, registry, pin, tmp_path, capsys):
    _use_fresh_pin(monkeypatch, tmp_path, pin)
    monkeypatch.setattr("check_source_catalog_parity.requests.get",
                        lambda *a, **k: _FakeResponse(status_code=500, body={}))
    monkeypatch.setenv("RENDER_APP_URL", "https://render.example.com/")
    monkeypatch.setenv("PIPELINE_SECRET", "test-secret")
    monkeypatch.setattr("sys.argv", _argv("--live"))
    assert check_source_catalog_parity.main() == 1
    out = capsys.readouterr().out
    assert "parity failed" in out
    assert "500" not in out, "raw upstream detail must not leak into the summary"


def test_main_live_writes_observation_artifact(monkeypatch, tmp_path, registry, pin):
    _use_fresh_pin(monkeypatch, tmp_path, pin)
    live = copy.deepcopy(pin)
    live["max_concurrent_source_runs"] = 3
    live["observed_at"] = "2026-09-06T00:00:00+00:00"
    monkeypatch.setattr("check_source_catalog_parity.requests.get",
                        lambda *a, **k: _FakeResponse(status_code=200, body=live))
    monkeypatch.setenv("RENDER_APP_URL", "https://render.example.com/")
    monkeypatch.setenv("PIPELINE_SECRET", "test-secret")
    output = tmp_path / "catalog-observation.json"
    monkeypatch.setattr("sys.argv", _argv("--live", "--output", str(output)))
    assert check_source_catalog_parity.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["max_concurrent_source_runs"] == 3


def test_main_live_ignores_unrequested_output_in_pinned_mode(monkeypatch, tmp_path, registry, pin, capsys):
    # Without --live, the gate must not write an "observation" artifact that
    # could be mistaken for live evidence.
    _use_fresh_pin(monkeypatch, tmp_path, pin)
    output = tmp_path / "catalog-observation.json"
    monkeypatch.setattr("sys.argv", _argv("--output", str(output)))
    assert check_source_catalog_parity.main() == 0
    assert not output.exists()
    assert "A catalog parity passed (pinned only)" in capsys.readouterr().out


def test_main_rejects_missing_secrets_fail_closed(monkeypatch, registry, pin, tmp_path, capsys):
    # A live run without configured credentials must fail closed with the
    # safe summary, never a KeyError traceback.
    _use_fresh_pin(monkeypatch, tmp_path, pin)
    monkeypatch.delenv("RENDER_APP_URL", raising=False)
    monkeypatch.delenv("PIPELINE_SECRET", raising=False)
    monkeypatch.setattr("sys.argv", _argv("--live"))
    assert check_source_catalog_parity.main() == 1
    assert "parity failed" in capsys.readouterr().out
