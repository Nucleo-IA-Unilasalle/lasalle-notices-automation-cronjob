import json
from datetime import datetime, timezone
from pathlib import Path

import discover_finep_opportunities as finep


FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "finep" / "page.json"


def _page():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_pagination_and_open_documentless_records_are_supported(monkeypatch):
    monkeypatch.setattr(finep, "FINEP_MAX_OPPORTUNITIES_PER_RUN", 10)
    result = finep.discover_opportunities(
        fetch_json=lambda _url: _page(),
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        min_year=2026,
    )
    stats, opportunities = result
    assert stats == {
        "records": 3,
        "inventory_records": 3,
        "opportunities": 2,
        "policy_rejected": 1,
        "parser_failures": 0,
        "audit_complete_inventory": 0,
    }
    assert [item["source_record_id"] for item in opportunities] == [
        "991625",
        "991626",
    ]
    assert [item["source_record_id"] for item in result.inventory] == [
        "991625",
        "991626",
        "900000",
    ]
    assert result.inventory[-1]["reason_code"] == "out_of_scope"
    assert result.inventory[-1]["evidence"]["policy"] == "minimum_notice_year"
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
    result = finep.discover_opportunities(
        fetch_json=lambda _url: {"items": [], "lastPage": 1}
    )
    stats, opportunities = result
    assert opportunities == []
    assert stats["inventory_parse_failed"] == 1
    assert result.parser_failures[0]["stage"] == "api_inventory"


def test_pagination_uses_stable_id_tiebreaker(monkeypatch):
    monkeypatch.setattr(finep, "FINEP_MAX_PAGES_PER_RUN", 2)
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        record_id = "2" if "page=1" in url else "1"
        return {
            "items": [{"id": record_id}],
            "lastPage": 2,
        }

    records = finep.fetch_api_pages(fetch_json=fetch_json)

    assert [record["id"] for record in records] == ["2", "1"]
    assert len(requested_urls) == 2
    assert all(
        "sort=dataDePublicacao:desc,id:desc" in url
        for url in requested_urls
    )


def test_audit_mode_bypasses_submission_cap(monkeypatch):
    monkeypatch.setattr(finep, "FINEP_MAX_OPPORTUNITIES_PER_RUN", 1)
    monkeypatch.setenv("DISCOVERY_AUDIT_ONLY", "true")

    result = finep.discover_opportunities(
        fetch_json=lambda _url: _page(),
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        min_year=2026,
    )

    assert result.stats["audit_complete_inventory"] == 1
    assert [item["source_record_id"] for item in result.opportunities] == [
        "991625",
        "991626",
    ]


def test_submission_mode_retains_source_cap(monkeypatch):
    monkeypatch.setattr(finep, "FINEP_MAX_OPPORTUNITIES_PER_RUN", 1)
    monkeypatch.delenv("DISCOVERY_AUDIT_ONLY", raising=False)

    result = finep.discover_opportunities(
        fetch_json=lambda _url: _page(),
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        min_year=2026,
    )

    assert result.stats["audit_complete_inventory"] == 0
    assert [item["source_record_id"] for item in result.opportunities] == [
        "991625",
    ]
    assert len(result.inventory) == 3
