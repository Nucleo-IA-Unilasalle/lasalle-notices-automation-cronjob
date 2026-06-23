"""Unit tests for ``scripts/discover_msgov_candidates.py``.

Ports the MSGOV source from
``lasalle-notices-automation/app/services/scraper/playwright/msgov.py``
into the cronjob, locking the discovery contract before Phase 4 ships.
Tests exercise the two-stage pure-Playwright discovery (listing →
detail URLs → PDFs with shadow DOM probing) and the
``process_candidate`` / ``submit_candidates`` handoff.

MSGOV is the only Phase 4 source that needs Playwright as the
**primary** path because the listing (``editaisms.prosas.com.br``)
is JS-rendered via a ``prosas-listagem-editais`` web component and
detail pages contain a dropdown that lazy-loads anexos. A few
``.doc`` annexes leak through discovery; the cronjob relies on
``pncp_http.validate_pdf`` (which checks both the ``b"%PDF"`` header
and ``application/pdf`` MIME) to reject them at download time.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects


LISTING_URL = "https://editaisms.prosas.com.br"


CHAMADA_DETAIL_URL = "https://editaisms.prosas.com.br/edital?id=abc123"
SPRINT_DETAIL_URL = "https://editaisms.prosas.com.br/edital?id=def456"
EXTERNAL_DETAIL_URL = "https://external.example.org/edital?id=zzz"


class _ACMGate:
    """Async context manager that yields a fixed value on ``__aenter__``."""

    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_: object) -> bool:
        return False


def _build_fake_pw(
    listing_hrefs: list[str],
    detail_pdfs_by_url: dict[str, list[str]],
) -> tuple[MagicMock, MagicMock]:
    """Build a fake Playwright environment.

    ``listing_hrefs`` is the list of hrefs returned by
    ``page.query_selector_all`` on the listing page.
    ``detail_pdfs_by_url`` maps each detail URL to the PDF hrefs
    that should be returned from its detail-page navigation.
    The same fake ``page`` is reused across navigations; it
    tracks the most recent ``page.goto`` URL and serves the
    matching hrefs.
    Returns ``(fake_async_pw, fake_page)``.
    """
    state: dict[str, Any] = {"current_url": "about:blank"}

    def _links_for(url: str) -> list[MagicMock]:
        if url in detail_pdfs_by_url:
            hrefs = list(detail_pdfs_by_url[url])
        else:
            hrefs = list(listing_hrefs)

        links: list[MagicMock] = []
        for href in hrefs:
            anchor = MagicMock()
            anchor.get_attribute = AsyncMock(return_value=href)
            links.append(anchor)
        return links

    async def fake_goto(url: str) -> None:
        state["current_url"] = url
        return None

    async def fake_query_selector_all(selector: str = "") -> list[MagicMock]:
        return _links_for(state["current_url"])

    fake_page = MagicMock()
    fake_page.goto = AsyncMock(side_effect=fake_goto)
    fake_page.wait_for_load_state = AsyncMock()
    fake_page.wait_for_selector = AsyncMock()
    fake_page.wait_for_timeout = AsyncMock()
    fake_page.query_selector_all = AsyncMock(side_effect=fake_query_selector_all)

    async def fake_evaluate(script: str) -> Any:
        return list(_links_for(state["current_url"]))

    fake_page.evaluate = AsyncMock(side_effect=fake_evaluate)

    fake_context = MagicMock()
    fake_context.new_page = AsyncMock(return_value=fake_page)

    fake_browser = MagicMock()
    fake_browser.new_context = AsyncMock(return_value=fake_context)
    fake_browser.close = AsyncMock()

    fake_pw = MagicMock()
    fake_pw.chromium.launch = AsyncMock(return_value=fake_browser)

    fake_async_pw = MagicMock(return_value=_ACMGate(fake_pw))

    return fake_async_pw, fake_page


def _patched_asyncio_run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestListingUrl:
    def test_default_listing_url(self) -> None:
        from discover_msgov_candidates import MSGOV_LISTING_URL

        assert MSGOV_LISTING_URL == "https://editaisms.prosas.com.br"


class TestDiscoverCandidates:
    def test_listing_yields_pdf_candidates_via_playwright(self) -> None:
        import types

        import discover_msgov_candidates as dmc

        fake_pw, _fake_page = _build_fake_pw(
            listing_hrefs=[
                "/edital?id=abc123",
                "/edital?id=def456",
                "https://external.example.org/edital?id=zzz",
                "/noticias?id=ignored",
                "/edital.html?id=foo",
            ],
            detail_pdfs_by_url={
                CHAMADA_DETAIL_URL: [
                    "https://example.s3.amazonaws.com/edital-abc123.pdf",
                    "https://example.s3.amazonaws.com/anexo-abc123.doc",
                ],
                SPRINT_DETAIL_URL: [
                    "https://example.s3.amazonaws.com/edital-def456.pdf",
                ],
            },
        )

        fake_async_api = types.ModuleType("playwright.async_api")
        fake_async_api.async_playwright = fake_pw  # type: ignore[attr-defined]
        fake_playwright = types.ModuleType("playwright")
        fake_playwright.async_api = fake_async_api  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "playwright": fake_playwright,
                "playwright.async_api": fake_async_api,
            },
        ):
            with patch.object(dmc.asyncio, "run", side_effect=_patched_asyncio_run):
                stats, candidates = dmc.discover_candidates()

        assert stats["candidates"] == 3
        urls = sorted(c["url"] for c in candidates)
        assert urls == sorted(
            [
                "https://example.s3.amazonaws.com/edital-abc123.pdf",
                "https://example.s3.amazonaws.com/anexo-abc123.doc",
                "https://example.s3.amazonaws.com/edital-def456.pdf",
            ],
        )
        for c in candidates:
            assert c["kind"] == "pdf"
            assert c["metadata"]["source"] == "msgov"
            assert c["metadata"]["listing_url"] == LISTING_URL

    def test_listing_filters_external_and_non_edital_hrefs(self) -> None:
        import types

        import discover_msgov_candidates as dmc

        # Only one valid detail URL (CHAMADA_DETAIL_URL); the others
        # should be filtered by host / path / no-id checks.
        fake_pw, _fake_page = _build_fake_pw(
            listing_hrefs=[
                "/edital?id=abc123",
                "/edital?id=",  # no id query param
                "https://external.example.org/edital?id=zzz",  # wrong host
                "/noticias?id=ignored",  # wrong path
                "https://editaisms.prosas.com.br/foo?id=bar",  # wrong path
            ],
            detail_pdfs_by_url={
                CHAMADA_DETAIL_URL: [
                    "https://example.s3.amazonaws.com/edital-abc123.pdf",
                ],
            },
        )

        fake_async_api = types.ModuleType("playwright.async_api")
        fake_async_api.async_playwright = fake_pw  # type: ignore[attr-defined]
        fake_playwright = types.ModuleType("playwright")
        fake_playwright.async_api = fake_async_api  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "playwright": fake_playwright,
                "playwright.async_api": fake_async_api,
            },
        ):
            with patch.object(dmc.asyncio, "run", side_effect=_patched_asyncio_run):
                stats, candidates = dmc.discover_candidates()

        assert stats["candidates"] == 1
        assert candidates[0]["url"] == (
            "https://example.s3.amazonaws.com/edital-abc123.pdf"
        )

    def test_returns_empty_when_playwright_missing(self) -> None:
        import discover_msgov_candidates as dmc

        stats: dict[str, int] = {}

        def _raise_import_error(coro: Any) -> object:
            coro.close()
            raise ImportError("playwright")

        with patch.object(dmc.asyncio, "run", side_effect=_raise_import_error):
            result_stats, candidates = dmc.discover_candidates()

        assert candidates == []
        assert result_stats["errors"] == 1
        assert result_stats["candidates"] == 0


class TestMagicByteRejection:
    """Verify the cronjob's PDF validation rejects non-PDF downloads
    such as the ``.doc`` annexes that leak through MSGOV discovery.
    """

    def test_validate_pdf_rejects_doc_magic_bytes(self) -> None:
        from ocr_worker.file_validation import validate_pdf

        doc_bytes = bytes.fromhex("D0CF11E0A1B11AE1") + b"fake ole2 doc" * 50
        with pytest.raises(Exception) as exc_info:
            validate_pdf(doc_bytes, max_size=1_000_000)
        assert "not a valid pdf" in str(exc_info.value).lower()

    def test_process_candidate_rejects_non_pdf_response(
        self,
    ) -> None:
        """``process_candidate`` propagates ``DownloadError`` when
        ``download_pncp_pdf`` raises it (which it does when
        ``validate_pdf`` rejects the body for non-PDF magic bytes)."""
        import pipeline_core
        from pncp_http import DownloadError

        with patch("pipeline_core.download_pncp_pdf") as mock_dl:
            mock_dl.side_effect = DownloadError(
                "PDF validation failed: File is not a valid PDF document"
            )

            result = pipeline_core.process_candidate(
                {"url": "https://example.org/anexo.doc", "kind": "pdf", "metadata": {"source": "msgov"}},
                extractor=MagicMock(),
                max_bytes=1_000_000,
            )

        assert "error" in result
        assert "not a valid pdf" in result["error"].lower()


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_msgov_source(self) -> None:
        import discover_msgov_candidates as dmc

        candidate = {
            "url": "https://example.s3.amazonaws.com/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "msgov"},
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
            with patch.object(dmc, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dmc.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dmc.pipeline_core,
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
                            dmc.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "msgov"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_msgov_candidates as dmc

        with patch.dict("os.environ", {}, clear=True):
            assert dmc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_msgov_candidates as dmc

        with patch.object(dmc, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dmc.main() == 0
