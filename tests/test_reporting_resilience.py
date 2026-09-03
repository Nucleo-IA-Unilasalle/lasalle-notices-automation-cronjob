from unittest.mock import patch
import requests
import pytest

@pytest.fixture(autouse=True)
def reset_breaker():
    import source_run_reporting as s
    s._process_breaker = s._TelemetryCircuitBreaker()

def test_telemetry_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", side_effect=requests.ConnectionError), patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter
        r = SourceRunReporter("x"); r.start(); assert r.telemetry_failed

def test_breaker_skips_following_sources(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", side_effect=requests.ConnectionError) as post, patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter
        for i in range(4): SourceRunReporter(str(i)).start()
    assert post.call_count == 9
