from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discover_tnc_candidates as tnc


FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "tnc" / "consultancies.html"
SHARED_TDR_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "sources"
    / "tnc"
    / "shared_tdr_conflict.html"
)


def test_blocks_are_separate_and_new_deadline_wins():
    html = FIXTURE.read_text(encoding="utf-8")
    stats, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: html,
        now=datetime(2026, 7, 23, tzinfo=ZoneInfo("America/Sao_Paulo")),
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert stats == {"blocks": 3, "opportunities": 2, "malformed_blocks": 1}
    assert opportunities[0]["application_deadline"] == "2026-07-31T21:00:00+00:00"
    assert opportunities[0]["opportunity_type"] == "consultancy"
    assert opportunities[0]["documents"][0]["document_kind"] == "pdf"
    assert opportunities[1]["documents"] == []


def test_missing_section_is_visible_audit_failure():
    stats, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: "<html><body>Noticias gerais</body></html>"
    )
    assert opportunities == []
    assert stats["section_parse_failed"] == 1


def test_reused_tdr_url_gets_distinct_fallback_identities():
    html = """
    <html><body>
      <h2>Conheça também nossas oportunidades para consultoria e prestação de serviços</h2>
      <div class="rich-text-editor"><div class="c-rich-text">
      <p>Primeira consultoria</p>
      <p><b>PRAZO:</b> 30/07/2026</p>
      <p><b>CONTATO:</b> primeira@tnc.org</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      <p>--------------------------------------------------------------------------------------</p>
      <p>Segunda consultoria</p>
      <p><b>PRAZO:</b> 31/07/2026</p>
      <p><b>CONTATO:</b> compras@tnc.org</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      </div></div>
    </body></html>
    """
    stats, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: html,
        fetch_document_text=lambda _url: (
            "Segunda consultoria. PRAZO: 31/07/2026. "
            "Contato: compras@tnc.org"
        ),
        now=datetime(2026, 7, 23, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )

    assert len(opportunities) == 2
    assert len({item["source_record_id"] for item in opportunities}) == 2
    assert all(
        item["source_record_id"].startswith("consultancy:")
        for item in opportunities
    )
    assert len({item["canonical_url"] for item in opportunities}) == 2
    assert opportunities[0]["documents"] == []
    assert opportunities[1]["documents"][0]["url"].endswith("/shared.pdf")
    assert "ambiguous_document_conflicts" not in stats


def test_reused_tdr_is_quarantined_when_document_does_not_prove_owner():
    html = """
    <html><body>
      <h2>Conheça também nossas oportunidades para consultoria e prestação de serviços</h2>
      <div class="rich-text-editor"><div class="c-rich-text">
      <p>Primeira consultoria</p>
      <p><b>PRAZO:</b> 30/07/2026</p>
      <p><b>CONTATO:</b> primeira@tnc.org</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      <p>--------------------------------------------------------------------------------------</p>
      <p>Segunda consultoria</p>
      <p><b>PRAZO:</b> 31/07/2026</p>
      <p><b>CONTATO:</b> segunda@tnc.org</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      </div></div>
    </body></html>
    """
    stats, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: html,
        fetch_document_text=lambda _url: "Documento sem prazo ou contato.",
        now=datetime(2026, 7, 23, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )

    assert all(item["documents"] == [] for item in opportunities)
    assert stats["ambiguous_document_conflicts"] == 1
    assert stats["document_conflicts"][0] == {
        "reason_code": "identity_mismatch",
        "document_url": "https://www.tnc.org.br/shared.pdf",
        "source_record_ids": [
            opportunities[0]["source_record_id"],
            opportunities[1]["source_record_id"],
        ],
        "resolution": "attachment_quarantined",
    }


def test_reused_tdr_is_quarantined_when_inspection_fails():
    html = """
    <html><body>
      <h2>Conheça também nossas oportunidades para consultoria e prestação de serviços</h2>
      <div class="rich-text-editor"><div class="c-rich-text">
      <p>Primeira consultoria</p>
      <p><b>PRAZO:</b> 30/07/2026</p>
      <p><b>CONTATO:</b> primeira@tnc.org</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      <p>--------------------------------------------------------------------------------------</p>
      <p>Segunda consultoria</p>
      <p><b>PRAZO:</b> 31/07/2026</p>
      <p><b>CONTATO:</b> segunda@tnc.org</p>
      <p><a href="/shared.pdf">VEJA O TERMO DE REFERÊNCIA AQUI</a></p>
      </div></div>
    </body></html>
    """

    def fail_inspection(_url: str) -> str:
        raise RuntimeError("network unavailable")

    stats, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: html,
        fetch_document_text=fail_inspection,
    )

    assert all(item["documents"] == [] for item in opportunities)
    assert stats["document_conflicts"][0]["inspection_error"] == "RuntimeError"


def test_live_shared_tdr_fixture_is_assigned_by_exact_pdf_markers():
    stats, opportunities = tnc.discover_opportunities(
        fetch_html=lambda _url: SHARED_TDR_FIXTURE.read_text(encoding="utf-8"),
        fetch_document_text=lambda _url: (
            "A documentação deverá ser enviada para dferreira@tnc.org "
            "até o dia 27/08/2025."
        ),
    )

    assert "ambiguous_document_conflicts" not in stats
    assert opportunities[0]["documents"] == []
    assert opportunities[1]["documents"][0]["url"].endswith(
        "/tdr-empresa-especializada-nap.pdf"
    )
