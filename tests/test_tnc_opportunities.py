from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discover_tnc_candidates as tnc


FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "tnc" / "consultancies.html"


def test_blocks_are_separate_and_new_deadline_wins():
    html = FIXTURE.read_text(encoding="utf-8")
    result = tnc.discover_opportunities(
        fetch_html=lambda _url: html,
        now=datetime(2026, 7, 23, tzinfo=ZoneInfo("America/Sao_Paulo")),
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    stats, opportunities = result
    assert stats == {
        "blocks": 3,
        "inventory_records": 2,
        "opportunities": 2,
        "malformed_blocks": 1,
        "policy_rejected": 0,
        "parser_failures": 1,
        "inventory_parse_failed": 1,
    }
    assert len(result.inventory) == 2
    assert opportunities[0]["application_deadline"] == "2026-07-31T21:00:00+00:00"
    assert opportunities[0]["opportunity_type"] == "consultancy"
    assert opportunities[0]["documents"][0]["document_kind"] == "pdf"
    assert opportunities[1]["documents"] == []


def test_missing_section_is_visible_audit_failure():
    result = tnc.discover_opportunities(
        fetch_html=lambda _url: "<html><body>Noticias gerais</body></html>"
    )
    stats, opportunities = result
    assert opportunities == []
    assert stats["section_parse_failed"] == 1
    assert result.parser_failures


def test_reused_tdr_url_gets_distinct_fallback_identities():
    html = """
    <html><body>
      <h2>Conheça também nossas oportunidades para consultoria e prestação de serviços</h2>
      <div class="rich-text-editor"><div class="c-rich-text">
      <p>Primeira consultoria</p>
      <p><b>PRAZO:</b> 30/07/2026</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      <p>--------------------------------------------------------------------------------------</p>
      <p>Segunda consultoria</p>
      <p><b>PRAZO:</b> 31/07/2026</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      </div></div>
    </body></html>
    """
    _, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: html,
        now=datetime(2026, 7, 23, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )

    assert len(opportunities) == 2
    assert len({item["source_record_id"] for item in opportunities}) == 2
    assert all(
        item["source_record_id"].startswith("consultancy:")
        for item in opportunities
    )
    assert len({item["canonical_url"] for item in opportunities}) == 2
