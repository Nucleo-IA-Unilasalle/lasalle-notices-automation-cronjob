from unittest.mock import MagicMock, patch, call
import requests
import pytest

@pytest.fixture(autouse=True)
def breaker():
    import source_run_reporting as s
    s._process_breaker = s._TelemetryCircuitBreaker()

def test_three_exhausted_deliveries_open_breaker(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    with patch("source_run_reporting.requests.post", side_effect=requests.ConnectionError), patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter, _process_breaker
        for i in range(3): SourceRunReporter(str(i)).start()
        assert _process_breaker.open
        SourceRunReporter("fourth").start()

def test_definitive_response_resets_streak(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    r = MagicMock(); r.status_code = 404
    with patch("source_run_reporting.requests.post", return_value=r), patch("source_run_reporting.time.sleep"):
        from source_run_reporting import SourceRunReporter, _process_breaker
        _process_breaker.consecutive_failures = 2; SourceRunReporter("x").start(); assert _process_breaker.consecutive_failures == 0

@pytest.mark.parametrize("status", [401, 403, 404, 409, 422])
def test_definitive_status_is_not_retried_or_counted(monkeypatch, status):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    r = MagicMock(status_code=status)
    with patch("source_run_reporting.requests.post", return_value=r) as post:
        from source_run_reporting import SourceRunReporter, _process_breaker
        SourceRunReporter("x").start()
    assert post.call_count == 1 and _process_breaker.consecutive_failures == 0

def test_three_definitive_failures_do_not_trip_breaker(monkeypatch):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    r = MagicMock(status_code=422)
    with patch("source_run_reporting.requests.post", return_value=r) as post:
        from source_run_reporting import SourceRunReporter, _process_breaker
        for n in range(3): SourceRunReporter(str(n)).start()
    assert post.call_count == 3 and not _process_breaker.open

def test_record_available_cannot_close_tripped_breaker():
    from source_run_reporting import _TelemetryCircuitBreaker
    b = _TelemetryCircuitBreaker(); b.tripped = True; b.record_available()
    assert b.open

@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_backoff_and_breaker_count(monkeypatch, status):
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true"); monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    r = MagicMock(status_code=status)
    with patch("source_run_reporting.requests.post", return_value=r) as post, patch("source_run_reporting.time.sleep") as sleep:
        from source_run_reporting import SourceRunReporter, _process_breaker
        SourceRunReporter("x").start()
    assert post.call_count == 3 and sleep.call_args_list == [call(2), call(4)]
    assert _process_breaker.consecutive_failures == 1
