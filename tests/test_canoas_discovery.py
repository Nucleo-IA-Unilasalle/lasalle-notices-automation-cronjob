"""Offline tests for the structured Canoas DOMC discoverer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import discover_canoas_opportunities as canoas


FIXTURES = Path(__file__).parent / "fixtures" / "sources" / "canoas"
SNAPSHOT = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _fixture_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _diary() -> dict:
    return _fixture_json("diary.json")


def _wp_search() -> list[dict]:
    return _fixture_json("wp_search.json")


def test_domc_inventory_flattens_editions_and_deterministic_policy_filters_noise():
    records = canoas.extract_publications(_diary())

    assert len(records) == 6
    assert records[0]["source_record_id"] == "140300"
    assert records[0]["day"] == "2026-08-20"
    assert records[0]["edition_id"] == "7401"
    assert records[-1]["edition_id"] == "7402"
    assert canoas.is_likely_opportunity(records[0]["title"])
    assert canoas.is_likely_opportunity(records[2]["title"])
    assert not canoas.is_likely_opportunity(records[1]["title"])
    assert not canoas.is_likely_opportunity(records[3]["title"])
    assert not canoas.is_likely_opportunity(records[4]["title"])
    assert canoas.build_diary_url("20/08/2026").endswith("day=20%2F08%2F2026")


def test_wordpress_page_preserves_canonical_body_and_owned_documents_only():
    page_url = _wp_search()[0]["link"]
    page = canoas.extract_wordpress_page(
        (FIXTURES / "wp_detail.html").read_text(encoding="utf-8"),
        page_url,
    )

    assert page["canonical_url"] == (
        "https://www.canoas.rs.gov.br/licitacoes/"
        "edital-244-2026-chamamento-publico"
    )
    assert "inscricoes estao abertas ate 30/09/2026" in canoas._fold(
        page["content"]
    )
    assert "resultado final" not in canoas._fold(page["content"])
    assert [item["document_kind"] for item in page["documents"]] == [
        "pdf",
        "docx",
        "other",
        "pdf",
    ]
    assert page["documents"][0]["is_principal"] is True
    assert all("example.invalid" not in item["url"] for item in page["documents"])

    opportunity = canoas.parse_canoas_opportunity(
        canoas.extract_publications(_diary())[0],
        wordpress=page,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
    )
    assert opportunity is not None
    assert opportunity["source_record_id"] == "140300"
    assert opportunity["canonical_url"] == page["canonical_url"]
    assert opportunity["authoritative_status"] == "open"
    assert opportunity["application_deadline"] == "2026-10-01T02:59:59+00:00"
    assert opportunity["opportunity_type"] == "other"
    assert len(opportunity["documents"]) == 5
    assert opportunity["documents"][-1]["url"].endswith("140300")
    assert opportunity["source_updated_at"] is None


def test_domc_pdf_is_structured_fallback_when_wordpress_is_unresolved():
    record = canoas.extract_publications(_diary())[2]
    opportunity = canoas.parse_canoas_opportunity(
        record,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
    )

    assert opportunity is not None
    assert opportunity["canonical_url"].endswith("/publication-file/140302")
    assert opportunity["documents"] == [
        {
            "source_document_id": "domc:140302",
            "document_kind": "pdf",
            "url": "https://sistemas.canoas.rs.gov.br/domc/api/"
            "publication-file/140302",
            "filename": "domc-publication-140302.pdf",
            "mime_type": "application/pdf",
            "is_principal": True,
            "is_renderable": False,
        }
    ]


def test_discover_resolves_wordpress_and_keeps_domc_evidence(monkeypatch):
    urls: list[str] = []

    def fetch_json(url: str):
        urls.append(url)
        if "/diary-by-day" in url:
            return _diary()
        if "/wp-json/" in url:
            return _wp_search()
        raise AssertionError(f"unexpected JSON URL: {url}")

    def fetch_html(url: str) -> str:
        urls.append(url)
        assert url.startswith("https://www.canoas.rs.gov.br/")
        return (FIXTURES / "wp_detail.html").read_text(encoding="utf-8")

    monkeypatch.setattr(canoas, "CANOAS_FETCH_BACKOFF_SECONDS", 0)
    stats, opportunities = canoas.discover_opportunities(
        fetch_json=fetch_json,
        fetch_html=fetch_html,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        min_year=2026,
        start_date="20/08/2026",
        end_date="20/08/2026",
    )

    assert stats["days_requested"] == 1
    assert stats["days_fetched"] == 1
    assert stats["records"] == 5
    assert stats["duplicates"] == 1
    assert stats["policy_rejected"] == 3
    assert stats["wordpress_lookups"] == 2
    assert stats["wordpress_matches"] == 1
    assert stats["wordpress_pages_fetched"] == 1
    assert stats["wordpress_failures"] == 0
    assert stats["opportunities"] == 2
    assert {item["source_record_id"] for item in opportunities} == {
        "140300",
        "140302",
    }
    resolved = next(item for item in opportunities if item["source_record_id"] == "140300")
    fallback = next(item for item in opportunities if item["source_record_id"] == "140302")
    assert resolved["canonical_url"].startswith("https://www.canoas.rs.gov.br/licitacoes/")
    assert any(item["document_kind"] == "docx" for item in resolved["documents"])
    assert any(item["mime_type"] == "application/vnd.oasis.opendocument.text" for item in resolved["documents"])
    assert any(item["url"].endswith("140300") for item in resolved["documents"])
    assert fallback["canonical_url"].endswith("/publication-file/140302")
    assert any("diary-by-day" in url for url in urls)
    assert any("wp-json" in url for url in urls)


def test_wordpress_number_year_alone_cannot_cross_link_procurement():
    publication = {
        "title": "EDITAL N 289/2026",
        "day": "2026-08-19",
    }
    wrong = {
        "id": 125165,
        "status": "publish",
        "date": "2026-08-05T11:28:20",
        "link": "https://www.canoas.rs.gov.br/licitacoes/edital-289-2026-cras/",
        "title": {"rendered": "EDITAL 289/2026 - Construcao do CRAS"},
        "class_list": ["modalidade-concorrencia-publica", "genero-obra"],
    }
    assert canoas.match_wordpress_record([wrong], publication) is None

    exact = dict(_wp_search()[0])
    exact["class_list"] = ["modalidade-chamamento-publico"]
    publication = canoas.extract_publications(_diary())[0]
    assert canoas.match_wordpress_record([exact], publication) == exact


def test_empty_domc_day_is_healthy_but_malformed_inventory_fails():
    assert canoas.extract_publications({}, default_day="16/08/2026") == []
    try:
        canoas.extract_publications({"editions": [{"id": 1}]})
    except ValueError as exc:
        assert "missing index" in str(exc)
    else:
        raise AssertionError("malformed DOMC edition must fail")


def test_deadline_status_uses_local_day_and_ignores_vigency_law_dates():
    assert canoas.extract_application_deadline(
        "O contrato tera prazo maximo de 180 dias conforme Lei de 27/04/2026.",
        default_year=2026,
        now=SNAPSHOT,
    ) is None
    deadline = canoas.extract_application_deadline(
        "Inscricoes de 20/08/2026 a 03/09/2026.",
        default_year=2026,
        now=SNAPSHOT,
    )
    assert deadline == "2026-09-04T02:59:59+00:00"
    assert canoas._status(
        "As inscricoes serao encerradas na data informada.",
        deadline=deadline,
        now=SNAPSHOT,
    ) == "open"


def test_wordpress_document_ids_are_global_and_stable():
    html = (FIXTURES / "wp_detail.html").read_text(encoding="utf-8")
    page_url = _wp_search()[0]["link"]
    first = canoas.extract_wordpress_page(html, page_url)
    second = canoas.extract_wordpress_page(html, page_url)
    ids = [item["source_document_id"] for item in first["documents"]]
    assert ids == [item["source_document_id"] for item in second["documents"]]
    assert len(ids) == len(set(ids))
    assert all(value.startswith("canoas:wp:") for value in ids)


def test_wordpress_failure_marks_audit_incomplete(monkeypatch):
    monkeypatch.setattr(canoas, "CANOAS_FETCH_MAX_ATTEMPTS", 1)

    def fetch_json(url: str):
        if "/diary-by-day" in url:
            return {"day": "20-08-2026", "editions": [_diary()["editions"][0]]}
        raise RuntimeError("wordpress unavailable")

    stats, opportunities = canoas.discover_opportunities(
        fetch_json=fetch_json,
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        start_date="20/08/2026",
        end_date="20/08/2026",
    )
    assert opportunities
    assert stats["wordpress_failures"] == 2
    assert stats["errors"] == 2
    assert stats["inventory_parse_failed"] == 1


def test_failures_and_caps_are_explicit(monkeypatch):
    monkeypatch.setattr(canoas, "CANOAS_FETCH_MAX_ATTEMPTS", 1)
    failed_stats, failed = canoas.discover_opportunities(
        fetch_json=lambda _url: (_ for _ in ()).throw(RuntimeError("offline")),
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        start_date="20/08/2026",
        end_date="20/08/2026",
    )
    assert failed == []
    assert failed_stats["daily_failures"] == 1
    assert failed_stats["inventory_parse_failed"] == 1
    assert failed_stats["errors"] == 1

    monkeypatch.setattr(canoas, "CANOAS_MAX_PUBLICATIONS_PER_RUN", 1)
    monkeypatch.setattr(canoas, "CANOAS_MAX_WORDPRESS_LOOKUPS_PER_RUN", 0)
    stats, opportunities = canoas.discover_opportunities(
        fetch_json=lambda url: _diary() if "/diary-by-day" in url else [],
        snapshot_at=SNAPSHOT,
        now=SNAPSHOT,
        start_date="20/08/2026",
        end_date="20/08/2026",
    )
    assert stats["publication_cap_reached"] == 1
    assert stats["wordpress_lookup_cap_reached"] == 1
    assert stats["inventory_parse_failed"] == 1
    assert len(opportunities) == 1


def test_orchestrator_registers_canoas_but_keeps_submission_opt_in():
    import discover_all_candidates as orchestrator

    assert orchestrator.SOURCE_MODULES["canoas"] == "discover_canoas_opportunities"
    assert "canoas" not in orchestrator.STRUCTURED_OPPORTUNITY_SOURCES
    assert callable(orchestrator.load_discoverer("canoas").discover_opportunities)
