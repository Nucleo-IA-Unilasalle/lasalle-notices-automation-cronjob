"""Cross-path regressions from the source reliability review."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import check_source_freshness as monitor
import discover_all_candidates as all_sources
import discover_finep_opportunities as finep
import discover_pncp_candidates as pncp
import durable_source_work as durable
import pipeline_core
import source_control
from source_run_reporting import SourceRunReporter


@pytest.mark.parametrize("partial", [{"page_cap_reached": 1}, {"detail_cap_reached": 1},
                                    {"document_failures": 1}, {}])
def test_pncp_only_complete_scan_writes_watermark(monkeypatch, partial):
    monkeypatch.setenv("SOURCE_WORK_ENABLED", "true")
    monkeypatch.setenv("RENDER_APP_URL", "https://example.com")
    monkeypatch.setenv("PIPELINE_SECRET", "test")
    monkeypatch.setattr(pncp, "PNCP_OPPORTUNITY_V2_ENABLED", False)
    monkeypatch.delenv("SOURCE_DRAIN_ONLY", raising=False)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(pncp, "discover_candidates", lambda: (
        {"records": 2, "candidates": 2, **partial},
        [{"url": "https://example.com/1.pdf"}, {"url": "https://example.com/2.pdf"}], now))
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(durable, "drain", lambda *args: 0)
    assert pncp._main_impl(SourceRunReporter(source_key="pncp")) == 0
    cursors = [c.kwargs["cursor"] for c in client.work.call_args_list if "cursor" in c.kwargs]
    assert len(cursors) == (0 if partial else 1)
    if cursors:
        assert cursors[0]["complete"] is True
        assert cursors[0]["last_successful_update"] == now.isoformat()
        assert cursors[0]["records_registered"] == 2


@pytest.mark.parametrize("complete", [False, True])
def test_pncp_does_not_resume_from_old_incomplete_watermark(monkeypatch, complete):
    monkeypatch.setenv("SOURCE_WORK_ENABLED", "true")
    stamp = "2026-09-01T12:00:00+00:00"
    client = Mock()
    client.work.return_value = {"cursor": durable.build_pncp_cursor(
        last_successful_update=stamp, complete=complete)}
    monkeypatch.setattr(source_control, "SourceControl", lambda source: client)
    assert pncp._load_update_checkpoint() == (datetime.fromisoformat(stamp) if complete else None)


def test_pncp_candidate_lookup_cap_marks_partial(monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN", 1)
    monkeypatch.setattr(pncp, "fetch_pncp_records", lambda **kw: ([{}, {}], None))
    monkeypatch.setattr(pncp, "validate_pncp_record_for_download", lambda record: True)
    monkeypatch.setattr(pncp, "fetch_pncp_documents", lambda record: ([], False))
    stats, _, _ = pncp.discover_candidates()
    assert stats["detail_cap_reached"] == 1


def test_registration_failure_preserves_completed_checkpoint(monkeypatch):
    client = Mock()
    client.work.side_effect = [{}, RuntimeError("registration ACK lost")]
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    assert not durable.register_collection(
        "pncp", "candidate", [{"url": "a"}, {"url": "b"}], {}, scope=durable.PNCP_SCOPE,
        cursor_builder=lambda n, complete: {"complete": True} if complete else None)
    assert all("cursor" not in c.kwargs for c in client.work.call_args_list)


@pytest.mark.parametrize("cap_kind", ["page", "candidate"])
def test_finep_caps_prevent_complete_checkpoint(monkeypatch, cap_kind):
    monkeypatch.setattr(finep, "FINEP_MAX_PAGES_PER_RUN", 1)
    monkeypatch.setattr(finep, "FINEP_MAX_OPPORTUNITIES_PER_RUN", 1 if cap_kind == "candidate" else 10)
    records = [{"id": str(n), "titulo": "Call", "situacao": "aberta"} for n in range(1, 3)]
    stats, opportunities = finep.discover_opportunities(fetch_json=lambda url: {
        "items": records, "lastPage": 2 if cap_kind == "page" else 1})
    assert stats[f"{cap_kind}_cap_reached"] == 1
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    assert not durable.register_collection("finep", "opportunity", opportunities, stats, scope=durable.FINEP_SCOPE)
    assert all("cursor" not in c.kwargs for c in client.work.call_args_list)


@pytest.mark.parametrize("last_page,partial", [(1, False), (2, True)])
def test_finep_orchestrator_emits_adapter_cursor(monkeypatch, last_page, partial):
    for key, value in {"SOURCES": "finep", "SOURCE_WORK_ENABLED": "true",
                       "RENDER_APP_URL": "https://example.com", "PIPELINE_SECRET": "test",
                       "SOURCE_RUN_REPORTING_ENABLED": "false", "DISCOVERY_AUDIT_ONLY": "false"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SOURCE_DRAIN_ONLY", raising=False)
    stats = {"records": 1, "opportunities": 1, "finep_pages_completed": [1],
             "finep_last_page": last_page, "finep_page_size": 20}
    discoverer = SimpleNamespace(discover_opportunities=lambda **kw: (
        stats, [{"source_record_id": "1", "source_key": "finep", "documents": []}]))
    monkeypatch.setattr(all_sources, "load_discoverer", lambda source: discoverer)
    monkeypatch.setattr(all_sources, "write_opportunity_audit", lambda *args: None)
    monkeypatch.setattr(durable, "drain", lambda *args: 0)
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    assert all_sources.main() == 0
    cursors = [c.kwargs["cursor"] for c in client.work.call_args_list if "cursor" in c.kwargs]
    assert len(cursors) == (0 if partial else 1)
    if cursors:
        assert cursors[0] == durable.build_finep_cursor(
            pages_completed=[1], last_page=1, page_size=20, records_enumerated=1,
            records_registered=1, complete=True, cycle_started_at=cursors[0]["cycle_started_at"])


@pytest.mark.parametrize("contract", ["candidate", "opportunity"])
@pytest.mark.parametrize("error", [None, "download: failed", "ocr: failed", "submission"])
def test_drain_reports_processing_and_submission(monkeypatch, contract, error):
    monkeypatch.setattr(durable, "remaining_drain_seconds", lambda: 1000)
    monkeypatch.setattr(pipeline_core, "SCRAPE_MAX_PDFS_PER_RUN", 5)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor", lambda: (None, None))
    result = {"worker_result": {"content_hash": "a" * 64, "content_length": 10,
                               "validated_at": "2026-09-01T12:00:00Z", "ocr_markdown": "text"}}
    if error in {"download: failed", "ocr: failed"}:
        result = {"error": error}
    monkeypatch.setattr(pipeline_core, "process_candidate", lambda *a, **kw: result)
    submit = Mock(return_value={"submitted": 1, "outcome_counts": {"inserted": 1}})
    if error == "submission":
        submit.side_effect = RuntimeError("ambiguous ACK")
    monkeypatch.setattr(pipeline_core, "submit_candidates", submit)
    monkeypatch.setattr(pipeline_core, "submit_opportunities", submit)
    client = Mock()
    payload = {"url": "https://example.com/a.pdf", "documents": [
        {"url": "https://example.com/a.pdf", "document_kind": "pdf"}]}
    client.work.side_effect = [{"items": [{"id": 1, "revision": 1, "contract": contract,
                                          "payload": payload}]}, {}, {"items": []}]
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    reporter = SourceRunReporter(source_key="bndes")
    assert durable.drain("bndes", reporter, {}) == int(error is not None)
    metrics = reporter.metrics
    assert metrics.documents_downloaded == int(error != "download: failed")
    assert metrics.ocr_succeeded == int(error in {None, "submission"})
    assert metrics.inserted == metrics.submitted == int(error is None)
    assert metrics.errors == int(error is not None)
    for key, expected in {"download_failures": error == "download: failed",
                          "ocr_failures": error == "ocr: failed",
                          "submission_failures": error == "submission"}.items():
        assert metrics.stats.get(key, 0) == int(expected)


@pytest.mark.parametrize("health", ["healthy", "failing", "warning", "stale", "checking", None])
def test_recent_failed_sources_are_not_monitor_healthy(monkeypatch, tmp_path, health):
    monkeypatch.setenv("RENDER_APP_URL", "https://example.com")
    monkeypatch.setenv("PIPELINE_SECRET", "test")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["monitor", "--output", str(output)])
    expected = [s["source_key"] for s in json.loads(monitor.REGISTRY_PATH.read_text())["sources"]
                if s["rollout_mode"] != "paused"]
    response = Mock()
    response.json.return_value = {"items": [{"source_key": key, "health_status": health,
        "last_checked_at": datetime.now(timezone.utc).isoformat()} for key in expected]}
    monkeypatch.setattr(monitor.requests, "get", lambda *a, **kw: response)
    assert monitor.main() == int(health != "healthy")
    report = json.loads(output.read_text())
    assert report["healthy"] == (expected if health == "healthy" else [])
    assert report["unhealthy"] == ([] if health == "healthy" else expected)
