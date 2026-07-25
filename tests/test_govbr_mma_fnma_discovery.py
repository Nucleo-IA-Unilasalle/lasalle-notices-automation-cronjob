"""Unit tests for ``scripts/discover_govbr_mma_fnma_candidates.py``.

Plan 03 adds the MMA FNMA editais / terms-of-reference page as a separate
source ``govbr_mma_fnma``. These tests mirror ``test_govbr_mma_discovery.py``
and additionally cover the Plan-03-specific behaviours: year-heading
association, principal edital retained while its retification is related
metadata, TDR opt-in that does NOT change the global ``scraper_filters``
default, cross-section link exclusion, inventory emission, and diagnostic
failure.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "govbr_mma_fnma"

LISTING_FIXTURE = FIXTURES_DIR / "fnma_editais.html"

LISTING_URL = (
    "https://www.gov.br/mma/pt-br/composicao/secex/dfre/"
    "fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractFnmaLinks:
    def test_year_heading_association(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_fnma_candidates import extract_fnma_links

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        entries = extract_fnma_links(soup, LISTING_URL)
        by_url = {e["url"]: e for e in entries}

        assert by_url[
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "fundo-nacional-do-meio-ambiente/editais/fnma-edital-antigo-2025.pdf"
        ]["year"] == 2025
        assert by_url[
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "fundo-nacional-do-meio-ambiente/editais/fnma-edital-principal-2026.pdf"
        ]["year"] == 2026

    def test_rejects_links_outside_content_core(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_fnma_candidates import extract_fnma_links

        html = """
        <html><body>
          <div id="content-core">
            <a href="./fnma-2026.pdf">Dentro</a>
          </div>
          <div id="other-content-core">
            <a href="./fora.pdf">Fora</a>
          </div>
          <footer><a href="./rodape.pdf">Rodape</a></footer>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        entries = extract_fnma_links(soup, LISTING_URL)
        urls = [e["url"] for e in entries]
        assert urls == [
            "https://www.gov.br/mma/pt-br/composicao/secex/dfre/"
            "fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1/"
            "fnma-2026.pdf"
        ]

    def test_current_cover_dom_year_and_accented_retification(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_fnma_candidates import extract_fnma_links

        html = """
        <main><div id="content"><div class="cover-richtext-tile">
          <div>Edital 2026 - EDITAL PRORROGADO</div>
          <div><a href="./edital-principal.pdf">Edital FNMA 1/2026</a></div>
          <div><a href="./RetificaodoEdital.pdf">Retificação</a></div>
        </div></div></main>
        """
        entries = extract_fnma_links(BeautifulSoup(html, "html.parser"), LISTING_URL)
        assert [entry["year"] for entry in entries] == [2026, 2026]
        assert entries[0]["related"] is False
        assert entries[1]["related"] is True


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOVBR_MMA_FNMA_MIN_NOTICE_YEAR", raising=False)
        import discover_govbr_mma_fnma_candidates as dpc

        importlib.reload(dpc)
        assert dpc.GOVBR_MMA_FNMA_MIN_NOTICE_YEAR == 2026


class TestMetadata:
    def test_results_based_subject_does_not_imply_closed_status(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_fnma_candidates import _extract_listing_metadata

        soup = BeautifulSoup(
            """
            <div id="content-core">
              <p>Edital para projetos de pagamentos por resultados ambientais.</p>
            </div>
            """,
            "html.parser",
        )
        root = soup.select_one("#content-core")
        assert root is not None

        assert _extract_listing_metadata(root, year=2026)["status"] == "unknown"

    def test_explicit_open_status_expires_after_deadline(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_fnma_candidates import _extract_listing_metadata

        soup = BeautifulSoup(
            """
            <div id="content-core">
              <p>Edital prorrogado. Propostas podem ser enviadas até 13/07/2026.</p>
            </div>
            """,
            "html.parser",
        )
        root = soup.select_one("#content-core")
        assert root is not None

        metadata = _extract_listing_metadata(
            root,
            year=2026,
            now=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
        assert metadata["deadline"] == "2026-07-13"
        assert metadata["status"] == "expired"


class TestDiscoverCandidates:
    def test_principal_retained_retification_related(self) -> None:
        from discover_govbr_mma_fnma_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))}
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        inventory, _ = build_inventory(listing_html=_read_fixture(LISTING_FIXTURE))

        urls = [c["url"] for c in candidates]
        # Principal edital retained as candidate.
        assert any("fnma-edital-principal-2026.pdf" in u for u in urls)
        # Retificacao is NOT a standalone candidate.
        assert not any("fnma-retificacao-2026.pdf" in u for u in urls)
        # TDR is NOT a standalone candidate under default policy.
        assert not any("termo-de-referencia-2026.pdf" in u for u in urls)

        # The principal record carries the retification + TDR as related docs.
        rec = next(
            r for r in inventory
            if any("fnma-edital-principal-2026.pdf" in u for u in r["document_urls"])
        )
        assert any("fnma-retificacao-2026.pdf" in u for u in rec["document_urls"])
        assert any("termo-de-referencia-2026.pdf" in u for u in rec["document_urls"])
        # Exactly one inventory record for the principal edital.
        assert len([
            r for r in inventory
            if any("fnma-edital-principal-2026.pdf" in u for u in r["document_urls"])
        ]) == 1

    def test_pre_2026_excluded_by_year_guard(self) -> None:
        from discover_govbr_mma_fnma_candidates import discover_candidates

        responses = {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))}
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert not any("antigo-2025" in u for u in urls)
        assert stats["year_rejected"] >= 1

    def test_status_unknown_when_no_deadline(self) -> None:
        from discover_govbr_mma_fnma_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))}
        with patch_request_with_safe_redirects(responses):
            _stats, _candidates = discover_candidates()

        inventory, _ = build_inventory(listing_html=_read_fixture(LISTING_FIXTURE))
        for record in inventory:
            assert record["status"] == "unknown"
            assert record["deadline"] is None

    def test_listing_fetch_failure_sets_error(self) -> None:
        from discover_govbr_mma_fnma_candidates import discover_candidates

        with patch_request_with_safe_redirects({LISTING_URL: requests.ConnectionError("down")}):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []

    def test_inventory_parse_failed_when_body_has_no_entries(self) -> None:
        from discover_govbr_mma_fnma_candidates import (
            build_inventory,
            discover_candidates,
        )

        empty_listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <p>Nenhum edital no momento.</p>
        </div></div></body></html>
        """
        responses = {LISTING_URL: make_response(empty_listing)}
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["inventory_parse_failed"] == 1
        assert stats["errors"] >= 1
        assert candidates == []
        inventory, _ = build_inventory(listing_html=empty_listing)
        assert inventory == []


class TestFnmaTdrPolicy:
    def test_tdr_opt_in_does_not_change_global_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The global scraper_filters default must remain "default".
        import scraper_filters

        assert scraper_filters.resolve_filter_policy("default")[0] is True
        _should, patterns = scraper_filters.resolve_filter_policy("default")
        assert any("termo" in p for p in patterns)

        # The FNMA module may opt in via its own flag without touching global.
        import discover_govbr_mma_fnma_candidates as dpc

        monkeypatch.setenv("GOVBR_MMA_FNMA_INCLUDE_TDR", "1")
        reloaded = importlib.reload(dpc)
        assert reloaded.FNMA_INCLUDE_TDR is True
        # Global default still unchanged — the global FILTER_POLICY is untouched,
        # not just a pure-function call into is_likely_edital.
        assert scraper_filters.resolve_filter_policy("default")[0] is True
        assert scraper_filters.is_likely_edital(
            "termo-de-referencia.pdf",
            "http://ex.com/termo-de-referencia.pdf",
            filter_policy="default",
        ) is False

    def test_tdr_is_related_metadata_under_default(self) -> None:
        from discover_govbr_mma_fnma_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))}
        with patch_request_with_safe_redirects(responses):
            _stats, candidates = discover_candidates()

        inventory, _ = build_inventory(listing_html=_read_fixture(LISTING_FIXTURE))
        urls = [c["url"] for c in candidates]
        # TDR not a candidate under default policy.
        assert not any("termo-de-referencia" in u for u in urls)
        # But it is attached as related metadata to the parent record.
        all_docs = [u for r in inventory for u in r["document_urls"]]
        assert any("termo-de-referencia-2026.pdf" in u for u in all_docs)

    def test_tdr_becomes_candidate_when_opt_in(self) -> None:
        from discover_govbr_mma_fnma_candidates import discover_candidates

        tdr_listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="./termo-de-referencia-2026.pdf">Termo de Referencia 2026</a>
        </div></div></body></html>
        """
        responses = {LISTING_URL: make_response(tdr_listing)}
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates(include_tdr=True)

        urls = [c["url"] for c in candidates]
        # With the source-local opt-in, the TDR becomes a candidate.
        assert any("termo-de-referencia-2026.pdf" in u for u in urls)
        assert stats["candidates"] == 1

    def test_tdr_excluded_when_opt_in_off(self) -> None:
        from discover_govbr_mma_fnma_candidates import discover_candidates

        tdr_listing = """
        <html><body><div id="content-core"><div id="parent-fieldname-text">
          <h2>2026</h2>
          <a href="./termo-de-referencia-2026.pdf">Termo de Referencia 2026</a>
        </div></div></body></html>
        """
        responses = {LISTING_URL: make_response(tdr_listing)}
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates(include_tdr=False)

        urls = [c["url"] for c in candidates]
        assert not any("termo-de-referencia" in u for u in urls)


class TestInventoryEmission:
    def test_build_inventory_plan01_fields(self) -> None:
        from discover_govbr_mma_fnma_candidates import build_inventory

        inventory, content_present = build_inventory(
            listing_html=_read_fixture(LISTING_FIXTURE),
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
            assert record["source_key"] == "govbr_mma_fnma"
            assert record["document_hashes"] == []

    def test_candidate_ids_present_in_inventory(self) -> None:
        from discover_govbr_mma_fnma_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))}
        with patch_request_with_safe_redirects(responses):
            _stats, candidates = discover_candidates()

        inventory, _ = build_inventory(listing_html=_read_fixture(LISTING_FIXTURE))

        inventory_ids = {r["source_record_id"] for r in inventory}
        # Every candidate's source_record_id must appear as an inventory
        # record id (Plan-01 ID-traceability by source_record_id).
        for candidate in candidates:
            assert candidate["metadata"]["source_record_id"] in inventory_ids

    def test_candidate_ids_present_in_inventory_under_opt_in(self) -> None:
        import discover_govbr_mma_fnma_candidates as dpc

        # Fixture has a principal edital PDF AND a TDR PDF.
        listing = _read_fixture(LISTING_FIXTURE)
        tdr_url = (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "fundo-nacional-do-meio-ambiente/editais/termo-de-referencia-2026.pdf"
        )
        principal_url = (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "fundo-nacional-do-meio-ambiente/editais/fnma-edital-principal-2026.pdf"
        )

        responses = {LISTING_URL: make_response(listing)}
        with patch_request_with_safe_redirects(responses):
            _stats, candidates = dpc.discover_candidates(include_tdr=True)

        inventory, _ = dpc.build_inventory(listing_html=listing, include_tdr=True)

        inventory_ids = {r["source_record_id"] for r in inventory}
        inventory_urls = {u for r in inventory for u in r["document_urls"]}

        # TDR candidate exists under opt-in.
        tdr_candidates = [c for c in candidates if "termo-de-referencia" in c["url"]]
        assert tdr_candidates
        tdr_record_id = tdr_candidates[0]["metadata"]["source_record_id"]
        # Its source_record_id is a TDR inventory principal record id.
        assert tdr_record_id in inventory_ids
        # The principal candidate is also traceable (default behavior intact).
        principal_id = dpc._fnma_record_id(
            principal_url, year=2026, title="Edital FNMA principal 2026",
        )
        assert principal_id in inventory_ids
        # Every candidate's source_record_id is traceable in the inventory.
        for candidate in candidates:
            assert candidate["metadata"]["source_record_id"] in inventory_ids
        # The TDR URL appears as a principal document in some record.
        assert any("termo-de-referencia-2026.pdf" in u for u in inventory_urls)
        # TDR opt-in must not promote retifications/results into opportunities.
        assert not any(
            "retificacao" in record["canonical_url"].lower()
            for record in inventory
        )
        principal_record = next(
            record for record in inventory if record["source_record_id"] == principal_id
        )
        assert any("retificacao" in url for url in principal_record["document_urls"])

    def test_tdr_is_related_only_under_default_no_principal_record(self) -> None:
        import discover_govbr_mma_fnma_candidates as dpc

        listing = _read_fixture(LISTING_FIXTURE)
        tdr_url = (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/"
            "fundo-nacional-do-meio-ambiente/editais/termo-de-referencia-2026.pdf"
        )
        tdr_record_id = dpc._fnma_record_id(tdr_url, year=2026, title="")

        inventory, _ = dpc.build_inventory(listing_html=listing, include_tdr=False)
        inventory_ids = {r["source_record_id"] for r in inventory}
        # Under default (opt-out) there is NO standalone TDR principal record.
        assert tdr_record_id not in inventory_ids
        # But the TDR URL is still auditable as related metadata.
        all_docs = [u for r in inventory for u in r["document_urls"]]
        assert any("termo-de-referencia-2026.pdf" in u for u in all_docs)


class TestSubmitHandoff:
    def test_main_calls_submit_with_fnma_source(self) -> None:
        import discover_govbr_mma_fnma_candidates as dpc

        candidate = {
            "url": "https://www.gov.br/mma/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "govbr_mma_fnma"},
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
        assert mock_submit.call_args.kwargs["source"] == "govbr_mma_fnma"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_govbr_mma_fnma_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_audit_mode_writes_fidelity_artifacts(self, tmp_path: Path) -> None:
        import discover_govbr_mma_fnma_candidates as dpc

        inventory = [{
            "source_key": dpc.SOURCE_KEY,
            "source_record_id": "record-1",
            "canonical_url": "https://www.gov.br/mma/edital.pdf",
            "title": "Edital",
            "status": "open",
            "published_at": None,
            "deadline": "2026-07-13",
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


class TestTwoPrincipalsSameYear:
    """B2: the FNMA source_record_id must be unique PER EDITAL, so two
    principal PDFs in the same year both become candidates / inventory
    records."""

    TWO_PRINCIPALS = """
    <html><body><div id="content-core"><div id="parent-fieldname-text">
      <h2>2026</h2>
      <ul>
        <li>
          <a href="./fnma-edital-A-2026.pdf">Edital A FNMA 2026</a>
        </li>
        <li>
          <a href="./fnma-edital-B-2026.pdf">Edital B FNMA 2026</a>
        </li>
        <li>
          <a href="./fnma-retificacao-2026.pdf">Retificacao FNMA 2026</a>
        </li>
      </ul>
    </div></div></body></html>
    """

    def test_two_principals_yield_two_candidates(self) -> None:
        from discover_govbr_mma_fnma_candidates import discover_candidates

        responses = {
            LISTING_URL: make_response(self.TWO_PRINCIPALS),
        }
        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert any("fnma-edital-A-2026.pdf" in u for u in urls)
        assert any("fnma-edital-B-2026.pdf" in u for u in urls)
        # Both principals are distinct candidates.
        assert len(candidates) == 2
        # Distinct record ids (unique per edital, not per year).
        record_ids = {c["metadata"]["source_record_id"] for c in candidates}
        assert len(record_ids) == 2

    def test_two_principals_yield_two_inventory_records(self) -> None:
        from discover_govbr_mma_fnma_candidates import (
            build_inventory,
            discover_candidates,
        )

        responses = {
            LISTING_URL: make_response(self.TWO_PRINCIPALS),
        }
        with patch_request_with_safe_redirects(responses):
            _stats, _candidates = discover_candidates()

        inventory, _ = build_inventory(listing_html=self.TWO_PRINCIPALS)
        # Both principals appear as their own inventory documents.
        all_docs = [u for r in inventory for u in r["document_urls"]]
        assert any("fnma-edital-A-2026.pdf" in u for u in all_docs)
        assert any("fnma-edital-B-2026.pdf" in u for u in all_docs)
        # Retificacao still attached as related metadata to the year group.
        assert any("fnma-retificacao-2026.pdf" in u for u in all_docs)

    def test_shared_pdf_url_still_dedups_across_calls(self) -> None:
        import discover_govbr_mma_fnma_candidates as fnma

        shared_seen_pdfs: set[str] = set()
        shared_seen_ids: set[str] = set()

        listing = self.TWO_PRINCIPALS
        responses = {LISTING_URL: make_response(listing)}
        with patch_request_with_safe_redirects(responses):
            _s1, c1 = fnma.discover_candidates(
                seen_ids=shared_seen_ids, seen_pdfs=shared_seen_pdfs,
            )

        # Re-running the SAME feed with the shared sets must not re-emit them.
        with patch_request_with_safe_redirects(responses):
            _s2, c2 = fnma.discover_candidates(
                seen_ids=shared_seen_ids, seen_pdfs=shared_seen_pdfs,
            )

        assert len(c1) == 2
        assert c2 == []
