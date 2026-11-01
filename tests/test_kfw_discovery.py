"""Unit tests for ``scripts/discover_kfw_candidates.py``.

Ports the KfW source from
``lasalle-notices-automation/app/services/scraper/playwright/kfw.py``
into the cronjob, locking the discovery contract before Phase 4 ships.
Tests exercise the ``extract_kfw_pdf_urls`` helper plus the two-stage
discovery (BS4 primary path, Playwright fallback only when the static
listing fetch fails; a fetched page with no call is an empty inventory) and the ``process_candidate`` / ``submit_candidates``
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

_LIBRARY_DIR = "/PDF/Download-Center/PDF-Dokumente-Richtlinien/"

# The 15 PDF anchors served by the live Procurement-Regulations page
# (captured 2026-10-30): guidelines in 4 languages x 3 editions plus the
# Sustainability Guideline. None is an open call.
LIVE_LIBRARY_PDFS = [
    "FZ-Vergaberichtlinien-V-2021-EN.pdf",
    "FZ-Vergaberichtlinien-V-2021-FR.pdf",
    "FZ-Vergaberichtlinien-V-2021-ES.pdf",
    "FZ-Vergaberichtlinien-V-2021-PT.pdf",
    "FC-Guidelines-for-Procurement-2023.pdf",
    "CF-Directives-pour-la-Passation-de-March%C3%A9s-2023-FR.pdf",
    "CF-Directrices-para-la-Contrataci%C3%B3n-2023-ES.pdf",
    "CF-Diretrizes-para-Contrata%C3%A7%C3%A3o-2023-PT.pdf",
    "FC-Guidelines-for-the-Procurement-2021.pdf",
    "CF-Directives-pour-la-Passation-2021.pdf",
    "CF-Directrices-para-la-Contrataci%C3%B3n-2021.pdf",
    "CF-Diretrizes-para-Contrata%C3%A7%C3%A3o-2021.pdf",
    "Nachhaltigkeitsrichtlinie_EN.pdf",
    "Nachhaltigkeitsrichtlinie_FR.pdf",
    "Nachhaltigkeitsrichtlinie_ES.pdf",
]


def _live_library_html() -> str:
    anchors = "\n".join(
        f'<a href="{_LIBRARY_DIR}{name}">English (PDF, 801 KB, non-accessible)</a>'
        for name in LIVE_LIBRARY_PDFS
    )
    return f"<html><body>{anchors}</body></html>"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestExtractKfwPdfUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_guidelines_are_not_candidates(self) -> None:
        """Procurement guidelines / regulations are reference documents.

        Both fixture PDFs carry ``procurement`` in the filename, which used
        to be enough to emit them as editais.
        """
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        assert extract_kfw_pdf_urls(soup, LISTING_URL) == []

    def test_live_library_page_yields_no_candidates(self) -> None:
        from discover_kfw_candidates import extract_kfw_pdf_urls

        assert extract_kfw_pdf_urls(_live_library_html(), LISTING_URL) == []

    def test_generic_procurement_filename_is_not_a_signal(self) -> None:
        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="/service/procurement-regulations/Procurement-Plan.pdf">Plan</a>
        </body></html>
        """
        assert extract_kfw_pdf_urls(html, LISTING_URL) == []

    def test_real_tender_document_is_still_emitted(self) -> None:
        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = _live_library_html().replace(
            "</body>",
            f'<a href="{_LIBRARY_DIR}Call-for-Proposals-Consulting-Services-2026.pdf">'
            "Call for Proposals - Consulting Services</a>"
            '<a href="/service/procurement-regulations/Invitation-to-Tender-Works-2026.pdf">'
            "Invitation to Tender</a>"
            "</body>",
        )
        assert extract_kfw_pdf_urls(html, LISTING_URL) == [
            "https://www.kfw-entwicklungsbank.de/PDF/Download-Center/PDF-Dokumente-Richtlinien/Call-for-Proposals-Consulting-Services-2026.pdf",
            "https://www.kfw-entwicklungsbank.de/service/procurement-regulations/Invitation-to-Tender-Works-2026.pdf",
        ]

    def test_guideline_with_call_vocabulary_is_rejected(self) -> None:
        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="/service/procurement-regulations/Call-for-Proposals-Guidelines.pdf">Guidelines</a>
          <a href="/service/procurement-regulations/eoi-2026.pdf">Procurement Guidelines for EOI</a>
        </body></html>
        """
        assert extract_kfw_pdf_urls(html, LISTING_URL) == []

    @pytest.mark.parametrize("name", LIVE_LIBRARY_PDFS)
    def test_reference_pattern_rejects_every_live_library_title_on_its_own(
        self, name: str,
    ) -> None:
        """The live library files carry no call vocabulary, so the extractor
        never reaches the reference filter for them; pin the filter itself."""
        from discover_kfw_candidates import _KFW_REFERENCE_DOCUMENT_PATTERN

        assert _KFW_REFERENCE_DOCUMENT_PATTERN.search(name)

    @pytest.mark.parametrize(
        "filename, link_text",
        [
            ("Call-for-Proposals-Sustainability-Project.pdf",
             "Call for proposals: sustainability project"),
            ("Call-for-Proposals-Nachhaltigkeit-Studie.pdf",
             "Call for Proposals - Nachhaltigkeit im Wohnungsbau"),
            ("RFP-Contratacao-de-Consultoria.pdf",
             "Request for Proposals - Contratação de consultoria"),
            ("Request-for-Proposals-Contratacion-de-Servicios.pdf",
             "Request for Proposals - Contratación de servicios"),
            ("Call-for-Proposals-Passation-de-Marches.pdf",
             "Call for Proposals - Passation de marchés au Mali"),
            ("Call-for-Proposals-Operations-Manual-Drafting.pdf",
             "Call for Proposals: drafting an operations manual"),
            ("Call-for-Tenders-Regulations-Compliance-Study.pdf",
             "Call for Tenders - study on energy regulations"),
            ("Call-for-Proposals-Template-Library.pdf",
             "Call for Proposals - template library development"),
            ("EOI-Handbook-Translation.pdf",
             "Expression of Interest - handbook translation"),
            ("Call-for-Proposals-Tourist-Guide.pdf",
             "Call for Proposals - tourist guide for the Amazon"),
            ("Call-for-Proposals-Directive-Implementation.pdf",
             "Call for Proposals - implementation of the EU directive"),
        ],
    )
    def test_genuine_call_with_a_subject_word_is_not_rejected(
        self, filename: str, link_text: str,
    ) -> None:
        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = (
            f'<html><body><a href="{_LIBRARY_DIR}{filename}">{link_text}</a>'
            "</body></html>"
        )
        assert extract_kfw_pdf_urls(html, LISTING_URL) == [
            f"https://www.kfw-entwicklungsbank.de{_LIBRARY_DIR}{filename}",
        ]

    @pytest.mark.parametrize(
        "filename, link_text",
        [
            ("Call-for-Proposals-Sustainability-Guideline.pdf", "Sustainability Guideline"),
            ("Call-for-Proposals-Nachhaltigkeitsrichtlinie.pdf", "Nachhaltigkeitsrichtlinie"),
            ("EOI-Procurement-Regulations.pdf", "Procurement Regulations"),
            ("EOI-Procurement-Manual.pdf", "Procurement Manual"),
            ("Invitation-to-Tender-Standard-Bidding-Documents.pdf", "Standard Bidding Documents"),
            ("Call-for-Proposals-Proposal-Template.pdf", "Proposal Template"),
            ("EOI-Model-Contract.pdf", "Model Contract"),
            ("RFP-Guide.pdf", "Request for proposals guide for borrowers"),
            ("EOI-Directives-pour-la-Passation.pdf", "Directives pour la Passation de Marchés"),
        ],
    )
    def test_reference_document_titles_with_call_vocabulary_stay_rejected(
        self, filename: str, link_text: str,
    ) -> None:
        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = (
            f'<html><body><a href="{_LIBRARY_DIR}{filename}">{link_text}</a>'
            "</body></html>"
        )
        assert extract_kfw_pdf_urls(html, LISTING_URL) == []

    def test_rejects_external_hosts(self) -> None:
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="https://external.example.org/call-for-proposals.pdf">Externo</a>
          <a href="https://www.kfw.de/call-for-proposals.pdf">Valido</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert extract_kfw_pdf_urls(soup, LISTING_URL) == [
            "https://www.kfw.de/call-for-proposals.pdf",
        ]

    def test_rejects_non_pdf_anchors(self) -> None:
        from bs4 import BeautifulSoup

        from discover_kfw_candidates import extract_kfw_pdf_urls

        html = """
        <html><body>
          <a href="/resources/report/call-for-proposals.docx">DOCX</a>
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
          <a href="https://www.kfw-entwicklungsbank.de/about-us/eoi-2026.pdf">Wrong path</a>
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
    def test_live_library_page_is_a_clean_empty_inventory(self) -> None:
        """The static document library has no open call: 0 candidates,
        0 errors, and no browser is started."""
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(_live_library_html())},
        ):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["candidates"] == 0
        assert stats["listings_fetched"] == 1
        assert stats["errors"] == 0
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_tender_document_is_emitted_via_bs4_without_browser(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        html = _live_library_html().replace(
            "</body>",
            f'<a href="{_LIBRARY_DIR}Call-for-Proposals-2026.pdf">Call for Proposals</a></body>',
        )
        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response(html)},
        ):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                stats, candidates = discover_candidates()

        assert [c["url"] for c in candidates] == [
            "https://www.kfw-entwicklungsbank.de/PDF/Download-Center/PDF-Dokumente-Richtlinien/Call-for-Proposals-2026.pdf",
        ]
        assert stats["candidates"] == 1
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_playwright_fallback_not_used_when_page_has_no_pdfs(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        with patch_request_with_safe_redirects(
            {LISTING_URL: make_response("<html><body>No PDFs here</body></html>")},
        ):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 0
        assert stats["errors"] == 0
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_listing_html_is_not_fetched_twice(self) -> None:
        from discover_kfw_candidates import discover_candidates
        import discover_kfw_candidates as dkc

        calls: list[str] = []

        def fake_request(*, method: str, url: str, timeout: int, **_: object) -> object:
            calls.append(url)
            if len(calls) > 1:
                raise requests.ConnectionError("second fetch should not happen")
            return make_response(_live_library_html())

        with patch_request_with_safe_redirects(fake_request):
            with patch.object(dkc, "_run_playwright_fallback") as mock_pw:
                stats, candidates = discover_candidates()

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


class TestRegistryEntry:
    def test_kfw_does_not_require_a_browser(self) -> None:
        import json

        registry_path = (
            Path(__file__).resolve().parent.parent / "config" / "source_schedule.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        entry = next(e for e in registry["sources"] if e["source_key"] == "kfw")
        assert entry["browser_required"] is False
