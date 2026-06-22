"""Unit tests for ``scripts/discover_wwf_candidates.py``.

Ports the WWF source from
``lasalle-notices-automation/app/services/scraper/sources/wwf.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_wwf_detail_urls`` helper plus the two-
stage discovery (listing direct PDFs + detail-page PDFs), year guard,
``is_likely_edital`` prefilter, and the ``process_candidate`` /
``submit_candidates`` handoff.
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
DETAIL_FIXTURE = FIXTURES_DIR / "detail.html"


LISTING_URL = "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/"
DETAIL_URL = (
    "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/?uNewsID=94482"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractWwfDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_detail_urls(self) -> None:
        from discover_wwf_candidates import extract_wwf_detail_urls

        discovered = extract_wwf_detail_urls(
            _read_fixture(LISTING_FIXTURE), LISTING_URL,
        )

        assert discovered == [
            "https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/?uNewsID=94482",
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


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WWF_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_wwf_candidates"),
        )
        assert module.WWF_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WWF_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_wwf_candidates"),
        )
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
        candidate = build_candidate(
            url,
            listing_url=LISTING_URL,
            origin="listing_pdf",
        )
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "wwf"
        assert meta["listing_url"] == LISTING_URL
        assert meta["origin"] == "listing_pdf"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_records_detail_origin(self) -> None:
        from discover_wwf_candidates import build_candidate

        url = "https://wwfbrnew.awsassets.panda.org/downloads/edital-2026.pdf"
        candidate = build_candidate(
            url,
            listing_url=LISTING_URL,
            detail_url=DETAIL_URL,
            origin="detail_page",
        )

        assert candidate is not None
        assert candidate["metadata"]["detail_url"] == DETAIL_URL
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
    def test_listing_yields_direct_pdfs_and_detail_page_pdfs(self) -> None:
        from discover_wwf_candidates import discover_candidates

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        # 1 listing PDF + 2 detail PDFs (carta-convite + divulgacao dup),
        # deduped to 2 unique URLs.
        assert stats["candidates"] == 2
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 1

        urls = [c["url"] for c in candidates]
        assert (
            "https://wwfbrnew.awsassets.panda.org/downloads/divulgacao_site_v3_sc005094.pdf"
        ) in urls
        assert (
            "https://wwfbrnew.awsassets.panda.org/downloads/carta-convite-concorrencia_analise-territorial-no-medio-e-baixo-tapajos_005094.pdf"
        ) in urls

        listing_origin_candidate = next(
            c for c in candidates
            if c["url"].endswith("divulgacao_site_v3_sc005094.pdf")
            and c["metadata"]["origin"] == "listing_pdf"
        )
        assert (
            "detail_url" not in listing_origin_candidate["metadata"]
        )

    def test_year_filter_excludes_pre_2026_pdf(self) -> None:
        from discover_wwf_candidates import discover_candidates

        listing_html = """
        <html>
          <body>
            <a href="/sobrenos/aquisicoesecontratacoes/?uNewsID=1">Processo 1</a>
            <a href="https://wwfbrnew.awsassets.panda.org/downloads/edital-2025.pdf">PDF 2025 direto</a>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <a href="https://wwfbrnew.awsassets.panda.org/downloads/anexo-2025.pdf">PDF 2025</a>
          </body>
        </html>
        """
        responses = {
            LISTING_URL: make_response(listing_html),
            DETAIL_URL.replace("94482", "1"): make_response(detail_html),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert "https://wwfbrnew.awsassets.panda.org/downloads/edital-2025.pdf" not in urls
        assert "https://wwfbrnew.awsassets.panda.org/downloads/anexo-2025.pdf" not in urls
        assert stats["year_rejected"] >= 1

    def test_listing_fetch_failure_is_logged(self) -> None:
        from discover_wwf_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []


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