from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_breaker():
    import source_run_reporting as s
    s._process_breaker = s._TelemetryCircuitBreaker()


def response(status=200, body=None):
    r = MagicMock(); r.status_code = status; r.json.return_value = body if body is not None else {"status": "success"}; return r


def test_context_starts_and_finishes(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true")
    monkeypatch.setenv("RENDER_APP_URL", "https://backend")
    monkeypatch.setenv("PIPELINE_SECRET", "secret")
    with patch("source_run_reporting.requests.post", return_value=response(body={"id": "run-1"})) as post, patch("source_run_reporting.requests.patch", return_value=response()) as patch_call:
        from source_run_reporting import SourceRunReporter
        with SourceRunReporter("x"):
            pass
    post.assert_called_once(); patch_call.assert_called_once()


def test_exception_is_failed(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", return_value=response(body={"id": "r"})), patch("source_run_reporting.requests.patch", return_value=response(body={"status": "failed"})) as p:
        from source_run_reporting import SourceRunReporter
        with pytest.raises(RuntimeError):
            with SourceRunReporter("x"): raise RuntimeError("boom")
    assert p.call_args.kwargs["json"]["status"] == "failed"


def test_failed_intent_is_not_overwritten_after_delivery_failure(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    import requests
    with patch("source_run_reporting.requests.post", return_value=response(body={"id": "r"})), patch("source_run_reporting.requests.patch", side_effect=requests.ConnectionError) as p, patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter
        r = SourceRunReporter("x"); r.start(); r.complete("failed"); r.complete("success")
    assert p.call_count == 3 and r._terminal_status == "failed"


def test_start_retry_budget_and_delivery_attempt(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", side_effect=[__import__('requests').ConnectionError, response(body={"id": "r"})]) as post, patch("source_run_reporting.requests.patch", side_effect=__import__('requests').ConnectionError) as p, patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter
        r = SourceRunReporter("x"); r.start(); r.complete("failed"); r.complete("success")
    assert post.call_count == 2 and p.call_count == 3 and r._terminal_status == "failed"


def test_exit_does_not_redeliver_after_failed_complete(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", return_value=response(body={"id": "r"})), patch("source_run_reporting.requests.patch", side_effect=__import__('requests').ConnectionError) as p, patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter
        with SourceRunReporter("x") as r:
            r.complete("failed")
            count = p.call_count
    assert p.call_count == count


def test_warning_derivation_from_metrics(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    for kind in ("error", "fidelity"):
        with patch("source_run_reporting.requests.post", return_value=response(body={"id": "r"})), patch("source_run_reporting.requests.patch", return_value=response(body={"status": "warning"})) as p:
            from source_run_reporting import SourceRunReporter
            with SourceRunReporter("x") as r:
                (r.record_error("x") if kind == "error" else r.record_fidelity_blockers(1))
        assert p.call_args.kwargs["json"]["status"] == "warning"


def test_clean_exit_is_success(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", return_value=response(body={"id": "r"})), patch("source_run_reporting.requests.patch", return_value=response()) as p:
        from source_run_reporting import SourceRunReporter
        with SourceRunReporter("x"): pass
    assert p.call_args.kwargs["json"]["status"] == "success"


def test_invalid_json_is_not_retried_on_start(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    r = response(); r.json.side_effect = ValueError("bad json")
    with patch("source_run_reporting.requests.post", return_value=r) as post, patch("source_run_reporting.time.sleep") as sleep:
        from source_run_reporting import SourceRunReporter
        run = SourceRunReporter("x"); run.start()
    assert post.call_count == 1 and not sleep.called and run.telemetry_failed


def test_invalid_json_and_divergent_patch_are_not_retried(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    start = response(body={"id": "r"}); bad = response(); bad.json.side_effect = ValueError("bad")
    with patch("source_run_reporting.requests.post", return_value=start), patch("source_run_reporting.requests.patch", return_value=bad) as p, patch("source_run_reporting.time.sleep") as sleep:
        from source_run_reporting import SourceRunReporter
        run = SourceRunReporter("x"); run.start(); run.complete("success")
    assert p.call_count == 1 and not sleep.called and run.telemetry_failed

    divergent = response(body={"status": "warning"})
    with patch("source_run_reporting.requests.post", return_value=start), patch("source_run_reporting.requests.patch", return_value=divergent) as p:
        run = SourceRunReporter("y"); run.start(); run.complete("success")
    assert p.call_count == 1 and run.telemetry_failed
