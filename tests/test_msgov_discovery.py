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
    *,
    listing_pages: list[list[str]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build a fake Playwright environment.

    ``listing_hrefs`` is the list of hrefs returned by
    ``page.query_selector_all`` on the listing page.
    ``detail_pdfs_by_url`` maps each detail URL to the PDF hrefs
    that should be returned from its detail-page navigation.
    When ``listing_pages`` is provided, the fake treats the listing as a
    multi-page carousel: evaluating the next-page script advances the
    current page index and returns ``'clicked-next'`` until the last
    page, after which it returns ``'next-disabled'``.
    The same fake ``page`` is reused across navigations; it
    tracks the most recent ``page.goto`` URL and serves the
    matching hrefs.
    Returns ``(fake_async_pw, fake_page)``.
    """
    state: dict[str, Any] = {
        "current_url": "about:blank",
        "listing_page_index": 0,
    }
    pages = listing_pages if listing_pages is not None else [list(listing_hrefs)]

    def _current_listing_hrefs() -> list[str]:
        index = min(state["listing_page_index"], len(pages) - 1)
        return list(pages[index])

    def _links_for(url: str) -> list[MagicMock]:
        if url in detail_pdfs_by_url:
            hrefs = list(detail_pdfs_by_url[url])
        else:
            hrefs = _current_listing_hrefs()

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
        # Pagination control script (returns a status string, not hrefs).
        if "clicked-next" in script and "prosas-listagem-editais" in script:
            if state["listing_page_index"] < len(pages) - 1:
                state["listing_page_index"] += 1
                return "clicked-next"
            return "next-disabled"
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
                    # Office annex on the same S3 host — must NOT become a
                    # candidate (filtered at discovery; see
                    # TestPdfCandidateFilter).
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

        assert stats["candidates"] == 2
        urls = sorted(c["url"] for c in candidates)
        assert urls == sorted(
            [
                "https://example.s3.amazonaws.com/edital-abc123.pdf",
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


class TestPdfCandidateFilter:
    """Detail pages expose office annexes on the same S3 hosts as PDFs.
    Those must not become candidates (they only ever failed magic-byte
    validation later, and they crowded real PDFs past the run cap).
    """

    def test_rejects_doc_annexes_on_s3(self) -> None:
        from discover_msgov_candidates import _is_pdf_candidate_href

        assert not _is_pdf_candidate_href(
            "https://prosas-prod-files.s3.sa-east-1.amazonaws.com/arquivos/x/ANEXO_II_EDITAVEL.doc",
        )
        assert not _is_pdf_candidate_href(
            "https://prosas-prod-files.s3.sa-east-1.amazonaws.com/arquivos/x/plano.xlsx?X-Amz-Signature=abc",
        )
        assert not _is_pdf_candidate_href(
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOK/n/x/o/anexo.docx",
        )

    def test_accepts_pdf_and_extensionless_s3(self) -> None:
        from discover_msgov_candidates import _is_pdf_candidate_href

        assert _is_pdf_candidate_href(
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOK/n/x/o/Edital.pdf",
        )
        assert _is_pdf_candidate_href(
            "https://prosas-prod-files.s3.sa-east-1.amazonaws.com/arquivos/edital.pdf?X-Amz-Signature=abc",
        )
        assert _is_pdf_candidate_href(
            "https://prosas-prod-files.s3.sa-east-1.amazonaws.com/arquivos/blob123",
        )


class TestStablePdfIdentity:
    """Signed Prosas/Oracle objectstorage URLs change on every page load;
    candidate identity must strip the preauthenticated ``/p/<token>/``
    segment and the query string so audit artifacts stay comparable.
    """

    def test_strips_objectstorage_token_and_query(self) -> None:
        from discover_msgov_candidates import _stable_pdf_identity

        signed = (
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com"
            "/p/ui2ZQnrNgUbuwnhVMbFZB22820yvelfLl8WFAUbN13xnBHQisCbq0Gb5sZ8syYYR"
            "/n/gr1ojmmb7tst/b/prosas-prod/o/arquivos/arquivos/005/046/166"
            "/original/Edital_xx-2026.pdf"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
        )
        stable = _stable_pdf_identity(signed)
        assert stable == (
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com"
            "/n/gr1ojmmb7tst/b/prosas-prod/o/arquivos/arquivos/005/046/166"
            "/original/Edital_xx-2026.pdf"
        )
        # A differently signed URL for the same object normalizes equal.
        re_signed = signed.replace("ui2ZQnrNgUbuwnhVMbFZB22820yvelfLl8WFAUbN13xnBHQisCbq0Gb5sZ8syYYR", "OTHERTOKEN").replace("Signature=abc", "Signature=xyz")
        assert _stable_pdf_identity(re_signed) == stable

    def test_build_candidate_sets_stable_identity_metadata(self) -> None:
        from discover_msgov_candidates import build_candidate

        signed = (
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com"
            "/p/TOK123/n/gr1ojmmb7tst/b/prosas-prod/o/arquivos/arquivos/005/022/265"
            "/original/Edital.pdf?X-Amz-Signature=zzz"
        )
        candidate = build_candidate(
            signed,
            listing_url=LISTING_URL,
            detail_url=f"{LISTING_URL}/edital.html?id=18863",
        )
        assert candidate["url"] == signed  # download URL keeps the signature
        metadata = candidate["metadata"]
        assert metadata["canonical_url"].endswith("/original/Edital.pdf")
        assert "/p/" not in metadata["canonical_url"]
        assert metadata["source_record_id"] == metadata["canonical_url"]
        assert metadata["status"] == "open"
        assert metadata["detail_url"] == f"{LISTING_URL}/edital.html?id=18863"


class TestListingPagination:
    """The open Prosas listing renders 20 editais per page; without
    walking the next-page control the adapter silently drops the rest
    of the open set (observed live: 23 open, 20 rendered).
    """

    def test_collects_detail_urls_across_listing_pages(self) -> None:
        import types

        import discover_msgov_candidates as dmc

        page1 = ["/edital.html?id=1001", "/edital.html?id=1002"]
        page2 = ["/edital.html?id=1003"]
        detail_pdfs = {
            f"{LISTING_URL}/edital.html?id=1001": [
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/AAA/n/x/o/edital-1001.pdf",
            ],
            f"{LISTING_URL}/edital.html?id=1002": [
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/BBB/n/x/o/edital-1002.pdf",
            ],
            f"{LISTING_URL}/edital.html?id=1003": [
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/CCC/n/x/o/edital-1003.pdf",
            ],
        }
        fake_pw, _fake_page = _build_fake_pw(
            listing_hrefs=page1,
            detail_pdfs_by_url=detail_pdfs,
            listing_pages=[page1, page2],
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

        urls = sorted(c["url"] for c in candidates)
        assert urls == sorted(
            [
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/AAA/n/x/o/edital-1001.pdf",
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/BBB/n/x/o/edital-1002.pdf",
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/CCC/n/x/o/edital-1003.pdf",
            ],
        )
        assert stats["candidates"] == 3
        assert stats["errors"] == 0
        # Stable identities drop the per-request /p/<token>/ segment.
        identities = sorted(c["metadata"]["source_record_id"] for c in candidates)
        assert identities == sorted(
            [
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/x/o/edital-1001.pdf",
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/x/o/edital-1002.pdf",
                "https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/x/o/edital-1003.pdf",
            ],
        )
