"""Closed-beta source admission must fail before a claim or ingestion starts."""

from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

import beta_admission
import run_managed_source as managed


def _env(value: str | None, *, mode: str = "closed_beta") -> dict[str, str]:
    environment = {beta_admission.MODE_ENV: mode}
    if value is not None:
        environment[beta_admission.ALLOWLIST_ENV] = value
    return environment


@pytest.mark.parametrize("value", [None, "", " bndes", "bndes ", "bndes,brde", "unknown"])
def test_allowlist_is_default_deny_for_unset_empty_malformed_and_unknown(value: str | None) -> None:
    with pytest.raises(beta_admission.BetaAdmissionDenied):
        beta_admission.admitted_source("bndes", environ=_env(value))


def test_allowlist_admits_only_the_one_selected_registry_source() -> None:
    assert beta_admission.admitted_source("bndes", environ=_env("bndes")) == "bndes"
    with pytest.raises(beta_admission.BetaAdmissionDenied, match="not selected"):
        beta_admission.admitted_source("brde", environ=_env("bndes"))


def test_allowlist_rejects_a_selected_structured_source_for_the_first_wave(monkeypatch) -> None:
    monkeypatch.setattr(beta_admission, "load_registry", lambda: {"defaults": {}})
    monkeypatch.setattr(
        beta_admission,
        "validate_registry",
        lambda registry: [
            {
                "source_key": "finep",
                "rollout_mode": "ingest",
                "submission_contract": "opportunity",
            }
        ],
    )
    with pytest.raises(beta_admission.BetaAdmissionDenied, match="candidate contract"):
        beta_admission.admitted_source("finep", environ=_env("finep"))


def test_allowlist_rejects_a_selected_source_held_outside_ingestion() -> None:
    registry = beta_admission.load_registry()
    registry["sources"][0]["rollout_mode"] = "audit"
    source = registry["sources"][0]["source_key"]
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(beta_admission, "load_registry", lambda: registry)
        with pytest.raises(beta_admission.BetaAdmissionDenied, match="held outside"):
            beta_admission.admitted_source(source, environ=_env(source))


@pytest.mark.parametrize("source", ["pncp", "bndes"])
def test_legacy_routes_are_blocked_even_when_their_source_is_selected(monkeypatch, source: str) -> None:
    monkeypatch.setenv(beta_admission.ALLOWLIST_ENV, source)
    assert beta_admission.main(["--source", source, "--legacy-route"]) == 2


@pytest.mark.parametrize("source", ["pncp", "finep", "brde"])
def test_legacy_mode_admits_every_ingest_contract_without_beta_allowlist(source: str) -> None:
    assert beta_admission.admitted_source(
        source,
        environ={beta_admission.MODE_ENV: "legacy"},
    ) == source


def test_legacy_routes_are_allowed_in_legacy_mode(monkeypatch) -> None:
    monkeypatch.setenv(beta_admission.MODE_ENV, "legacy")
    monkeypatch.delenv(beta_admission.ALLOWLIST_ENV, raising=False)
    assert beta_admission.main(["--source", "pncp", "--legacy-route"]) == 0


@pytest.mark.parametrize("mode", ["", "all", "LEGACY", " legacy"])
def test_unknown_admission_mode_fails_closed(mode: str) -> None:
    with pytest.raises(beta_admission.BetaAdmissionDenied, match="SOURCE_ADMISSION_MODE"):
        beta_admission.admitted_source(
            "bndes", environ={beta_admission.MODE_ENV: mode}
        )


def test_managed_worker_does_not_construct_a_claim_client_when_unselected(monkeypatch) -> None:
    monkeypatch.delenv(beta_admission.ALLOWLIST_ENV, raising=False)
    monkeypatch.setattr(managed, "load_registry", lambda: {"defaults": {}})
    monkeypatch.setattr(
        managed,
        "validate_registry",
        lambda registry: [{"source_key": "bndes", "rollout_mode": "ingest"}],
    )
    client = Mock()
    monkeypatch.setattr(managed, "SourceControl", client)
    assert managed.main(["--source", "bndes", "scripts/discover_all_candidates.py"]) == 2
    client.assert_not_called()


def test_cli_rejects_manual_unknown_source(monkeypatch) -> None:
    monkeypatch.setenv(beta_admission.ALLOWLIST_ENV, "bndes")
    assert beta_admission.main(["--source", "not-a-source"]) == 2


@pytest.mark.parametrize(
    ("source", "script"),
    [
        ("bndes", "scripts/discover_pncp_candidates.py"),
        ("pncp", "scripts/discover_all_candidates.py"),
    ],
)
def test_managed_worker_rejects_wrong_source_script_pair_before_claim(monkeypatch, source: str, script: str) -> None:
    monkeypatch.setenv(beta_admission.ALLOWLIST_ENV, source)
    client = Mock()
    monkeypatch.setattr(managed, "SourceControl", client)
    assert managed.main(["--source", source, script]) == 2
    client.assert_not_called()
