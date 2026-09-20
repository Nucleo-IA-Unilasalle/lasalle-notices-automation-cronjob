from datetime import datetime, timezone
from pathlib import Path

import discover_fbds_opportunities as fbds


FIXTURES = Path(__file__).parent / "fixtures" / "sources" / "fbds"


def test_listing_and_detail_create_stable_zip_backed_opportunity():
    listing = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    detail = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    pages = {fbds.FBDS_LISTING_URL: listing}
    records = fbds.extract_fbds_records(listing, fbds.FBDS_LISTING_URL)
    pages[records[0]["canonical_url"]] = detail
    stats, opportunities = fbds.discover_opportunities(
        fetch_html=pages.__getitem__,
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert stats["opportunities"] == 1
    opportunity = opportunities[0]
    assert opportunity["source_record_id"] == "24"
    assert opportunity["application_deadline"].startswith("2026-09-30")
    assert [item["document_kind"] for item in opportunity["documents"]] == [
        "pdf",
        "zip",
    ]
    assert all(not item["is_renderable"] for item in opportunity["documents"])


def test_footer_documents_are_not_attributed_to_record():
    record = {
        "source_record_id": "24",
        "canonical_url": "https://restaura-amazonia.fbds.org.br/record-24",
        "title": "Edital 24",
    }
    detail = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    opportunity = fbds.parse_fbds_detail(record, detail)
    assert not any("relatorio.pdf" in item["url"] for item in opportunity["documents"])


def test_missing_listing_content_fails_audit_visibly():
    stats, opportunities = fbds.discover_opportunities(
        fetch_html=lambda _url: "<html><body><footer>Editais</footer></body></html>"
    )
    assert opportunities == []
    assert stats["inventory_parse_failed"] == 1


def test_current_spip_principal_section_is_supported():
    listing = """
    <html><body><section id="Principal">
      <a href="Apoio-a-Restauracao-Ecologica-24">Informacoes completas</a>
    </section><footer><a href="/relatorio.pdf">Relatorio</a></footer></body></html>
    """
    detail = """
    <html><body><section id="Principal">
      <h1>Edital 004/2026</h1><p>Aberto. Prazo: 30/09/2026.</p>
      <a href="/arquivos/edital.zip">Edital completo</a>
    </section></body></html>
    """
    records = fbds.extract_fbds_records(listing, fbds.FBDS_LISTING_URL)
    opportunity = fbds.parse_fbds_detail(records[0], detail)
    assert records[0]["source_record_id"] == "24"
    assert opportunity["documents"][0]["document_kind"] == "zip"


def test_concluido_badge_is_closed_not_unknown():
    detail = """
    <html><body><section id="Principal">
      <div class="button is-small is-uppercase">Edital 004/2025 - Unidades de Conservacao
        <b>Concluído</b>
      </div>
      <h1>Apoio a Restauracao</h1>
      <p>Submissão das propostas até as 18:00 (horário de Brasília) do dia 10/11/2025.</p>
      <a id="Download" href="/IMG/zip/edital.zip">Baixe o edital</a>
    </section></body></html>
    """
    record = {
        "source_record_id": "24",
        "canonical_url": "https://restaura-amazonia.fbds.org.br/record-24",
        "title": "Edital 004/2025",
    }
    opportunity = fbds.parse_fbds_detail(record, detail)
    assert opportunity["authoritative_status"] == "closed"
    assert opportunity["application_deadline"] == "2025-11-10T18:00:00-03:00"
    assert opportunity["documents"][0]["is_principal"] is True


def test_body_open_mention_does_not_override_concluido_badge():
    detail = """
    <html><body><section id="Principal">
      <div class="button is-small is-uppercase">Edital 002/2025 <b>Concluído</b></div>
      <h1>Apoio a Restauracao</h1>
      <p>Nota: está aberto um edital com foco em Terras Indígenas (Edital 003).</p>
    </section></body></html>
    """
    record = {
        "source_record_id": "e",
        "canonical_url": "https://restaura-amazonia.fbds.org.br/record-e",
        "title": "Edital 002/2025",
    }
    opportunity = fbds.parse_fbds_detail(record, detail)
    assert opportunity["authoritative_status"] == "closed"


def test_status_text_fallback_normalizes_to_open_closed():
    record = {
        "source_record_id": "1",
        "canonical_url": "https://restaura-amazonia.fbds.org.br/record-1",
        "title": "Edital",
    }
    open_opp = fbds.parse_fbds_detail(
        record, "<html><body><main>Inscricoes abertas. Prazo: 30/09/2026.</main></body></html>"
    )
    assert open_opp["authoritative_status"] == "open"
    closed_opp = fbds.parse_fbds_detail(
        record, "<html><body><main>Edital encerrado. Prazo: 01/01/2025.</main></body></html>"
    )
    assert closed_opp["authoritative_status"] == "closed"
