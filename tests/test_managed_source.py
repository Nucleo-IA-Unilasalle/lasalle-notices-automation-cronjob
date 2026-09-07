from unittest.mock import Mock

import pytest

import run_managed_source as managed
import durable_source_work as durable
import pipeline_core


def test_job_budget_accounts_for_setup_and_cleanup():
    assert managed.remaining_budget(1000, 1000) == 1080
    assert managed.remaining_budget(1300, 1000) == 780
    assert managed.remaining_budget(2300, 1000) == 0
    with pytest.raises(ValueError):
        managed.remaining_budget(999, 1000)


def test_partial_inventory_never_advances_checkpoint(monkeypatch):
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    assert not durable.register_collection("pncp", "candidate", [{"url": "https://example.com/a"}], {"detail_cap_reached": 1})
    assert client.work.call_count == 1
    assert "cursor" not in client.work.call_args.kwargs


def test_collection_commits_descriptors_before_cursor(monkeypatch):
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    assert durable.register_collection("demo", "candidate", [{"url": "https://example.com/a"}], {}, cursor={"page": 2})
    assert client.work.call_args_list[0].kwargs["items"]
    assert client.work.call_args_list[-1].kwargs["cursor"] == {"page": 2}


def test_exhausted_budget_does_not_take_or_initialize_ocr(monkeypatch):
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", "0")
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    extractor = Mock()
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor", extractor)
    reporter = Mock()
    reporter.metrics.stats = {}
    assert durable.drain("demo", reporter, {}) == 0
    client.work.assert_not_called()
    extractor.assert_not_called()
    assert reporter.metrics.stats["cap_reached"]


def test_submission_headers_fence_managed_workers(monkeypatch):
    monkeypatch.setenv("SOURCE_CLAIM_TOKEN", "secret-claim")
    assert pipeline_core.submission_headers("bearer")["X-Source-Claim"] == "secret-claim"


def test_claim_scope_matches_adapter_checkpoint_scope():
    """Cross-repo contract: the scope the client claims with must equal the
    scope its register/checkpoint calls use (scope_mismatch 409 otherwise).

    Both mappings must stay in sync: SOURCE_SCOPES (source_control.py, used
    at claim time by the supervisor) and scope_for_adapter (durable_source_work.py,
    used by register/checkpoint call sites). A drift here breaks every managed
    PNCP/Finep collection run against a v3 server.
    """
    import source_control

    for source in ("pncp", "finep", "bndes", "demo"):
        assert source_control.scope_for(source) == durable.scope_for_adapter(source), source
    assert source_control.scope_for("pncp") == durable.PNCP_SCOPE
    assert source_control.scope_for("finep") == durable.FINEP_SCOPE
    assert source_control.scope_for("bndes") == "default"


def test_claim_payload_carries_scope_and_purpose():
    import source_control

    captured = {}

    class _Control(source_control.SourceControl):
        def __init__(self, source):
            import os
            os.environ.setdefault("RENDER_APP_URL", "https://r.example.com")
            os.environ.setdefault("PIPELINE_SECRET", "tok")
            super().__init__(source)

        def post(self, path, payload):
            captured.update(path=path, payload=payload)
            return {"claim_token": "tok-" + "x" * 40}

    control = _Control("pncp")
    control.claim()
    assert captured["path"] == "source-schedule/claims"
    assert captured["payload"]["scope"] == "pncp-updates-v1"
    assert captured["payload"]["purpose"] == "collection"
    control2 = _Control("bndes")
    control2.claim(force=True)
    assert captured["payload"]["scope"] == "default"
    assert captured["payload"]["force"] is True


def test_drain_only_rejects_audit_combination(monkeypatch):
    import os
    from unittest.mock import patch
    import discover_all_candidates
    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": "bndes",
        "DISCOVERY_AUDIT_ONLY": "true",
        "DISCOVERY_AUDIT_DIR": "artifacts/test-audit",
        "SOURCE_DRAIN_ONLY": "true",
    }
    with patch.dict(os.environ, env, clear=True):
        assert discover_all_candidates.main() == 2


def test_drain_only_requires_work_enabled(monkeypatch):
    import os
    from unittest.mock import patch
    import discover_all_candidates
    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": "bndes",
        "SOURCE_DRAIN_ONLY": "true",
    }
    with patch.dict(os.environ, env, clear=True):
        assert discover_all_candidates.main() == 2


# --- Budget edge cases: process-tree cleanup, renewal uncertainty,
# --- ambiguous ACK, subprocess death, retries, ZIP caps, partial snapshots.
# --- The supervisor (run_managed_source) is the hard stop; the 420s
# --- preflight in durable_source_work only avoids starting doomed work.


def _drain_reporter():
    reporter = Mock()
    reporter.metrics.stats = {}
    return reporter


def _take_batch(items):
    return {"items": items, "backlog": {"pending": 0, "quarantined": 0}}


def test_stop_process_tree_is_noop_without_a_live_process():
    managed.stop_process_tree(None)
    process = Mock()
    process.poll.return_value = 3
    managed.stop_process_tree(process)
    process.wait.assert_not_called()


def test_stop_process_tree_kills_running_tree_and_waits(monkeypatch):
    import os as _os
    import subprocess as _sp

    kill_calls = []
    if _os.name == "nt":
        def _fake_run(*args, **kwargs):
            kill_calls.append((args, kwargs))
            return Mock(returncode=0)
        monkeypatch.setattr(_sp, "run", _fake_run)
    else:
        def _fake_killpg(pid, sig):
            kill_calls.append((pid, sig))
        monkeypatch.setattr(_os, "killpg", _fake_killpg)
    process = Mock()
    process.pid = 4242
    process.poll.return_value = None
    managed.stop_process_tree(process)
    assert kill_calls, "a running child must be killed, never orphaned"
    process.wait.assert_called_once()


def _managed_registry(monkeypatch):
    monkeypatch.setattr(
        managed, "load_registry",
        lambda: {"defaults": {"run_timeout_minutes": 20,
                              "application_budget_seconds": 1080,
                              "pdf_limit": 5}},
    )
    monkeypatch.setattr(
        managed, "validate_registry",
        lambda registry: [{"source_key": "bndes", "rollout_mode": "ingest",
                           "submission_contract": "candidate",
                           "filter_policy": "default"}],
    )


class _FakeControl:
    instances = []

    def __init__(self, source, token=None):
        self.source = source
        self.token = "test-claim-token-1234567890"
        self.renew_calls = 0
        self.released = []
        self.renew_error = None
        type(self).instances.append(self)

    def claim(self, force=False, purpose="collection"):
        return {"claim_token": self.token}

    def renew(self):
        self.renew_calls += 1
        if self.renew_error is not None:
            raise self.renew_error
        return {"ok": True}

    def release(self, outcome):
        self.released.append(outcome)
        return {"ok": True}


class _FakeProcess:
    def __init__(self, polls, returncode=0):
        self._polls = list(polls)
        self.returncode = returncode
        self.pid = 99999
        self.waited = False

    def poll(self):
        if self._polls:
            return self._polls.pop(0)
        return self.returncode

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


def _managed_env(monkeypatch, monotonic_values=None, sleeps=None):
    import subprocess as _sp
    import time as _time

    monkeypatch.setenv("SOURCE_JOB_STARTED_AT", str(_time.time()))
    monkeypatch.setenv("SOURCE_JOB_TIMEOUT_MINUTES", "20")
    monkeypatch.delenv("DISCOVERY_AUDIT_ONLY", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: Mock(returncode=0))
    if sleeps is not None:
        monkeypatch.setattr(_time, "sleep", sleeps)
    else:
        monkeypatch.setattr(_time, "sleep", lambda seconds: None)
    if monotonic_values is not None:
        state = {"n": 0}

        def _fake_monotonic():
            state["n"] += 1
            return monotonic_values(state["n"])

        monkeypatch.setattr(_time, "monotonic", _fake_monotonic)


def test_renewal_uncertainty_kills_tree_and_releases_failed(monkeypatch):
    _FakeControl.instances.clear()
    _managed_registry(monkeypatch)
    monkeypatch.setattr(managed, "SourceControl", _FakeControl)
    process = _FakeProcess(polls=[None, None])
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: process)
    _managed_env(monkeypatch, monotonic_values=lambda n: 1000.0 if n <= 4 else 1061.0)
    _FakeControl.renew_error = None

    original_renew = _FakeControl.renew

    def _flaky_renew(self):
        self.renew_calls += 1
        raise RuntimeError("lease renewal uncertain")

    monkeypatch.setattr(_FakeControl, "renew", _flaky_renew)
    try:
        result = managed.main(["--source", "bndes", "scripts/discover_all_candidates.py"])
    finally:
        monkeypatch.setattr(_FakeControl, "renew", original_renew)
    assert result == 1
    assert process.waited, "renewal uncertainty must kill the child tree"
    assert _FakeControl.instances and _FakeControl.instances[-1].released == ["failed"]


def test_subprocess_death_releases_failed_with_child_exit_code(monkeypatch):
    _FakeControl.instances.clear()
    _managed_registry(monkeypatch)
    monkeypatch.setattr(managed, "SourceControl", _FakeControl)
    process = _FakeProcess(polls=[3], returncode=3)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: process)
    _managed_env(monkeypatch)
    result = managed.main(["--source", "bndes", "scripts/discover_all_candidates.py"])
    assert result == 3
    assert _FakeControl.instances[-1].released == ["failed"]


def test_deadline_expiry_kills_tree_before_lease_expiry(monkeypatch):
    _FakeControl.instances.clear()
    _managed_registry(monkeypatch)
    monkeypatch.setattr(managed, "SourceControl", _FakeControl)
    process = _FakeProcess(polls=[None] * 10, returncode=0)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: process)
    _managed_env(monkeypatch, monotonic_values=lambda n: 1000.0 if n <= 3 else 3000.0)
    result = managed.main(["--source", "bndes", "scripts/discover_all_candidates.py"])
    assert result == 1
    assert process.waited, "deadline expiry must kill the child tree"
    assert _FakeControl.instances[-1].released == ["failed"]


def _drain_env(monkeypatch, deadline_offset=3600):
    import time as _time

    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", str(_time.time() + deadline_offset))


def test_ambiguous_ack_is_finished_failed_never_accepted(monkeypatch):
    _drain_env(monkeypatch)
    item = {"id": 7, "revision": 1, "contract": "candidate",
            "payload": {"url": "https://example.com/a.pdf"}}
    takes = [_take_batch([item]), _take_batch([])]
    finishes = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append((action, kwargs))
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_candidate",
                        lambda payload, **kwargs: {"worker_result": {"ok": True}})
    # Submitted count disagrees with the single drained item, and the backend
    # flags the row invalid: either signal alone must fail the ACK.
    monkeypatch.setattr(pipeline_core, "submit_candidates",
                        lambda candidates, **kwargs: {"submitted": 1,
                                                     "outcome_counts": {"invalid": 1},
                                                     "failed": 0, "failed_batches": 0})
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 1
    assert finishes[0][1]["outcome"] == "failed"
    assert finishes[0][1]["error_code"] == "submission_failed"


def test_submit_transport_error_is_ambiguous_and_retried_by_server(monkeypatch):
    _drain_env(monkeypatch)
    item = {"id": 8, "revision": 1, "contract": "candidate",
            "payload": {"url": "https://example.com/b.pdf"}}
    takes = [_take_batch([item]), _take_batch([])]
    finishes = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append((action, kwargs))
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_candidate",
                        lambda payload, **kwargs: {"worker_result": {"ok": True}})

    def _boom(candidates, **kwargs):
        raise RuntimeError("connection reset during ACK")

    monkeypatch.setattr(pipeline_core, "submit_candidates", _boom)
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 1
    assert finishes[0][1] == {"item_id": 8, "revision": 1,
                              "outcome": "failed", "error_code": "submission_failed"}


def test_download_and_ocr_failures_keep_distinct_error_codes(monkeypatch):
    _drain_env(monkeypatch)
    items = [{"id": 11, "revision": 1, "contract": "candidate",
              "payload": {"url": "https://example.com/missing.pdf"}},
             {"id": 12, "revision": 1, "contract": "candidate",
              "payload": {"url": "https://example.com/broken.pdf"}}]
    takes = [_take_batch([items[0]]), _take_batch([items[1]]), _take_batch([])]
    finishes = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))

    def _extract(payload, **kwargs):
        if "missing" in payload["url"]:
            return {"url": payload["url"], "metadata": {},
                    "error": "download: HTTP 404"}
        return {"url": payload["url"], "metadata": {},
                "error": "ocr: extractor crashed"}

    monkeypatch.setattr(pipeline_core, "process_candidate", _extract)
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 2
    assert finishes[0]["error_code"] == "download_failed"
    assert finishes[1]["error_code"] == "ocr_failed"


def test_cap_deferred_item_is_not_a_failure(monkeypatch):
    _drain_env(monkeypatch)
    item = {"id": 21, "revision": 1, "contract": "opportunity",
            "payload": {"source_key": "demo", "source_record_id": "1"}}
    takes = [_take_batch([item])]
    finishes = []
    submitted = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    stats = {}

    def _capped(opportunity, **kwargs):
        kwargs["stats"]["pdf_download_cap_reached"] = 1
        return {"documents": [{"validation_outcome": "download_cap_reached"}]}

    monkeypatch.setattr(pipeline_core, "process_opportunity", _capped)
    monkeypatch.setattr(pipeline_core, "submit_opportunities",
                        lambda opps: submitted.append(opps) or {"submitted": 1,
                                                               "outcome_counts": {}})
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, stats) == 0
    assert submitted == [], "cap-deferred work must stay pending, never submit"
    assert finishes[0]["outcome"] == "deferred"
    assert finishes[0]["error_code"] is None
    assert reporter.metrics.stats["cap_reached"] is True


def test_partial_attachment_snapshot_is_never_submitted(monkeypatch):
    _drain_env(monkeypatch)
    item = {"id": 31, "revision": 1, "contract": "opportunity",
            "payload": {"source_key": "demo", "source_record_id": "9"}}
    takes = [_take_batch([item]), _take_batch([])]
    finishes = []
    submitted = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_opportunity",
                        lambda opportunity, **kwargs: {"documents": [
                            {"validation_outcome": "pdf_validation_failed"}]})
    monkeypatch.setattr(pipeline_core, "submit_opportunities",
                        lambda opps: submitted.append(opps) or {"submitted": 1,
                                                               "outcome_counts": {}})
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 1
    assert submitted == [], "incomplete snapshots must not overwrite accepted documents"
    # Refined code (observation #3): partial attachment snapshots are no
    # longer conflated with candidate-path download failures.
    assert finishes[0] == {"item_id": 31, "revision": 1,
                           "outcome": "failed",
                           "error_code": "attachment_validation_failed"}


@pytest.mark.parametrize("outcome", [
    "pdf_validation_failed",          # PDF download or OCR failure
    "zip_validation_failed",          # archive download/inspection failure
    "docx_validation_failed",        # non-PDF attachment failure
    "attachment_validation_failed",  # unknown document_kind
])
def test_any_attachment_validation_failure_uses_the_refined_code(monkeypatch, outcome):
    """Every *_validation_failed attachment outcome — not only PDF download
    errors — refuses the partial snapshot and reports the refined code."""
    _drain_env(monkeypatch)
    item = {"id": 32, "revision": 1, "contract": "opportunity",
            "payload": {"source_key": "demo", "source_record_id": "10"}}
    takes = [_take_batch([item]), _take_batch([])]
    finishes = []
    submitted = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_opportunity",
                        lambda opportunity, **kwargs: {"documents": [
                            {"validation_outcome": outcome}]})
    monkeypatch.setattr(pipeline_core, "submit_opportunities",
                        lambda opps: submitted.append(opps) or {"submitted": 1,
                                                                "outcome_counts": {}})
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 1
    assert submitted == [], "incomplete snapshots must never be submitted"
    assert finishes[0]["outcome"] == "failed"
    assert finishes[0]["error_code"] == "attachment_validation_failed"


def test_opportunity_processing_exception_is_processing_failed(monkeypatch):
    """An unexpected processing exception is not labeled a download failure."""
    _drain_env(monkeypatch)
    item = {"id": 33, "revision": 1, "contract": "opportunity",
            "payload": {"source_key": "demo", "source_record_id": "11"}}
    takes = [_take_batch([item]), _take_batch([])]
    finishes = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))

    def _boom(opportunity, **kwargs):
        raise RuntimeError("unexpected extractor crash")

    monkeypatch.setattr(pipeline_core, "process_opportunity", _boom)
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 1
    assert finishes[0] == {"item_id": 33, "revision": 1,
                           "outcome": "failed", "error_code": "processing_failed"}


def test_drain_error_code_vocabulary_matches_repo_a_contract():
    """Cross-repo lock: every code the drain can finish with must be in
    Repo A's ``SourceWorkRequest.error_code`` Literal. An old server would 422
    the finish call and lose the item's retry state. ``worker_interrupted`` is
    server-side spool-only and excluded here.
    """
    import inspect
    import re as _re

    repo_a_codes = {
        "download_failed",
        "ocr_failed",
        "submission_failed",
        "budget_exhausted",
        "attachment_validation_failed",
        "processing_failed",
    }
    emitted = set()
    for _, function in inspect.getmembers(durable, inspect.isfunction):
        try:
            source_text = inspect.getsource(function)
        except OSError:
            continue
        # Only the drain finish tuples: ("failed", "<error_code>").
        for match in _re.finditer(r'\("failed",\s*"([a-z_]+)"\)', source_text):
            emitted.add(match.group(1))
    assert emitted, "the scan must find the drain's failure codes"
    assert emitted <= repo_a_codes, (
        f"codes emitted by the drain but not accepted by Repo A: {emitted - repo_a_codes}"
    )
    assert {"attachment_validation_failed", "processing_failed"} <= emitted


def test_failed_item_does_not_starve_next_item(monkeypatch):
    _drain_env(monkeypatch)
    takes = [_take_batch([{"id": 41, "revision": 1, "contract": "candidate",
                           "payload": {"url": "https://example.com/bad.pdf"}}]),
             _take_batch([{"id": 42, "revision": 1, "contract": "candidate",
                           "payload": {"url": "https://example.com/good.pdf"}}]),
             _take_batch([])]
    finishes = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_candidate",
                        lambda payload, **kwargs: (
                            {"url": payload["url"], "metadata": {},
                             "error": "download: HTTP 500"}
                            if "bad" in payload["url"]
                            else {"worker_result": {"ok": True}}))
    monkeypatch.setattr(pipeline_core, "submit_candidates",
                        lambda candidates, **kwargs: {"submitted": 1,
                                                     "outcome_counts": {"inserted": 1},
                                                     "failed": 0, "failed_batches": 0})
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 1
    assert [call["item_id"] for call in finishes] == [41, 42]
    assert finishes[0]["outcome"] == "failed"
    assert finishes[1]["outcome"] == "accepted"


def test_capped_listing_flags_never_advance_checkpoint(monkeypatch):
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    for stats in ({"search_result_cap_reached": 1}, {"partial_inventory": 1},
                  {"page_cap_reached": 1}, {"candidate_cap_reached": 1}):
        client.work.reset_mock()
        assert not durable.register_collection(
            "demo", "candidate", [{"url": "https://example.com/a"}], stats)
        assert client.work.call_count == 1
        assert "cursor" not in client.work.call_args.kwargs


# --- Fix 1: a lease expiry mid-drain must exit cleanly (code 1, one stderr
# --- line, no traceback) and must never leave the collection-success marker.


def _lease_conflict_client(reason="claim_expired", takes=1):
    """SourceControl mock whose take loop loses the lease after N takes."""
    from source_control import AdmissionConflict

    client = Mock()
    state = {"takes": 0}

    def _fake_work(action, **kwargs):
        if action == "take":
            state["takes"] += 1
            if state["takes"] > takes:
                raise AdmissionConflict(reason)
            return _take_batch([{"id": state["takes"], "revision": 1,
                                "contract": "candidate",
                                "payload": {"url": f"https://example.com/{state['takes']}.pdf"}}])
        return {"backlog": {}}

    client.work.side_effect = _fake_work
    return client


def _collection_work_mock(marker, conflict_reason):
    """Spool mock: register/finish succeed, take loses the lease.

    Registration advances the cursor (creating the real success marker) so the
    test proves the drain-abort path removes it afterwards.
    """
    from source_control import AdmissionConflict

    client = Mock()

    def _fake_work(action, **kwargs):
        if action == "register":
            cursor = kwargs.get("cursor")
            if cursor is not None and cursor.get("complete"):
                marker.touch()
            return {"backlog": {}}
        raise AdmissionConflict(conflict_reason)

    client.work.side_effect = _fake_work
    return client


def test_pncp_drain_only_lease_conflict_exits_clean(monkeypatch, tmp_path, capsys):
    import time as _time
    from unittest.mock import patch
    import discover_pncp_candidates

    marker = tmp_path / "collection-complete"
    marker.touch()
    monkeypatch.setenv("SOURCE_COLLECTION_COMPLETE_FILE", str(marker))
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", str(_time.time() + 3600))
    monkeypatch.setattr(durable, "SourceControl",
                        lambda source: _lease_conflict_client(takes=0))
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))

    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCE_WORK_ENABLED": "true",
        "SOURCE_DRAIN_ONLY": "true",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
    }
    with patch.dict("os.environ", env):
        assert discover_pncp_candidates.main() == 1
    err = capsys.readouterr().err
    assert "drain aborted: source lease expired mid-drain (claim_expired)" in err
    assert "Traceback" not in err
    assert not marker.exists(), "an aborted drain must not keep the success marker"


def test_pncp_managed_drain_lease_conflict_removes_success_marker(monkeypatch, tmp_path, capsys):
    from datetime import datetime, timezone
    from unittest.mock import patch
    import discover_pncp_candidates

    marker = tmp_path / "collection-complete"
    monkeypatch.setenv("SOURCE_COLLECTION_COMPLETE_FILE", str(marker))
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", str(__import__("time").time() + 3600))
    client = _collection_work_mock(marker, "claim_missing")
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)

    candidate = {"url": "https://example.com/edital.pdf", "kind": "pdf",
                 "metadata": {"numeroControlePNCP": "X-1", "sequencialDocumento": 1}}
    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCE_WORK_ENABLED": "true",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
    }
    with patch.dict("os.environ", env), patch(
        "discover_pncp_candidates.discover_candidates",
        return_value=({"records": 1, "candidates": 1}, [candidate],
                      datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)),
    ):
        assert discover_pncp_candidates.main() == 1
    err = capsys.readouterr().err
    assert "drain aborted: source lease expired mid-drain (claim_missing)" in err
    assert "Traceback" not in err
    assert marker.exists() is False, "an aborted drain must not keep the success marker"


def test_pncp_drain_non_lease_conflict_still_propagates(monkeypatch, tmp_path):
    from unittest.mock import patch
    from source_control import AdmissionConflict
    import discover_pncp_candidates

    marker = tmp_path / "collection-complete"
    monkeypatch.setenv("SOURCE_COLLECTION_COMPLETE_FILE", str(marker))
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", str(__import__("time").time() + 3600))
    client = Mock()
    client.work.side_effect = AdmissionConflict("work_conflict")
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)

    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCE_WORK_ENABLED": "true",
        "SOURCE_DRAIN_ONLY": "true",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
    }
    with patch.dict("os.environ", env):
        with pytest.raises(AdmissionConflict):
            discover_pncp_candidates.main()


def test_all_sources_drain_only_lease_conflict_exits_clean(monkeypatch, tmp_path, capsys):
    import time as _time
    from unittest.mock import patch
    import discover_all_candidates

    marker = tmp_path / "collection-complete"
    marker.touch()
    monkeypatch.setenv("SOURCE_COLLECTION_COMPLETE_FILE", str(marker))
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", str(_time.time() + 3600))
    monkeypatch.setattr(durable, "SourceControl",
                        lambda source: _lease_conflict_client(takes=0))
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))

    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": "bndes",
        "SOURCE_DRAIN_ONLY": "true",
        "SOURCE_WORK_ENABLED": "true",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
        "SOURCE_COLLECTION_COMPLETE_FILE": str(marker),
        "SOURCE_DEADLINE_EPOCH": str(_time.time() + 3600),
    }
    with patch.dict("os.environ", env, clear=True):
        assert discover_all_candidates.main() == 1
    err = capsys.readouterr().err
    assert "drain aborted: source lease expired mid-drain (claim_expired)" in err
    assert "Traceback" not in err
    assert not marker.exists(), "an aborted drain must not keep the success marker"


def test_all_sources_managed_drain_lease_conflict_fails_the_run(monkeypatch, tmp_path, capsys):
    import time as _time
    from unittest.mock import patch
    import discover_all_candidates

    marker = tmp_path / "collection-complete"
    monkeypatch.setenv("SOURCE_COLLECTION_COMPLETE_FILE", str(marker))
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", str(_time.time() + 3600))
    client = _collection_work_mock(marker, "claim_expired")
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)

    discoverer = Mock()
    discoverer.__dict__["discover_candidates"] = lambda **kwargs: ({"candidates": 1}, [])

    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": "bndes",
        "SOURCE_WORK_ENABLED": "true",
        "SOURCE_RUN_REPORTING_ENABLED": "false",
        "SOURCE_COLLECTION_COMPLETE_FILE": str(marker),
        "SOURCE_DEADLINE_EPOCH": str(_time.time() + 3600),
    }
    with patch.dict("os.environ", env, clear=True), patch(
        "discover_all_candidates.load_discoverer", return_value=discoverer,
    ):
        assert discover_all_candidates.main() == 1
    err = capsys.readouterr().err
    assert "drain aborted: source lease expired mid-drain (claim_expired)" in err
    assert "Traceback" not in err
    assert not marker.exists(), "an aborted drain must not keep the success marker"


# --- Fix 2: the candidate branch of drain() enforces the run-wide PDF cap
# --- exactly like the legacy loop (check before take/processing, record only
# --- on successful extraction, defer-and-stop at the cap).


def test_candidate_cap_reached_before_drain_takes_nothing(monkeypatch):
    _drain_env(monkeypatch)
    monkeypatch.setattr(pipeline_core, "SCRAPE_MAX_PDFS_PER_RUN", 5)
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    extractor = Mock()
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor", extractor)
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {"pdfs_downloaded": 5}) == 0
    client.work.assert_not_called()
    extractor.assert_not_called()
    assert reporter.metrics.stats["cap_reached"] is True


def test_candidate_cap_deferred_after_successful_item(monkeypatch):
    _drain_env(monkeypatch)
    monkeypatch.setattr(pipeline_core, "SCRAPE_MAX_PDFS_PER_RUN", 1)
    items = [{"id": 51, "revision": 1, "contract": "candidate",
              "payload": {"url": "https://example.com/first.pdf"}},
             {"id": 52, "revision": 1, "contract": "candidate",
              "payload": {"url": "https://example.com/second.pdf"}}]
    takes = [_take_batch([items[0]]), _take_batch([items[1]])]
    finishes = []
    submitted = []

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        finishes.append(kwargs)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_candidate",
                        lambda payload, **kwargs: {"worker_result": {"ok": True}})
    monkeypatch.setattr(pipeline_core, "submit_candidates",
                        lambda candidates, **kwargs: submitted.append(candidates) or {
                            "submitted": 1, "outcome_counts": {"inserted": 1},
                            "failed": 0, "failed_batches": 0})
    stats = {}
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, stats) == 0
    assert stats["pdfs_downloaded"] == 1, "only the successful extraction consumes the cap"
    assert [call["item_id"] for call in finishes] == [51, 52]
    assert finishes[0]["outcome"] == "accepted"
    assert finishes[1] == {"item_id": 52, "revision": 1,
                           "outcome": "deferred", "error_code": None}
    assert len(submitted) == 1, "the deferred candidate must never be submitted"
    assert reporter.metrics.stats["cap_reached"] is True
    assert client.work.call_count == 4, "drain stops after the deferred finish (no third take)"


def test_candidate_failed_download_does_not_consume_pdf_cap(monkeypatch):
    _drain_env(monkeypatch)
    monkeypatch.setattr(pipeline_core, "SCRAPE_MAX_PDFS_PER_RUN", 1)
    takes = [_take_batch([{"id": 61, "revision": 1, "contract": "candidate",
                           "payload": {"url": "https://example.com/broken.pdf"}}]),
             _take_batch([{"id": 62, "revision": 1, "contract": "candidate",
                           "payload": {"url": "https://example.com/good.pdf"}}]),
             _take_batch([])]

    def _fake_work(action, **kwargs):
        if action == "take":
            return takes.pop(0)
        return {"backlog": {}}

    client = Mock()
    client.work.side_effect = _fake_work
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor",
                        lambda: (object(), object()))
    monkeypatch.setattr(pipeline_core, "process_candidate",
                        lambda payload, **kwargs: (
                            {"url": payload["url"], "metadata": {},
                             "error": "download: HTTP 500"}
                            if "broken" in payload["url"]
                            else {"worker_result": {"ok": True}}))
    monkeypatch.setattr(pipeline_core, "submit_candidates",
                        lambda candidates, **kwargs: {"submitted": 1,
                                                      "outcome_counts": {"inserted": 1},
                                                      "failed": 0, "failed_batches": 0})
    stats = {}
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, stats) == 1
    assert stats["pdfs_downloaded"] == 1
    assert reporter.metrics.stats.get("cap_reached") is not True


def test_candidate_drain_deadline_preflight_is_unchanged(monkeypatch):
    # The deadline floor still fires before any take even when the PDF budget
    # is wide open, and still reports cap_reached (work remains) without
    # initializing OCR.
    monkeypatch.setenv("SOURCE_DEADLINE_EPOCH", "0")
    client = Mock()
    monkeypatch.setattr(durable, "SourceControl", lambda source: client)
    extractor = Mock()
    monkeypatch.setattr(pipeline_core, "make_default_ocr_extractor", extractor)
    reporter = _drain_reporter()
    assert durable.drain("demo", reporter, {}) == 0
    client.work.assert_not_called()
    extractor.assert_not_called()
    assert reporter.metrics.stats["cap_reached"] is True
