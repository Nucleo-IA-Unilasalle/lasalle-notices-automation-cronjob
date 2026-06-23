"""Unit tests for ``scripts/discover_tnc_candidates.py``.

Ports the TNC source from
``lasalle-notices-automation/app/services/scraper/sources/tnc.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_tnc_detail_urls`` helper (including its
JSON ``data-details`` aggregation payload handling), the two-stage
discovery (listing -> detail pages), year guard, ``is_likely_edital``
prefilter, and the ``process_candidate`` / ``submit_candidates`` handoff.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "tnc"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_FIXTURE = FIXTURES_DIR / "detail.html"


LISTING_URL = "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"
DETAIL_URL = (
    "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"
    "fomentar-a-inovacao-fortalecer-a-conservacao"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractTncDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_detail_urls_from_anchors_and_json_payload(self) -> None:
        from discover_tnc_candidates import extract_tnc_detail_urls

        discovered = extract_tnc_detail_urls(
            _read_fixture(LISTING_FIXTURE), LISTING_URL,
        )

        # The fixture has 2 anchors and 1 JSON payload entry, all
        # pointing to the same `/fomentar-a-inovacao-fortalecer-a-conservacao`
        # URL and 1 separate `/parcerias-para-fortalecer-a-ciencia-na-amazonia`.
        # The anchor pointing to "/noticia-institucional-sem-sinal" lacks a
        # signal token and is dropped.
        assert discovered == [
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"
            "fomentar-a-inovacao-fortalecer-a-conservacao",
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"
            "parcerias-para-fortalecer-a-ciencia-na-amazonia",
        ]

    def test_rejects_off_host_and_off_path_links(self) -> None:
        from discover_tnc_candidates import extract_tnc_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="https://example.org/conecte-se/comunicacao/noticias/edital">Outro host</a>
            <a href="/sobre/a-organizacao">Path fora</a>
            <a href="/conecte-se/comunicacao/noticias/categoria">Sem slug</a>
            <a href="/conecte-se/comunicacao/noticias/edital-2026">Valido</a>
          </body>
        </html>
        """
        assert extract_tnc_detail_urls(listing_html, LISTING_URL) == [
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/edital-2026",
        ]

    def test_requires_signal_token(self) -> None:
        from discover_tnc_candidates import extract_tnc_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/conecte-se/comunicacao/noticias/institucional">Sem sinal</a>
            <a href="/conecte-se/comunicacao/noticias/edital-2026">Com sinal</a>
          </body>
        </html>
        """
        assert extract_tnc_detail_urls(listing_html, LISTING_URL) == [
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/edital-2026",
        ]

    def test_json_payload_is_parsed(self) -> None:
        from discover_tnc_candidates import extract_tnc_detail_urls

        listing_html = """
        <html>
          <body>
            <span class="articleAggregationDetailsStr" data-details='[{"link":"https://www.tnc.org.br/conecte-se/comunicacao/noticias/edital-json-2026","title":"Edital JSON","description":"chamada publica"}]'></span>
          </body>
        </html>
        """
        assert extract_tnc_detail_urls(listing_html, LISTING_URL) == [
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/edital-json-2026",
        ]

    def test_malformed_json_payload_is_ignored(self) -> None:
        from discover_tnc_candidates import extract_tnc_detail_urls

        listing_html = """
        <html>
          <body>
            <span class="articleAggregationDetailsStr" data-details="not-json{"></span>
            <a href="/conecte-se/comunicacao/noticias/edital-anchor-2026">Edital</a>
          </body>
        </html>
        """
        assert extract_tnc_detail_urls(listing_html, LISTING_URL) == [
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/edital-anchor-2026",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_tnc_candidates import TNC_LISTING_URL

        assert TNC_LISTING_URL == "https://www.tnc.org.br/conecte-se/comunicacao/noticias/"


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TNC_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_tnc_candidates"),
        )
        assert module.TNC_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TNC_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_tnc_candidates"),
        )
        assert module.TNC_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("TNC_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_tnc_candidates"))

    def test_year_extracted_from_pdf_path(self) -> None:
        from discover_tnc_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2026.pdf",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_tnc_candidates import _extract_year_from_url

        assert _extract_year_from_url(DETAIL_URL) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_tnc_candidates import _passes_year_guard

        url_2025 = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2025.pdf"
        url_2026 = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2026.pdf"
        url_unknown = DETAIL_URL

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_tnc_candidates import _candidate_passes_edital_prefilter

        url = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_tnc_candidates import _candidate_passes_edital_prefilter

        url = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-resultado-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_tnc_candidates import _candidate_passes_edital_prefilter

        url = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-resultado-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_tnc_candidates import build_candidate

        url = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2026.pdf"
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
        assert meta["source"] == "tnc"
        assert meta["listing_url"] == LISTING_URL
        assert meta["detail_url"] == DETAIL_URL
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_tnc_candidates import build_candidate

        url = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2025.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_tnc_candidates import build_candidate

        url = "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-resultado-2026.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_listing_and_detail_pages_yield_pdf_candidates(self) -> None:
        from discover_tnc_candidates import discover_candidates

        responses = {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            DETAIL_URL: make_response(_read_fixture(DETAIL_FIXTURE)),
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/parcerias-para-fortalecer-a-ciencia-na-amazonia": make_response("<html></html>"),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 2

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-recomendacoescop26.pdf"
        ) in urls
        assert (
            "https://www.tnc.org.br/content/dam/tnc/nature/en/documents/brasil/tnc-policy-bioeconomia_ptbr.pdf"
        ) in urls

    def test_year_filter_excludes_pre_2026_pdf(self) -> None:
        from discover_tnc_candidates import discover_candidates

        listing_html = """
        <html>
          <body>
            <a href="/conecte-se/comunicacao/noticias/edital-2025">Edital 2025</a>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <a href="/content/dam/tnc/nature/en/documents/brasil/tnc-edital-2025.pdf">PDF 2025</a>
          </body>
        </html>
        """
        responses = {
            LISTING_URL: make_response(listing_html),
            "https://www.tnc.org.br/conecte-se/comunicacao/noticias/edital-2025": make_response(detail_html),
        }

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["year_rejected"] == 1

    def test_listing_fetch_failure_is_logged(self) -> None:
        from discover_tnc_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert candidates == []


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_tnc_source(self) -> None:
        import discover_tnc_candidates as dpc

        candidate = {
            "url": "https://www.tnc.org.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "tnc"},
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
        assert call_args.kwargs["source"] == "tnc"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_tnc_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_tnc_candidates as dpc

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