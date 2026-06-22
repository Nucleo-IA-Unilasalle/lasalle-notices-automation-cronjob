"""Unit tests for ``scripts/discover_worldbank_candidates.py``.

Ports the WorldBank source from
``lasalle-notices-automation/app/services/scraper/playwright/worldbank.py``
into the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_worldbank_pdf_urls`` helper plus the
two-stage discovery (BS4 primary path, Playwright fallback when the
BS4 path returns nothing), year guard, ``is_likely_edital`` prefilter,
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

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "worldbank"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"


LISTING_URL = (
    "https://www.worldbank.org/en/programs/sief-trust-fund/brief/"
    "sief-call-for-proposals-8-edtech-for-foundational-learning"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractWorldbankPdfUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_signal_pdf_urls(self) -> None:
        from bs4 import BeautifulSoup

        from discover_worldbank_candidates import extract_worldbank_pdf_urls

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        discovered = extract_worldbank_pdf_urls(soup, LISTING_URL)

        # The fixture has 5 anchors:
        # - /content/dam/.../call-for-proposals-forest-2026.pdf -> signal
        # - https://thedocs.../call-for-proposals-energy-2027.pdf?download=1 -> signal
        # - duplicate with fragment -> deduped
        # - /content/dam/.../annual-report-2026.pdf -> no signal (annual report)
        # - https://example.org/... -> external host, dropped
        assert discovered == [
            "https://www.worldbank.org/content/dam/worldbank/documents/procurement/"
            "call-for-proposals-forest-2026.pdf",
            "https://thedocs.worldbank.org/en/doc/abc123/"
            "call-for-proposals-energy-2027.pdf?download=1",
        ]

    def test_rejects_external_hosts(self) -> None:
        from bs4 import BeautifulSoup

        from discover_worldbank_candidates import extract_worldbank_pdf_urls

        html = """
        <html><body>
          <a href="https://external.example.org/call-for-proposals.pdf">Externo</a>
          <a href="https://www.worldbank.org/call-for-proposals.pdf">Valido</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_worldbank_pdf_urls(soup, LISTING_URL) == [
            "https://www.worldbank.org/call-for-proposals.pdf",
        ]

    def test_rejects_non_pdf_anchors(self) -> None:
        from bs4 import BeautifulSoup

        from discover_worldbank_candidates import extract_worldbank_pdf_urls

        html = """
        <html><body>
          <a href="/resources/report/call-for-proposals.docx">DOCX</a>
          <a href="/resources/page/procurement">Sem extensao</a>
          <a href="/resources/procurement-2026.pdf">PDF</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_worldbank_pdf_urls(soup, LISTING_URL) == [
            "https://www.worldbank.org/resources/procurement-2026.pdf",
        ]

    def test_strips_url_fragment(self) -> None:
        from bs4 import BeautifulSoup

        from discover_worldbank_candidates import extract_worldbank_pdf_urls

        html = """
        <html><body>
          <a href="/content/dam/worldbank/procurement.pdf#page=2">Fragment</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_worldbank_pdf_urls(soup, LISTING_URL) == [
            "https://www.worldbank.org/content/dam/worldbank/procurement.pdf",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_worldbank_candidates import WORLDBANK_LISTING_URL

        assert WORLDBANK_LISTING_URL == (
            "https://www.worldbank.org/en/programs/sief-trust-fund/brief/"
            "sief-call-for-proposals-8-edtech-for-foundational-learning"
        )


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WORLDBANK_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_worldbank_candidates"),
        )
        assert module.WORLDBANK_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORLDBANK_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_worldbank_candidates"),
        )
        assert module.WORLDBANK_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("WORLDBANK_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_worldbank_candidates"))

    def test_year_extracted_from_pdf_path(self) -> None:
        from discover_worldbank_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.worldbank.org/content/dam/worldbank/procurement/call-for-proposals-2026.pdf",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_worldbank_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.worldbank.org/content/dam/worldbank/procurement.pdf",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_worldbank_candidates import _passes_year_guard

        url_2024 = "https://www.worldbank.org/content/dam/worldbank/procurement-2024.pdf"
        url_2026 = "https://www.worldbank.org/content/dam/worldbank/procurement-2026.pdf"
        url_unknown = "https://www.worldbank.org/content/dam/worldbank/procurement.pdf"

        assert _passes_year_guard(url_2024, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_worldbank_candidates import _candidate_passes_edital_prefilter

        url = "https://www.worldbank.org/content/dam/worldbank/edital-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_worldbank_candidates import _candidate_passes_edital_prefilter

        url = "https://www.worldbank.org/content/dam/worldbank/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_worldbank_candidates import _candidate_passes_edital_prefilter

        url = "https://www.worldbank.org/content/dam/worldbank/resultado-final-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_worldbank_candidates import build_candidate

        url = "https://www.worldbank.org/content/dam/worldbank/call-for-proposals-2026.pdf"
        before = datetime.now(timezone.utc)
        candidate = build_candidate(url, listing_url=LISTING_URL)
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "worldbank"
        assert meta["listing_url"] == LISTING_URL
        assert meta["extracted_year"] == 2026
        assert meta["origin"] == "listing_pdf"
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_worldbank_candidates import build_candidate

        url = "https://www.worldbank.org/content/dam/worldbank/call-for-proposals-2025.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_worldbank_candidates import build_candidate

        url = "https://www.worldbank.org/content/dam/worldbank/resultado-final-2026.pdf"
        assert build_candidate(url, listing_url=LISTING_URL) is None


class TestDiscoverCandidates:
    def test_listing_yields_signal_pdf_candidates_via_bs4(self) -> None:
        from discover_worldbank_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))},
        ):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["listings_fetched"] == 1
        assert stats["playwright_fallback_used"] == 0

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.worldbank.org/content/dam/worldbank/documents/procurement/"
            "call-for-proposals-forest-2026.pdf"
        ) in urls

    def test_playwright_fallback_used_when_bs4_yields_nothing(self) -> None:
        from discover_worldbank_candidates import discover_candidates
        import discover_worldbank_candidates as dpc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response("<html><body>No PDFs here</body></html>")},
        ):
            with patch.object(dpc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = [
                    "https://www.worldbank.org/call-for-proposals-2026.pdf",
                ]
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 1
        assert stats["playwright_fallback_used"] == 1
        urls = [c["url"] for c in candidates]
        assert "https://www.worldbank.org/call-for-proposals-2026.pdf" in urls
        assert candidates[0]["metadata"]["origin"] == "listing_pdf"

    def test_playwright_fallback_not_used_when_bs4_yields_results(self) -> None:
        from discover_worldbank_candidates import discover_candidates
        import discover_worldbank_candidates as dpc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))},
        ):
            with patch.object(dpc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_year_filter_excludes_pre_2026_pdf(self) -> None:
        from discover_worldbank_candidates import discover_candidates

        html = """
        <html><body>
          <a href="/content/dam/worldbank/call-for-proposals-2025.pdf">2025</a>
          <a href="/content/dam/worldbank/call-for-proposals-2026.pdf">2026</a>
        </body></html>
        """
        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(html)},
        ):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.worldbank.org/content/dam/worldbank/call-for-proposals-2025.pdf"
        ) not in urls
        assert (
            "https://www.worldbank.org/content/dam/worldbank/call-for-proposals-2026.pdf"
        ) in urls
        assert stats["year_rejected"] == 1

    def test_listing_fetch_failure_falls_back_to_playwright(self) -> None:
        from discover_worldbank_candidates import discover_candidates
        import discover_worldbank_candidates as dpc

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            with patch.object(dpc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert stats["playwright_fallback_used"] == 1
        assert candidates == []


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_worldbank_source(self) -> None:
        import discover_worldbank_candidates as dpc

        candidate = {
            "url": "https://www.worldbank.org/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "worldbank"},
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
        assert call_args.kwargs["source"] == "worldbank"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_worldbank_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_worldbank_candidates as dpc

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