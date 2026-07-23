import json
from datetime import datetime, timezone
from pathlib import Path

import discover_finep_opportunities as finep


FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "finep" / "page.json"


def _page():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_pagination_and_open_documentless_records_are_supported(monkeypatch):
    monkeypatch.setattr(finep, "FINEP_MAX_OPPORTUNITIES_PER_RUN", 10)
    stats, opportunities = finep.discover_opportunities(
        fetch_json=lambda _url: _page(),
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        min_year=2026,
    )
    assert stats == {"records": 3, "opportunities": 2, "policy_rejected": 1}
    assert [item["source_record_id"] for item in opportunities] == [
        "991625",
        "991626",
    ]
    assert opportunities[1]["documents"] == []


def test_call_owned_pdf_is_kept_but_site_manual_is_excluded():
    documents = finep.extract_record_documents(_page()["items"][0])
    assert [item["url"] for item in documents] == [
        "https://download.finep.gov.br/2026/edital-brics.pdf"
    ]


def test_markdown_and_identity_are_deterministic():
    record = _page()["items"][0]
    first = finep.record_to_opportunity(
        record, snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc)
    )
    second = finep.record_to_opportunity(
        record, snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc)
    )
    assert first == second
    assert first["canonical_url"].endswith("/991625")
    assert first["source_kind"] == "api"


def test_empty_or_malformed_api_is_a_visible_audit_failure():
    stats, opportunities = finep.discover_opportunities(
        fetch_json=lambda _url: {"items": [], "lastPage": 1}
    )
    assert opportunities == []
    assert stats["inventory_parse_failed"] == 1
