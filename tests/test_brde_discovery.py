"""Unit tests for ``scripts/discover_brde_candidates.py``.

Ports the BRDE source from
``lasalle-notices-automation/app/services/scraper/sources/brde.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the same ``extract_brde_fsa_detail_urls`` helper used by
the FastAPI version plus the new cronjob plumbing (year guard,
``is_likely_edital`` prefilter, two-stage discovery,
``process_candidate`` / ``submit_candidates`` handoff).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "brde"


PALACETE_FIXTURE = FIXTURES_DIR / "palacete_editais.html"
FSA_LISTING_FIXTURE = FIXTURES_DIR / "fsa_chamadas.html"
CHAMADA_DETAIL_FIXTURE = FIXTURES_DIR / "chamada_detail.html"


PALACETE_LISTING_URL = "https://www.brde.com.br/palacete/editais/"
FSA_LISTING_URL = "https://www.brde.com.br/fsa/chamadas-de-investimento/"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractBrdeFsaDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version;
    these tests lock its behaviour against the recorded fixture."""

    def test_fsa_listing_yields_detail_urls(self) -> None:
        from discover_brde_candidates import extract_brde_fsa_detail_urls

        discovered = extract_brde_fsa_detail_urls(
            _read_fixture(FSA_LISTING_FIXTURE), FSA_LISTING_URL,
        )

        assert discovered == [
            "https://www.brde.com.br/fsa/chamada-publica-brde-fsa-prodecine-03-2016",
            "https://www.brde.com.br/fsa/chamada-publica-brde-fsa-prodav-03-2017",
        ]

    def test_rejects_unrelated_or_cross_host_links(self) -> None:
        from discover_brde_candidates import extract_brde_fsa_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/fsa/chamadas-de-investimento/chamadas-publicas/desenvolvimento/?tab=ci">Categoria</a>
            <a href="/institucional/">Institucional</a>
            <a href="https://www.outro-dominio.com.br/fsa/chamada-publica-brde-fsa-outra">Externo</a>
          </body>
        </html>
        """
        assert extract_brde_fsa_detail_urls(listing_html, FSA_LISTING_URL) == []

    def test_dedupes_canonicalised_paths(self) -> None:
        from discover_brde_candidates import extract_brde_fsa_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/fsa/chamada-publica-brde-fsa-x/?utm_source=foo">A</a>
            <a href="/fsa/chamada-publica-brde-fsa-x/">B</a>
          </body>
        </html>
        """
        assert extract_brde_fsa_detail_urls(
            listing_html, FSA_LISTING_URL,
        ) == ["https://www.brde.com.br/fsa/chamada-publica-brde-fsa-x"]


class TestListingUrls:
    def test_default_listing_urls(self) -> None:
        from discover_brde_candidates import (
            BRDE_PALACETE_LISTING_URL,
            BRDE_FSA_LISTING_URL,
        )

        assert BRDE_PALACETE_LISTING_URL == "https://www.brde.com.br/palacete/editais/"
        assert BRDE_FSA_LISTING_URL == "https://www.brde.com.br/fsa/chamadas-de-investimento/"


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BRDE_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_brde_candidates"),
        )
        assert module.BRDE_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRDE_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_brde_candidates"),
        )
        assert module.BRDE_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("BRDE_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_brde_candidates"))

    def test_year_extracted_from_pdf_filename(self) -> None:
        from discover_brde_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.brde.com.br/palacete/wp-content/uploads/2025/05/"
            "edital-de-patrocinio-brde-cultural-2026-1.pdf",
        ) == 2026

    def test_year_extracted_from_compound_filename(self) -> None:
        from discover_brde_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf",
        ) == 2025

    def test_no_year_returns_none(self) -> None:
        from discover_brde_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.brde.com.br/fsa/chamadas-de-investimento/",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_brde_candidates import _passes_year_guard

        url_2025 = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf"
        )
        url_2026 = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2025/05/"
            "edital-de-patrocinio-brde-cultural-2026-1.pdf"
        )
        url_unknown = (
            "https://www.brde.com.br/fsa/chamadas-de-investimento/"
        )

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_brde_candidates import _candidate_passes_edital_prefilter

        url = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2025/05/"
            "edital-de-patrocinio-brde-cultural-2026-1.pdf"
        )
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_brde_candidates import _candidate_passes_edital_prefilter

        url = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf"
        )
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_brde_candidates import _candidate_passes_edital_prefilter

        url = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf"
        )
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_has_pdf_kind_and_metadata(self) -> None:
        from datetime import datetime, timezone

        from discover_brde_candidates import build_candidate

        url = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2025/05/"
            "edital-de-patrocinio-brde-cultural-2026-1.pdf"
        )
        before = datetime.now(timezone.utc)
        candidate = build_candidate(url, listing_url=PALACETE_LISTING_URL)
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "brde"
        assert meta["listing_url"] == PALACETE_LISTING_URL
        assert meta["origin"] == "listing_pdf"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_brde_candidates import build_candidate

        url = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf"
        )
        assert build_candidate(url, listing_url=PALACETE_LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_brde_candidates import build_candidate

        url = (
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf"
        )
        assert build_candidate(url, listing_url=PALACETE_LISTING_URL) is None


class TestDiscoverCandidates:
    def test_returns_pdfs_from_both_palacete_and_fsa_detail_pages(self) -> None:
        from discover_brde_candidates import discover_candidates

        palacete_html = _read_fixture(PALACETE_FIXTURE)
        fsa_listing_html = _read_fixture(FSA_LISTING_FIXTURE)
        detail_html = _read_fixture(CHAMADA_DETAIL_FIXTURE)

        prodecine_detail = (
            "https://www.brde.com.br/fsa/chamada-publica-brde-fsa-prodecine-03-2016"
        )
        prodav_detail = (
            "https://www.brde.com.br/fsa/chamada-publica-brde-fsa-prodav-03-2017"
        )

        responses = {
            PALACETE_LISTING_URL: make_response(palacete_html),
            FSA_LISTING_URL: make_response(fsa_listing_html),
            prodecine_detail: make_response(detail_html),
            prodav_detail: make_response("<div class='page-content'></div>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        # Palacete: 1 PDF (2026 edital survives; 2025 errata filtered).
        # FSA detail pages: PRODECINE-2016/PRODAV-2017 PDFs are filtered
        # by the year guard. Net result: 1 candidate.
        assert stats["candidates"] == 1
        assert stats["listings_fetched"] == 2
        assert stats["details_fetched"] == 2
        assert stats["year_rejected"] >= 2

        assert (
            "https://www.brde.com.br/palacete/wp-content/uploads/2025/05/"
            "edital-de-patrocinio-brde-cultural-2026-1.pdf"
        ) in urls
        assert (
            "https://www.brde.com.br/palacete/wp-content/uploads/2024/08/"
            "errata-edital-de-ocupacao-2024-2025-1.pdf"
        ) not in urls
        assert (
            "https://www.brde.com.br/wp-content/uploads/2018/07/"
            "Edital_PRODECINE-03-2016_Retificacao04.pdf"
        ) not in urls

        palacete_pdf = candidates[0]
        assert palacete_pdf["metadata"]["origin"] == "listing_pdf"
        assert palacete_pdf["metadata"]["listing_url"] == PALACETE_LISTING_URL

    def test_palacete_pdf_is_recorded_with_origin_listing_pdf(self) -> None:
        from discover_brde_candidates import discover_candidates

        responses = {
            PALACETE_LISTING_URL: make_response(_read_fixture(PALACETE_FIXTURE)),
            FSA_LISTING_URL: make_response("<html></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 1
        palacete_pdf = candidates[0]
        assert palacete_pdf["metadata"]["origin"] == "listing_pdf"
        assert palacete_pdf["metadata"]["listing_url"] == PALACETE_LISTING_URL

    def test_year_filter_excludes_pre_2026_urls(self) -> None:
        from discover_brde_candidates import discover_candidates

        listing_html = """
        <html>
          <body>
            <a href="/palacete/wp-content/uploads/2025/05/edital-de-patrocinio-2025.pdf?MOD=AJPERES">
              Edital 2025
            </a>
          </body>
        </html>
        """
        responses = {
            PALACETE_LISTING_URL: make_response(listing_html),
            FSA_LISTING_URL: make_response("<html></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["year_rejected"] == 1

    def test_palacete_listing_fetch_failure_is_logged(self) -> None:
        from discover_brde_candidates import discover_candidates

        responses = {
            PALACETE_LISTING_URL: requests.ConnectionError("network down"),
            FSA_LISTING_URL: make_response("<html></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []

    def test_fsa_listing_failure_does_not_block_palacete_results(self) -> None:
        from discover_brde_candidates import discover_candidates

        responses = {
            PALACETE_LISTING_URL: make_response(_read_fixture(PALACETE_FIXTURE)),
            FSA_LISTING_URL: requests.ConnectionError("network down"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert stats["candidates"] == 1


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_brde_source(self) -> None:
        import discover_brde_candidates as dpc

        candidate = {
            "url": "https://www.brde.com.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "brde"},
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
                    dpc.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dpc.pipeline_core,
                        "submit_candidates",
                    ) as mock_submit:
                        mock_submit.return_value = {
                            "total": 1,
                            "submitted": 1,
                            "failed_batches": 0,
                            "errors": [],
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
        assert call_args.kwargs["source"] == "brde"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_brde_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_brde_candidates as dpc

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
