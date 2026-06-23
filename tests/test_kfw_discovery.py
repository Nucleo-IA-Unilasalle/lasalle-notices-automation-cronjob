"""Unit tests for ``scripts/discover_kfw_candidates.py``.

Ports the KfW source from
``lasalle-notices-automation/app/services/scraper/playwright/kfw.py``
into the cronjob, locking the discovery contract before Phase 4 ships.
Tests exercise the ``extract_kfw_pdf_urls`` helper plus the two-stage
discovery (BS4 primary path, Playwright fallback when the BS4 path
returns nothing) and the ``process_candidate`` / ``submit_candidates``
handoff.

KfW hosts the listing on ``kfw-entwicklungsbank.de`` (subpaths
``/service/procurement-regulations/``, ``/document-center/``, or
``/pdf/download-center/pdf-dokumente-richtlinien/``) and PDFs on
``kfw.de`` or ``kfw-entwicklungsbank.de``. The listing host is
gated: only PDFs under those three procurement subpaths are kept
when the host is ``kfw-entwicklungsbank.de``.
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

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "kfw"


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"


LISTING_URL = (
    "https://www.kfw-entwicklungsbank.de/Service/Procurement-Regulations/"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractKfwPdfUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_yields_signal_pdf_urls(self) -> None:
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        discovered = extract_kfw_pdf_urls(soup, LISTING_URL)

        # The fixture has 6 anchors:
        # - /service/procurement-regulations/KfW-Development-Bank-Procurement-Regulations.pdf -> signal
        # - https://www.kfw-entwicklungsbank.de/.../KfW-Consultant-Guidelines-Procurement.pdf?download=1 -> signal
        # - duplicate fragment -> deduped
        # - /service/reports/Annual-Report-2026.pdf -> no signal
        # - https://example.org/... -> external host, dropped
        # - /newsroom/latest-news/feature-story -> non-PDF, dropped
        assert discovered == [
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/KfW-Development-Bank-Procurement-Regulations.pdf",
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/KfW-Consultant-Guidelines-Procurement.pdf?download=1",
        ]

    def test_rejects_external_hosts(self) -> None:
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="https://external.example.org/procurement.pdf">Externo</a>
          <a href="https://www.kfw.de/procurement.pdf">Valido</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_kfw_pdf_urls(soup, LISTING_URL) == [
            "https://www.kfw.de/procurement.pdf",
        ]

    def test_rejects_non_pdf_anchors(self) -> None:
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="/resources/report/procurement.docx">DOCX</a>
          <a href="/resources/page/eoi">Sem extensao</a>
          <a href="/service/procurement-regulations/eoi-2026.pdf">PDF</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_kfw_pdf_urls(soup, LISTING_URL) == [
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/eoi-2026.pdf",
        ]

    def test_kfw_entwicklungsbank_host_path_gate(self) -> None:
        """Paths outside the procurement subpaths are dropped on
        ``kfw-entwicklungsbank.de``; signals are still required.
        """
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="https://www.kfw-entwicklungsbank.de/about-us/procurement-2026.pdf">Wrong path</a>
          <a href="https://www.kfw-entwicklungsbank.de/document-center/eoi-2026.pdf">Document center</a>
          <a href="https://www.kfw-entwicklungsbank.de/document-center/call-for-proposals.pdf">Document center signal</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        discovered = extract_kfw_pdf_urls(soup, LISTING_URL)
        assert discovered == [
            "https://www.kfw-entwicklungsbank.de/document-center/eoi-2026.pdf",
            "https://www.kfw-entwicklungsbank.de/document-center/call-for-proposals.pdf",
        ]

    def test_strips_url_fragment(self) -> None:
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="/service/procurement-regulations/eoi-2026.pdf#page=2">Fragment</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_kfw_pdf_urls(soup, LISTING_URL) == [
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/eoi-2026.pdf",
        ]


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_kfw_candidates import KFW_LISTING_URL

        assert KFW_LISTING_URL == (
            "https://www.kfw-entwicklungsbank.de/Service/Procurement-Regulations/"
        )


class TestDiscoverCandidates:
    def test_listing_yields_signal_pdf_candidates_via_bs4(self) -> None:
        from discover_kfw_candidates import discover_candidates

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))},
        ):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["listings_fetched"] == 1
        assert stats["playwright_fallback_used"] == 0

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/KfW-Development-Bank-Procurement-Regulations.pdf"
        ) in urls

    def test_playwright_fallback_used_when_bs4_yields_nothing(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response("<html><body>No PDFs here</body></html>")},
        ):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = [
                    "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/call-for-proposals-2026.pdf",
                ]
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 1
        assert stats["playwright_fallback_used"] == 1
        urls = [c["url"] for c in candidates]
        assert (
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/call-for-proposals-2026.pdf"
        ) in urls

    def test_playwright_fallback_not_used_when_bs4_yields_results(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE))},
        ):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_listing_html_is_not_fetched_twice_for_bs4_results(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        calls: list[str] = []

        def fake_request(*, method: str, url: str, timeout: int, **_: object) -> object:
            calls.append(url)
            if len(calls) > 1:
                raise requests.ConnectionError("second fetch should not happen")
            return make_response(_read_fixture(LISTING_FIXTURE))

        with patch_request_with_safe_redirects(fake_request):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 2
        assert stats["errors"] == 0
        assert stats["playwright_fallback_used"] == 0
        assert calls == [LISTING_URL]
        mock_pw.assert_not_called()

    def test_listing_fetch_failure_falls_back_to_playwright(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert stats["playwright_fallback_used"] == 1
        assert candidates == []


class TestPlaywrightFallback:
    """The Playwright fallback imports ``async_playwright`` lazily and
    feeds every anchor's ``href``/``title``/``aria-label``/text back
    through ``extract_kfw_pdf_urls``.
    """

    def _fake_async_pw(self, links: list[dict[str, str]]) -> MagicMock:
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
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_run_playwright_fallback_returns_pdfs_from_page(self) -> None:
        import types

        import discover_kfw_candidates as dkc

        fake_pw = self._fake_async_pw(
            [
                {
                    "href": "/service/procurement-regulations/eoi-2026.pdf",
                    "text": "Expression of Interest 2026",
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
            with patch.object(dkc.asyncio, "run", side_effect=self._patched_asyncio_run):
                pdfs = dkc._run_playwright_fallback(LISTING_URL, stats=stats)

        assert pdfs == [
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/eoi-2026.pdf",
        ]

    def test_run_playwright_fallback_returns_empty_when_playwright_missing(
        self,
    ) -> None:
        import discover_kfw_candidates as dkc

        stats: dict[str, int] = {}

        def _raise_import_error(coro: Any) -> object:
            coro.close()
            raise ImportError("playwright")

        with patch.object(dkc.asyncio, "run", side_effect=_raise_import_error):
            pdfs = dkc._run_playwright_fallback(LISTING_URL, stats=stats)

        assert pdfs == []
        assert stats["errors"] == 1


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_kfw_source(self) -> None:
        import discover_kfw_candidates as dkc

        candidate = {
            "url": "https://www.kfw-entwicklungsbank.de/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "kfw"},
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
            with patch.object(dkc, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dkc.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dkc.pipeline_core,
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
                            dkc.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "kfw"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_kfw_candidates as dkc

        with patch.dict("os.environ", {}, clear=True):
            assert dkc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_kfw_candidates as dkc

        with patch.object(dkc, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dkc.main() == 0
