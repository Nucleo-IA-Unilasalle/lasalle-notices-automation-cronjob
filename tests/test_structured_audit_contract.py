"""Regression tests for independent structured-source audit bundles."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from source_fidelity import run_audit
from verify_structured_audit_artifacts import verify_bundle


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "audit"
    / "structured_contract_cases.json"
)


def _contract_cases():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        pytest.param(
            fixture["base_record"],
            case["mutation"],
            case["expected_reason_code"],
            id=case["name"],
        )
        for case in fixture["cases"]
    ]


@pytest.mark.parametrize(
    ("base", "mutation", "expected_reason_code"),
    _contract_cases(),
)
def test_independent_inputs_expose_every_blocking_mutation(
    base,
    mutation,
    expected_reason_code,
):
    inventory = [copy.deepcopy(base)]
    discovery = [copy.deepcopy(base)]

    if mutation == "remove_discovery":
        discovery.clear()
    elif mutation == "add_extra_discovery":
        extra = copy.deepcopy(base)
        extra["source_record_id"] = "extra"
        extra["canonical_url"] = "https://example.test/calls/extra"
        extra["document_urls"] = []
        discovery.append(extra)
    elif mutation == "duplicate_discovery_id":
        duplicate = copy.deepcopy(base)
        duplicate["canonical_url"] = "https://example.test/calls/duplicate"
        duplicate["document_urls"] = []
        discovery.append(duplicate)
    elif mutation == "duplicate_inventory_url":
        duplicate = copy.deepcopy(base)
        duplicate["source_record_id"] = "duplicate"
        duplicate["document_urls"] = []
        inventory.append(duplicate)
    elif mutation == "change_discovery_status":
        discovery[0]["status"] = "closed"
    elif mutation == "change_discovery_deadline":
        discovery[0]["deadline"] = "2026-10-01T23:59:00Z"
    elif mutation == "claim_unvalidated_renderable_document":
        discovery[0]["renderable"] = True
        discovery[0]["content_type_validated"] = False
        discovery[0]["hash_validated"] = False
    else:
        raise AssertionError(f"unknown fixture mutation: {mutation}")

    reason_codes = {
        exception.reason_code
        for exception in run_audit(inventory, discovery).blocking_exceptions()
    }
    assert expected_reason_code in reason_codes


def _write_bundle(path: Path, *, parser_failures=None) -> None:
    opportunity = {
        "source_key": "finep",
        "source_record_id": "42",
        "canonical_url": "https://example.test/calls/42",
        "title": "Chamada 42",
        "authoritative_status": "open",
        "source_published_at": None,
        "application_deadline": None,
        "documents": [],
    }
    inventory = [
        {
            "source_key": "finep",
            "source_record_id": "42",
            "canonical_url": "https://example.test/calls/42",
            "title": "Chamada 42",
            "status": "open",
            "published_at": None,
            "deadline": None,
            "document_urls": [],
            "document_hashes": [],
        }
    ]
    artifacts = {
        "audit_manifest.json": {
            "contract_version": 2,
            "source": "finep",
            "inventory_origin": "authoritative_source_records",
            "discovery_origin": "accepted_opportunity_projections",
            "inventory_records": 1,
            "discovery_records": 1,
            "policy_rejections": 0,
            "parser_failures": len(parser_failures or []),
        },
        "source_inventory.json": inventory,
        "discovery.json": inventory,
        "opportunities.json": [opportunity],
        "policy_rejections.json": [],
        "parser_failures.json": parser_failures or [],
        "stats.json": {"inventory_records": 1, "opportunities": 1},
    }
    path.mkdir()
    for name, value in artifacts.items():
        (path / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def test_bundle_verifier_accepts_independent_contract(tmp_path):
    source_dir = tmp_path / "finep"
    _write_bundle(source_dir)

    assert verify_bundle(source_dir) == []


def test_bundle_verifier_rejects_parser_failure_even_with_empty_diff(tmp_path):
    source_dir = tmp_path / "finep"
    _write_bundle(
        source_dir,
        parser_failures=[
            {
                "source_key": "finep",
                "stage": "api_inventory",
                "error": "malformed response",
                "evidence": {},
            }
        ],
    )

    errors = verify_bundle(source_dir)

    assert any("parser_failures.json contains 1" in error for error in errors)
