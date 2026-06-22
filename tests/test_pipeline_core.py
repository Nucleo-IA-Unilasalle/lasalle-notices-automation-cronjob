"""Unit tests for scripts/pipeline_core.py.

Verifies the generic download/OCR/submit flow extracted from
``discover_pncp_candidates.py`` plus the two new env vars
(``SCRAPE_MAX_PDF_BYTES`` / ``SCRAPE_MAX_PDFS_PER_RUN``) that now
live in the cronjob repo. The existing PNCP test suite covers the
behaviour of ``process_candidate`` and ``submit_candidates`` via
the ``discover_pncp_candidates`` re-export path; this module focuses
on the parts that are new or PNCP-agnostic.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pipeline_core
from pncp_http import DownloadError, DownloadResult


@pytest.fixture(autouse=True)
def _reset_pipeline_core_env() -> None:
    """Restore env-driven module constants between tests.

    The ``SCRAPE_MAX_PDF_BYTES`` / ``SCRAPE_MAX_PDFS_PER_RUN`` constants are
    captured at import time, so tests that override the env vars must reload
    the module within the test and we must reload it back to its default
    state once the test ends (after ``monkeypatch`` has restored the env
    vars to their pre-test values). The same reload also refreshes the
    ``discover_pncp_candidates`` re-export of ``process_candidate`` so the
    identity check (``dpc.process_candidate is pipeline_core.process_candidate``)
    holds across reloads.
    """
    yield
    os.environ.pop("SCRAPE_MAX_PDF_BYTES", None)
    os.environ.pop("SCRAPE_MAX_PDFS_PER_RUN", None)
    importlib.reload(pipeline_core)
    import discover_pncp_candidates  # noqa: PLC0415  (rebound after reload)
    importlib.reload(discover_pncp_candidates)


# ---------------------------------------------------------------------------
# Env-var defaults
# ---------------------------------------------------------------------------

class TestEnvVarDefaults:
    def test_scrape_max_pdf_bytes_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SCRAPE_MAX_PDF_BYTES", raising=False)
        module = importlib.reload(pipeline_core)
        assert module.SCRAPE_MAX_PDF_BYTES == 15_000_000

    def test_scrape_max_pdfs_per_run_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SCRAPE_MAX_PDFS_PER_RUN", raising=False)
        module = importlib.reload(pipeline_core)
        assert module.SCRAPE_MAX_PDFS_PER_RUN == 5

    def test_scrape_max_pdf_bytes_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCRAPE_MAX_PDF_BYTES", "1234567")
        module = importlib.reload(pipeline_core)
        assert module.SCRAPE_MAX_PDF_BYTES == 1_234_567

    def test_scrape_max_pdfs_per_run_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCRAPE_MAX_PDFS_PER_RUN", "11")
        module = importlib.reload(pipeline_core)
        assert module.SCRAPE_MAX_PDFS_PER_RUN == 11


# ---------------------------------------------------------------------------
# Per-run download counter
# ---------------------------------------------------------------------------

class TestDownloadCounter:
    def test_limit_reached_returns_false_when_below_cap(self) -> None:
        stats: dict[str, int] = {"pdfs_downloaded": 0}
        assert pipeline_core.pdf_download_limit_reached(stats) is False

    def test_limit_reached_returns_true_when_at_cap(self) -> None:
        stats: dict[str, int] = {"pdfs_downloaded": 5}
        assert pipeline_core.pdf_download_limit_reached(stats) is True

    def test_limit_reached_returns_true_when_above_cap(self) -> None:
        stats: dict[str, int] = {"pdfs_downloaded": 6}
        assert pipeline_core.pdf_download_limit_reached(stats) is True

    def test_limit_reached_treats_missing_key_as_zero(self) -> None:
        assert pipeline_core.pdf_download_limit_reached({}) is False

    def test_record_pdf_download_increments_counter(self) -> None:
        stats: dict[str, int] = {}
        pipeline_core.record_pdf_download(stats)
        assert stats["pdfs_downloaded"] == 1
        pipeline_core.record_pdf_download(stats)
        assert stats["pdfs_downloaded"] == 2

    def test_record_pdf_download_initialises_missing_counter(self) -> None:
        stats: dict[str, int] = {"pdfs_downloaded": 3}
        pipeline_core.record_pdf_download(stats)
        assert stats["pdfs_downloaded"] == 4


# ---------------------------------------------------------------------------
# process_candidate — generic behaviour (PNCP-coupling-free)
# ---------------------------------------------------------------------------

class TestProcessCandidate:
    def test_success_returns_worker_result(self) -> None:
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"source": "bndes"},
        }
        pdf_bytes = b"%PDF-1.4 content"

        async def fake_extract(data: bytes) -> str:
            return "# Edital"

        extractor = MagicMock()
        extractor.extract = fake_extract

        dl = DownloadResult(
            content=pdf_bytes,
            content_hash="abc",
            content_length=len(pdf_bytes),
        )

        with patch("pipeline_core.download_pncp_pdf", return_value=dl):
            result = pipeline_core.process_candidate(
                candidate, extractor=extractor, max_bytes=5_000_000,
            )

        assert "worker_result" in result
        wr = result["worker_result"]
        assert wr["ocr_markdown"] == "# Edital"
        assert wr["content_hash"] == "abc"
        assert wr["content_length"] == len(pdf_bytes)
        assert wr["validation_outcome"] == "valid_pdf"
        assert "validated_at" in wr

    def test_preserves_kind_when_provided(self) -> None:
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "html",
            "metadata": {"foo": "bar"},
        }

        async def fake_extract(data: bytes) -> str:
            return ""

        extractor = MagicMock()
        extractor.extract = fake_extract

        dl = DownloadResult(content=b"%PDF-1.4", content_hash="h", content_length=8)
        with patch("pipeline_core.download_pncp_pdf", return_value=dl):
            result = pipeline_core.process_candidate(
                candidate, extractor=extractor, max_bytes=5_000_000,
            )

        assert result["kind"] == "html"

    def test_defaults_kind_to_pdf_when_missing(self) -> None:
        candidate = {
            "url": "https://example.com/doc.pdf",
            "metadata": {},
        }

        async def fake_extract(data: bytes) -> str:
            return ""

        extractor = MagicMock()
        extractor.extract = fake_extract

        dl = DownloadResult(content=b"%PDF-1.4", content_hash="h", content_length=8)
        with patch("pipeline_core.download_pncp_pdf", return_value=dl):
            result = pipeline_core.process_candidate(
                candidate, extractor=extractor, max_bytes=5_000_000,
            )

        assert result["kind"] == "pdf"

    def test_download_failure_returns_error_dict(self) -> None:
        candidate = {
            "url": "https://example.com/missing.pdf",
            "kind": "pdf",
            "metadata": {"source": "bndes"},
        }
        with patch(
            "pipeline_core.download_pncp_pdf",
            side_effect=DownloadError("HTTP 404 permanent"),
        ):
            result = pipeline_core.process_candidate(
                candidate, extractor=MagicMock(), max_bytes=5_000_000,
            )

        assert "error" in result
        assert "download" in result["error"]
        assert result["url"] == "https://example.com/missing.pdf"
        assert "worker_result" not in result

    def test_ocr_failure_returns_error_dict(self) -> None:
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {},
        }
        dl = DownloadResult(content=b"%PDF-1.4", content_hash="h", content_length=8)

        async def failing_extract(_: bytes) -> str:
            raise RuntimeError("OCR crashed")

        extractor = MagicMock()
        extractor.extract = failing_extract

        with patch("pipeline_core.download_pncp_pdf", return_value=dl):
            result = pipeline_core.process_candidate(
                candidate, extractor=extractor, max_bytes=5_000_000,
            )

        assert "error" in result
        assert "ocr" in result["error"]

    def test_worker_result_does_not_carry_pdf_bytes(self) -> None:
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {},
        }
        pdf_bytes = b"%PDF-1.4 test"

        async def fake_extract(_: bytes) -> str:
            return "markdown"

        extractor = MagicMock()
        extractor.extract = fake_extract

        dl = DownloadResult(
            content=pdf_bytes,
            content_hash="abc",
            content_length=len(pdf_bytes),
        )
        with patch("pipeline_core.download_pncp_pdf", return_value=dl):
            result = pipeline_core.process_candidate(
                candidate, extractor=extractor, max_bytes=5_000_000,
            )

        assert "content" not in result
        assert "pdf_bytes" not in result


# ---------------------------------------------------------------------------
# submit_candidates — source-agnostic
# ---------------------------------------------------------------------------

def _valid_candidate(url: str = "https://example.com/doc.pdf", **meta: object) -> dict[str, object]:
    return {
        "url": url,
        "kind": "pdf",
        "metadata": {**meta},
        "worker_result": {
            "ocr_markdown": "# Edital",
            "content_hash": "h",
            "content_length": 100,
            "validated_at": "2026-06-12T12:00:00+00:00",
            "validation_outcome": "valid_pdf",
        },
    }


def _error_candidate(url: str = "https://example.com/bad.pdf") -> dict[str, object]:
    return {
        "url": url,
        "metadata": {},
        "error": "download: HTTP 404",
    }


class TestSubmitCandidates:
    def test_uses_provided_source_field(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=mock_resp) as mock_post:
                pipeline_core.submit_candidates([_valid_candidate()], source="bndes")

        body = mock_post.call_args.kwargs["json"]
        assert body["source"] == "bndes"
        assert len(body["candidates"]) == 1

    def test_submits_pncp_source_when_explicit(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=mock_resp) as mock_post:
                pipeline_core.submit_candidates([_valid_candidate()], source="pncp")

        body = mock_post.call_args.kwargs["json"]
        assert body["source"] == "pncp"

    def test_only_valid_candidates_are_submitted(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=mock_resp) as mock_post:
                result = pipeline_core.submit_candidates(
                    [_valid_candidate(), _error_candidate()],
                    source="bndes",
                )

        body = mock_post.call_args.kwargs["json"]
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["url"] == "https://example.com/doc.pdf"
        assert "content" not in body["candidates"][0]
        assert "pdf_bytes" not in body["candidates"][0]
        assert result["total"] == 2
        assert result["submitted"] == 1
        assert result["filtered_out"] == 1

    def test_transient_errors_retry(self) -> None:
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.json.return_value = {}
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch(
                "pipeline_core.requests.post",
                side_effect=[resp_503, resp_ok],
            ) as mock_post:
                with patch("pipeline_core.time.sleep"):
                    result = pipeline_core.submit_candidates(
                        [_valid_candidate()], source="bndes",
                    )

        assert mock_post.call_count == 2
        assert result["submitted"] == 1

    def test_auth_failure_stops_immediately(self) -> None:
        import requests as req_lib

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.json.return_value = {"error": "unauthorized"}
        resp_401.raise_for_status.side_effect = req_lib.HTTPError(response=resp_401)

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=resp_401) as mock_post:
                result = pipeline_core.submit_candidates(
                    [_valid_candidate()], source="bndes",
                )

        assert mock_post.call_count == 1
        assert result["submitted"] == 0
        assert result["failed_batches"] == 1

    def test_markdown_respects_size_limit(self) -> None:
        candidate = _valid_candidate()
        candidate["worker_result"]["ocr_markdown"] = "x" * 1_000_001

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=mock_resp) as mock_post:
                pipeline_core.submit_candidates([candidate], source="bndes")

        body = mock_post.call_args.kwargs["json"]
        md = body["candidates"][0]["worker_result"]["ocr_markdown"]
        assert len(md) <= 1_000_000

    def test_summary_carries_filtered_out_count(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 0, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=mock_resp):
                result = pipeline_core.submit_candidates(
                    [_valid_candidate(), _error_candidate(), _error_candidate("https://example.com/x.pdf")],
                    source="bndes",
                )

        assert result["total"] == 3
        assert result["filtered_out"] == 2
        assert result["submitted"] == 1


# ---------------------------------------------------------------------------
# Counter integration via discover_pncp_candidates re-export
# ---------------------------------------------------------------------------

class TestReExports:
    """Ensures discover_pncp_candidates re-exports pipeline_core so existing
    per-source code (and the existing test suite) keeps working after the
    extraction.
    """

    def test_discover_pncp_candidates_exposes_process_candidate(self) -> None:
        import discover_pncp_candidates as dpc
        assert dpc.process_candidate is pipeline_core.process_candidate

    def test_discover_pncp_candidates_exposes_submit_candidates_wrapper(self) -> None:
        import discover_pncp_candidates as dpc
        # The PNCP discoverer exposes a wrapper that pins source="pncp".
        assert callable(dpc.submit_candidates)
        assert dpc.submit_candidates is not pipeline_core.submit_candidates

    def test_pncp_submit_wrapper_passes_pncp_source(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=mock_resp) as mock_post:
                import discover_pncp_candidates as dpc
                dpc.submit_candidates([_valid_candidate(control="2026-0001")])

        body = mock_post.call_args.kwargs["json"]
        assert body["source"] == "pncp"
