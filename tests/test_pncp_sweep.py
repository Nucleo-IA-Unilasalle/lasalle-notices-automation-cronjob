"""Multi-run simulation of the durable, resumable PNCP sweep.

A fake PNCP serves paginated streams and a fake SourceControl holds the stored
cursor, so each ``_main_impl`` call behaves like one scheduled run. The fake
control validates every cursor write with a copy of REPO_A's rules
(``validate_collection_cursor``), so a regression or an over-claim fails here
the way it would return HTTP 400/409 in production.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests

import discover_pncp_candidates as pncp
import durable_source_work as durable
import source_control
from source_run_reporting import SourceRunReporter


# --- copy of REPO_A app/services/source_work_service.py cursor rules ----------

def _cursor_time(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Collection cursor watermark must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return (1, value)
    return (0, parsed.isoformat())


class Conflict(Exception):
    pass


def backend_validate(cursor, previous):
    assert cursor.get("cursor_version") == 1
    assert cursor.get("adapter") == "pncp" and cursor.get("scope") == "pncp-updates-v1"
    _cursor_time(cursor.get("last_successful_update"))
    for field in ("records_enumerated", "records_registered", "document_lookups_completed",
                  "documents_selected", "search_pages_completed"):
        value = cursor.get(field)
        assert isinstance(value, int) and not isinstance(value, bool) and value >= 0, field
    for field in ("search_truncated", "complete"):
        assert isinstance(cursor.get(field), bool), field
    if previous is not None and previous.get("cursor_version") == 1:
        old_time = _cursor_time(previous.get("last_successful_update"))
        new_time = _cursor_time(cursor.get("last_successful_update"))
        if new_time < old_time:
            raise Conflict("cursor regressed behind stored watermark")
        if new_time == old_time:
            for field in ("records_registered", "document_lookups_completed",
                          "documents_selected", "search_pages_completed", "records_enumerated"):
                if cursor[field] < previous.get(field, 0):
                    raise Conflict("cursor regressed within its watermark cycle")


class FakeControl:
    """Fake SourceControl: one stored cursor and a spool keyed by identity."""

    def __init__(self):
        self.cursor = None
        self.spool = {}
        self.writes = []  # every accepted cursor write, in order
        self.fail_register_on_call = None  # 1-based register call that raises
        self.register_calls = 0

    def __call__(self, source):
        return self

    def work(self, action, **kwargs):
        if action == "checkpoint":
            return {"cursor": copy.deepcopy(self.cursor)}
        if action == "register":
            self.register_calls += 1
            if self.fail_register_on_call == self.register_calls:
                raise RuntimeError("registration ACK lost")
            for item in kwargs.get("items", []):
                meta = item["metadata"]
                self.spool[(meta["numeroControlePNCP"], meta["sequencialDocumento"])] = item
            cursor = kwargs.get("cursor")
            if cursor is not None:
                backend_validate(cursor, self.cursor)
                if cursor["records_registered"] > len(self.spool):
                    raise Conflict("cursor claims records beyond the registered spool")
                self.cursor = copy.deepcopy(cursor)
                self.writes.append(copy.deepcopy(cursor))
            return {}
        return {"items": []}


# --- fake PNCP ---------------------------------------------------------------

NOW = datetime.now(timezone.utc)


def make_record(n, *, modality=6, stamp="fresh"):
    stamps = {
        "fresh": (NOW - timedelta(minutes=30)).isoformat(),
        "stale": (NOW - timedelta(days=9)).isoformat(),
        None: None,
    }
    value = stamps[stamp]
    return {
        "numeroControlePNCP": f"CTRL-{n}",
        "anoCompra": 2026,
        "sequencialCompra": n,
        "modalidadeId": modality,
        "situacaoCompraId": 1,
        "dataEncerramentoProposta": (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "dataAberturaProposta": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "dataAtualizacaoGlobal": value,
        "dataAtualizacao": value,
        "dataPublicacaoPncp": value,
        "orgaoEntidade": {"cnpj": "11111111000100"},
        "unidadeOrgao": {"municipioNome": "Porto Alegre", "ufSigla": "RS"},
    }


class FakePncp:
    def __init__(self, dataset):
        self.dataset = dataset  # {(endpoint, modality|None): [records]}
        self.search_urls = []
        self.fail_search = lambda url: None  # url -> exception | None
        self.fail_documents = lambda record_seq: False

    def __call__(self, url, *, timeout=None):
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if "/arquivos" in parsed.path:
            seq = int(parsed.path.split("/")[-2])
            if self.fail_documents(seq):
                raise requests.ConnectionError("document list unavailable")
            return [{
                "sequencialDocumento": 1,
                "tipoDocumentoNome": "Edital",
                "titulo": "Edital",
                "url": f"https://pncp.gov.br/pncp-api/v1/orgaos/x/compras/2026/{seq}/arquivos/1",
            }]
        self.search_urls.append(url)
        error = self.fail_search(url)
        if error is not None:
            raise error
        endpoint = parsed.path.rsplit("/", 1)[-1]
        modality = query.get("codigoModalidadeContratacao")
        rows = self.dataset.get((endpoint, int(modality) if modality else None), [])
        page, size = int(query["pagina"]), int(query["tamanhoPagina"])
        total = -(-len(rows) // size)
        return {
            "data": rows[(page - 1) * size: page * size],
            "totalRegistros": len(rows),
            "totalPaginas": total,
        }


def default_dataset():
    r = {n: make_record(n, modality=6) for n in range(1, 6)}
    return {
        ("proposta", None): [make_record(7, modality=6)],
        ("publicacao", 6): [r[1], r[2], r[3], r[4], r[5]],
        ("atualizacao", 6): [r[1]],  # same control as the publicacao stream
        ("publicacao", 8): [make_record(6, modality=8)],
    }


class Harness:
    def __init__(self, monkeypatch, tmp_path, dataset=None, *, max_pages=2):
        self.control = FakeControl()
        self.pncp = FakePncp(dataset if dataset is not None else default_dataset())
        self.marker = tmp_path / "collection-complete"
        monkeypatch.setenv("SOURCE_WORK_ENABLED", "true")
        monkeypatch.setenv("RENDER_APP_URL", "https://example.com")
        monkeypatch.setenv("PIPELINE_SECRET", "test")
        monkeypatch.setenv("SOURCE_COLLECTION_COMPLETE_FILE", str(self.marker))
        monkeypatch.delenv("SOURCE_DRAIN_ONLY", raising=False)
        monkeypatch.setattr(pncp, "PNCP_OPPORTUNITY_V2_ENABLED", False)
        monkeypatch.setattr(pncp, "PNCP_PAGE_SIZE", 2)
        monkeypatch.setattr(pncp, "PNCP_PAGE_DELAY_SECONDS", 0.0)
        monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", max_pages)
        monkeypatch.setattr(pncp, "PNCP_MIN_NOTICE_YEAR", 2026)
        monkeypatch.setattr(pncp, "UF_FILTER", "RS")
        monkeypatch.setattr(pncp, "FEDERAL_CNPJS", ())
        monkeypatch.setattr(pncp, "fetch_json", self.pncp)
        monkeypatch.setattr(source_control, "SourceControl", self.control)
        monkeypatch.setattr(durable, "SourceControl", self.control)
        monkeypatch.setattr(durable, "drain", lambda *args: 0)

    def run(self):
        self.marker.unlink(missing_ok=True)
        self.pncp.search_urls = []
        reporter = SourceRunReporter(source_key="pncp")
        return pncp._main_impl(reporter), reporter

    def run_until_complete(self, limit=30):
        for _ in range(limit):
            self.run()
            if self.marker.exists():
                return
        raise AssertionError("sweep never completed")

    def pages(self):
        """(endpoint, modality, page) of every search request of the last run."""
        out = []
        for url in self.pncp.search_urls:
            parsed = urlparse(url)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            out.append((parsed.path.rsplit("/", 1)[-1],
                        query.get("codigoModalidadeContratacao"), int(query["pagina"])))
        return out


@pytest.fixture
def harness(monkeypatch, tmp_path):
    return Harness(monkeypatch, tmp_path)


def complete_cursor(stamp, **extra):
    return durable.build_pncp_cursor(
        last_successful_update=stamp, records_enumerated=3, records_registered=3,
        document_lookups_completed=3, documents_selected=3, search_pages_completed=4,
        complete=True, **extra)


# --- 1. capped run writes a progress cursor ----------------------------------

def test_capped_run_writes_progress_cursor_and_no_marker(harness):
    rc, reporter = harness.run()
    assert rc == 0
    assert reporter.metrics.stats["partial_inventory"] is True
    assert not harness.marker.exists()
    assert len(harness.control.writes) == 1
    cursor = harness.control.cursor
    assert cursor["complete"] is False
    assert cursor["last_complete_update"] is None
    sweep = cursor["sweep"]
    # proposta (1 page) and the first publicacao/6 page are done.
    assert (sweep["stream_index"], sweep["next_page"]) == (1, 2)
    assert sweep["version"] == 1 and sweep["skipped_records"] is False
    assert cursor["last_successful_update"] == sweep["started_at"]
    assert pncp._load_update_checkpoint() is None  # not a vouched watermark
    assert len(harness.control.spool) == 3  # CTRL-7, CTRL-1, CTRL-2


# --- 2. next run resumes at the stored stream/page ----------------------------

def test_next_run_resumes_without_refetching_earlier_pages(harness):
    harness.run()
    started = harness.control.cursor["sweep"]["started_at"]
    harness.run()
    assert harness.pages()[0] == ("publicacao", "6", 2)
    assert ("proposta", None, 1) not in harness.pages()
    assert ("publicacao", "6", 1) not in harness.pages()
    assert harness.control.cursor["sweep"]["started_at"] == started
    assert (harness.control.cursor["sweep"]["stream_index"],
            harness.control.cursor["sweep"]["next_page"]) == (2, 1)


# --- 3. repeated runs finish and write complete=True --------------------------

def test_repeated_runs_complete_with_started_at_watermark(harness):
    harness.run()
    started = harness.control.cursor["sweep"]["started_at"]
    harness.run_until_complete()
    final = harness.control.cursor
    assert final["complete"] is True
    assert final["last_successful_update"] == started
    assert "sweep" not in final and "last_complete_update" not in final
    assert harness.marker.exists()
    assert pncp._load_update_checkpoint() == datetime.fromisoformat(started)
    # Every record became a descriptor; the shared control number was deduped.
    assert {key[0] for key in harness.control.spool} == {f"CTRL-{n}" for n in range(1, 8)}
    # The watermark never regressed (the fake applies REPO_A's rule on write;
    # assert the sequence explicitly as well).
    keys = [_cursor_time(w["last_successful_update"]) for w in harness.control.writes]
    assert keys == sorted(keys)
    assert len(harness.control.writes) >= 5
    # The final run is uncapped: no cap flag when the last page finishes.
    stats_cap = [w["search_truncated"] for w in harness.control.writes]
    assert stats_cap[-1] is False and all(stats_cap[:-1])


# --- 4. 429 mid-stream keeps position and does not skip ------------------------

def test_rate_limit_keeps_position_without_skipping(harness, monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", 5)

    def limited(url):
        if "pagina=3" in url and "publicacao" in url and "codigoModalidadeContratacao=6" in url:
            response = requests.Response()
            response.status_code = 429
            return requests.HTTPError("rate limited", response=response)
        return None

    harness.pncp.fail_search = limited
    rc, reporter = harness.run()
    sweep = harness.control.cursor["sweep"]
    assert (sweep["stream_index"], sweep["next_page"]) == (1, 3)
    assert sweep["skipped_records"] is False
    assert reporter.metrics.stats["partial_inventory"] is True
    assert not harness.marker.exists()
    # Searching stopped at the 429: nothing after page 3 was requested.
    assert harness.pages()[-1] == ("publicacao", "6", 3)

    harness.pncp.fail_search = lambda url: None
    harness.run()
    assert harness.pages()[0] == ("publicacao", "6", 3)  # retried, not skipped


def test_rate_limit_with_no_candidates_keeps_advanced_pages(monkeypatch, tmp_path):
    # Pages advanced over records that yield no candidate must survive the
    # "search failed and produced no candidates" early return.
    empty = {("proposta", None): [], ("publicacao", 6): []}
    harness = Harness(monkeypatch, tmp_path, empty, max_pages=10)

    def limited(url):
        if "atualizacao" in url:
            response = requests.Response()
            response.status_code = 429
            return requests.HTTPError("rate limited", response=response)
        return None

    harness.pncp.fail_search = limited
    rc, _ = harness.run()
    assert rc == 1
    sweep = harness.control.cursor["sweep"]
    assert (sweep["stream_index"], sweep["next_page"]) == (2, 1)
    assert harness.control.cursor["complete"] is False


# --- 5. registration failure writes no cursor ---------------------------------

def test_registration_failure_writes_no_cursor(harness):
    harness.run()
    before = copy.deepcopy(harness.control.cursor)
    writes = len(harness.control.writes)
    harness.control.fail_register_on_call = harness.control.register_calls + 2
    rc, _ = harness.run()
    assert harness.control.cursor == before
    assert len(harness.control.writes) == writes
    assert not harness.marker.exists()
    harness.control.fail_register_on_call = None
    harness.run()  # resumes from the same stored position
    assert harness.pages()[0] == ("publicacao", "6", 2)


# --- 6. poison page is skipped on the third failure and blocks complete -------

def test_poison_page_is_skipped_on_third_failure_and_never_completes(harness, monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", 40)
    harness.pncp.fail_documents = lambda seq: seq == 3  # CTRL-3 sits on publicacao/6 page 2

    harness.run()
    for expected in (1, 2):
        sweep = harness.control.cursor["sweep"]
        assert (sweep["stream_index"], sweep["next_page"]) == (1, 2)
        assert sweep["page_failures"] == expected and sweep["skipped_records"] is False
        assert not harness.marker.exists()
        if expected == 1:
            harness.run()
    started = harness.control.cursor["sweep"]["started_at"]

    harness.run()  # third consecutive failure: skip the page and finish the sweep
    cursor = harness.control.cursor
    assert not harness.marker.exists()
    assert cursor["complete"] is False and "sweep" not in cursor
    assert cursor.get("last_complete_update") is None
    assert not any(w["complete"] for w in harness.control.writes)

    harness.run()  # a new sweep starts from the same (absent) prior watermark
    assert harness.control.cursor["sweep"]["started_at"] != started
    assert harness.pages()[0] == ("proposta", None, 1)


@pytest.mark.parametrize("payload", [
    {},
    {"message": "erro interno"},
    {"data": [], "totalRegistros": 0},
    {"data": [], "totalPaginas": "many"},
    {"data": None, "totalPaginas": 1},
])
def test_malformed_ok_response_is_a_failure_not_an_empty_page(harness, monkeypatch, payload):
    monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", 40)
    real = harness.pncp

    def serve(url, *, timeout=None):
        if "/publicacao" in url and "codigoModalidadeContratacao=6" in url and "pagina=2" in url:
            real.search_urls.append(url)
            return payload
        return real(url, timeout=timeout)

    monkeypatch.setattr(pncp, "fetch_json", serve)
    harness.run()
    sweep = harness.control.cursor["sweep"]
    assert (sweep["stream_index"], sweep["next_page"]) == (1, 2)
    assert sweep["page_failures"] == 1
    assert not harness.marker.exists()


def test_explicit_empty_envelope_finishes_the_stream(monkeypatch, tmp_path):
    harness = Harness(monkeypatch, tmp_path, {}, max_pages=40)
    rc, _ = harness.run()
    assert rc == 0
    assert harness.marker.exists()
    assert harness.control.cursor["complete"] is True


def test_shrunken_window_rewinds_so_shifted_rows_are_not_missed(monkeypatch, tmp_path):
    # Page size 2. Run 1 reads CTRL-1..4 and stops; CTRL-1 then closes, moving
    # CTRL-5 from page 3 onto the page already visited.
    rows = [make_record(n) for n in range(1, 7)]
    harness = Harness(monkeypatch, tmp_path, {("publicacao", 6): rows}, max_pages=3)
    harness.run()
    sweep = harness.control.cursor["sweep"]
    assert (sweep["stream_index"], sweep["next_page"]) == (1, 3)
    assert sweep["stream_total"] == 6
    del rows[0]

    harness.run_until_complete()
    assert {key[0] for key in harness.control.spool} == {f"CTRL-{n}" for n in range(1, 7)}


def test_rewind_does_not_charge_failures_to_another_page(monkeypatch, tmp_path):
    rows = [make_record(n) for n in range(1, 7)]
    harness = Harness(monkeypatch, tmp_path, {("publicacao", 6): rows}, max_pages=3)
    harness.run()  # stops at publicacao/6 page 3

    def page_3_down(url):
        return _http_error(400) if "publicacao" in url and "pagina=3" in url else None

    harness.pncp.fail_search = page_3_down
    harness.run()
    harness.run()
    assert harness.control.cursor["sweep"]["page_failures"] == 2
    harness.pncp.fail_search = lambda url: None
    del rows[0]
    harness.pncp.fail_documents = lambda seq: seq == 4  # CTRL-4 now sits on the rewound page
    harness.run()
    sweep = harness.control.cursor["sweep"]
    assert sweep["next_page"] == 2 and sweep["page_failures"] == 1
    assert sweep["skipped_records"] is False


def test_grown_window_does_not_rewind(monkeypatch, tmp_path):
    rows = [make_record(n) for n in range(1, 7)]
    harness = Harness(monkeypatch, tmp_path, {("publicacao", 6): rows}, max_pages=3)
    harness.run()
    rows.append(make_record(7))
    harness.run()
    assert harness.pages()[:2] == [("publicacao", "6", 3), ("publicacao", "6", 4)]


def test_each_sweep_moves_the_watermark_so_the_counter_floor_cannot_outlive_pruning(harness):
    stamp = (NOW - timedelta(days=40)).isoformat()
    harness.control.cursor = complete_cursor(stamp)
    harness.control.cursor["records_registered"] = 900
    harness.run()
    cursor = harness.control.cursor
    assert cursor["complete"] is False
    assert cursor["last_complete_update"] == stamp
    assert cursor["last_successful_update"] == cursor["sweep"]["started_at"]
    assert cursor["records_registered"] <= len(harness.control.spool)
    assert pncp._load_update_checkpoint() is None


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(str(status), response=response)


def _bad_publicacao_page_2(error):
    def fail(url):
        if "publicacao" in url and "codigoModalidadeContratacao=6" in url and "pagina=2" in url:
            return error
        return None
    return fail


def test_rejected_search_page_is_skipped_on_third_run_and_never_completes(harness, monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", 40)
    harness.pncp.fail_search = _bad_publicacao_page_2(_http_error(400))

    for expected in (1, 2):
        harness.run()
        sweep = harness.control.cursor["sweep"]
        assert (sweep["stream_index"], sweep["next_page"]) == (1, 2)
        assert sweep["page_failures"] == expected and sweep["skipped_records"] is False

    harness.run()
    sweep = harness.control.cursor["sweep"]
    assert (sweep["stream_index"], sweep["next_page"]) == (1, 3)
    assert sweep["page_failures"] == 0 and sweep["skipped_records"] is True

    harness.run()  # the rest of the sweep runs, but it may not be recorded complete
    assert not harness.marker.exists()
    assert not any(w["complete"] for w in harness.control.writes)


def test_outage_holds_the_search_page_longer_than_a_rejected_one(harness, monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", 40)
    harness.pncp.fail_search = _bad_publicacao_page_2(_http_error(503))

    for expected in range(1, pncp.PNCP_SWEEP_OUTAGE_FAILURE_LIMIT):
        harness.run()
        sweep = harness.control.cursor["sweep"]
        assert (sweep["stream_index"], sweep["next_page"]) == (1, 2)
        assert sweep["page_failures"] == expected and sweep["skipped_records"] is False

    harness.run()
    sweep = harness.control.cursor["sweep"]
    assert (sweep["stream_index"], sweep["next_page"]) == (1, 3)
    assert sweep["skipped_records"] is True


def test_outage_that_clears_resumes_the_page_without_a_skip(harness, monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_MAX_PAGES_PER_RUN", 40)
    harness.pncp.fail_search = _bad_publicacao_page_2(_http_error(503))
    harness.run()
    harness.pncp.fail_search = lambda url: None
    harness.run()
    assert harness.marker.exists()
    assert harness.control.cursor["complete"] is True


# --- 7. incremental mode -------------------------------------------------------

def test_incremental_sweep_skips_proposta_and_filters_overlap(monkeypatch, tmp_path):
    dataset = {
        ("publicacao", 6): [
            make_record(1, stamp="stale"),
            make_record(2, stamp="fresh"),
            make_record(3, stamp=None),
        ],
    }
    harness = Harness(monkeypatch, tmp_path, dataset, max_pages=40)
    watermark = (NOW - timedelta(days=3)).isoformat()
    harness.control.cursor = complete_cursor(watermark)

    rc, _ = harness.run()
    endpoints = {endpoint for endpoint, _, _ in harness.pages()}
    assert endpoints == {"publicacao", "atualizacao"}
    assert {key[0] for key in harness.control.spool} == {"CTRL-2", "CTRL-3"}
    first = parse_qs(urlparse(harness.pncp.search_urls[0]).query)
    brasilia = timezone(timedelta(hours=-3))
    expected_start = (datetime.fromisoformat(watermark).astimezone(brasilia).date()
                      - timedelta(days=1)).strftime("%Y%m%d")
    assert first["dataInicial"] == [expected_start]
    # 3 modalities x (publicacao, atualizacao); publicacao/6 spans two pages.
    assert len(harness.pages()) == 7
    assert ("proposta", None, 1) not in harness.pages()
    final = harness.control.cursor
    assert final["complete"] is True and harness.marker.exists()
    assert _cursor_time(final["last_successful_update"]) > _cursor_time(watermark)


# --- 8. stale sweep restarts ----------------------------------------------------

def test_stale_sweep_restarts_from_the_first_stream(harness):
    old_start = (NOW - timedelta(days=8)).isoformat()
    sweep = {
        "version": 1, "started_at": old_start, "window_start": "20260101",
        "window_end": "20260131", "stream_index": 3, "next_page": 2,
        "skipped_records": False, "page_failures": 0, "streams": 7,
    }
    harness.control.cursor = durable.build_pncp_cursor(
        last_successful_update=old_start, complete=False, sweep=sweep,
        last_complete_update=None)
    harness.run()
    assert harness.pages()[0] == ("proposta", None, 1)
    new_sweep = harness.control.cursor["sweep"]
    assert new_sweep["started_at"] != old_start
    # The restarted sweep moved the watermark forward, never back.
    assert harness.control.cursor["last_successful_update"] == new_sweep["started_at"]


def test_recent_sweep_is_resumed(harness):
    start = (NOW - timedelta(days=2)).isoformat()
    today = NOW.astimezone(timezone(timedelta(hours=-3))).date()
    sweep = {
        "version": 1, "started_at": start,
        "window_start": (today - timedelta(days=30)).strftime("%Y%m%d"),
        "window_end": today.strftime("%Y%m%d"), "stream_index": 3, "next_page": 1,
        "skipped_records": False, "page_failures": 0, "streams": 7,
    }
    harness.control.cursor = durable.build_pncp_cursor(
        last_successful_update=start, complete=False, sweep=sweep, last_complete_update=None)
    harness.run()
    assert harness.pages()[0] == ("publicacao", "8", 1)
    assert harness.control.cursor["sweep"]["started_at"] == start


# --- 9. legacy cursors start a fresh sweep ----------------------------------------

def test_versioned_cursor_without_sweep_starts_a_fresh_backfill(harness):
    harness.control.cursor = durable.build_pncp_cursor(
        last_successful_update=(NOW - timedelta(days=1)).isoformat(),
        records_enumerated=5, records_registered=0, complete=False)
    harness.run()
    assert harness.pages()[0] == ("proposta", None, 1)
    assert harness.control.cursor["last_complete_update"] is None
    assert harness.control.cursor["sweep"]["stream_index"] == 1


def test_bare_legacy_watermark_starts_a_fresh_incremental_sweep(harness):
    watermark = (NOW - timedelta(days=2)).isoformat()
    harness.control.cursor = {"last_successful_update": watermark}
    harness.run()
    assert {endpoint for endpoint, _, _ in harness.pages()} <= {"publicacao", "atualizacao"}
    assert harness.control.cursor["last_complete_update"] == watermark
    sweep = harness.control.cursor["sweep"]
    assert sweep["streams"] == 6 and (sweep["stream_index"], sweep["next_page"]) == (0, 3)


# --- contract edges ------------------------------------------------------------------

def test_register_collection_progress_cursor_needs_every_descriptor_acked():
    client = MagicMock()
    client.work.side_effect = [{}, RuntimeError("lost")]
    progress = {"complete": False}
    with patch.object(durable, "SourceControl", lambda source: client):
        assert not durable.register_collection(
            "pncp", "candidate", [{"url": "a"}, {"url": "b"}], {"page_cap_reached": 1},
            scope=durable.PNCP_SCOPE, progress_cursor=progress)
    assert all("cursor" not in c.kwargs for c in client.work.call_args_list)


def test_register_collection_progress_cursor_does_not_complete():
    client = MagicMock()
    with patch.object(durable, "SourceControl", lambda source: client):
        assert not durable.register_collection(
            "pncp", "candidate", [{"url": "a"}], {"page_cap_reached": 1},
            scope=durable.PNCP_SCOPE, progress_cursor={"complete": False})
    assert client.work.call_args.kwargs["cursor"] == {"complete": False}


def test_build_pncp_cursor_sweep_fields_only_for_incomplete_cursors():
    plain = durable.build_pncp_cursor(last_successful_update="x", complete=True)
    assert "sweep" not in plain and "last_complete_update" not in plain
    progress = durable.build_pncp_cursor(
        last_successful_update="x", sweep={"version": 1}, last_complete_update=None)
    assert progress["sweep"] == {"version": 1} and progress["last_complete_update"] is None


# --- sub-fixes ----------------------------------------------------------------------------

def test_fetch_json_caps_an_honoured_retry_after():
    limited = MagicMock(status_code=429, headers={"Retry-After": "3600"})
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"data": []}
    with patch("discover_pncp_candidates.requests.get", side_effect=[limited, ok]), \
            patch("discover_pncp_candidates.time.sleep") as sleep:
        pncp.fetch_json("https://pncp.gov.br/api/test")
    sleep.assert_called_once_with(60)


def test_fetch_json_treats_204_as_an_empty_window():
    empty = MagicMock(status_code=204)
    empty.json.side_effect = ValueError("no body")
    with patch("discover_pncp_candidates.requests.get", return_value=empty) as get:
        payload = pncp.fetch_json("https://pncp.gov.br/api/test")
    assert payload["data"] == [] and get.call_count == 1


def test_search_pages_pause_between_pages(monkeypatch):
    monkeypatch.setattr(pncp, "PNCP_PAGE_DELAY_SECONDS", 0.3)
    pages = [{"data": [], "totalPaginas": 2}, {"data": [], "totalPaginas": 2}]
    with patch("discover_pncp_candidates.fetch_json", side_effect=pages), \
            patch("discover_pncp_candidates.time.sleep") as sleep:
        pncp.fetch_pncp_search_pages("https://pncp.gov.br/api/test", {})
    sleep.assert_called_once_with(0.3)


def test_main_reports_scraping_failed_for_a_failed_run(monkeypatch):
    seen = {}

    class Reporter:
        telemetry_failed = False

        def __init__(self, source_key):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def record_error(self, code):
            seen["code"] = code

        def complete(self, outcome):
            seen["outcome"] = outcome

    monkeypatch.setattr(pncp, "SourceRunReporter", Reporter)
    monkeypatch.setattr(pncp, "_main_impl", lambda reporter: 1)
    assert pncp.main() == 1
    assert seen == {"code": "scraping_failed", "outcome": "failed"}
