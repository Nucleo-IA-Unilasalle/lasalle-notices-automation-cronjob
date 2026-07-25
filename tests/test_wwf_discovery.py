"""Unit tests for ``scripts/discover_wwf_candidates.py``.

Ports the WWF source from
``lasalle-notices-automation/app/services/scraper/sources/wwf.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.

Plan 02 ("WWF Discovery Precision Repair") changes discovery from
scanning every listing anchor to structurally parsing the
``EDITAIS ABERTOS`` / ``EDITAIS ENCERRADOS`` sections and following only
those row detail URLs. These tests lock that behaviour: section parsing,
status preservation, process-number extraction, generic-document
rejection, retification/annex retention, cross-record dedup, the
selector-drift failure path, and Plan-01-compatible inventory output.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "wwf"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_94482 = FIXTURES_DIR / "detail_94482.html"
DETAIL_94483 = FIXTURES_DIR / "detail_94483.html"
DETAIL_94484 = FIXTURES_DIR / "detail_94484.html"
LISTING_DOCX_FIXTURE = FIXTURES_DIR / "listing_docx.html"
DETAIL_94946 = FIXTURES_DIR / "detail_94946.html"
DETAIL_94947 = FIXTURES_DIR / "detail_94947.html"
DETAIL_94948 = FIXTURES_DIR / "detail_94948.html"


LISTING_URL = "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/"
DETAIL_94482_URL = LISTING_URL + "?94482/Prestacao-de-servicos-de-analise-territorial"
DETAIL_94483_URL = LISTING_URL + "?94483/Consultoria-em-educacao-ambiental"
DETAIL_94484_URL = LISTING_URL + "?94484/Carta-convite-concorrencia-analise-territorial"
DETAIL_94946_URL = LISTING_URL + "?94946/Consultoria-eventos"
DETAIL_94947_URL = LISTING_URL + "?94947/Consultoria-genero"
DETAIL_94948_URL = LISTING_URL + "?94948/Consultoria-comunicacao"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _default_responses() -> dict[str, object]:
    return {
        LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
        DETAIL_94482_URL: make_response(_read_fixture(DETAIL_94482)),
        DETAIL_94483_URL: make_response(_read_fixture(DETAIL_94483)),
        DETAIL_94484_URL: make_response(_read_fixture(DETAIL_94484)),
    }


def _docx_responses() -> dict[str, object]:
    return {
        LISTING_URL: make_response(_read_fixture(LISTING_DOCX_FIXTURE)),
        DETAIL_94946_URL: make_response(_read_fixture(DETAIL_94946)),
        DETAIL_94947_URL: make_response(_read_fixture(DETAIL_94947)),
        DETAIL_94948_URL: make_response(_read_fixture(DETAIL_94948)),
    }


class TestExtractWwfDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_detail_urls(self) -> None:
        from discover_wwf_candidates import extract_wwf_detail_urls

        discovered = extract_wwf_detail_urls(_read_fixture(LISTING_FIXTURE), LISTING_URL)

        assert discovered == [
            DETAIL_94482_URL,
            DETAIL_94483_URL,
            DETAIL_94484_URL,
        ]

    def test_rejects_off_host_and_non_aquisicoesecontratacoes_paths(self) -> None:
        from discover_wwf_candidates import extract_wwf_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="https://example.org/sobrenos/aquisicoesecontratacoes/?uNewsID=1">Outro host</a>
            <a href="/noticias/?uNewsID=2">Path fora</a>
            <a href="/sobrenos/aquisicoesecontratacoes/?uNewsID=abc">uNewsID nao numerico</a>
            <a href="/sobrenos/aquisicoesecontratacoes/?uNewsID=3">Valido</a>
          </body>
        </html>
        """
        assert extract_wwf_detail_urls(listing_html, LISTING_URL) == [
            "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/?uNewsID=3",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_wwf_candidates import WWF_LISTING_URL

        assert WWF_LISTING_URL == "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/"


class TestSectionParsing:
    def test_open_and_closed_sections_produce_statuses(self) -> None:
        from discover_wwf_candidates import parse_listing_sections

        rows = parse_listing_sections(_read_fixture(LISTING_FIXTURE))
        assert rows is not None
        open_rows = [r for r in rows if r["status"] == "open"]
        closed_rows = [r for r in rows if r["status"] == "closed"]
        assert {r["source_record_id"] for r in open_rows} == {"005705", "005706"}
        assert {r["source_record_id"] for r in closed_rows} == {"005094"}

    def test_process_number_becomes_source_record_id(self) -> None:
        from discover_wwf_candidates import parse_listing_sections

        rows = parse_listing_sections(_read_fixture(LISTING_FIXTURE))
        assert rows is not None
        by_id = {r["source_record_id"]: r for r in rows}
        assert by_id["005705"]["canonical_url"] == DETAIL_94482_URL
        assert "Prestação de serviços de análise territorial" in by_id["005705"]["title"]
        assert by_id["005705"]["published_at"] == "2026-07-16T00:00:00Z"

    def test_missing_sections_returns_none(self) -> None:
        from discover_wwf_candidates import parse_listing_sections

        html = "<html><body><h2>Outra coisa</h2></body></html>"
        assert parse_listing_sections(html) is None

    def test_one_missing_section_returns_none(self) -> None:
        from discover_wwf_candidates import parse_listing_sections

        html = "<html><body><h2>EDITAIS ABERTOS</h2></body></html>"
        assert parse_listing_sections(html) is None

    def test_fallback_to_uNewsID_when_no_process_number(self) -> None:
        from discover_wwf_candidates import parse_listing_sections

        html = """
        <html><body>
          <h2>EDITAIS ABERTOS</h2>
          <a href="https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/?uNewsID=77777">
            Chamada pública sem número
          </a>
          <h2>EDITAIS ENCERRADOS</h2>
        </body></html>
        """
        rows = parse_listing_sections(html)
        assert rows is not None
        assert rows[0]["source_record_id"] == "77777"
        assert rows[0]["status"] == "open"


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WWF_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(__import__("discover_wwf_candidates"))
        assert module.WWF_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WWF_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(__import__("discover_wwf_candidates"))
        assert module.WWF_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("WWF_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_wwf_candidates"))

    def test_year_extracted_from_pdf_path(self) -> None:
        from discover_wwf_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://wwfbrnew.awsassets.panda.org/downloads/edital-2026.pdf",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_wwf_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://wwfbrnew.awsassets.panda.org/downloads/edital.pdf",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_wwf_candidates import _passes_year_guard

        url_2025 = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2025.pdf"
        url_2026 = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2026.pdf"
        url_unknown = "https://wwfbrnew.awsassets.panda.org/downloads/edital.pdf"

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_wwf_candidates import _candidate_passes_edital_prefilter

        url = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_wwf_candidates import _candidate_passes_edital_prefilter

        url = "https://wwfbrnew.awsassets.panda.org/downloads/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_generic_supplier_assets_rejected(self) -> None:
        from discover_wwf_candidates import _candidate_passes_edital_prefilter

        generic = [
            "https://x/awsassets.panda.org/downloads/documentos-necessarios.pdf",
            "https://x/awsassets.panda.org/downloads/requisitos-basicos.pdf",
            "https://x/awsassets.panda.org/downloads/modelo-de-proposta.pdf",
            "https://x/awsassets.panda.org/downloads/proposta-modelo-2026.pdf",
            "https://x/awsassets.panda.org/downloads/portal-fornecedor.pdf",
            "https://x/awsassets.panda.org/downloads/fornecedor-portal.pdf",
        ]
        for url in generic:
            assert _candidate_passes_edital_prefilter(url, "default") is False, url

    def test_retificacao_and_anexo_retained(self) -> None:
        from discover_wwf_candidates import _candidate_passes_edital_prefilter

        retained = [
            "https://x/awsassets.panda.org/downloads/retificacao-005705-2026.pdf",
            "https://x/awsassets.panda.org/downloads/errata-001.pdf",
            "https://x/awsassets.panda.org/downloads/anexo-005705-2026.pdf",
        ]
        for url in retained:
            assert _candidate_passes_edital_prefilter(url, "default") is True, url

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_wwf_candidates import _candidate_passes_edital_prefilter

        url = "https://wwfbrnew.awsassets.panda.org/downloads/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_wwf_candidates import build_candidate

        url = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2026.pdf"
        before = datetime.now(timezone.utc)
        candidate = build_candidate(url, listing_url=LISTING_URL, origin="detail_page")
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "wwf"
        assert meta["listing_url"] == LISTING_URL
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_records_detail_origin(self) -> None:
        from discover_wwf_candidates import build_candidate

        url = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2026.pdf"
        candidate = build_candidate(
            url, listing_url=LISTING_URL, detail_url=DETAIL_94482_URL, origin="detail_page",
        )

        assert candidate is not None
        assert candidate["metadata"]["detail_url"] == DETAIL_94482_URL
        assert candidate["metadata"]["origin"] == "detail_page"

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_wwf_candidates import build_candidate

        url = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2025.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_wwf_candidates import build_candidate

        url = "https://wwfbrnew.awsassets.panda.org/downloads/resultado-final-2026.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_discovery_follows_only_edital_rows(self) -> None:
        from discover_wwf_candidates import discover_candidates

        with patch_request_with_safe_redirects(_default_responses()):
            stats, candidates = discover_candidates()

        # 3 open/closed detail rows -> 7 unique PDFs (anexo shared across
        # 94482 and 94483 is deduped). Generic listing docs are not scanned.
        assert stats["candidates"] == 7
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 3
        assert stats["section_parse_failed"] == 0

        urls = [c["url"] for c in candidates]
        assert (
            "https://wwfbrnew.awsassets.panda.org/downloads/edital-005705-analise-territorial-2026.pdf"
            in urls
        )
        # Generic supplier asset must NOT be a candidate.
        assert all("modelo-de-proposta" not in u for u in urls)
        # Generic listing-level docs were never followed.
        assert all("documentos-necessarios" not in u for u in urls)
        assert all("requisitos-basicos" not in u for u in urls)
        # The source-record-specific divulgacao document is retained.
        assert any("divulgacao_site_v3_sc005705" in u for u in urls)
        assert stats["prefilter_rejected"] >= 1

    def test_retificacao_and_anexo_retained_as_candidates(self) -> None:
        from discover_wwf_candidates import discover_candidates

        with patch_request_with_safe_redirects(_default_responses()):
            _, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert any("retificacao-005705" in u for u in urls)
        assert any("anexo-005705" in u for u in urls)
        assert any("retificacao-005094" in u for u in urls)

    def test_candidates_trace_to_specific_row(self) -> None:
        from discover_wwf_candidates import discover_candidates

        with patch_request_with_safe_redirects(_default_responses()):
            _, candidates = discover_candidates()

        for c in candidates:
            meta = c["metadata"]
            assert "source_record_id" in meta
            assert "detail_url" in meta
            assert meta["detail_url"].startswith(LISTING_URL + "?")
            assert meta["title"]
            assert meta["published_at"]

    def test_missing_detail_content_area_is_a_failure(self) -> None:
        from discover_wwf_candidates import discover_candidates

        responses = _default_responses()
        responses[DETAIL_94482_URL] = make_response(
            '<html><body><a href="https://example.test/unrelated.pdf">PDF</a></body></html>',
        )
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["detail_parse_failed"] == 1
        assert stats["errors"] == 1
        assert all("unrelated.pdf" not in candidate["url"] for candidate in candidates)

    def test_duplicate_pdf_urls_across_records_not_duplicated(self) -> None:
        from discover_wwf_candidates import discover_candidates

        with patch_request_with_safe_redirects(_default_responses()):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert urls == list(dict.fromkeys(urls))
        assert stats["candidates"] == len(set(urls))

    def test_missing_sections_fails_audit_not_silent_zero(self) -> None:
        from discover_wwf_candidates import discover_candidates

        responses = {
            LISTING_URL: make_response(
                "<html><body><h2>Sem editais</h2></body></html>",
            ),
        }
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["section_parse_failed"] == 1
        assert stats["errors"] >= 1
        assert candidates == []
        assert stats["candidates"] == 0

    def test_listing_fetch_failure_is_logged(self) -> None:
        from discover_wwf_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []


class TestBuildInventory:
    def test_inventory_is_plan01_compatible(self) -> None:
        from discover_wwf_candidates import build_inventory

        inventory, present = build_inventory(
            listing_html=_read_fixture(LISTING_FIXTURE),
            detail_responses={
                DETAIL_94482_URL: _read_fixture(DETAIL_94482),
                DETAIL_94483_URL: _read_fixture(DETAIL_94483),
                DETAIL_94484_URL: _read_fixture(DETAIL_94484),
            },
        )
        assert present is True
        assert len(inventory) == 3

        field_names = {
            "source_key", "source_record_id", "canonical_url", "title",
            "status", "published_at", "deadline", "document_urls", "document_hashes",
        }
        for record in inventory:
            assert set(record.keys()) >= field_names
            assert record["source_key"] == "wwf"

        by_id = {r["source_record_id"]: r for r in inventory}
        assert by_id["005705"]["status"] == "open"
        assert by_id["005094"]["status"] == "closed"
        # Retificacao/anexo retained in inventory; generic proposta excluded.
        docs_5705 = by_id["005705"]["document_urls"]
        assert any("retificacao-005705" in u for u in docs_5705)
        assert any("anexo-005705" in u for u in docs_5705)
        assert all("modelo-de-proposta" not in u for u in docs_5705)

    def test_inventory_missing_sections_reports_absent(self) -> None:
        from discover_wwf_candidates import build_inventory

        inventory, present = build_inventory(
            listing_html="<html><body><h2>nada</h2></body></html>",
            detail_responses={},
        )
        assert present is False
        assert inventory == []


class TestDocxOpportunities:
    def test_all_three_live_docx_records_are_structured_opportunities(self) -> None:
        from discover_wwf_candidates import discover_opportunities

        with patch_request_with_safe_redirects(_docx_responses()):
            stats, opportunities = discover_opportunities()

        assert stats["opportunities"] == 3
        assert stats["docx_opportunities"] == 3
        assert stats["documentless_opportunities"] == 0
        assert stats["candidates"] == 0
        assert {item["source_record_id"] for item in opportunities} == {
            "94946", "94947", "94948",
        }
        for opportunity in opportunities:
            assert opportunity["authoritative_status"] == "open"
            assert opportunity["opportunity_type"] == "consultancy"
            assert len(opportunity["documents"]) == 1
            document = opportunity["documents"][0]
            assert document["document_kind"] == "docx"
            assert document["is_renderable"] is False
            assert document["mime_type"].endswith(
                "officedocument.wordprocessingml.document"
            )

    def test_generic_supplier_docx_is_excluded(self) -> None:
        from discover_wwf_candidates import build_inventory

        inventory, present = build_inventory(
            listing_html=_read_fixture(LISTING_DOCX_FIXTURE),
            detail_responses={
                DETAIL_94946_URL: _read_fixture(DETAIL_94946),
                DETAIL_94947_URL: _read_fixture(DETAIL_94947),
                DETAIL_94948_URL: _read_fixture(DETAIL_94948),
            },
        )

        assert present is True
        urls = [
            url
            for record in inventory
            for url in record["document_urls"]
        ]
        assert len(urls) == 3
        assert all(url.endswith(".docx") for url in urls)
        assert all("modelo-de-proposta" not in url for url in urls)

    def test_audit_discovery_accounts_for_docx_records(self, tmp_path) -> None:
        import json
        import discover_wwf_candidates as dpc

        with patch_request_with_safe_redirects(_docx_responses()):
            assert dpc.main(["--audit-dir", str(tmp_path)]) == 0

        discovery = json.loads((tmp_path / "discovery.json").read_text())
        opportunities = json.loads((tmp_path / "opportunities.json").read_text())
        assert len(discovery) == 3
        assert len(opportunities) == 3
        assert all(record["document_urls"] for record in discovery)
        assert all(
            item["documents"][0]["document_kind"] == "docx"
            for item in opportunities
        )


class TestRssFallback:
    def test_official_feeds_replace_a_forbidden_listing(self) -> None:
        import discover_wwf_candidates as dpc

        open_feed = """<?xml version="1.0" encoding="utf-8"?>
        <rss><channel>
          <item><title>Consultoria eventos</title>
            <link>http://originlaccms1.wwf-sites.org:8301/sobrenos/aquisicoesecontratacoes/?uNewsID=94946</link>
          </item>
          <item><title>Consultoria genero</title>
            <link>http://originlaccms1.wwf-sites.org:8301/sobrenos/aquisicoesecontratacoes/?uNewsID=94947</link>
          </item>
          <item><title>Consultoria comunicacao</title>
            <link>http://originlaccms1.wwf-sites.org:8301/sobrenos/aquisicoesecontratacoes/?uNewsID=94948</link>
          </item>
        </channel></rss>"""
        closed_feed = """<?xml version="1.0" encoding="utf-8"?>
        <rss><channel /></rss>"""
        responses = {
            LISTING_URL: make_response(status_code=403),
            dpc.WWF_OPEN_RSS_URL: make_response(open_feed),
            dpc.WWF_CLOSED_RSS_URL: make_response(closed_feed),
            LISTING_URL + "?uNewsID=94946": make_response(_read_fixture(DETAIL_94946)),
            LISTING_URL + "?uNewsID=94947": make_response(_read_fixture(DETAIL_94947)),
            LISTING_URL + "?uNewsID=94948": make_response(_read_fixture(DETAIL_94948)),
        }

        with patch_request_with_safe_redirects(responses):
            stats, opportunities = dpc.discover_opportunities()

        assert stats["rss_fallback_used"] == 1
        assert stats["rss_feeds_fetched"] == 2
        assert stats["errors"] == 0
        assert len(opportunities) == 3
        assert all(item["documents"] for item in opportunities)


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_wwf_source(self) -> None:
        import discover_wwf_candidates as dpc

        candidate = {
            "url": "https://wwfbrnew.awsassets.panda.org/downloads/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "wwf"},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00+00:00",
                "validation_outcome": "valid_pdf",
            },
        }

        ocr_mod = MagicMock()
        config_mod = MagicMock()
        module_stubs = {
            "ocr_worker.ocr_extraction_config": config_mod,
            "ocr_worker.pdf_markdown_extractor": ocr_mod,
        }
        with patch.dict(sys.modules, module_stubs):
            with patch.object(dpc, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dpc.pipeline_core, "process_candidate", return_value=candidate,
                ):
                    with patch.object(
                        dpc.pipeline_core, "submit_candidates",
                    ) as mock_submit:
                        mock_submit.return_value = {
                            "total": 1, "submitted": 1, "failed_batches": 0, "errors": [],
                        }
                        with patch.dict(
                            "os.environ",
                            {
                                "RENDER_APP_URL": "https://r.example.com",
                                "PIPELINE_SECRET": "tok",
                            },
                        ):
                            dpc.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "wwf"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_wwf_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_wwf_candidates as dpc

        with patch.object(dpc, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dpc.main() == 0

    def test_main_returns_1_when_discovery_reports_parser_failure(self) -> None:
        import discover_wwf_candidates as dpc

        with patch.object(dpc, "discover_candidates") as mock_disc:
            mock_disc.return_value = (
                {"candidates": 0, "errors": 1, "section_parse_failed": 1},
                [],
            )
            with patch.dict(
                "os.environ",
                {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok"},
            ):
                assert dpc.main() == 1

    def test_audit_mode_writes_json_without_submission_env(self, tmp_path) -> None:
        import json
        import discover_wwf_candidates as dpc

        with patch.object(dpc, "_discover_candidates_and_inventory") as discover:
            discover.return_value = (
                {"candidates": 1, "errors": 0, "section_parse_failed": 0},
                [{"url": "https://example.test/edital.pdf", "metadata": {"source_record_id": "1"}}],
                [{
                    "source_key": "wwf", "source_record_id": "1",
                    "canonical_url": "https://example.test/1", "title": "Edital",
                    "status": "open", "published_at": None, "deadline": None,
                    "document_urls": ["https://example.test/edital.pdf"],
                    "document_hashes": [],
                }],
            )
            with patch.dict("os.environ", {}, clear=True):
                assert dpc.main(["--audit-dir", str(tmp_path)]) == 0

        assert json.loads((tmp_path / "source_inventory.json").read_text())
        assert json.loads((tmp_path / "discovery.json").read_text())
        assert json.loads((tmp_path / "candidates.json").read_text())
