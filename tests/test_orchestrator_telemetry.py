"""Exercise real terminal reporting and fidelity verification without HTTP I/O."""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import discover_all_candidates as orchestrator
import source_run_reporting as reporting


def response(status_code, body):
    return SimpleNamespace(status_code=status_code, json=lambda: body)


@pytest.fixture
def run_environment(monkeypatch):
    with patch.dict(os.environ, {
        "SOURCES": "finep",
        "RENDER_APP_URL": "https://backend.example",
        "PIPELINE_SECRET": "test-secret",
        "SOURCE_RUN_REPORTING_ENABLED": "true",
    }, clear=True):
        monkeypatch.setattr(reporting, "_process_breaker", reporting._TelemetryCircuitBreaker())
        monkeypatch.setattr(orchestrator.pipeline_core, "make_default_ocr_extractor", lambda: (None, None))
        monkeypatch.setattr(orchestrator.pipeline_core, "process_opportunity", lambda item, **kwargs: item)
        yield


@pytest.fixture
def terminal_reports(monkeypatch):
    reports = []

    def capture(url, *, json, **kwargs):
        reports.append(json)
        return response(200, {"status": json["status"]})

    monkeypatch.setattr(reporting.requests, "patch", capture)
    monkeypatch.setattr(reporting.requests, "post", lambda *args, **kwargs: response(201, {"id": "run-id"}))
    return reports


def opportunity(record_id="42"):
    return {
        "source_key": "finep",
        "source_record_id": record_id,
        "canonical_url": f"https://example.com/{record_id}",
        "title": "Chamada",
        "authoritative_status": "open",
        "documents": [{"document_kind": "pdf", "is_renderable": True}],
    }


def use_opportunities(monkeypatch, items):
    discoverer = SimpleNamespace(discover_opportunities=lambda: ({"opportunities": len(items)}, items))
    monkeypatch.setattr(orchestrator, "load_discoverer", lambda source: discoverer)


@pytest.mark.parametrize("duplicate, expected_blockers", [(False, 0), (True, 4)])
def test_actual_fidelity_result_precedes_terminal_report(
    run_environment, terminal_reports, monkeypatch, tmp_path, duplicate, expected_blockers,
):
    monkeypatch.setenv("DISCOVERY_AUDIT_ONLY", "true")
    monkeypatch.setenv("DISCOVERY_AUDIT_DIR", str(tmp_path))
    items = [opportunity(), opportunity() if duplicate else opportunity("43")]
    use_opportunities(monkeypatch, items)
    submit = Mock(side_effect=AssertionError("audit must not submit"))
    monkeypatch.setattr(orchestrator.pipeline_core, "submit_opportunities", submit)

    assert orchestrator.main() == int(duplicate)

    summary = json.loads((tmp_path / "finep/fidelity/summary.json").read_text(encoding="utf-8"))
    assert summary["total_blocking_exceptions"] == expected_blockers
    assert len(terminal_reports) == 1
    assert terminal_reports[0]["fidelity_blockers"] == expected_blockers
    assert terminal_reports[0]["status"] == ("failed" if duplicate else "success")
    assert terminal_reports[0]["error_code"] == ("fidelity_violation" if duplicate else None)
    submit.assert_not_called()


def test_invalid_audit_does_not_reuse_stale_passing_summary(
    run_environment, terminal_reports, monkeypatch, tmp_path,
):
    monkeypatch.setenv("DISCOVERY_AUDIT_ONLY", "true")
    monkeypatch.setenv("DISCOVERY_AUDIT_DIR", str(tmp_path))
    use_opportunities(monkeypatch, [opportunity()])
    assert orchestrator.main() == 0
    terminal_reports.clear()
    original_write = orchestrator.write_opportunity_audit

    def write_invalid_artifacts(*args):
        original_write(*args)
        (tmp_path / "finep/discovery.json").write_text("not json", encoding="utf-8")

    monkeypatch.setattr(orchestrator, "write_opportunity_audit", write_invalid_artifacts)
    assert orchestrator.main() == 1
    assert len(terminal_reports) == 1
    assert terminal_reports[0]["status"] == "failed"
    assert terminal_reports[0]["fidelity_blockers"] > 0
    assert terminal_reports[0]["error_code"] == "fidelity_violation"


@pytest.mark.parametrize("accepted", [0, 1])
def test_real_opportunity_submission_failures_report_non_success(
    run_environment, terminal_reports, monkeypatch, accepted,
):
    use_opportunities(monkeypatch, [opportunity(), opportunity("43")])

    def post(url, *, json, **kwargs):
        if url.endswith("/source-runs"):
            return response(201, {"id": "run-id"})
        assert url.endswith("/opportunities")
        if accepted and json["source_record_id"] == "42":
            return response(200, {"outcome": "inserted"})
        return response(422, {"detail": "invalid submission"})

    monkeypatch.setattr(reporting.requests, "post", post)
    assert orchestrator.main() == 1
    assert len(terminal_reports) == 1
    report = terminal_reports[0]
    assert report["status"] == ("warning" if accepted else "failed")
    assert report["errors"] == 2 - accepted
    assert report["submitted"] == accepted
    assert report["inserted"] == accepted
    assert report["stats"]["submission_failures"] == 2 - accepted
    assert report["error_code"] == "submission_failed"


def test_candidate_submission_exception_is_failed_with_download_metrics(
    run_environment, terminal_reports, monkeypatch,
):
    monkeypatch.setenv("SOURCES", "bndes")
    candidate = {"url": "https://example.com/42.pdf", "worker_result": {"ocr_markdown": "text"}}
    discoverer = SimpleNamespace(discover_candidates=lambda: ({"candidates": 1}, [candidate]))
    monkeypatch.setattr(orchestrator, "load_discoverer", lambda source: discoverer)
    monkeypatch.setattr(orchestrator, "process_source_candidates", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(orchestrator.pipeline_core, "submit_candidates", Mock(side_effect=RuntimeError("submission error")))

    assert orchestrator.main() == 1
    assert len(terminal_reports) == 1
    report = terminal_reports[0]
    assert report["status"] == "failed"
    assert report["errors"] == 1
    assert report["error_code"] == "submission_failed"
    assert report["stats"]["submission_failures"] == 1
    assert report["documents_downloaded"] == 1
    assert report["ocr_succeeded"] == 1
