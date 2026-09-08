"""Offline regression tests for the opt-in staging failure-injection runner."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def runner_module():
    path = Path(__file__).parents[1] / "scripts" / "run_staging_failure_injection.py"
    spec = importlib.util.spec_from_file_location("staging_failure_injection", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_mutation_requires_explicit_argument_and_acknowledgement(runner_module, monkeypatch):
    monkeypatch.delenv("STAGING_FAILURE_INJECTION_ACK", raising=False)

    with pytest.raises(RuntimeError, match="pass --allow-live-staging-mutation explicitly"):
        runner_module.require_live_mutation_consent([])

    with pytest.raises(RuntimeError, match="STAGING_FAILURE_INJECTION_ACK=staging-only"):
        runner_module.require_live_mutation_consent(["--allow-live-staging-mutation"])


def test_live_mutation_rejects_any_nonfixed_target(runner_module, monkeypatch):
    monkeypatch.setenv("STAGING_FAILURE_INJECTION_ACK", "staging-only")
    monkeypatch.setattr(runner_module, "BASE_URL", "https://production.example.invalid")

    with pytest.raises(RuntimeError, match="fixed staging API URL"):
        runner_module.require_live_mutation_consent(["--allow-live-staging-mutation"])


def test_sanitize_dict_redacts_full_sensitive_values_without_token_fragments(runner_module):
    raw_token = "a-very-sensitive-token-value"
    sanitized = runner_module.sanitize_dict(
        {
            "claim_token": raw_token,
            "Authorization": "Bearer pipeline-secret",
            "nested": {"api-key": "key-value", "safe": "ok"},
        }
    )

    rendered = repr(sanitized)
    assert raw_token not in rendered
    assert "pipeline-secret" not in rendered
    assert "key-value" not in rendered
    assert sanitized["nested"]["safe"] == "ok"
    assert sanitized["claim_token"].startswith("[REDACTED sha256:")


def test_exception_after_claim_still_releases_tracked_lease(runner_module, monkeypatch):
    class Response:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((url, json))
        if url.endswith("/claims"):
            return Response(201, {"claim_token": "lease-token"})
        assert url.endswith("/claims/release")
        return Response(200, {"accepted": True})

    monkeypatch.setattr(runner_module.requests, "post", fake_post)
    runner = runner_module.StagingTestRunner("test-secret")

    with pytest.raises(RuntimeError, match="simulated assertion failure"):
        try:
            runner.post("source-schedule/claims", {"source_key": "brde"})
            raise RuntimeError("simulated assertion failure")
        finally:
            cleanup = runner.cleanup_active_claims()

    assert cleanup == [{"source_key": "brde", "status_code": 200, "accepted": True}]
    assert calls[-1][1]["outcome"] == "noop"


def test_expiry_reclaim_retires_old_token_without_cleanup_false_failure(runner_module, monkeypatch):
    class Response:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    claim_tokens = iter(["expired-token", "reclaimed-token"])

    def fake_post(url, *, json, headers, timeout):
        if url.endswith("/claims/renew"):
            return Response(409, {"detail": {"reason": "claim_expired"}})
        if url.endswith("/claims/release"):
            return Response(200, {"accepted": True})
        return Response(201, {"claim_token": next(claim_tokens)})

    monkeypatch.setattr(runner_module.requests, "post", fake_post)
    runner = runner_module.StagingTestRunner("test-secret")
    claim_payload = {"source_key": "bndes"}
    runner.post("source-schedule/claims", claim_payload)
    runner.post(
        "source-schedule/claims/renew",
        {"source_key": "bndes", "claim_token": "expired-token"},
    )
    runner.post("source-schedule/claims", claim_payload)
    runner.post(
        "source-schedule/claims/release",
        {"source_key": "bndes", "claim_token": "reclaimed-token"},
    )

    assert runner.cleanup_active_claims() == []


def test_main_returns_nonzero_when_cleanup_fails_after_passing_probes(
    runner_module, monkeypatch, tmp_path
):
    class FailedRunner:
        def __init__(self, secret):
            assert secret == "test-secret"

        @staticmethod
        def _result():
            return {"gate_passed": True}

        run_task_1_concurrency_limit = _result
        run_task_2_stale_owner_fencing = _result
        run_task_3_lease_expiry_and_renewal = _result

        @staticmethod
        def cleanup_active_claims():
            return [{"source_key": "brde", "status_code": 500, "accepted": False}]

    script_path = tmp_path / "repo" / "scripts" / "runner.py"
    script_path.parent.mkdir(parents=True)
    (tmp_path / "repo" / "docs" / "evidence").mkdir(parents=True)
    monkeypatch.setattr(runner_module, "Path", lambda _: script_path)
    monkeypatch.setattr(runner_module, "require_live_mutation_consent", lambda argv: None)
    monkeypatch.setattr(runner_module, "get_pipeline_secret", lambda: "test-secret")
    monkeypatch.setattr(runner_module, "StagingTestRunner", FailedRunner)

    assert runner_module.main() == 1


def test_main_returns_nonzero_when_a_probe_gate_fails(runner_module, monkeypatch, tmp_path):
    class FailedProbeRunner:
        def __init__(self, secret):
            assert secret == "test-secret"

        @staticmethod
        def _result():
            return {"gate_passed": False}

        run_task_1_concurrency_limit = _result
        run_task_2_stale_owner_fencing = _result
        run_task_3_lease_expiry_and_renewal = _result

        @staticmethod
        def cleanup_active_claims():
            return []

    script_path = tmp_path / "repo" / "scripts" / "runner.py"
    script_path.parent.mkdir(parents=True)
    (tmp_path / "repo" / "docs" / "evidence").mkdir(parents=True)
    monkeypatch.setattr(runner_module, "Path", lambda _: script_path)
    monkeypatch.setattr(runner_module, "require_live_mutation_consent", lambda argv: None)
    monkeypatch.setattr(runner_module, "get_pipeline_secret", lambda: "test-secret")
    monkeypatch.setattr(runner_module, "StagingTestRunner", FailedProbeRunner)

    assert runner_module.main() == 1


def test_main_cleans_up_when_a_probe_raises(runner_module, monkeypatch):
    cleanup_calls = []

    class ExplodingRunner:
        def __init__(self, secret):
            assert secret == "test-secret"

        @staticmethod
        def run_task_1_concurrency_limit():
            raise RuntimeError("simulated probe failure")

        @staticmethod
        def cleanup_active_claims():
            cleanup_calls.append(True)
            return []

    monkeypatch.setattr(runner_module, "require_live_mutation_consent", lambda argv: None)
    monkeypatch.setattr(runner_module, "get_pipeline_secret", lambda: "test-secret")
    monkeypatch.setattr(runner_module, "StagingTestRunner", ExplodingRunner)

    with pytest.raises(RuntimeError, match="simulated probe failure"):
        runner_module.main()

    assert cleanup_calls == [True]
