"""Offline tests for the structured DOPA opportunity discoverer."""

import json
from datetime import datetime, timezone
from pathlib import Path

import discover_dopa_opportunities as dopa


FIXTURES = Path(__file__).parent / "fixtures" / "sources" / "dopa"
SNAPSHOT = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _search() -> list[dict]:
    return json.loads((FIXTURES / "search.json").read_text(encoding="utf-8"))


def _detail_open() -> dict:
    return json.loads((FIXTURES / "detail_open.json").read_text(encoding="utf-8"))


def test_incremental_search_filters_noise_year_scope_and_duplicates(monkeypatch):
    urls: list[str] = []

    def fetch_json(url: str):
        urls.append(url)
        if "/detalhes" in url:
            return _detail_open()
        return _search()

    monkeypatch.setattr(dopa, "DOPA_FETCH_BACKOFF_SECONDS", 0)
    stats, opportunities = dopa.discover_opportunities(
        fetch_json=fetch_json,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        min_year=2026,
        start_date="2026-08-19",
        end_date="2026-08-20",
    )

    assert "dataInicial=2026-08-19" in urls[0]
    assert "dataFinal=2026-08-20" in urls[0]
    assert "escopo=executivo" in urls[0]
    assert stats["records"] == 6
    assert stats["details_fetched"] == 1
    assert stats["duplicate_records"] == 1
    assert stats["year_rejected"] == 1
    assert stats["policy_rejected"] == 3
    assert stats["opportunities"] == 1
    assert opportunities[0]["source_record_id"] == "9001"


def test_detail_content_and_owned_attachments_are_normalized():
    record = _search()[0]
    opportunity = dopa.record_to_opportunity(
        record, _detail_open(), snapshot_at=SNAPSHOT, now=SNAPSHOT
    )

    assert opportunity is not None
    assert opportunity["source_key"] == "dopa"
    assert opportunity["source_record_id"] == "9001"
    assert opportunity["authoritative_status"] == "open"
    assert opportunity["application_deadline"] == "2026-10-01T02:59:59+00:00"
    assert opportunity["source_published_at"] == "2026-08-20T03:00:00+00:00"
    assert opportunity["source_updated_at"] is None
    assert len(opportunity["documents"]) == 2
    assert opportunity["documents"][0]["is_principal"] is True
    assert opportunity["documents"][1]["filename"].endswith(".pdf")
    assert "Resultado final" not in opportunity["source_markdown"]
    assert "<p>" not in opportunity["source_markdown"]


def test_post_act_procurement_and_closed_notice_are_rejected():
    assert not dopa.is_likely_opportunity("Resultado do Edital 1/2026")
    assert not dopa.is_likely_opportunity(
        "DLC - Abertura de Pregao Eletronico 1/2026"
    )
    for title in (
        "TORNA SEM EFEITO Edital de Chamamento Publico 003/2026",
        "EXTRATO DE TERMO DE CREDENCIAMENTO 004/2026",
        "CERTIFICADO DE CREDENCIAMENTO 006/2026",
        "EDITAL 097/2026 AVALIACAO DOS COTISTAS RACIAIS",
        "DESIGNA servidores para fiscalizar Contratos do Edital 003/2025",
        "CONTRATO 103823/2026 Credenciamento 010/2025",
    ):
        assert not dopa.is_likely_opportunity(title)
    closed_record = {
        "idConteudo": 9006,
        "tituloConteudo": "Edital 012/2026 - Chamada Publica",
        "dataConteudo": "19/08/2026",
        "tipo": "Executivo",
    }
    opportunity = dopa.record_to_opportunity(
        closed_record,
        json.loads((FIXTURES / "detail_closed.json").read_text(encoding="utf-8")),
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
    )
    assert opportunity is None


def test_search_failure_and_caps_are_visible(monkeypatch):
    monkeypatch.setattr(dopa, "DOPA_FETCH_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(dopa, "DOPA_MAX_SEARCH_RESULTS", 1)
    def fetch_json(url: str):
        return _detail_open() if "/detalhes" in url else _search()

    stats, opportunities = dopa.discover_opportunities(
        fetch_json=fetch_json, snapshot_at=SNAPSHOT, now=SNAPSHOT
    )
    assert stats["search_result_cap_reached"] == 1
    assert stats["records"] == 6
    assert stats["inventory_parse_failed"] == 1
    assert len(opportunities) == 1

    failed_stats, failed = dopa.discover_opportunities(
        fetch_json=lambda _url: (_ for _ in ()).throw(RuntimeError("offline")),
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
    )
    assert failed == []
    assert failed_stats["search_failures"] == 1
    assert failed_stats["errors"] == 1
    assert failed_stats["inventory_parse_failed"] == 1


def test_deadline_does_not_match_atendimento_or_prefer_law_date():
    assert dopa.extract_deadline(
        "Em atendimento a Lei 14.538, de 27/04/2026.",
        default_year=2026,
        now=SNAPSHOT,
    ) is None

    deadline = dopa.extract_deadline(
        "O contrato tera prazo maximo de 180 dias, conforme Lei 14.538, "
        "de 27/04/2026. A documentacao devera ser enviada ate o dia "
        "24/08/2026.",
        default_year=2026,
        now=SNAPSHOT,
    )
    assert deadline == "2026-08-25T02:59:59+00:00"

    assert dopa.extract_deadline(
        "O contrato tera prazo maximo de 180 dias, conforme Lei 14.538, "
        "de 27/04/2026.",
        default_year=2026,
        now=SNAPSHOT,
    ) is None


def test_iso_deadline_and_future_encerramento_are_open():
    deadline = dopa.extract_deadline(
        "Inscricoes abertas ate 2026-09-30.",
        default_year=2026,
        now=SNAPSHOT,
    )
    assert deadline == "2026-10-01T02:59:59+00:00"
    assert dopa._status_from_text(
        "Inscricoes abertas e serao encerradas na data informada.",
        deadline=deadline,
        now=SNAPSHOT,
    ) == "open"


def test_yearless_deadline_rolls_over_at_year_end():
    deadline = dopa.extract_deadline(
        "Inscricoes abertas ate 15/01.",
        default_year=2026,
        now=datetime(2026, 12, 20, tzinfo=timezone.utc),
    )
    assert deadline == "2027-01-16T02:59:59+00:00"


def test_default_window_uses_porto_alegre_calendar_date():
    start, end = dopa._window_dates(
        now=datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
        window_days=3,
    )
    assert start.isoformat() == "2026-08-17"
    assert end.isoformat() == "2026-08-19"


def test_detail_policy_rejects_later_acts_but_not_future_process_steps():
    record = {
        "idConteudo": 42,
        "tituloConteudo": "Edital 090/2026 - Concurso Publico",
        "dataConteudo": "20/08/2026",
        "tipo": "Executivo",
    }
    detail = {
        "protocolo": 42,
        "hierarquiaPoderSecao": "Executivo - Editais",
        "hierarquiaTipoConteudo": "Editais",
        "dataPublicacao": "20/08/2026",
        "textoConteudo": (
            "<p>EDITAL 090/2026</p><p>As Listas Preliminares de Inscritos "
            "constam no anexo.</p>"
        ),
        "anexos": [],
    }
    assert dopa.record_to_opportunity(
        record, detail, snapshot_at=SNAPSHOT, now=SNAPSHOT
    ) is None

    detail["textoConteudo"] = (
        "<p>EDITAL 090/2026 CONCURSO PUBLICO</p>"
        "<p>O Municipio torna publicos os gabaritos oficiais definitivos "
        "e o resultado provisorio nas provas objetivas.</p>"
    )
    assert dopa.record_to_opportunity(
        record, detail, snapshot_at=SNAPSHOT, now=SNAPSHOT
    ) is None

    detail["textoConteudo"] = (
        "<p>EDITAL DE ABERTURA 090/2026</p>"
        "<p>Inscricoes abertas ate 30/09/2026. Os aprovados serao "
        "objeto de convocacao posterior.</p>"
    )
    assert dopa.record_to_opportunity(
        record, detail, snapshot_at=SNAPSHOT, now=SNAPSHOT
    ) is not None


def test_bare_administrative_edital_is_not_an_opportunity():
    record = {
        "idConteudo": 623746,
        "tituloConteudo": "EDITAL TART 40864262",
        "dataConteudo": "18/08/2026",
        "tipo": "Executivo",
    }
    detail = {
        "protocolo": 623746,
        "hierarquiaPoderSecao": "Executivo - Documentos Oficiais",
        "hierarquiaTipoConteudo": "Documentos Oficiais",
        "dataPublicacao": "19/08/2026",
        "textoConteudo": (
            "<p>EDITAL TART 40864262</p><p>O Tribunal Administrativo "
            "torna publica a pauta da sessao de julgamento da Camara.</p>"
        ),
        "anexos": [],
    }
    assert dopa.record_to_opportunity(
        record, detail, snapshot_at=SNAPSHOT, now=SNAPSHOT
    ) is None


def test_detail_fetch_is_derived_from_id_and_attachments_are_host_bounded():
    record = dict(_search()[0])
    record["linkPaginaDetalhes"] = "https://attacker.example/private.json"
    detail = _detail_open()
    detail["anexos"].extend(
        [
            {"texto": "Anexo externo PDF", "url": "https://attacker.example/a.pdf"},
            {
                "texto": "Anexo oficial PDF",
                "url": "http://dopaonlineupload.procempa.com.br/extra.pdf",
            },
        ]
    )
    urls: list[str] = []

    def fetch_json(url: str):
        urls.append(url)
        return detail if "/detalhes" in url else [record]

    stats, opportunities = dopa.discover_opportunities(
        fetch_json=fetch_json,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        start_date="2026-08-20",
        end_date="2026-08-20",
    )

    assert urls[1] == dopa.DOPA_DETAIL_URL_TEMPLATE.format(id=9001)
    assert all("attacker.example" not in item["url"] for item in opportunities[0]["documents"])
    official = [
        item for item in opportunities[0]["documents"]
        if item["filename"] == "extra.pdf"
    ][0]
    assert official["url"].startswith("https://")
    assert official["source_document_id"].endswith(":extra.pdf")
    assert stats["attachment_rejected"] == 3


def test_detail_failure_marks_discovery_incomplete(monkeypatch):
    monkeypatch.setattr(dopa, "DOPA_FETCH_MAX_ATTEMPTS", 1)

    def fetch_json(url: str):
        if "/detalhes" in url:
            raise RuntimeError("detail unavailable")
        return [_search()[0]]

    stats, opportunities = dopa.discover_opportunities(
        fetch_json=fetch_json,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        start_date="2026-08-20",
        end_date="2026-08-20",
    )

    assert opportunities == []
    assert stats["detail_failures"] == 1
    assert stats["inventory_parse_failed"] == 1
