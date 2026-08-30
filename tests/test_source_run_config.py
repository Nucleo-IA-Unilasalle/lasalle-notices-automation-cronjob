import os
import re
import pytest

def test_local_identity_and_trigger(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    from source_run_reporting import SourceRunReporter
    r = SourceRunReporter("x"); assert r.trigger_kind == "local" and re.fullmatch(r"local:[0-9a-f-]{36}", r.external_run_id)

def test_github_identity_is_bounded(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123"); monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
    from source_run_reporting import SourceRunReporter
    r = SourceRunReporter("x"); assert re.fullmatch(r"github:[0-9a-f]{64}", r.external_run_id) and len(r.external_run_id) < 160

def test_dispatch_is_manual(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1"); monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    from source_run_reporting import SourceRunReporter
    assert SourceRunReporter("x").trigger_kind == "manual"

def test_github_non_dispatch_is_schedule(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1"); monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    from source_run_reporting import SourceRunReporter
    assert SourceRunReporter("x").trigger_kind == "schedule"

def test_explicit_trigger_override(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1"); monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    from source_run_reporting import SourceRunReporter
    assert SourceRunReporter("x", trigger_kind="backfill").trigger_kind == "backfill"

@pytest.mark.parametrize("missing", ["RENDER_APP_URL", "PIPELINE_SECRET"])
def test_enabled_without_credentials_never_posts(monkeypatch, missing):
    from unittest.mock import patch
    monkeypatch.setenv("SOURCE_RUN_REPORTING_ENABLED", "true")
    monkeypatch.setenv("RENDER_APP_URL", "https://b"); monkeypatch.setenv("PIPELINE_SECRET", "s")
    monkeypatch.delenv(missing, raising=False)
    from source_run_reporting import SourceRunReporter
    with patch("source_run_reporting.requests.post") as post:
        run = SourceRunReporter("x"); run.start()
    assert run.telemetry_failed and not post.called
