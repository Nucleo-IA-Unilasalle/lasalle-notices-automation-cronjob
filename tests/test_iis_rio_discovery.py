"""Unit tests for ``scripts/discover_iis_rio_candidates.py``.

Ports the IIS-Rio source from
``lasalle-notices-automation/app/services/scraper/sources/iis_rio.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_iis_rio_detail_urls`` helper plus the
paginated discovery (multi-page listing + detail pages), year guard,
``is_likely_edital`` prefilter with ``include_tdr`` policy, and the
``process_candidate`` / ``submit_candidates`` handoff.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "iis_rio"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_FIXTURE = FIXTURES_DIR / "detail.html"


LISTING_URL = "https://www.iis-rio.org/noticias/"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractIisRioDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_detail_urls(self) -> None:
        from discover_iis_rio_candidates import extract_iis_rio_detail_urls

        discovered = extract_iis_rio_detail_urls(
            _read_fixture(LISTING_FIXTURE), LISTING_URL,
        )

        assert discovered == [
            "https://www.iis-rio.org/noticias/3a-chamada-para-selecao-de-bolsistas-para-o-projeto-gef-areas-privadas-tdr-gef-iis-002-2020",
            "https://www.iis-rio.org/noticias/servico-de-consultoria-para-aplicacao-de-questionarios-com-produtoresas-de-soja",
        ]

    def test_rejects_off_host_or_non_noticias_paths(self) -> None:
        from discover_iis_rio_candidates import extract_iis_rio_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="https://example.org/noticias/edital">Outro host</a>
            <a href="/projetos/edital">Fora de /noticias/</a>
            <a href="/noticias/categoria/vaga">Multi nivel</a>
          </body>
        </html>
        """
        assert extract_iis_rio_detail_urls(listing_html, LISTING_URL) == []

    def test_requires_signal_token(self) -> None:
        from discover_iis_rio_candidates import extract_iis_rio_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/noticias/institucional">Sem sinal</a>
            <a href="/noticias/edital-2026">Com sinal</a>
          </body>
        </html>
        """
        assert extract_iis_rio_detail_urls(listing_html, LISTING_URL) == [
            "https://www.iis-rio.org/noticias/edital-2026",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_iis_rio_candidates import IIS_RIO_LISTING_URL, IIS_RIO_MAX_PAGES

        assert IIS_RIO_LISTING_URL == "https://www.iis-rio.org/noticias/"
        assert IIS_RIO_MAX_PAGES == 10


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IIS_RIO_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_iis_rio_candidates"),
        )
        assert module.IIS_RIO_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IIS_RIO_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_iis_rio_candidates"),
        )
        assert module.IIS_RIO_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("IIS_RIO_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_iis_rio_candidates"))

    def test_year_extracted_from_pdf_path(self) -> None:
        from discover_iis_rio_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.iis-rio.org/wp-content/uploads/2025/07/termo-de-referencia.pdf",
        ) == 2025

    def test_no_year_returns_none(self) -> None:
        from discover_iis_rio_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.iis-rio.org/noticias/edital",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_iis_rio_candidates import _passes_year_guard

        url_2025 = "https://www.iis-rio.org/wp-content/uploads/2025/07/termo-de-referencia.pdf"
        url_2026 = "https://www.iis-rio.org/wp-content/uploads/2026/07/termo-de-referencia.pdf"
        url_unknown = "https://www.iis-rio.org/noticias/edital"

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_include_tdr_policy_accepts_tdr_pdf(self) -> None:
        from discover_iis_rio_candidates import _candidate_passes_edital_prefilter

        url = "https://www.iis-rio.org/wp-content/uploads/2026/07/termo-de-referencia.pdf"
        assert _candidate_passes_edital_prefilter(url, "include_tdr") is True

    def test_default_policy_rejects_tdr_pdf(self) -> None:
        from discover_iis_rio_candidates import _candidate_passes_edital_prefilter

        url = "https://www.iis-rio.org/wp-content/uploads/2026/07/termo-de-referencia.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_candidate_rejected_when_filename_matches_other_exclusion(self) -> None:
        from discover_iis_rio_candidates import _candidate_passes_edital_prefilter

        url = "https://www.iis-rio.org/wp-content/uploads/2026/07/resultado-final.pdf"
        assert _candidate_passes_edital_prefilter(url, "include_tdr") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_iis_rio_candidates import _candidate_passes_edital_prefilter

        url = "https://www.iis-rio.org/wp-content/uploads/2026/07/resultado-final.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_iis_rio_candidates import build_candidate

        url = "https://www.iis-rio.org/wp-content/uploads/2026/07/termo-de-referencia.pdf"
        detail = "https://www.iis-rio.org/noticias/edital-2026"
        before = datetime.now(timezone.utc)
        candidate = build_candidate(
            url,
            listing_url=LISTING_URL,
            detail_url=detail,
            origin="detail_page",
        )
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "iis_rio"
        assert meta["listing_url"] == LISTING_URL
        assert meta["detail_url"] == detail
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_iis_rio_candidates import build_candidate

        url = "https://www.iis-rio.org/wp-content/uploads/2025/07/termo-de-referencia.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_iis_rio_candidates import build_candidate

        url = "https://www.iis-rio.org/wp-content/uploads/2026/07/resultado-final.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_listing_and_detail_pages_yield_pdf_candidates(self) -> None:
        from discover_iis_rio_candidates import discover_candidates

        # Override the fixture detail URLs to point at 2026 PDFs so they
        # survive the year guard (the recorded fixture only carries
        # 2020/2023/2025 PDFs).
        detail_html_2026 = """
        <html>
          <body>
            <main>
              <a href="https://www.iis-rio.org/wp-content/uploads/2026/07/termo-de-referencia-consultoria.pdf">Termo de referencia</a>
              <a href="https://www.iis-rio.org/noticias/">Voltar noticias</a>
            </main>
          </body>
        </html>
        """

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            "https://www.iis-rio.org/noticias/3a-chamada-para-selecao-de-bolsistas-para-o-projeto-gef-areas-privadas-tdr-gef-iis-002-2020": make_response(detail_html_2026),
            "https://www.iis-rio.org/noticias/servico-de-consultoria-para-aplicacao-de-questionarios-com-produtoresas-de-soja": make_response("<html><body></body></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] >= 1
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 2

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.iis-rio.org/wp-content/uploads/2026/07/termo-de-referencia-consultoria.pdf"
        ) in urls

        candidate = candidates[0]
        assert candidate["metadata"]["origin"] == "detail_page"
        assert candidate["metadata"]["listing_url"] == LISTING_URL
        assert candidate["metadata"]["detail_url"].startswith(
            "https://www.iis-rio.org/noticias/",
        )

    def test_year_filter_excludes_pre_2026_tdr(self) -> None:
        from discover_iis_rio_candidates import discover_candidates

        listing_html = """
        <html><body>
          <a href="/noticias/edital-antigo">Edital antigo</a>
        </body></html>
        """
        detail_html = """
        <html><body>
          <a href="/wp-content/uploads/2024/01/termo-de-referencia.pdf">TDR 2024</a>
        </body></html>
        """
        responses = {
            LISTING_URL: make_response(listing_html),
            "https://www.iis-rio.org/noticias/edital-antigo": make_response(detail_html),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["year_rejected"] == 1

    def test_listing_fetch_failure_is_logged(self) -> None:
        from discover_iis_rio_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []

    def test_pagination_stops_when_no_new_urls(self) -> None:
        from discover_iis_rio_candidates import (
            IIS_RIO_LISTING_URL,
            discover_candidates,
        )

        page2 = f"{IIS_RIO_LISTING_URL}?tipo-de-noticia=noticia&paged=2"
        empty_listing = "<html><body></body></html>"

        responses = {
            IIS_RIO_LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            page2: make_response(empty_listing),
        }

        with patch_request_with_safe_redirects(responses):
            stats, _candidates = discover_candidates()

        assert stats["listings_fetched"] == 2
        assert stats["details_fetched"] == 2


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_iis_rio_source(self) -> None:
        import discover_iis_rio_candidates as dpc

        candidate = {
            "url": "https://www.iis-rio.org/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "iis_rio"},
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
        assert call_args.kwargs["source"] == "iis_rio"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_iis_rio_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_iis_rio_candidates as dpc

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