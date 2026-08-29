from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import discover_ibama_candidates as ibama


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sources" / "ibama"
MAIN_URL = (
    "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/"
    "orientacoes-sobre-o-edital-de-chamamento-publico-no-22-2026-2013-"
    "credenciamento-de-projetos-para-recuperacao-de-vegetacao-nativa"
)
OSC_URL = "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/chamada-publica-para-osc-7-2026"
RESULT_URL = "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/resultado-do-edital-22-2026"
NOISE_URL = "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/webinario-tira-duvidas-sobre-edital-22-2026"
BRIGADISTA_URL = "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/prevfogo-ibama-abre-chamamento-publico-para-contratacao-de-brigadistas-florestais-de-logistica"


def _pages() -> dict[str, str]:
    pages = {
        ibama.IBAMA_CHAMAMENTOS_URL: "chamamentos.html",
        ibama.IBAMA_EDITAIS_URL: "editais.html",
        ibama.IBAMA_NOTAS_URL: "notas.html",
        ibama.IBAMA_CHAMAMENTOS_RSS_URL: "chamamentos_rss.xml",
        ibama.IBAMA_NOTAS_RSS_URL: "notas_rss.xml",
        MAIN_URL: "detail_reverdear.html",
        "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/orientacoes-sobre-o-edital-de-chamamento-publico-no-22-2026": "detail_reverdear.html",
        RESULT_URL: "detail_retificacao.html",
        OSC_URL: "detail_osc.html",
        NOISE_URL: "detail_noise.html",
        BRIGADISTA_URL: "detail_noise.html",
    }
    return {
        url: (FIXTURE_DIR / filename).read_text(encoding="utf-8")
        for url, filename in pages.items()
    }


def test_discovery_is_structured_and_merges_related_pages() -> None:
    pages = _pages()
    stats, opportunities = ibama.discover_opportunities(
        fetch_html=pages.__getitem__,
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        now=datetime(2026, 7, 23, tzinfo=ibama.SAO_PAULO),
    )

    assert stats["inventory_parse_failed"] == 0
    assert stats["opportunities"] == 2
    by_id = {item["source_record_id"]: item for item in opportunities}
    assert set(by_id) == {"edital-22-2026", "edital-7-2026"}

    reverdear = by_id["edital-22-2026"]
    assert reverdear["canonical_url"] == MAIN_URL
    assert reverdear["source_key"] == "ibama"
    assert reverdear["source_published_at"].endswith("-03:00")
    assert reverdear["source_updated_at"].endswith("-03:00")
    assert reverdear["proposal_opens_at"].startswith("2026-08-03")
    assert reverdear["application_deadline"].startswith("2026-09-08T23:59:59")
    assert reverdear["authoritative_status"] == "open"
    assert {doc["document_kind"] for doc in reverdear["documents"]} == {
        "pdf", "zip", "docx", "other",
    }
    ods = next(doc for doc in reverdear["documents"] if doc["filename"].endswith(".ods"))
    assert ods["mime_type"] == "application/vnd.oasis.opendocument.spreadsheet"
    assert any("retificacao_26" in doc["url"] for doc in reverdear["documents"])
    assert stats["retifications_merged"] >= 1
    assert stats["related_documents"] >= 3
    assert all(
        not doc["is_principal"]
        for doc in reverdear["documents"]
        if "anexo_" in doc["url"] or "retificacao_" in doc["url"]
    )
    assert "anexos_22_2026.zip (zip, relacionado)" in reverdear["source_markdown"]
    assert len({item["source_record_id"] for item in opportunities}) == 2


def test_identity_prefers_edital_number_and_uses_slug_fallback() -> None:
    assert ibama.source_record_id(
        "Edital de Chamamento Público nº 22/2026", MAIN_URL,
    ) == "edital-22-2026"
    assert ibama.source_record_id(
        "Retificação do Edital nº 26/2026 retifica o Edital nº 22/2026",
        RESULT_URL,
    ) == "edital-22-2026"
    assert ibama.source_record_id("Oportunidade ambiental", MAIN_URL) == "edital-22-2026"
    assert ibama.source_record_id(
        "Oportunidade ambiental", "https://www.gov.br/ibama/oportunidade-sem-numero",
    ) == "slug-oportunidade-sem-numero"
    assert ibama.source_record_id(
        "Processo SEI nº 02001.000123/2026-00", MAIN_URL,
    ) == "processo-02001-000123-2026-00"
    assert ibama.source_record_id(
        "Retificação", "https://www.gov.br/ibama/retificacao-edital-22-2026",
    ) == "edital-22-2026"
    assert ibama.source_record_id(
        "Edital publicado no dia 03/08/2026",
        "https://www.gov.br/ibama/oportunidade-sem-numero",
    ) == "slug-oportunidade-sem-numero"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.gov.br/ibama/x/anexo.pdf/view", "https://www.gov.br/ibama/x/anexo.pdf"),
        ("https://www.gov.br/ibama/x/anexo.pdf/@@download/file", "https://www.gov.br/ibama/x/anexo.pdf"),
        ("https://www.gov.br/ibama/x/@@download/file", "https://www.gov.br/ibama/x/@@download/file"),
    ],
)
def test_document_urls_are_normalized_without_destroying_download_endpoint(raw: str, expected: str) -> None:
    assert ibama.normalize_document_url(raw) == expected


def test_rss_parser_supports_rdf_and_keeps_dates() -> None:
    records, present = ibama.parse_rss_records(
        (FIXTURE_DIR / "chamamentos_rss.xml").read_text(encoding="utf-8"),
        ibama.IBAMA_CHAMAMENTOS_RSS_URL,
    )
    assert present is True
    assert records[0]["url"] == MAIN_URL
    assert records[0]["published_at"].endswith("+00:00")


def test_noise_and_pncp_are_rejected_deterministically() -> None:
    pages = _pages()
    noise = ibama.parse_detail(NOISE_URL, pages[NOISE_URL], fallback_title="Webinário edital")
    assert noise is None
    assert ibama._scope_disposition("Edital de licitação PNCP 12345678000190-1-000001/2026", "https://www.gov.br/x") == "pncp"
    assert ibama._scope_disposition("Prevfogo abre chamamento para brigadistas", BRIGADISTA_URL) == "out_of_scope"
    assert ibama._scope_disposition(
        "Edital de notificação nº 2/2026", "https://www.gov.br/ibama/notificacao",
    ) == "out_of_scope"
    assert ibama._scope_disposition(
        "Chamamento para brigadistas", "https://www.gov.br/ibama/chamada-ambiental",
    ) == "out_of_scope"
    assert ibama._scope_disposition(
        "Edital de doações patrimoniais", "https://www.gov.br/ibama/doacoes",
    ) == "out_of_scope"


def test_detail_body_enforces_pncp_and_administrative_exclusions() -> None:
    template = """
    <html><body><h1>{title}</h1><main>
      <p>{body}</p><a href="edital.pdf">Edital PDF</a>
    </main></body></html>
    """
    assert ibama.parse_detail(
        "https://www.gov.br/ibama/pt-br/chamada-ambiental",
        template.format(
            title="Chamamento ambiental nº 9/2026",
            body="O identificador de controle PNCP é 12345678000190-1-000001/2026.",
        ),
    ) is None
    assert ibama.parse_detail(
        "https://www.gov.br/ibama/pt-br/ato-administrativo",
        template.format(
            title="Edital ambiental nº 10/2026",
            body="Notificações administrativas aos interessados.",
        ),
    ) is None


def test_portuguese_month_deadline_and_expired_extension_status() -> None:
    description = (
        "A consulta recebe contribuições de 3 de agosto a 2 de setembro de 2026."
    )
    opens, deadline = ibama._extract_schedule(description, default_year=2026)
    assert opens == "2026-08-03T00:00:00-03:00"
    assert deadline == "2026-09-02T23:59:59-03:00"
    assert ibama._status(
        "Prazo prorrogado até 2 de setembro de 2026",
        deadline,
        datetime(2026, 9, 3, tzinfo=ibama.SAO_PAULO),
    ) == "closed"


def test_discovered_payload_matches_coordinated_repo_a_enums_and_keys() -> None:
    stats, opportunities = ibama.discover_opportunities(fetch_html=_pages().__getitem__)
    assert stats["inventory_parse_failed"] == 0
    opportunity_keys = {
        "source_key", "source_record_id", "source_kind", "opportunity_type",
        "canonical_url", "title", "description", "authoritative_status",
        "source_published_at", "source_updated_at", "proposal_opens_at",
        "application_deadline", "source_snapshot_at", "source_markdown",
        "source_content_hash", "documents",
    }
    document_keys = {
        "source_document_id", "document_kind", "url", "filename", "mime_type",
        "is_principal", "is_renderable",
    }
    assert all(set(item) == opportunity_keys for item in opportunities)
    assert {item["opportunity_type"] for item in opportunities} == {"other"}
    assert all(
        set(document) == document_keys
        for item in opportunities
        for document in item["documents"]
    )
    assert all(
        document["document_kind"] in {"pdf", "docx", "zip", "other"}
        for item in opportunities
        for document in item["documents"]
    )


def test_missing_feed_or_detail_is_an_explicit_partial_failure() -> None:
    pages = _pages()
    pages.pop(ibama.IBAMA_NOTAS_RSS_URL)
    stats, opportunities = ibama.discover_opportunities(fetch_html=pages.__getitem__)
    assert opportunities
    assert stats["errors"] >= 1
    assert stats["partial_inventory"] == 1
    assert stats["inventory_parse_failed"] == 1


def test_caps_are_reported_as_failed_partial_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = _pages()
    monkeypatch.setattr(ibama, "IBAMA_MAX_DETAILS_PER_RUN", 1)
    stats, opportunities = ibama.discover_opportunities(fetch_html=pages.__getitem__)
    assert len(opportunities) <= 1
    assert stats["cap_reached"] == 1
    assert stats["candidate_cap_reached"] == 1
    assert stats["inventory_parse_failed"] == 1


def test_rss_and_document_caps_are_explicit_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _pages()
    monkeypatch.setattr(ibama, "IBAMA_MAX_RSS_ITEMS", 1)
    stats, _ = ibama.discover_opportunities(fetch_html=pages.__getitem__)
    assert stats["cap_reached"] == 1
    assert stats["partial_inventory"] == 1
    assert stats["inventory_parse_failed"] == 1

    monkeypatch.setattr(ibama, "IBAMA_MAX_RSS_ITEMS", 250)
    monkeypatch.setattr(ibama, "IBAMA_MAX_DOCUMENTS_PER_OPPORTUNITY", 1)
    stats, opportunities = ibama.discover_opportunities(fetch_html=pages.__getitem__)
    assert stats["document_cap_reached"] == 1
    assert stats["inventory_parse_failed"] == 1
    assert all(len(item["documents"]) <= 1 for item in opportunities)
