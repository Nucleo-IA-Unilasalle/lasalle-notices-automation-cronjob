from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discover_tnc_candidates as tnc


FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "tnc" / "consultancies.html"


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
