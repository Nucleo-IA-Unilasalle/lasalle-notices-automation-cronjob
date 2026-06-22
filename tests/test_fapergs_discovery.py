"""Unit tests for ``scripts/discover_fapergs_candidates.py``.

Ports the FAPERGS source from
``lasalle-notices-automation/app/services/scraper/sources/fapergs.py``
into the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_fapergs_detail_urls`` helper plus the
two-stage discovery (static listing + AJAX endpoint + detail pages),
year guard, ``is_likely_edital`` prefilter, and the
``process_candidate`` / ``submit_candidates`` handoff.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "fapergs"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_CENTELHA_FIXTURE = FIXTURES_DIR / "detail_centelha.html"


LISTING_URL = "https://fapergs.rs.gov.br/abertos?classificacao=3242"
AJAX_URL = (
    "https://fapergs.rs.gov.br/_service/conteudo/pagedlistfilho"
    "?id=2042&currentPage=1&pageSize=50"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractFapergsDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_detail_urls(self) -> None:
        from discover_fapergs_candidates import extract_fapergs_detail_urls

        discovered = extract_fapergs_detail_urls(
            _read_fixture(LISTING_FIXTURE), LISTING_URL,
        )

        assert discovered == [
            "https://fapergs.rs.gov.br/programa-centelha-rs-2025",
            "https://fapergs.rs.gov.br/edital-outro-exemplo-2025",
        ]

    def test_rejects_off_host_and_non_signal_links(self) -> None:
        from discover_fapergs_candidates import extract_fapergs_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="https://outro-dominio.rs.gov.br/edital">Outro dominio</a>
            <a href="/noticias/institucional">Sem sinal</a>
            <a href="/programa-centelha-rs-2026">Centelha</a>
          </body>
        </html>
        """
        assert extract_fapergs_detail_urls(
            listing_html, LISTING_URL,
        ) == ["https://fapergs.rs.gov.br/programa-centelha-rs-2026"]

    def test_skips_direct_pdf_anchors(self) -> None:
        from discover_fapergs_candidates import extract_fapergs_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/chamada-2026/edital.pdf">PDF direto</a>
            <a href="/chamada-2026">Detalhe</a>
          </body>
        </html>
        """
        assert extract_fapergs_detail_urls(
            listing_html, LISTING_URL,
        ) == ["https://fapergs.rs.gov.br/chamada-2026"]


class TestListingUrls:
    def test_default_listing_urls(self) -> None:
        from discover_fapergs_candidates import (
            FAPERGS_LISTING_URL,
            FAPERGS_AJAX_URL,
        )

        assert FAPERGS_LISTING_URL == "https://fapergs.rs.gov.br/abertos?classificacao=3242"
        assert FAPERGS_AJAX_URL == (
            "https://fapergs.rs.gov.br/_service/conteudo/pagedlistfilho"
            "?id=2042&currentPage=1&pageSize=50"
        )


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FAPERGS_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_fapergs_candidates"),
        )
        assert module.FAPERGS_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FAPERGS_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_fapergs_candidates"),
        )
        assert module.FAPERGS_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("FAPERGS_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_fapergs_candidates"))

    def test_year_extracted_from_detail_path(self) -> None:
        from discover_fapergs_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://fapergs.rs.gov.br/programa-centelha-rs-2026",
        ) == 2026

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_fapergs_candidates import _passes_year_guard

        assert _passes_year_guard(
            "https://fapergs.rs.gov.br/programa-centelha-rs-2025",
            min_year=2026,
        ) is False
        assert _passes_year_guard(
            "https://fapergs.rs.gov.br/programa-centelha-rs-2026",
            min_year=2026,
        ) is True
        assert _passes_year_guard(
            "https://fapergs.rs.gov.br/abertos?classificacao=3242",
            min_year=2026,
        ) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_fapergs_candidates import _candidate_passes_edital_prefilter

        url = "https://fapergs.rs.gov.br/upload/arquivos/2025/edital-centelha.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_fapergs_candidates import _candidate_passes_edital_prefilter

        url = "https://fapergs.rs.gov.br/upload/arquivos/2025/resultado-final.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_fapergs_candidates import _candidate_passes_edital_prefilter

        url = "https://fapergs.rs.gov.br/upload/arquivos/2025/resultado-final.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_fapergs_candidates import build_candidate

        url = "https://fapergs.rs.gov.br/upload/arquivos/2025/edital-2026.pdf"
        detail = "https://fapergs.rs.gov.br/programa-centelha-rs-2026"
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
        assert meta["source"] == "fapergs"
        assert meta["listing_url"] == LISTING_URL
        assert meta["detail_url"] == detail
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_fapergs_candidates import build_candidate

        url = "https://fapergs.rs.gov.br/upload/arquivos/2025/edital-2025.pdf"
        assert build_candidate(
            url,
            listing_url=LISTING_URL,
            detail_url="https://fapergs.rs.gov.br/programa-centelha-rs-2025",
        ) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_fapergs_candidates import build_candidate

        url = "https://fapergs.rs.gov.br/upload/arquivos/2025/resultado-final-2026.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_static_listing_yields_pdfs_from_each_detail_page(self) -> None:
        from discover_fapergs_candidates import discover_candidates

        listing_html = _read_fixture(LISTING_FIXTURE)
        detail_html = _read_fixture(DETAIL_CENTELHA_FIXTURE)

        # Override the fixture detail URLs (which are 2025) with 2026
        # variants so they survive the year guard at min_year=2026.
        listing_html_2026 = listing_html.replace(
            "programa-centelha-rs-2025", "programa-centelha-rs-2026",
        ).replace(
            "edital-outro-exemplo-2025", "edital-outro-exemplo-2026",
        )
        detail_html_2026 = detail_html.replace(
            "/2025/", "/2026/",
        ).replace(
            "anexo-centelha", "anexo-centelha-2026",
        )

        centelha_url = "https://fapergs.rs.gov.br/programa-centelha-rs-2026"
        other_url = "https://fapergs.rs.gov.br/edital-outro-exemplo-2026"

        responses = {
            LISTING_URL: make_response(listing_html_2026),
            centelha_url: make_response(detail_html_2026),
            other_url: make_response("<html></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 2
        urls = [c["url"] for c in candidates]
        assert "https://fapergs.rs.gov.br/upload/arquivos/2026/centelha.pdf" in urls
        assert (
            "https://fapergs.rs.gov.br/upload/arquivos/2026/anexo-centelha-2026.pdf?download=1"
        ) in urls

    def test_ajax_response_adds_detail_urls(self) -> None:
        from discover_fapergs_candidates import discover_candidates

        static_listing = """
        <html><body></body></html>
        """
        ajax_body = """
        <html>
          <body>
            <a href="/ajax-edital-2026">Edital via AJAX</a>
          </body>
        </html>
        """
        ajax_payload = {"body": ajax_body, "pagecount": 1}
        ajax_response = MagicMock()
        ajax_response.status_code = 200
        ajax_response.raise_for_status = MagicMock()
        ajax_response.json.return_value = ajax_payload

        ajax_detail = make_response(
            "<html><body><a href='/upload/arquivos/ajax-edital.pdf'>PDF</a></body></html>",
        )

        responses = {
            LISTING_URL: make_response(static_listing),
            AJAX_URL: ajax_response,
            "https://fapergs.rs.gov.br/ajax-edital-2026": ajax_detail,
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert "https://fapergs.rs.gov.br/upload/arquivos/ajax-edital.pdf" in urls

    def test_year_filter_excludes_pre_2026_detail_urls(self) -> None:
        from discover_fapergs_candidates import discover_candidates

        listing_html = """
        <html>
          <body>
            <a href="/edital-2025">Edital 2025</a>
          </body>
        </html>
        """
        # PDF URL itself carries 2025 so the year guard rejects it
        # without depending on inherited detail-URL year metadata.
        detail_html = "<a href='/upload/arquivos/2025/edital.pdf'>PDF</a>"

        responses = {
            LISTING_URL: make_response(listing_html),
            "https://fapergs.rs.gov.br/edital-2025": make_response(detail_html),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["year_rejected"] == 1

    def test_listing_fetch_failure_is_logged(self) -> None:
        import requests

        from discover_fapergs_candidates import discover_candidates

        with patch_request_with_safe_redirects({LISTING_URL: requests.ConnectionError("down")}):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_fapergs_source(self) -> None:
        import discover_fapergs_candidates as dpc

        candidate = {
            "url": "https://fapergs.rs.gov.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "fapergs"},
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
        assert call_args.kwargs["source"] == "fapergs"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_fapergs_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_fapergs_candidates as dpc

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
