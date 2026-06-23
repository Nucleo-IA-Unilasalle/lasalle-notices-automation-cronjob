"""Unit tests for ``scripts/discover_funbio_candidates.py``.

Ports the FUNBIO source from
``lasalle-notices-automation/app/services/scraper/sources/funbio.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_funbio_detail_urls`` and
``extract_funbio_pdf_urls`` helpers plus the two-stage discovery
(listing -> detail pages), year guard, ``is_likely_edital`` prefilter,
and the ``process_candidate`` / ``submit_candidates`` handoff.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "funbio"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_FIXTURE = FIXTURES_DIR / "detail.html"


LISTING_URL = "https://chamadas.funbio.org.br/"
DETAIL_URL = "https://chamadas.funbio.org.br/floresta-viva-piaui"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractFunbioDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_matching_detail_urls(self) -> None:
        from discover_funbio_candidates import extract_funbio_detail_urls

        discovered = extract_funbio_detail_urls(
            _read_fixture(LISTING_FIXTURE), LISTING_URL,
        )

        assert discovered == [
            "https://chamadas.funbio.org.br/floresta-viva-piaui",
        ]

    def test_rejects_off_host_or_blocked_paths(self) -> None:
        from discover_funbio_candidates import extract_funbio_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="https://example.org/floresta-viva-piaui">Outro host</a>
            <a href="/quem-somos">Bloqueado</a>
            <a href="/calendario-chamadas">Calendario</a>
            <a href="/multi/nivel">Multi nivel</a>
          </body>
        </html>
        """
        assert extract_funbio_detail_urls(listing_html, LISTING_URL) == []

    def test_requires_signal_token(self) -> None:
        from discover_funbio_candidates import extract_funbio_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/sobre-nos">Sem sinal</a>
            <a href="/chamada-publica-2026">Com sinal</a>
          </body>
        </html>
        """
        assert extract_funbio_detail_urls(listing_html, LISTING_URL) == [
            "https://chamadas.funbio.org.br/chamada-publica-2026",
        ]


class TestExtractFunbioPdfUrls:
    def test_extracts_download_regulamento_anchors(self) -> None:
        from bs4 import BeautifulSoup

        from discover_funbio_candidates import extract_funbio_pdf_urls

        soup = BeautifulSoup(_read_fixture(DETAIL_FIXTURE), "html.parser")
        discovered = extract_funbio_pdf_urls(soup, DETAIL_URL)

        assert discovered == [
            "/floresta-viva-piaui/download/regulamento?id=abdb24f9-beb5-4779-b3c2-2d2fe9bb93d5",
        ]

    def test_blocks_privacy_anchors_even_if_pdf(self) -> None:
        from bs4 import BeautifulSoup

        from discover_funbio_candidates import extract_funbio_pdf_urls

        html = """
        <html>
          <body>
            <a href="/static/P-42-2020-Politica-de-Privacidade-do-Funbio.pdf">
              Politica de Privacidade
            </a>
            <a href="/static/regulamento-edital-2026.pdf">Regulamento</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        discovered = extract_funbio_pdf_urls(soup, DETAIL_URL)

        assert discovered == ["/static/regulamento-edital-2026.pdf"]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_funbio_candidates import FUNBIO_LISTING_URL

        assert FUNBIO_LISTING_URL == "https://chamadas.funbio.org.br/"


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FUNBIO_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_funbio_candidates"),
        )
        assert module.FUNBIO_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FUNBIO_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_funbio_candidates"),
        )
        assert module.FUNBIO_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("FUNBIO_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_funbio_candidates"))

    def test_year_extracted_from_pdf_slug(self) -> None:
        from discover_funbio_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "/floresta-viva-piaui/download/regulamento?id=abc&id-data=2026",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_funbio_candidates import _extract_year_from_url

        assert _extract_year_from_url(DETAIL_URL) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_funbio_candidates import _passes_year_guard

        url_2025 = "/static/regulamento-edital-2025.pdf"
        url_2026 = "/static/regulamento-edital-2026.pdf"
        url_unknown = DETAIL_URL

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_funbio_candidates import _candidate_passes_edital_prefilter

        url = "/floresta-viva-piaui/download/regulamento-edital-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_funbio_candidates import _candidate_passes_edital_prefilter

        url = "/static/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_funbio_candidates import _candidate_passes_edital_prefilter

        url = "/static/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_funbio_candidates import build_candidate

        url = "/floresta-viva-piaui/download/regulamento-edital-2026.pdf"
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
        assert meta["source"] == "funbio"
        assert meta["listing_url"] == LISTING_URL
        assert meta["detail_url"] == DETAIL_URL
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_funbio_candidates import build_candidate

        url = "/static/regulamento-edital-2025.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_funbio_candidates import build_candidate

        url = "/static/resultado-final-2026.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_listing_and_detail_pages_yield_pdf_candidates(self) -> None:
        from discover_funbio_candidates import discover_candidates

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 1
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 1

        urls = [c["url"] for c in candidates]
        assert (
            "https://chamadas.funbio.org.br/floresta-viva-piaui/download/regulamento"
            "?id=abdb24f9-beb5-4779-b3c2-2d2fe9bb93d5"
        ) in urls

        candidate = candidates[0]
        assert candidate["metadata"]["origin"] == "detail_page"
        assert candidate["metadata"]["listing_url"] == LISTING_URL
        assert candidate["metadata"]["detail_url"] == DETAIL_URL

    def test_year_filter_excludes_pre_2026_pdf(self) -> None:
        from discover_funbio_candidates import discover_candidates

        listing_html = """
        <html><body>
          <a href="/floresta-2025">Floresta 2025</a>
        </body></html>
        """
        detail_html = """
        <html><body>
          <a href="/static/regulamento-edital-2025.pdf">Regulamento 2025</a>
        </body></html>
        """
        responses = {
            LISTING_URL: make_response(listing_html),
            "https://chamadas.funbio.org.br/floresta-2025": make_response(detail_html),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["year_rejected"] == 1

    def test_listing_fetch_failure_is_logged(self) -> None:
        from discover_funbio_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_funbio_source(self) -> None:
        import discover_funbio_candidates as dpc

        candidate = {
            "url": "https://chamadas.funbio.org.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "funbio"},
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
        assert call_args.kwargs["source"] == "funbio"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_funbio_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_funbio_candidates as dpc

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