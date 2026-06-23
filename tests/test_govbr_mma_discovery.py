"""Unit tests for ``scripts/discover_govbr_mma_candidates.py``.

Ports the GOVBR-MMA source from
``lasalle-notices-automation/app/services/scraper/sources/govbr.py``
(line 85 ``scrape_govbr_mma``; ``scrape_govbr_mcti`` at line 115 is
intentionally NOT ported because it is degraded). Tests exercise the
``extract_govbr_mma_detail_urls`` helper plus the two-stage discovery
(Plone listing -> detail pages), year guard, ``is_likely_edital``
prefilter, and the ``process_candidate`` / ``submit_candidates``
handoff.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "govbr_mma"


LISTING_FIXTURE = FIXTURES_DIR / "editais_listing.html"
DETAIL_FIXTURE = FIXTURES_DIR / "chamamento_detail.html"


LISTING_URL = "https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais"
DETAIL_URL = (
    "https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/"
    "chamamento-publico-locacao-de-imovel/chamamento-publico-locacao-de-imovel"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractGovbrMmaDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_internal_detail_urls(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_candidates import extract_govbr_mma_detail_urls

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        discovered = extract_govbr_mma_detail_urls(soup, LISTING_URL)

        # The fixture has 4 anchors inside #content-core. Three are
        # internal to /mma/.../editais:
        #   - chamamento-publico-locacao-de-imovel/chamamento-publico-locacao-de-imovel
        #   - compras-diretas
        #   - licitacoes/licitacoes
        # One points to a cross-section page (/biodiversidade-e-biomas)
        # which is NOT under the listing prefix and is dropped.
        assert discovered == [
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/"
            "chamamento-publico-locacao-de-imovel/chamamento-publico-locacao-de-imovel",
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/compras-diretas",
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/licitacoes/licitacoes",
        ]

    def test_rejects_anchors_outside_content_core(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_candidates import extract_govbr_mma_detail_urls

        html = """
        <html>
          <body>
            <a href="./listing-self">Listing self (dropped)</a>
            <div id="content-core">
              <a href="./edital-2026">Internal</a>
              <a href="https://www.gov.br/mma/pt-br/assuntos/algum-lugar">Fora do prefixo</a>
            </div>
            <div id="other-content-core">
              <a href="./in-other-block">Outside content-core</a>
            </div>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        discovered = extract_govbr_mma_detail_urls(soup, LISTING_URL)

        assert discovered == [
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/edital-2026",
        ]

    def test_skips_direct_pdf_anchors(self) -> None:
        from bs4 import BeautifulSoup

        from discover_govbr_mma_candidates import extract_govbr_mma_detail_urls

        html = """
        <html><body>
          <div id="content-core">
            <a href="./edital-2026.pdf">PDF direto</a>
            <a href="./edital-2026">Detalhe</a>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        discovered = extract_govbr_mma_detail_urls(soup, LISTING_URL)

        assert discovered == [
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/edital-2026",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_govbr_mma_candidates import GOVBR_MMA_LISTING_URL

        assert GOVBR_MMA_LISTING_URL == (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais"
        )


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOVBR_MMA_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_govbr_mma_candidates"),
        )
        assert module.GOVBR_MMA_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOVBR_MMA_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_govbr_mma_candidates"),
        )
        assert module.GOVBR_MMA_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("GOVBR_MMA_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_govbr_mma_candidates"))

    def test_year_extracted_from_pdf_path(self) -> None:
        from discover_govbr_mma_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.gov.br/mma/editais/edital-chamamento-2026.pdf",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_govbr_mma_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.gov.br/mma/editais/edital.pdf",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_govbr_mma_candidates import _passes_year_guard

        url_2025 = "https://www.gov.br/mma/editais/edital-2025.pdf"
        url_2026 = "https://www.gov.br/mma/editais/edital-2026.pdf"
        url_unknown = "https://www.gov.br/mma/editais/edital.pdf"

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_govbr_mma_candidates import _candidate_passes_edital_prefilter

        url = "https://www.gov.br/mma/editais/edital-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_govbr_mma_candidates import _candidate_passes_edital_prefilter

        url = "https://www.gov.br/mma/editais/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_govbr_mma_candidates import _candidate_passes_edital_prefilter

        url = "https://www.gov.br/mma/editais/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_govbr_mma_candidates import build_candidate

        url = "https://www.gov.br/mma/editais/edital-2026.pdf"
        before = datetime.now(timezone.utc)
        candidate = build_candidate(
            url,
            listing_url=LISTING_URL,
            detail_url=DETAIL_URL,
            origin="detail_page",
        )
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "govbr_mma"
        assert meta["listing_url"] == LISTING_URL
        assert meta["detail_url"] == DETAIL_URL
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_govbr_mma_candidates import build_candidate

        url = "https://www.gov.br/mma/editais/edital-2025.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_govbr_mma_candidates import build_candidate

        url = "https://www.gov.br/mma/editais/resultado-final-2026.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_listing_and_detail_pages_yield_pdf_candidates(self) -> None:
        from discover_govbr_mma_candidates import discover_candidates

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/compras-diretas": make_response("<html></html>"),
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/licitacoes/licitacoes": make_response("<html></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 3
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 3

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/"
            "chamamento-publico-locacao-de-imovel/edital-de-chamamento-publico-locacao-imovel-02.pdf"
        ) in urls
        assert (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/"
            "chamamento-publico-locacao-de-imovel/aviso-chamamento-publico-locacao-jornal-brasilia.pdf"
        ) in urls
        assert (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/"
            "chamamento-publico-locacao-de-imovel/aviso-chamamento-publico-locacao-correio.pdf"
        ) in urls

    def test_year_filter_excludes_pre_2026_pdf(self) -> None:
        from discover_govbr_mma_candidates import discover_candidates

        listing_html = """
        <html><body>
          <div id="content-core">
            <a href="./chamamento-2025">Chamamento antigo</a>
          </div>
        </body></html>
        """
        detail_html = """
        <html><body>
          <a href="./chamamento-2025/edital-2025.pdf">Edital 2025</a>
        </body></html>
        """
        detail_url = (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/chamamento-2025"
        )
        responses = {
            LISTING_URL: make_response(listing_html),
            detail_url: make_response(detail_html),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.gov.br/mma/pt-br/acesso-a-informacao/"
            "licitacoes-e-contratos/editais/chamamento-2025/edital-2025.pdf"
        ) not in urls
        assert stats["year_rejected"] == 1

    def test_listing_fetch_failure_is_logged(self) -> None:
        from discover_govbr_mma_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_govbr_mma_source(self) -> None:
        import discover_govbr_mma_candidates as dpc

        candidate = {
            "url": "https://www.gov.br/mma/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "govbr_mma"},
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
        assert call_args.kwargs["source"] == "govbr_mma"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_govbr_mma_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_govbr_mma_candidates as dpc

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