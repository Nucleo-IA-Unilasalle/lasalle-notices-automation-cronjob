from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ocr_worker import kreuzberg_extractor
from ocr_worker.run_ocr_worker import (
    DEFAULT_MARKDOWN_MAX_BYTES,
    LeaseHeartbeat,
    OCRWorker,
    OCRWorkerApi,
    PayloadTooLargeError,
    RenderCommunicationError,
    WorkerClaim,
    WorkerSettings,
    classify_error,
)


def _claim(edital_id: int) -> WorkerClaim:
    return WorkerClaim(
        edital_id=edital_id,
        source_url=f"https://example.com/{edital_id}.pdf",
        original_filename=None,
        claim_token=f"token-{edital_id}",
        expires_at=datetime.now(timezone.utc),
    )


class _NoopHeartbeat:
    def __init__(self, *_args, **_kwargs) -> None:
        self.ownership_lost = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_claim_schema_errors_are_structured_communication_errors() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "claims": [{
            "edital_id": 1,
            "source_url": "https://example.com/a.pdf",
            "claim_token": "token",
        }]
    }
    response.raise_for_status.return_value = None
    api = OCRWorkerApi(
        "https://render.example",
        "secret",
        session=MagicMock(post=MagicMock(return_value=response)),
    )

    with pytest.raises(RenderCommunicationError, match="expires_at"):
        api.claim(1)


def test_complete_rejects_oversized_markdown_before_http_call() -> None:
    session = MagicMock()
    api = OCRWorkerApi("https://render.example", "secret", session=session)

    with pytest.raises(PayloadTooLargeError):
        api.complete(_claim(1), "x" * (DEFAULT_MARKDOWN_MAX_BYTES + 1))

    session.post.assert_not_called()


def test_renew_rejects_malformed_success_response() -> None:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {"status": "ok"}
    api = OCRWorkerApi(
        "https://render.example",
        "secret",
        session=MagicMock(post=MagicMock(return_value=response)),
    )

    with pytest.raises(RenderCommunicationError, match="expires_at"):
        api.renew(_claim(1))


def test_malformed_renewal_response_returns_worker_communication_failure() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.failures: list[int] = []

        def claim(self, _limit: int):
            return [_claim(1)]

        def fail(self, claim, *, error_kind: str, error_message: str) -> None:
            assert error_kind == "communication_error"
            self.failures.append(claim.edital_id)

    class BrokenHeartbeat:
        communication_error = RenderCommunicationError("malformed renewal")
        ownership_lost = True

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class Extractor:
        async def extract(self, _pdf: bytes) -> str:
            return "ok"

    api = FakeApi()
    with patch("ocr_worker.run_ocr_worker.LeaseHeartbeat", BrokenHeartbeat):
        result = OCRWorker(
            api=api,
            downloader=lambda _url: b"pdf",
            extractor=Extractor(),
            renew_interval_seconds=60,
        ).run(limit=1)

    assert result == 1
    assert api.failures == [1]


def test_oversized_claim_is_failed_as_payload_too_large_and_worker_continues() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.failures: list[tuple[int, str]] = []

        def claim(self, _limit: int):
            return [_claim(1)]

        def fail(self, claim, *, error_kind: str, error_message: str) -> None:
            self.failures.append((claim.edital_id, error_kind))

    class Extractor:
        async def extract(self, _pdf: bytes) -> str:
            return "123456"

    api = FakeApi()
    with patch("ocr_worker.run_ocr_worker.LeaseHeartbeat", _NoopHeartbeat):
        result = OCRWorker(
            api=api,
            downloader=lambda _url: b"pdf",
            extractor=Extractor(),
            renew_interval_seconds=60,
            markdown_max_bytes=5,
        ).run(limit=1)

    assert result == 0
    assert api.failures == [(1, "payload_too_large")]


def test_communication_failure_accounts_for_current_and_remaining_claims() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.failures: list[int] = []

        def claim(self, _limit: int):
            return [_claim(1), _claim(2)]

        def complete(self, *_args, **_kwargs) -> None:
            raise RenderCommunicationError("connection lost")

        def fail(self, claim, *, error_kind: str, error_message: str) -> None:
            self.failures.append(claim.edital_id)

    class Extractor:
        async def extract(self, _pdf: bytes) -> str:
            return "ok"

    api = FakeApi()
    with patch("ocr_worker.run_ocr_worker.LeaseHeartbeat", _NoopHeartbeat):
        result = OCRWorker(
            api=api,
            downloader=lambda _url: b"pdf",
            extractor=Extractor(),
            renew_interval_seconds=60,
        ).run(limit=2)

    assert result == 1
    assert api.failures == [1, 2]


def test_failure_report_communication_error_retries_current_claim_idempotently() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.failures: list[int] = []
            self.failure_attempts: dict[int, int] = {}

        def claim(self, _limit: int):
            return [_claim(1), _claim(2)]

        def fail(self, claim, *, error_kind: str, error_message: str) -> None:
            del error_kind, error_message
            attempts = self.failure_attempts.get(claim.edital_id, 0) + 1
            self.failure_attempts[claim.edital_id] = attempts
            if claim.edital_id == 1 and attempts == 1:
                raise RenderCommunicationError("failure report connection lost")
            self.failures.append(claim.edital_id)

    class Extractor:
        async def extract(self, _pdf: bytes) -> str:
            raise RuntimeError("OCR failed")

    api = FakeApi()
    with patch("ocr_worker.run_ocr_worker.LeaseHeartbeat", _NoopHeartbeat):
        result = OCRWorker(
            api=api,
            downloader=lambda _url: b"pdf",
            extractor=Extractor(),
            renew_interval_seconds=60,
        ).run(limit=2)

    assert result == 1
    assert api.failure_attempts == {1: 2, 2: 1}
    assert api.failures == [1, 2]


def test_heartbeat_join_is_bounded() -> None:
    api = MagicMock()
    heartbeat = LeaseHeartbeat(api, _claim(1), 60, join_timeout_seconds=0.25)
    heartbeat._thread = MagicMock()
    heartbeat._thread.is_alive.return_value = True

    heartbeat.__exit__(None, None, None)

    heartbeat._thread.join.assert_called_once_with(timeout=0.25)


def test_worker_settings_expose_workflow_ocr_defaults_and_page_cap() -> None:
    with patch.dict(
        os.environ,
        {"RENDER_APP_URL": "https://example.com", "PIPELINE_SECRET": "secret"},
        clear=True,
    ):
        settings = WorkerSettings.from_env()

    assert settings.ocr_config.extraction_timeout_seconds == 300
    assert settings.ocr_config.max_pages == 50
    assert settings.markdown_max_bytes == 5_000_000


def test_worker_settings_clamp_payload_and_page_limits() -> None:
    with patch.dict(
        os.environ,
        {
            "RENDER_APP_URL": "https://example.com",
            "PIPELINE_SECRET": "secret",
            "OCR_WORKER_MARKDOWN_MAX_BYTES": "999999999",
            "OCR_MAX_PDF_PAGES": "0",
        },
        clear=True,
    ):
        settings = WorkerSettings.from_env()

    assert settings.markdown_max_bytes == DEFAULT_MARKDOWN_MAX_BYTES
    assert settings.ocr_config.max_pages == 50


@pytest.mark.parametrize("timeout_value", ["0", "-1", "not-an-integer"])
def test_worker_settings_use_shared_default_for_invalid_ocr_timeout(
    timeout_value: str,
) -> None:
    with patch.dict(
        os.environ,
        {
            "RENDER_APP_URL": "https://example.com",
            "PIPELINE_SECRET": "secret",
            "KREUZBERG_EXTRACTION_TIMEOUT_SECONDS": timeout_value,
        },
        clear=True,
    ):
        settings = WorkerSettings.from_env()

    assert settings.ocr_config.extraction_timeout_seconds == 300


def test_ocr_extraction_honours_max_page_cap() -> None:
    class FakeOCR:
        def predict(self, _file_path: str):
            return [
                {"page_index": 0, "rec_texts": ["first"]},
                {"page_index": 1, "rec_texts": ["second"]},
                {"page_index": 2, "rec_texts": ["third"]},
            ]

    with patch.object(kreuzberg_extractor, "_get_ocr_instance", return_value=FakeOCR()):
        text = kreuzberg_extractor.extract_file_sync("document.pdf", max_pages=2)

    assert "first" in text
    assert "second" in text
    assert "third" not in text


def test_payload_too_large_error_is_classified() -> None:
    assert classify_error(PayloadTooLargeError("too large")) == "payload_too_large"
