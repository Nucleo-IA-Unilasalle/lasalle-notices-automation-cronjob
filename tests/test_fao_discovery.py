"""Unit tests for ``scripts/discover_fao_candidates.py``.

Ports the FAO source from
``lasalle-notices-automation/app/services/scraper/playwright/fao.py``
into the cronjob, locking the discovery contract before Phase 4 ships.
Tests exercise the ``extract_fao_pdf_urls`` helper plus the two-stage
discovery (BS4 primary path, Playwright fallback when the BS4 path
returns nothing) and the ``process_candidate`` / ``submit_candidates``
handoff.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "fao"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"


LISTING_URL = "https://www.fao.org/plant-treaty/areas-of-work/funding/"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractFaoPdfUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_signal_pdf_urls(self) -> None:
        from bs4 import BeautifulSoup

        from discover_fao_candidates import extract_fao_pdf_urls

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        discovered = extract_fao_pdf_urls(soup, LISTING_URL)

        # The fixture has 6 anchors:
        # - /4/cd1234en/cd1234en.pdf -> signal (call for proposals)
        # - https://openknowledge.fao.org/.../call-for-proposals-climate-2027.pdf -> signal
        # - duplicate /4/cd1234en/cd1234en.pdf -> deduped
        # - /publications/annual-report-2026.pdf -> no signal (annual report)
        # - https://example.org/... -> external host, dropped
        # - /news/detail -> non-PDF, dropped
        assert discovered == [
            "https://www.fao.org/4/cd1234en/cd1234en.pdf",
            "https://openknowledge.fao.org/server/api/core/bitstreams/4f6f/content/call-for-proposals-climate-2027.pdf?download=1",
        ]

    def test_rejects_external_hosts(self) -> None:
        from bs4 import BeautifulSoup

        from discover_fao_candidates import extract_fao_pdf_urls

        html = """
        <html><body>
          <a href="https://external.example.org/call-for-proposals.pdf">Externo</a>
          <a href="https://www.fao.org/call-for-proposals.pdf">Valido</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_fao_pdf_urls(soup, LISTING_URL) == [
            "https://www.fao.org/call-for-proposals.pdf",
        ]

    def test_rejects_non_pdf_anchors(self) -> None:
        from bs4 import BeautifulSoup

        from discover_fao_candidates import extract_fao_pdf_urls

        html = """
        <html><body>
          <a href="/resources/report/call-for-proposals.docx">DOCX</a>
          <a href="/resources/page/procurement">Sem extensao</a>
          <a href="/resources/procurement-2026.pdf">PDF</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_fao_pdf_urls(soup, LISTING_URL) == [
            "https://www.fao.org/resources/procurement-2026.pdf",
        ]

    def test_strips_url_fragment(self) -> None:
        from bs4 import BeautifulSoup

        from discover_fao_candidates import extract_fao_pdf_urls

        html = """
        <html><body>
          <a href="/resources/procurement-2026.pdf#page=2">Fragment</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_fao_pdf_urls(soup, LISTING_URL) == [
            "https://www.fao.org/resources/procurement-2026.pdf",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_fao_candidates import FAO_LISTING_URL

        assert FAO_LISTING_URL == (
            "https://www.fao.org/plant-treaty/areas-of-work/funding/"
        )


class TestDiscoverCandidates:
    def test_listing_yields_signal_pdf_candidates_via_bs4(self) -> None:
        from discover_fao_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))},
        ):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["listings_fetched"] == 1
        assert stats["playwright_fallback_used"] == 0

        urls = [c["url"] for c in candidates]
        assert "https://www.fao.org/4/cd1234en/cd1234en.pdf" in urls

    def test_playwright_fallback_used_when_bs4_yields_nothing(self) -> None:
        from discover_fao_candidates import discover_candidates
        import discover_fao_candidates as dfc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response("<html><body>No PDFs here</body></html>")},
        ):
            with patch.object(dfc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = [
                    "https://www.fao.org/call-for-proposals-2026.pdf",
                ]
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 1
        assert stats["playwright_fallback_used"] == 1
        urls = [c["url"] for c in candidates]
        assert "https://www.fao.org/call-for-proposals-2026.pdf" in urls

    def test_playwright_fallback_not_used_when_bs4_yields_results(self) -> None:
        from discover_fao_candidates import discover_candidates
        import discover_fao_candidates as dfc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))},
        ):
            with patch.object(dfc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_listing_html_is_not_fetched_twice_for_bs4_results(self) -> None:
        from discover_fao_candidates import discover_candidates
        import discover_fao_candidates as dfc

        calls: list[str] = []

        def fake_request(*, method: str, url: str, timeout: int, **_: object) -> object:
            calls.append(url)
            if len(calls) > 1:
                raise requests.ConnectionError("second fetch should not happen")
            return make_response(_read_fixture(LISTING_FIXTURE))

        with patch_request_with_safe_redirects(fake_request):
            with patch.object(dfc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["errors"] == 0
        assert stats["playwright_fallback_used"] == 0
        assert calls == [LISTING_URL]
        mock_pw.assert_not_called()

    def test_listing_fetch_failure_falls_back_to_playwright(self) -> None:
        from discover_fao_candidates import discover_candidates
        import discover_fao_candidates as dfc

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            with patch.object(dfc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert stats["playwright_fallback_used"] == 1
        assert candidates == []


class TestPlaywrightFallback:
    """The Playwright fallback imports ``async_playwright`` lazily and
    feeds every anchor's ``href``/``title``/``aria-label``/text back
    through ``extract_fao_pdf_urls``.
    """

    def _fake_async_pw(self, links: list[dict[str, str]]) -> MagicMock:
        """Build a fake ``async_playwright`` that yields ``links``.

        Each link is a dict with ``href``, ``title``, ``aria-label``,
        and ``text`` keys; the fake page returns the matching values
        from its async getters.
        """
        fake_links: list[MagicMock] = []
        for link in links:
            attrs = {
                "href": link.get("href", ""),
                "title": link.get("title", ""),
                "aria-label": link.get("aria-label", ""),
            }
            anchor = MagicMock()
            anchor.get_attribute = AsyncMock(
                side_effect=lambda attr, _a=attrs: _a.get(attr, ""),
            )
            anchor.inner_text = AsyncMock(return_value=link.get("text", ""))
            fake_links.append(anchor)

        fake_page = MagicMock()
        fake_page.goto = AsyncMock()
        fake_page.query_selector_all = AsyncMock(return_value=fake_links)

        fake_context = MagicMock()
        fake_context.new_page = AsyncMock(return_value=fake_page)

        fake_browser = MagicMock()
        fake_browser.new_context = AsyncMock(return_value=fake_context)
        fake_browser.close = AsyncMock()

        fake_pw = MagicMock()
        fake_pw.chromium.launch = AsyncMock(return_value=fake_browser)

        class _ACMGate:
            def __init__(self, value: object) -> None:
                self.value = value

            async def __aenter__(self) -> object:
                return self.value

            async def __aexit__(self, *_: object) -> bool:
                return False

        fake_async_pw = MagicMock(return_value=_ACMGate(fake_pw))
        return fake_async_pw

    def _patched_asyncio_run(self, coro: Any) -> Any:
        """Run a coroutine to completion without touching the running loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_run_playwright_fallback_returns_pdfs_from_page(self) -> None:
        import types

        import discover_fao_candidates as dfc

        fake_pw = self._fake_async_pw(
            [
                {
                    "href": "/4/cd5678en/call-for-proposals-2026.pdf",
                    "text": "Call for Proposals 2026",
                },
                {
                    "href": "https://example.org/external.pdf",
                    "text": "External",
                },
            ],
        )

        fake_async_api = types.ModuleType("playwright.async_api")
        fake_async_api.async_playwright = fake_pw  # type: ignore[attr-defined]
        fake_playwright = types.ModuleType("playwright")
        fake_playwright.async_api = fake_async_api  # type: ignore[attr-defined]

        stats: dict[str, int] = {}
        with patch.dict(
            sys.modules,
            {
                "playwright": fake_playwright,
                "playwright.async_api": fake_async_api,
            },
        ):
            with patch.object(dfc.asyncio, "run", side_effect=self._patched_asyncio_run):
                pdfs = dfc._run_playwright_fallback(LISTING_URL, stats=stats)

        assert pdfs == [
            "https://www.fao.org/4/cd5678en/call-for-proposals-2026.pdf",
        ]

    def test_run_playwright_fallback_returns_empty_when_playwright_missing(
        self,
    ) -> None:
        import discover_fao_candidates as dfc

        stats: dict[str, int] = {}

        def _raise_import_error(coro: Any) -> object:
            coro.close()
            raise ImportError("playwright")

        with patch.object(dfc.asyncio, "run", side_effect=_raise_import_error):
            pdfs = dfc._run_playwright_fallback(LISTING_URL, stats=stats)

        assert pdfs == []
        assert stats["errors"] == 1


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_fao_source(self) -> None:
        import discover_fao_candidates as dfc

        candidate = {
            "url": "https://www.fao.org/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "fao"},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-22T12:00:00+00:00",
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
            with patch.object(dfc, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dfc.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dfc.pipeline_core,
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
                            dfc.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "fao"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_fao_candidates as dfc

        with patch.dict("os.environ", {}, clear=True):
            assert dfc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_fao_candidates as dfc

        with patch.object(dfc, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dfc.main() == 0
