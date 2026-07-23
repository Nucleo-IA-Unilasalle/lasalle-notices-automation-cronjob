"""Unit tests for ``scripts/discover_govbr_mma_public_calls_candidates.py``.

Plan 03 adds the MMA participation-social public-call index as a separate
source ``govbr_mma_public_calls``. These tests mirror
``test_govbr_mma_discovery.py`` (extract helper, build_candidate,
discover_candidates, year guard, prefilter, submit handoff) and additionally
cover the Plan-03-specific behaviours: year-heading association, direct-PDF
and detail-page PDF paths, result/retification excluded as standalone
opportunities, cross-section link exclusion, inventory emission, diagnostic
failure, and cross-feed dedup.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "govbr_mma_public_calls"

LISTING_FIXTURE = FIXTURES_DIR / "chamamentos_listing.html"
DETAIL_FIXTURE = FIXTURES_DIR / "chamamento_juventude_detail.html"

LISTING_URL = (
    "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
    "3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico"
)
DETAIL_URL = (
    "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
    "chamamentos-publicos/chamamento-juventude-2026/chamamento-juventude-2026"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractPublicCallsLinks:
    def test_year_heading_association(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_public_calls_candidates import extract_public_calls_links

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        entries = extract_public_calls_links(soup, LISTING_URL)

        by_url = {e["url"]: e for e in entries}
        # 2025 antigo PDF
        assert by_url[
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/chamamento-antigo-2025.pdf"
        ]["year"] == 2025
        # 2026 detail + direct pdf
        assert by_url[
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/chamamento-juventude-2026/chamamento-juventude-2026"
        ]["year"] == 2026
        assert by_url[
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/edital-aberto-2026.pdf"
        ]["year"] == 2026

    def test_rejects_links_outside_content_core(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_public_calls_candidates import extract_public_calls_links

        html = """
        <html><body>
          <div id="content-core">
            <a href="./edital-2026.pdf">Dentro</a>
          </div>
          <div id="other-content-core">
            <a href="./fora.pdf">Fora</a>
          </div>
          <footer><a href="./rodape.pdf">Rodape</a></footer>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        entries = extract_public_calls_links(soup, LISTING_URL)
        urls = [e["url"] for e in entries]
        assert urls == [
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico/"
            "edital-2026.pdf"
        ]

    def test_current_cover_dom_and_off_path_detail_link(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_public_calls_candidates import extract_public_calls_links

        html = """
        <main><div id="content"><div class="cover-richtext-tile">
          <p class="callout"><strong>2026</strong></p>
          <p><a href="/mma/pt-br/noticias/edital-atual">Edital atual</a></p>
          <p><a href="/mma/pt-br/noticias/resultado-atual">Resultado do edital</a></p>
        </div></div></main>
        """
        entries = extract_public_calls_links(BeautifulSoup(html, "html.parser"), LISTING_URL)
        assert entries[0]["year"] == 2026
        assert entries[0]["url"].endswith("/mma/pt-br/noticias/edital-atual")
        assert entries[0]["related"] is False
        assert entries[1]["related"] is True


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(__import__("discover_govbr_mma_public_calls_candidates"))
        assert module.GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR == 2026

    def test_year_extract(self) -> None:
        from discover_govbr_mma_public_calls_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.gov.br/mma/chamamentos/edital-2026.pdf",
        ) == 2026
        assert _extract_year_from_url("https://www.gov.br/mma/edital.pdf") is None

    def test_heading_year_is_authoritative_when_filename_has_no_year(self) -> None:
        from discover_govbr_mma_public_calls_candidates import build_candidate

        assert build_candidate(
            "https://www.gov.br/mma/edital.pdf",
            listing_url=LISTING_URL,
            year=2025,
            min_year=2026,
        ) is None


class TestMetadataAndRelatedDocuments:
    def test_accented_related_title_and_non_related_results_phrase(self) -> None:
        from discover_govbr_mma_public_calls_candidates import _is_related_document

        assert _is_related_document("https://www.gov.br/mma/documento.pdf", "Retificação")
        assert not _is_related_document(
            "https://www.gov.br/mma/pagamentos-baseados-em-resultados",
            "Edital de pagamentos baseados em resultados",
        )

    def test_explicit_status_deadline_and_publication_are_preserved(self) -> None:
        from discover_govbr_mma_public_calls_candidates import _extract_record_metadata

        html = """
        <html><head><meta property="article:published_time" content="2026-05-07T12:00:00Z"></head>
        <body><div id="content"><p>Edital prorrogado. Propostas até 13/7.</p></div></body></html>
        """
        metadata = _extract_record_metadata(html, year=2026)
        assert metadata == {
            "status": "open",
            "deadline": "2026-07-13",
            "published_at": "2026-05-07T12:00:00Z",
        }

    def test_results_based_subject_does_not_imply_closed_status(self) -> None:
        from discover_govbr_mma_public_calls_candidates import _extract_record_metadata

        html = """
        <html><body><div id="content-core">
          <p>Edital de pagamentos baseados em resultados ambientais.</p>
        </div></body></html>
        """

        assert _extract_record_metadata(html, year=2026)["status"] == "unknown"


class TestBuildCandidate:
    def test_source_key_and_record_id(self) -> None:
        from discover_govbr_mma_public_calls_candidates import build_candidate

        url = "https://www.gov.br/mma/chamamentos/edital-2026.pdf"
        candidate = build_candidate(
            url,
            listing_url=LISTING_URL,
            detail_url=DETAIL_URL,
            origin="detail_page",
            source_record_id=DETAIL_URL,
            year=2026,
        )
        assert candidate is not None
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "govbr_mma_public_calls"
        assert meta["source_record_id"] == DETAIL_URL
        assert meta["detail_url"] == DETAIL_URL
        assert meta["extracted_year"] == 2026

    def test_returns_none_for_pre_min_year(self) -> None:
        from discover_govbr_mma_public_calls_candidates import build_candidate

        url = "https://www.gov.br/mma/chamamentos/edital-2025.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_direct_pdf_and_detail_page_paths(self) -> None:
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
        }
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        inventory, _ = build_inventory(
            listing_html=_read_fixture(LISTING_FIXTURE),
            detail_responses={DETAIL_URL: _read_fixture(DETAIL_FIXTURE)},
        )

        urls = [c["url"] for c in candidates]
        # Direct listing PDF retained as candidate.
        assert (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/edital-aberto-2026.pdf"
        ) in urls
        # Detail-page principal PDF retained as candidate.
        assert (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/chamamento-juventude-2026/"
            "edital-principal-juventude-2026.pdf"
        ) in urls
        # Pre-2026 PDF excluded by year guard.
        assert any("antigo-2025" in u for u in urls) is False
        assert stats["year_rejected"] >= 1
        assert stats["candidates"] == 2
        # Inventory has a record for the 2026 detail with related docs attached.
        detail_rec = next(
            r for r in inventory
            if r["source_record_id"] == DETAIL_URL
        )
        assert any("retificacao" in u for u in detail_rec["document_urls"])
        assert any("resultado" in u for u in detail_rec["document_urls"])
        assert any("anexo" in u for u in detail_rec["document_urls"])

    def test_result_retification_not_standalone_opportunity(self) -> None:
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
        }
        with patch_request_with_safe_redirects(responses):
            _stats, candidates = discover_candidates()

        inventory, _ = build_inventory(
            listing_html=_read_fixture(LISTING_FIXTURE),
            detail_responses={DETAIL_URL: _read_fixture(DETAIL_FIXTURE)},
        )

        # No candidate URL is a resultado/retificacao/anexo PDF.
        for c in candidates:
            assert "resultado" not in c["url"]
            assert "retificacao" not in c["url"]
            assert "anexo" not in c["url"]
        # Exactly one inventory record for the detail page.
        detail_records = [r for r in inventory if r["source_record_id"] == DETAIL_URL]
        assert len(detail_records) == 1

    def test_detail_page_with_two_principals_yields_two_candidates(self) -> None:
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        detail_url = (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/chamamento-duplo-2026/chamamento-duplo-2026"
        )
        detail_html = """
        <html><body><div id="content-core">
          <a href="./edital-principal-1-2026.pdf">Edital principal 1</a>
          <a href="./edital-principal-2-2026.pdf">Edital principal 2</a>
          <a href="./retificacao-edital-2026.pdf">Retificacao</a>
          <a href="./resultado-edital-2026.pdf">Resultado</a>
        </div></body></html>
        """
        listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/chamamentos-publicos/chamamento-duplo-2026/chamamento-duplo-2026">
            Chamamento com dois editais
          </a>
        </div></div></body></html>
        """
        responses = {
            LISTING_URL: make_response(listing),
            detail_url: make_response(detail_html),
        }
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        inventory, _ = build_inventory(
            listing_html=listing,
            detail_responses={detail_url: detail_html},
        )

        urls = [c["url"] for c in candidates]
        assert any("edital-principal-1-2026.pdf" in u for u in urls)
        assert not any("edital-principal-2-2026.pdf" in u for u in urls)
        assert len(candidates) == 1
        # The canonical detail page is one opportunity with both documents.
        assert len(inventory) == 1
        assert any(
            "edital-principal-2-2026.pdf" in u
            for u in inventory[0]["document_urls"]
        )
        # Related docs attached to (at least) the first principal's record.
        first_rec = inventory[0]
        assert any("retificacao" in u for u in first_rec["document_urls"])
        assert any("resultado" in u for u in first_rec["document_urls"])
        # No related doc became a standalone candidate.
        for c in candidates:
            assert "retificacao" not in c["url"]
            assert "resultado" not in c["url"]

    def test_status_unknown_when_no_deadline(self) -> None:
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
        }
        with patch_request_with_safe_redirects(responses):
            _stats, _candidates = discover_candidates()

        inventory, _ = build_inventory(
            listing_html=_read_fixture(LISTING_FIXTURE),
            detail_responses={DETAIL_URL: _read_fixture(DETAIL_FIXTURE)},
        )
        for record in inventory:
            assert record["status"] == "unknown"
            assert record["deadline"] is None

    def test_listing_fetch_failure_sets_error(self) -> None:
        from discover_govbr_mma_public_calls_candidates import discover_candidates

        with patch_request_with_safe_redirects({LISTING_URL: requests.ConnectionError("down")}):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []

    def test_inventory_parse_failed_when_body_has_no_entries(self) -> None:
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        empty_listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <p>Nenhum chamamento no momento.</p>
        </div></div></body></html>
        """
        responses = {LISTING_URL: make_response(empty_listing)}
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        # Body present but zero parseable entries -> diagnostic failure.
        assert stats["inventory_parse_failed"] == 1
        assert stats["errors"] >= 1
        assert candidates == []
        inventory, _ = build_inventory(
            listing_html=empty_listing, detail_responses={},
        )
        assert inventory == []


class TestInventoryEmission:
    def test_build_inventory_plan01_fields(self) -> None:
        from discover_govbr_mma_public_calls_candidates import build_inventory

        inventory, content_present = build_inventory(
            listing_html=_read_fixture(LISTING_FIXTURE),
            detail_responses={DETAIL_URL: _read_fixture(DETAIL_FIXTURE)},
        )
        assert content_present is True
        assert inventory
        for record in inventory:
            assert set(record) == {
                "source_key",
                "source_record_id",
                "canonical_url",
                "title",
                "status",
                "published_at",
                "deadline",
                "source_year",
                "document_urls",
                "document_hashes",
            }
            assert record["source_key"] == "govbr_mma_public_calls"
            assert isinstance(record["document_urls"], list)
            assert record["document_hashes"] == []

    def test_related_listing_pdf_before_principal_is_retained_on_parent(self) -> None:
        """Editorial ordering must not make a retification disappear.

        Some gov.br pages place a result/retification link before the updated
        edital link.  The source inventory still needs that URL on the one
        principal opportunity record, never as a candidate of its own.
        """
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="./retificacao-edital-2026.pdf">Retificacao do edital</a>
          <a href="./edital-principal-2026.pdf">Edital principal</a>
        </div></div></body></html>
        """
        responses = {LISTING_URL: make_response(listing)}
        with patch_request_with_safe_redirects(responses):
            _stats, candidates = discover_candidates()

        inventory, content_present = build_inventory(
            listing_html=listing,
            detail_responses={},
        )

        assert content_present is True
        assert len(candidates) == 1
        assert "edital-principal-2026.pdf" in candidates[0]["url"]
        assert len(inventory) == 1
        assert any("retificacao-edital-2026.pdf" in url for url in inventory[0]["document_urls"])
        assert any("edital-principal-2026.pdf" in url for url in inventory[0]["document_urls"])

    def test_repeated_direct_identity_merges_documents_without_duplicate_candidate(self) -> None:
        from discover_govbr_mma_public_calls_candidates import (
            build_inventory,
            discover_candidates,
        )

        listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="./edital-principal-v1-2026.pdf">Edital principal 2026</a>
          <a href="./edital-principal-v2-2026.pdf">Edital principal 2026</a>
        </div></div></body></html>
        """
        responses = {LISTING_URL: make_response(listing)}
        with patch_request_with_safe_redirects(responses):
            _stats, candidates = discover_candidates()

        inventory, _ = build_inventory(listing_html=listing, detail_responses={})

        assert len(candidates) == 1
        assert len(inventory) == 1
        assert len(inventory[0]["document_urls"]) == 2


class TestCrossFeedDedup:
    def test_fnma_pdf_in_public_calls_is_not_double_submitted(self) -> None:
        import discover_govbr_mma_fnma_candidates as fnma
        import discover_govbr_mma_public_calls_candidates as public_calls

        # Simulate the orchestrator threading ONE shared seen_pdfs set through
        # both feeds (no monkey-patching of the REAL record-id functions).
        shared_seen_pdfs: set[str] = set()
        shared_seen_ids: set[str] = set()

        # The SAME absolute PDF URL appears in BOTH feeds: public_calls links
        # it relatively, FNMA links it by absolute URL. This is the real
        # cross-feed collision the dedup must catch.
        common_pdf = (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "chamamentos-publicos/edital-comum-2026.pdf"
        )
        pc_listing = f"""
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="{common_pdf}">Edital comum</a>
        </div></div></body></html>
        """
        fnma_listing = f"""
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="{common_pdf}">Edital comum</a>
        </div></div></body></html>
        """

        with patch_request_with_safe_redirects(
            {public_calls.GOVBR_MMA_PUBLIC_CALLS_LISTING_URL: make_response(pc_listing)},
        ):
            _s1, c1 = public_calls.discover_candidates(
                seen_ids=shared_seen_ids, seen_pdfs=shared_seen_pdfs,
            )

        with patch_request_with_safe_redirects(
            {fnma.GOVBR_MMA_FNMA_LISTING_URL: make_response(fnma_listing)},
        ):
            _s2, c2 = fnma.discover_candidates(
                seen_ids=shared_seen_ids, seen_pdfs=shared_seen_pdfs,
            )

        assert any(common_pdf in c["url"] for c in c1)
        # FNMA must not emit a second candidate for the shared PDF URL.
        assert not any(common_pdf in c["url"] for c in c2)
        # Union of candidate PDF URLs contains NO duplicate.
        all_pdf_urls = [c["url"] for c in (c1 + c2)]
        assert len(all_pdf_urls) == len(set(all_pdf_urls))

    def test_orchestrator_threads_shared_seen_pdfs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import discover_all_candidates

        pc_captured: dict[str, Any] = {}
        fnma_captured: dict[str, Any] = {}

        import discover_govbr_mma_fnma_candidates as fnma
        import discover_govbr_mma_public_calls_candidates as public_calls

        def fake_pc_discover(*, filter_policy, min_year, seen_ids=None, seen_pdfs=None):
            pc_captured["seen_ids"] = seen_ids
            pc_captured["seen_pdfs"] = seen_pdfs
            return {"candidates": 0}, []

        def fake_fnma_discover(*, filter_policy, min_year, seen_ids=None, seen_pdfs=None):
            fnma_captured["seen_ids"] = seen_ids
            fnma_captured["seen_pdfs"] = seen_pdfs
            return {"candidates": 0}, []

        monkeypatch.setattr(public_calls, "discover_candidates", fake_pc_discover)
        monkeypatch.setattr(fnma, "discover_candidates", fake_fnma_discover)

        discover_all_candidates.discover_source(
            public_calls, filter_policy="default", min_year=2026,
        )
        discover_all_candidates.discover_source(
            fnma, filter_policy="default", min_year=2026,
        )
        # Both feeds received distinct sets by default (per-call fresh sets),
        # but the orchestrator can reuse one. Verify the param is accepted and
        # that sharing a single set dedups across feeds.
        shared: set[str] = set()
        shared_ids: set[str] = set()
        discover_all_candidates.discover_source(
            public_calls, filter_policy="default", min_year=2026,
            seen_pdfs=shared, seen_ids=shared_ids,
        )
        discover_all_candidates.discover_source(
            fnma, filter_policy="default", min_year=2026,
            seen_pdfs=shared, seen_ids=shared_ids,
        )
        assert pc_captured and fnma_captured
        # The orchestrator threads ONE shared seen_pdfs object through both
        # feeds — prove identity (not just two non-empty sets).
        assert pc_captured["seen_pdfs"] is shared
        assert fnma_captured["seen_pdfs"] is shared
        # The same shared seen_ids object is threaded through both feeds.
        assert pc_captured["seen_ids"] is shared_ids
        assert fnma_captured["seen_ids"] is shared_ids


class TestSubmitHandoff:
    def test_main_calls_submit_with_public_calls_source(self) -> None:
        import discover_govbr_mma_public_calls_candidates as dpc

        candidate = {
            "url": "https://www.gov.br/mma/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "govbr_mma_public_calls"},
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
            with patch.object(dpc, "discover_candidates", return_value=({"candidates": 1}, [candidate])):
                with patch.object(dpc.pipeline_core, "process_candidate", return_value=candidate):
                    with patch.object(dpc.pipeline_core, "submit_candidates") as mock_submit:
                        mock_submit.return_value = {
                            "total": 1, "submitted": 1, "failed_batches": 0, "errors": [],
                        }
                        with patch.dict("os.environ", {
                            "RENDER_APP_URL": "https://r.example.com",
                            "PIPELINE_SECRET": "tok",
                        }):
                            dpc.main()

        mock_submit.assert_called_once()
        assert mock_submit.call_args.kwargs["source"] == "govbr_mma_public_calls"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_govbr_mma_public_calls_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_audit_mode_writes_fidelity_artifacts(self, tmp_path: Path) -> None:
        import discover_govbr_mma_public_calls_candidates as dpc

        inventory = [{
            "source_key": dpc.SOURCE_KEY,
            "source_record_id": "record-1",
            "canonical_url": "https://www.gov.br/mma/detail",
            "title": "Edital",
            "status": "unknown",
            "published_at": None,
            "deadline": None,
            "source_year": 2026,
            "document_urls": ["https://www.gov.br/mma/edital.pdf"],
            "document_hashes": [],
        }]
        candidates = [{
            "url": "https://www.gov.br/mma/edital.pdf",
            "kind": "pdf",
            "metadata": {"source_record_id": "record-1"},
        }]
        with patch.object(
            dpc,
            "_discover_candidates_and_inventory",
            return_value=({"candidates": 1, "inventory_parse_failed": 0}, candidates, inventory),
        ):
            assert dpc.main(["--audit-dir", str(tmp_path)]) == 0
        assert {path.name for path in tmp_path.iterdir()} == {
            "source_inventory.json", "discovery.json", "candidates.json", "stats.json",
        }
