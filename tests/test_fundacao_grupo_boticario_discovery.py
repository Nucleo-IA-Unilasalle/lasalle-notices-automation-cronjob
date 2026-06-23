"""Unit tests for ``scripts/discover_fundacao_grupo_boticario_candidates.py``.

Ports the Fundação Grupo Boticário source from
``lasalle-notices-automation/app/services/scraper/playwright/fundacao_grupo_boticario.py``
into the cronjob, locking the discovery contract before Phase 4 ships.
Tests exercise the two-stage discovery (listing → detail URLs → PDFs)
on both the BS4 primary path and the Playwright fallback, plus the
``process_candidate`` / ``submit_candidates`` handoff.

The listing lives at
``https://fundacaogrupoboticario.org.br/`` and links to detail pages
on ``fundacaogrupoboticario.org.br`` and ``goias.gov.br`` (FAPEG).
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

FIXTURES_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sources"
    / "fundacao_grupo_boticario"
)


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_CHAMADA_FIXTURE = FIXTURES_DIR / "detail_chamada.html"
DETAIL_SPRINT_FIXTURE = FIXTURES_DIR / "detail_sprint.html"


LISTING_URL = "https://fundacaogrupoboticario.org.br/"


CHAMADA_DETAIL_URL = (
    "https://goias.gov.br/fapeg/chamada-publica-fapeg-fgb-no-07-2026-chamada-cerrado-solucoes-para-protecao-da-biodiversidade-no-cerrado-de-goias-frente-aos-incendios-florestais"
)
SPRINT_DETAIL_URL = (
    "https://fundacaogrupoboticario.org.br/sprint-prevencao-ao-fogo-no-cerrado"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestDetailUrlExtraction:
    """The detail-URL extraction is a verbatim port of the FastAPI helper."""

    def test_listing_yields_signal_detail_urls(self) -> None:
        from bs4 import BeautifulSoup

        from discover_fundacao_grupo_boticario_candidates import (
            extract_fundacao_grupo_boticario_detail_urls_from_soup,
        )

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        discovered = extract_fundacao_grupo_boticario_detail_urls_from_soup(
            soup, LISTING_URL,
        )

        # The fixture has 4 anchors:
        # - goias.gov.br/fapeg/chamada-publica-fapeg-fgb-no-07-2026 -> signal (chamada)
        # - conexao oceano (third-party host) -> filtered out
        # - fundacaogrupoboticario.org.br/sprint-prevencao-ao-fogo-no-cerrado -> signal (sprint)
        # - fundacaogrupoboticario.org.br/noticias -> blacklisted path, dropped
        assert discovered == [
            CHAMADA_DETAIL_URL,
            SPRINT_DETAIL_URL,
        ]

    def test_is_fundacao_grupo_boticario_host(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            is_fundacao_grupo_boticario_host,
        )

        assert (
            is_fundacao_grupo_boticario_host(
                "https://fundacaogrupoboticario.org.br/sprint-prevencao/",
            )
            is True
        )
        assert (
            is_fundacao_grupo_boticario_host(
                "https://www.fundacaogrupoboticario.org.br/sprint-prevencao/",
            )
            is True
        )
        assert (
            is_fundacao_grupo_boticario_host("https://goias.gov.br/fapeg/chamada/")
            is False
        )


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
        )

        assert (
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URL
            == "https://fundacaogrupoboticario.org.br/"
        )


class TestDiscoverCandidates:
    def _setup_responses(
        self,
    ) -> dict[str, Any]:
        return {
            LISTING_URL: make_response(_read_fixture(LISTING_FIXTURE)),
            CHAMADA_DETAIL_URL: make_response(_read_fixture(DETAIL_CHAMADA_FIXTURE)),
            SPRINT_DETAIL_URL: make_response(_read_fixture(DETAIL_SPRINT_FIXTURE)),
        }

    def test_listing_yields_pdf_candidates_via_bs4(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            discover_candidates,
        )

        with patch_request_with_safe_redirects(self._setup_responses()):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 4
        assert stats["listings_fetched"] == 1
        assert stats["details_fetched"] == 2
        assert stats["playwright_fallback_used"] == 0

        urls = sorted(c["url"] for c in candidates)
        assert urls == sorted(
            [
                "https://goias.gov.br/fapeg/wp-content/uploads/sites/32/2026/04/chamada-publica-fapeg-fgb-07-2026.pdf",
                "https://goias.gov.br/fapeg/wp-content/uploads/sites/32/2026/04/anexo-i-chamada-publica-fapeg-fgb-07-2026.pdf?download=1",
                "https://fundacaogrupoboticario.org.br/wp-content/uploads/2026/03/regulamento-sprint-prevencao-ao-fogo.pdf",
                "https://fundacaogrupoboticario.org.br/wp-content/uploads/2026/03/cronograma-sprint-prevencao-ao-fogo.pdf#page=2",
            ]
        )

        for c in candidates:
            assert c["kind"] == "pdf"
            assert c["metadata"]["source"] == "fundacao_grupo_boticario"
            assert c["metadata"]["listing_url"] == LISTING_URL

    def test_playwright_fallback_used_when_bs4_yields_nothing(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            discover_candidates,
        )
        import discover_fundacao_grupo_boticario_candidates as dfb

        goias_detail = (
            "https://goias.gov.br/fapeg/chamada-publica-fapeg-fgb-no-08-2026/"
        )
        goias_detail_canonical = (
            "https://goias.gov.br/fapeg/chamada-publica-fapeg-fgb-no-08-2026"
        )
        goias_pdf = (
            "https://goias.gov.br/fapeg/wp-content/uploads/chamada-publica-08.pdf"
        )
        empty_listing = "<html><body><a>No detail URLs here</a></body></html>"
        with patch_request_with_safe_redirects(
            {
                LISTING_URL: make_response(empty_listing),
                goias_detail_canonical: make_response(
                    f'<html><body><a href="{goias_pdf}">Edital</a></body></html>'
                ),
            },
        ):
            with patch.object(dfb, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = [goias_detail_canonical]
                stats, candidates = discover_candidates()

        assert stats["candidates"] == 1
        assert stats["playwright_fallback_used"] == 1
        urls = [c["url"] for c in candidates]
        assert goias_pdf in urls

    def test_playwright_fallback_not_used_when_bs4_yields_results(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            discover_candidates,
        )
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(self._setup_responses()):
            with patch.object(dfb, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, _candidates = discover_candidates()

        assert stats["candidates"] == 4
        assert stats["playwright_fallback_used"] == 0
        mock_pw.assert_not_called()

    def test_listing_fetch_failure_falls_back_to_playwright(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            discover_candidates,
        )
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(
            {LISTING_URL: requests.ConnectionError("down")},
        ):
            with patch.object(dfb, "_run_playwright_fallback") as mock_pw:
                mock_pw.return_value = []
                stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        assert stats["playwright_fallback_used"] == 1
        assert candidates == []


class TestPlaywrightFallback:
    """The Playwright fallback imports ``async_playwright`` lazily and
    returns detail URLs after a single page navigation. Detail-page
    PDFs are then resolved by feeding each detail URL back through
    ``extract_fundacao_grupo_boticario_detail_urls_from_soup`` (or its
    detail-page equivalent); the cronjob keeps it simple by
    reproducing the FastAPI pattern of rebuilding an HTML fragment.
    """

    def _fake_async_pw(self, links: list[dict[str, str]]) -> MagicMock:
        fake_links: list[MagicMock] = []
        for link in links:
            anchor = MagicMock()
            anchor.get_attribute = AsyncMock(return_value=link.get("href", ""))
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

    def test_run_playwright_fallback_returns_detail_urls(self) -> None:
        import types

        import discover_fundacao_grupo_boticario_candidates as dfb

        fake_pw = self._fake_async_pw(
            [
                {"href": CHAMADA_DETAIL_URL + "/"},
                {"href": "https://fundacaogrupoboticario.org.br/noticias/"},
                {"href": SPRINT_DETAIL_URL + "/"},
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
            with patch.object(dfb.asyncio, "run", side_effect=self._patched_asyncio_run):
                detail_urls = dfb._run_playwright_fallback(LISTING_URL, stats=stats)

        assert detail_urls == [CHAMADA_DETAIL_URL, SPRINT_DETAIL_URL]

    def test_run_playwright_fallback_returns_empty_when_playwright_missing(
        self,
    ) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        stats: dict[str, int] = {}

        def _raise_import_error(coro: Any) -> object:
            coro.close()
            raise ImportError("playwright")

        with patch.object(dfb.asyncio, "run", side_effect=_raise_import_error):
            detail_urls = dfb._run_playwright_fallback(LISTING_URL, stats=stats)

        assert detail_urls == []
        assert stats["errors"] == 1


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_fundacao_grupo_boticario_source(
        self,
    ) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        candidate = {
            "url": "https://fundacaogrupoboticario.org.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "fundacao_grupo_boticario"},
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
            with patch.object(dfb, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dfb.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dfb.pipeline_core,
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
                            dfb.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "fundacao_grupo_boticario"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch.dict("os.environ", {}, clear=True):
            assert dfb.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch.object(dfb, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dfb.main() == 0
