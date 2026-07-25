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
    result = fbds.discover_opportunities(
        fetch_html=pages.__getitem__,
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    stats, opportunities = result
    assert stats["opportunities"] == 1
    assert result.inventory[0]["source_record_id"] == "24"
    assert result.inventory[0] is not opportunities[0]
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
    result = fbds.discover_opportunities(
        fetch_html=lambda _url: "<html><body><footer>Editais</footer></body></html>"
    )
    stats, opportunities = result
    assert opportunities == []
    assert stats["inventory_parse_failed"] == 1
    assert result.parser_failures


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
