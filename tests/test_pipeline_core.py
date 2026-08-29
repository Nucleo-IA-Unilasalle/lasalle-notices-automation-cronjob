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
from unittest.mock import MagicMock, patch

import pytest

import pipeline_core
from pncp_http import DownloadError, DownloadResult


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
    def test_default_batch_size_is_safe_for_repo_a_payload_cap(self) -> None:
        assert pipeline_core.RENDER_SUBMIT_BATCH_SIZE == 5

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

    def test_http_200_invalid_item_outcome_is_a_failed_submission(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "inserted": 0,
            "updated": 0,
            "reactivated": 0,
            "duplicates": 0,
            "invalid": 1,
            "items": [{
                "url": "https://example.com/doc.pdf",
                "pncp_control_number": None,
                "pncp_document_sequence": None,
                "outcome": "invalid",
            }],
        }

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=response):
                result = pipeline_core.submit_candidates(
                    [_valid_candidate()], source="pncp"
                )

        assert result["submitted"] == 0
        assert result["failed_batches"] == 1
        assert "invalid candidate outcomes" in result["errors"][0]

    def test_http_200_mixed_item_outcomes_are_reported_as_partial(self) -> None:
        candidates = [
            _valid_candidate("https://example.com/valid.pdf"),
            _valid_candidate("https://example.com/invalid.pdf"),
        ]
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "inserted": 1,
            "updated": 0,
            "reactivated": 0,
            "duplicates": 0,
            "invalid": 1,
            "items": [
                {
                    "url": "https://example.com/valid.pdf",
                    "pncp_control_number": None,
                    "pncp_document_sequence": None,
                    "outcome": "inserted",
                },
                {
                    "url": "https://example.com/invalid.pdf",
                    "pncp_control_number": None,
                    "pncp_document_sequence": None,
                    "outcome": "invalid",
                },
            ],
        }

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=response):
                result = pipeline_core.submit_candidates(candidates, source="bndes")

        assert result["submitted"] == 1
        assert result["failed_batches"] == 1

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

    def test_batches_are_split_by_serialized_worker_and_metadata_size(self, monkeypatch) -> None:
        monkeypatch.setattr(pipeline_core, "RENDER_SUBMIT_MAX_PAYLOAD_CHARS", 500)
        candidates = [
            {
                **_valid_candidate(f"https://example.com/{index}.pdf"),
                "metadata": {"description": "x" * 100},
            }
            for index in range(2)
        ]
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"inserted": 1}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.post", return_value=response) as mock_post:
                result = pipeline_core.submit_candidates(candidates, source="bndes")

        assert mock_post.call_count == 2
        assert result["submitted"] == 2
        for call in mock_post.call_args_list:
            body = call.kwargs["json"]
            assert sum(
                len(pipeline_core.json.dumps(value, ensure_ascii=False, default=str))
                for candidate in body["candidates"]
                for value in (candidate.get("worker_result"), candidate.get("metadata"))
                if value
            ) <= 500

    def test_422_batch_is_split_without_repeating_the_oversized_payload(self) -> None:
        response_422 = MagicMock()
        response_422.status_code = 422
        response_ok = MagicMock()
        response_ok.status_code = 200
        response_ok.json.return_value = {"inserted": 1}
        candidates = [_valid_candidate(f"https://example.com/{index}.pdf") for index in range(2)]

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch(
                "pipeline_core.requests.post",
                side_effect=[response_422, response_ok, response_ok],
            ) as mock_post:
                result = pipeline_core.submit_candidates(candidates, source="bndes")

        assert mock_post.call_count == 3
        assert len(mock_post.call_args_list[0].kwargs["json"]["candidates"]) == 2
        assert all(
            len(call.kwargs["json"]["candidates"]) == 1
            for call in mock_post.call_args_list[1:]
        )
        assert result["submitted"] == 2

    def test_documentless_preflight_skips_disabled_payload_but_submits_valid_pdf(self) -> None:
        documentless = {
            "source_key": "tnc",
            "source_record_id": "docless-1",
            "source_kind": "web",
            "opportunity_type": "funding",
            "title": "Documentless call",
            "source_snapshot_at": "2026-08-02T00:00:00+00:00",
            "source_markdown": "# Call",
            "source_content_hash": "",
            "documents": [],
        }
        documentless["source_content_hash"] = __import__("hashlib").sha256(
            documentless["source_markdown"].encode()
        ).hexdigest()
        pdf = {
            **documentless,
            "source_record_id": "pdf-1",
            "documents": [{
                "document_kind": "pdf",
                "url": "https://example.com/call.pdf",
                "is_renderable": True,
                "is_principal": True,
                "content_hash": "a" * 64,
                "validation_outcome": "valid_pdf",
            }],
        }
        capability_response = MagicMock()
        capability_response.status_code = 200
        capability_response.json.return_value = {
            "status": "ok",
            "documentless_opportunities_enabled": False,
            "documentless_opportunity_rollout": "disabled",
        }
        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {"outcome": "inserted"}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.get", return_value=capability_response) as mock_get:
                with patch("pipeline_core.requests.post", return_value=submit_response) as mock_post:
                    result = pipeline_core.submit_opportunities([documentless, pdf])

        mock_get.assert_called_once()
        assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer tok"}
        assert mock_get.call_args.args[0] == "https://r.example.com/api/pipeline/capabilities"
        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["json"]["source_record_id"] == "pdf-1"
        assert result["submitted"] == 1
        assert result["failed"] == 1
        assert "disabled" in result["errors"][0]

    def test_documentless_preflight_allows_payload_when_repo_a_enables_rollout(self) -> None:
        opportunity = {
            "source_key": "tnc",
            "source_record_id": "docless-enabled",
            "source_kind": "web",
            "opportunity_type": "funding",
            "title": "Documentless call",
            "source_snapshot_at": "2026-08-02T00:00:00+00:00",
            "source_markdown": "# Call",
            "source_content_hash": __import__("hashlib").sha256(b"# Call").hexdigest(),
            "documents": [],
        }
        capability_response = MagicMock()
        capability_response.status_code = 200
        capability_response.json.return_value = {
            "status": "ok",
            "documentless_opportunities_enabled": True,
            "documentless_opportunity_rollout": "enabled",
        }
        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {"outcome": "inserted"}

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.get", return_value=capability_response) as mock_get:
                with patch("pipeline_core.requests.post", return_value=submit_response) as mock_post:
                    result = pipeline_core.submit_opportunities([opportunity])

        mock_get.assert_called_once()
        mock_post.assert_called_once()
        assert result["submitted"] == 1
        assert result["failed"] == 0


class TestDocumentlessCapability:
    @pytest.mark.parametrize(
        ("enabled", "rollout"),
        [(True, "enabled"), (False, "disabled")],
    )
    def test_reads_repo_a_contract(self, enabled: bool, rollout: str) -> None:
        assert pipeline_core._read_documentless_capability(
            {
                "status": "ok",
                "documentless_opportunities_enabled": enabled,
                "documentless_opportunity_rollout": rollout,
            }
        ) is enabled

    @pytest.mark.parametrize(
        "payload",
        [
            {"documentless_opportunities_enabled": True},
            {
                "status": "ok",
                "documentless_opportunities": True,
                "documentless_opportunity_rollout": "enabled",
            },
            {
                "status": "ok",
                "documentless_opportunities_enabled": True,
                "documentless_opportunity_rollout": "enabled",
                "capabilities": {},
            },
            {
                "status": "ready",
                "documentless_opportunities_enabled": True,
                "documentless_opportunity_rollout": "enabled",
            },
            {
                "status": "ok",
                "documentless_opportunities_enabled": 1,
                "documentless_opportunity_rollout": "enabled",
            },
            {
                "status": "ok",
                "documentless_opportunities_enabled": True,
                "documentless_opportunity_rollout": "disabled",
            },
            {
                "status": "ok",
                "documentless_opportunities_enabled": True,
                "documentless_opportunity_rollout": [],
            },
        ],
    )
    def test_rejects_non_contract_shapes(self, payload: dict[str, object]) -> None:
        with pytest.raises(pipeline_core.CapabilityPreflightError):
            pipeline_core._read_documentless_capability(payload)

    def test_preflight_uses_hardcoded_contract_path(self, monkeypatch) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "ok",
            "documentless_opportunities_enabled": True,
            "documentless_opportunity_rollout": "enabled",
        }
        monkeypatch.setenv("RENDER_CAPABILITIES_PATH", "/wrong/path")

        with patch("pipeline_core.requests.get", return_value=response) as mock_get:
            assert pipeline_core._preflight_documentless_opportunities(
                "https://r.example.com", "tok"
            ) is True

        assert mock_get.call_args.args[0] == (
            "https://r.example.com/api/pipeline/capabilities"
        )


class TestSubmitOpportunities:
    def test_oversized_source_markdown_is_rejected_without_post(self) -> None:
        opportunity = {
            "source_key": "tnc",
            "source_record_id": "oversized-source",
            "source_markdown": "x" * (pipeline_core.OPPORTUNITY_MARKDOWN_MAX_CHARS + 1),
            "documents": [],
        }

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.get") as mock_get:
                with patch("pipeline_core.requests.post") as mock_post:
                    result = pipeline_core.submit_opportunities([opportunity])

        mock_get.assert_not_called()
        mock_post.assert_not_called()
        assert result["submitted"] == 0
        assert result["failed"] == 1
        assert "source_markdown" in result["errors"][0]
        assert str(pipeline_core.OPPORTUNITY_MARKDOWN_MAX_CHARS) in result["errors"][0]

    def test_oversized_document_markdown_is_rejected_without_post(self) -> None:
        opportunity = {
            "source_key": "tnc",
            "source_record_id": "oversized-document",
            "source_markdown": "# Call",
            "documents": [{
                "document_kind": "pdf",
                "url": "https://example.com/call.pdf",
                "extracted_markdown": "x" * (
                    pipeline_core.OPPORTUNITY_MARKDOWN_MAX_CHARS + 1
                ),
            }],
        }

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }):
            with patch("pipeline_core.requests.get") as mock_get:
                with patch("pipeline_core.requests.post") as mock_post:
                    result = pipeline_core.submit_opportunities([opportunity])

        mock_get.assert_not_called()
        mock_post.assert_not_called()
        assert result["submitted"] == 0
        assert result["failed"] == 1
        assert "documents[0].extracted_markdown" in result["errors"][0]


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


# ---------------------------------------------------------------------------
# make_default_ocr_extractor — shared OCR helper
# ---------------------------------------------------------------------------

class TestMakeDefaultOcrExtractor:
    """Locks the env-driven OCR configuration that ``main()`` functions
    previously duplicated per source. Centralising this means Phase 3
    sources inherit the same defaults (and env-var names) without
    restating the wiring."""

    def test_passes_defaults_when_no_env_vars_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("KREUZBERG_PADDLE_LANGUAGE", raising=False)
        monkeypatch.delenv("KREUZBERG_PADDLE_MODEL_TIER", raising=False)
        monkeypatch.delenv("KREUZBERG_USE_GPU", raising=False)
        monkeypatch.delenv("KREUZBERG_FORCE_OCR_DEFAULT", raising=False)
        monkeypatch.delenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", raising=False)

        captured: dict[str, object] = {}

        class FakeConfig:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        class FakeExtractor:
            def __init__(self, *, ocr_config: object) -> None:
                captured["extractor_ocr_config"] = ocr_config

        with patch.dict(sys.modules, {
            "ocr_worker.ocr_extraction_config": MagicMock(OCRExtractionConfig=FakeConfig),
            "ocr_worker.pdf_markdown_extractor": MagicMock(PDFMarkdownExtractor=FakeExtractor),
        }):
            config, extractor = pipeline_core.make_default_ocr_extractor()

        assert isinstance(config, FakeConfig)
        assert isinstance(extractor, FakeExtractor)
        assert captured["language"] == "latin"
        assert captured["model_tier"] == "tiny"
        assert captured["use_gpu"] is False
        assert captured["force_ocr"] is False
        assert captured["extraction_timeout_seconds"] == 300
        assert captured["extractor_ocr_config"] is config

    def test_honours_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KREUZBERG_PADDLE_LANGUAGE", "pt")
        monkeypatch.setenv("KREUZBERG_PADDLE_MODEL_TIER", "small")
        monkeypatch.setenv("KREUZBERG_USE_GPU", "true")
        monkeypatch.setenv("KREUZBERG_FORCE_OCR_DEFAULT", "True")
        monkeypatch.setenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", "120")

        captured: dict[str, object] = {}

        class FakeConfig:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        class FakeExtractor:
            def __init__(self, *, ocr_config: object) -> None:
                captured["extractor_ocr_config"] = ocr_config

        with patch.dict(sys.modules, {
            "ocr_worker.ocr_extraction_config": MagicMock(OCRExtractionConfig=FakeConfig),
            "ocr_worker.pdf_markdown_extractor": MagicMock(PDFMarkdownExtractor=FakeExtractor),
        }):
            config, extractor = pipeline_core.make_default_ocr_extractor()

        assert captured["language"] == "pt"
        assert captured["model_tier"] == "small"
        assert captured["use_gpu"] is True
        assert captured["force_ocr"] is True
        assert captured["extraction_timeout_seconds"] == 120

    @pytest.mark.parametrize("timeout_value", ["0", "-1", "not-an-integer"])
    def test_uses_same_default_for_invalid_ocr_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        timeout_value: str,
    ) -> None:
        monkeypatch.setenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", timeout_value)

        captured: dict[str, object] = {}

        class FakeConfig:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        class FakeExtractor:
            def __init__(self, *, ocr_config: object) -> None:
                captured["extractor_ocr_config"] = ocr_config

        with patch.dict(sys.modules, {
            "ocr_worker.ocr_extraction_config": MagicMock(OCRExtractionConfig=FakeConfig),
            "ocr_worker.pdf_markdown_extractor": MagicMock(PDFMarkdownExtractor=FakeExtractor),
        }):
            pipeline_core.make_default_ocr_extractor()

        assert captured["extraction_timeout_seconds"] == 300
