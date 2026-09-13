"""Offline contract tests for the disposable P1 harness.

The executable harness itself is deliberately not run from this suite: doing
so would need a real local PostgreSQL service and a Repo A dependency set. The
tests protect its safety guard, threshold semantics, and redaction contract.
"""

from __future__ import annotations

import inspect

import pytest

import run_p1_isolated_harness as harness


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://tester:secret@127.0.0.1:55432/p1_test",
        "postgresql+psycopg://tester:secret@localhost/p1_test_2026",
        "postgres://tester:secret@[::1]/scratch",
    ],
)
def test_database_guard_accepts_only_loopback_disposable_targets(database_url: str) -> None:
    target = harness.validate_disposable_database_url(database_url)
    assert target.host in harness.LOOPBACK_HOSTS
    assert target.database not in {"production", "staging"}


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://tester:secret@db.example.test/p1_test",
        "postgresql://tester:secret@127.0.0.1/prod",
        "postgresql://tester:secret@127.0.0.1/production_shadow",
        "postgresql://tester:secret@127.0.0.1/staging",
        "sqlite:///tmp/p1_test.db",
        "",
    ],
)
def test_database_guard_rejects_remote_or_production_looking_targets(database_url: str) -> None:
    with pytest.raises(harness.HarnessConfigurationError):
        harness.validate_disposable_database_url(database_url)


def test_schema_name_is_scoped_and_safe() -> None:
    assert harness.SCHEMA_RE.fullmatch(harness.make_schema_name())


def test_redaction_removes_database_urls_bearer_tokens_and_explicit_secrets() -> None:
    value = (
        "postgresql://tester:db-password@127.0.0.1/p1_test "
        "Authorization: Bearer claim-token "
        "PIPELINE_SECRET=super-secret"
    )
    redacted = harness.redact(value, ("super-secret", "claim-token"))
    assert "db-password" not in redacted
    assert "claim-token" not in redacted
    assert "super-secret" not in redacted
    assert "<redacted>" in redacted


def test_percentile_and_empty_latency_summary_are_deterministic() -> None:
    assert harness.percentile([], 95) is None
    assert harness.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    summary = harness.safe_latency_summary(harness.RequestStats())
    assert summary["requests"] == 0
    assert summary["p95_ms"] is None


def test_quantitative_gate_does_not_pass_with_unknown_storage_budget() -> None:
    stats = harness.RequestStats(total=10)
    stats.latencies_ms = [100.0] * 10
    result = harness.evaluate_thresholds(
        request_stats=stats,
        claim_p95_ms=100.0,
        peak_connections=2,
        usable_connections=10,
        storage_headroom_ratio=None,
        service_rate_per_hour=100.0,
        arrival_rate_per_hour=22.0,
    )
    assert result["status"] == "blocked_or_failed"
    assert result["checks"]["storage_headroom_ge_20pct"] is False


def test_quantitative_gate_passes_only_when_all_declared_limits_are_measured() -> None:
    stats = harness.RequestStats(total=100)
    stats.latencies_ms = [100.0] * 100
    result = harness.evaluate_thresholds(
        request_stats=stats,
        claim_p95_ms=100.0,
        peak_connections=6,
        usable_connections=10,
        storage_headroom_ratio=0.5,
        service_rate_per_hour=30.0,
        arrival_rate_per_hour=22.0,
    )
    assert result["status"] == "pass"
    assert all(result["checks"].values())


def test_harness_contains_real_process_and_http_boundaries() -> None:
    source = inspect.getsource(harness)
    assert "uvicorn" in source
    assert "subprocess.Popen" in source
    assert "from source_control import AdmissionConflict, SourceControl" in source
    assert "stream=True" in source
    assert "PGOPTIONS" in source
    assert "changed_content_replay" in source
    assert "poison_backoff_and_quarantine" in source


def test_changed_fixture_keeps_identity_but_changes_content() -> None:
    first, _ = harness._make_candidate_payload("bndes", 200, variant="v1")
    second, _ = harness._make_candidate_payload("bndes", 200, variant="v2")
    assert first["metadata"]["source_record_id"] == second["metadata"]["source_record_id"]
    assert first["worker_result"]["content_hash"] != second["worker_result"]["content_hash"]
    assert first["worker_result"]["ocr_markdown"] != second["worker_result"]["ocr_markdown"]


def test_poison_expiry_helper_does_not_expire_the_source_claim() -> None:
    assert "retry_after_at" in harness._EXPIRE_WORK_SQL
    assert "claim_expires_at" not in harness._EXPIRE_WORK_SQL


def test_worker_parser_accepts_changed_replay_mode() -> None:
    args = harness._parse_args([
        "--worker-mode", "changed_replay",
        "--worker-source", "bndes",
        "--worker-items", "items.json",
        "--worker-control", "control.json",
        "--worker-ready", "ready",
    ])
    assert args.worker_mode == "changed_replay"


def test_parent_parser_requires_safe_capacity_inputs() -> None:
    args = harness._parse_args([
        "--database-url", "postgresql://tester:secret@127.0.0.1/p1_test",
        "--admitted-source", "brde",
        "--warm-samples", "5",
        "--arrival-rate-per-hour", "22",
    ])
    assert args.warm_samples == 5
    assert args.admitted_source == "brde"
    with pytest.raises(SystemExit):
        harness._parse_args(["--warm-samples", "4"])
