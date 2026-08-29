from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

# The workflow executes this file by path rather than installing ``scripts``
# as a package. Add the sibling script directory before importing it.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import requests

if __package__:
    from .file_validation import FileValidationError, validate_pdf
    from .ocr_extraction_config import OCRExtractionConfig, parse_ocr_timeout
    from .pdf_markdown_extractor import PDFMarkdownExtractor
    try:
        from scripts.url_validation import is_safe_url
    except ModuleNotFoundError:
        from url_validation import is_safe_url
else:
    from file_validation import FileValidationError, validate_pdf
    from ocr_extraction_config import OCRExtractionConfig, parse_ocr_timeout
    from pdf_markdown_extractor import PDFMarkdownExtractor
    from url_validation import is_safe_url

logger = logging.getLogger(__name__)

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}

_CLAIM_MAX_ATTEMPTS = 4
_CLAIM_RETRY_SLEEP_SECONDS = 120
DEFAULT_MARKDOWN_MAX_BYTES = 5_000_000
DEFAULT_HEARTBEAT_JOIN_TIMEOUT_SECONDS = 5.0
DEFAULT_OCR_MAX_PAGES = 50


class ClaimOwnershipLost(RuntimeError):
    """Raised when Render rejects a claim operation because ownership changed."""


class DownloadError(RuntimeError):
    """Raised when the worker cannot fetch a PDF safely."""


class RenderCommunicationError(RuntimeError):
    """Raised when the worker cannot communicate with Render reliably."""


class PayloadTooLargeError(RuntimeError):
    """Raised before sending a markdown payload larger than Repo A accepts."""


class TransientRenewalError(RuntimeError):
    """Raised when a lease renewal fails temporarily and should be retried."""


@dataclass(frozen=True)
class WorkerClaim:
    edital_id: int
    source_url: str
    original_filename: str | None
    claim_token: str
    expires_at: datetime


@dataclass(frozen=True)
class WorkerSettings:
    render_app_url: str
    pipeline_secret: str
    limit: int
    renew_interval_seconds: float
    pdf_max_bytes: int
    download_timeout_seconds: int
    markdown_max_bytes: int
    heartbeat_join_timeout_seconds: float
    ocr_config: OCRExtractionConfig

    @classmethod
    def from_env(cls, *, limit_override: int | None = None) -> "WorkerSettings":
        render_app_url = os.environ["RENDER_APP_URL"].rstrip("/")
        pipeline_secret = os.environ["PIPELINE_SECRET"]
        limit = limit_override or int(os.getenv("OCR_WORKER_MAX_CLAIMS", "5"))
        renew_interval_seconds = float(os.getenv("OCR_WORKER_RENEW_INTERVAL_SECONDS", "60"))
        pdf_max_bytes = int(os.getenv("SCRAPE_MAX_PDF_BYTES", "15000000"))
        download_timeout_seconds = int(os.getenv("AI_SOURCE_RESOLUTION_TIMEOUT_SECONDS", "60"))
        try:
            markdown_max_bytes = int(
                os.getenv("OCR_WORKER_MARKDOWN_MAX_BYTES", str(DEFAULT_MARKDOWN_MAX_BYTES))
            )
        except (TypeError, ValueError):
            markdown_max_bytes = DEFAULT_MARKDOWN_MAX_BYTES
        markdown_max_bytes = min(DEFAULT_MARKDOWN_MAX_BYTES, max(1, markdown_max_bytes))
        try:
            heartbeat_join_timeout_seconds = float(
                os.getenv(
                    "OCR_WORKER_HEARTBEAT_JOIN_TIMEOUT_SECONDS",
                    str(DEFAULT_HEARTBEAT_JOIN_TIMEOUT_SECONDS),
                )
            )
        except (TypeError, ValueError):
            heartbeat_join_timeout_seconds = DEFAULT_HEARTBEAT_JOIN_TIMEOUT_SECONDS
        heartbeat_join_timeout_seconds = max(0.0, heartbeat_join_timeout_seconds)
        try:
            max_pages = int(os.getenv("OCR_MAX_PDF_PAGES", str(DEFAULT_OCR_MAX_PAGES)))
        except (TypeError, ValueError):
            max_pages = DEFAULT_OCR_MAX_PAGES
        max_pages = max_pages if max_pages > 0 else DEFAULT_OCR_MAX_PAGES
        ocr_config = OCRExtractionConfig(
            language=os.getenv("KREUZBERG_PADDLE_LANGUAGE", "latin"),
            model_tier=os.getenv("KREUZBERG_PADDLE_MODEL_TIER", "tiny"),
            use_gpu=os.getenv("KREUZBERG_USE_GPU", "false").lower() == "true",
            force_ocr=os.getenv("KREUZBERG_FORCE_OCR_DEFAULT", "false").lower() == "true",
            extraction_timeout_seconds=parse_ocr_timeout(
                os.getenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS")
            ),
            max_pages=max_pages,
        )
        return cls(
            render_app_url=render_app_url,
            pipeline_secret=pipeline_secret,
            limit=limit,
            renew_interval_seconds=renew_interval_seconds,
            pdf_max_bytes=pdf_max_bytes,
            download_timeout_seconds=download_timeout_seconds,
            markdown_max_bytes=markdown_max_bytes,
            heartbeat_join_timeout_seconds=heartbeat_join_timeout_seconds,
            ocr_config=ocr_config,
        )


class OCRWorkerApi:
    def __init__(self, base_url: str, pipeline_secret: str, *, session=None):
        self._base_url = base_url.rstrip("/")
        self._pipeline_secret = pipeline_secret
        self._session = session or requests.Session()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._pipeline_secret}"}

    def isolated(self) -> "OCRWorkerApi":
        return OCRWorkerApi(self._base_url, self._pipeline_secret, session=requests.Session())

    def close(self) -> None:
        self._session.close()

    @staticmethod
    def _parse_claim(item: Any, index: int) -> WorkerClaim:
        if not isinstance(item, dict):
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: expected an object"
            )

        edital_id = item.get("edital_id")
        source_url = item.get("source_url")
        claim_token = item.get("claim_token")
        expires_at_raw = item.get("expires_at")
        original_filename = item.get("original_filename")
        if not isinstance(edital_id, int) or isinstance(edital_id, bool) or edital_id <= 0:
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: edital_id must be a positive integer"
            )
        if not isinstance(source_url, str) or not source_url.strip():
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: source_url must be a non-empty string"
            )
        if not isinstance(claim_token, str) or not claim_token:
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: claim_token must be a non-empty string"
            )
        if original_filename is not None and not isinstance(original_filename, str):
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: original_filename must be a string"
            )
        if not isinstance(expires_at_raw, str) or not expires_at_raw:
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: expires_at must be an ISO timestamp"
            )
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: expires_at is not ISO-8601"
            ) from exc
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise RenderCommunicationError(
                f"Invalid OCR claim payload at index {index}: expires_at must include a timezone"
            )
        return WorkerClaim(
            edital_id=edital_id,
            source_url=source_url,
            original_filename=original_filename,
            claim_token=claim_token,
            expires_at=expires_at,
        )

    def claim(self, limit: int) -> list[WorkerClaim]:
        last_exc: Exception | None = None
        for attempt in range(1, _CLAIM_MAX_ATTEMPTS + 1):
            try:
                response = self._session.post(
                    f"{self._base_url}/api/pipeline/ocr/claim?limit={limit}",
                    headers=self._auth_headers(),
                    timeout=60,
                )
                if response.status_code in {401, 403, 404}:
                    raise RenderCommunicationError(
                        f"Non-retryable HTTP {response.status_code} on claim"
                    )
                response.raise_for_status()
            except requests.ReadTimeout as exc:
                last_exc = exc
                logger.warning(
                    "Claim attempt %d/%d timed out (Render cold start?)",
                    attempt, _CLAIM_MAX_ATTEMPTS,
                )
                if attempt < _CLAIM_MAX_ATTEMPTS:
                    time.sleep(_CLAIM_RETRY_SLEEP_SECONDS)
                    continue
                raise RenderCommunicationError(
                    f"Failed to claim OCR work after {_CLAIM_MAX_ATTEMPTS} attempts: {exc}"
                ) from exc
            except requests.ConnectionError as exc:
                last_exc = exc
                logger.warning(
                    "Claim attempt %d/%d connection error",
                    attempt, _CLAIM_MAX_ATTEMPTS,
                )
                if attempt < _CLAIM_MAX_ATTEMPTS:
                    time.sleep(_CLAIM_RETRY_SLEEP_SECONDS)
                    continue
                raise RenderCommunicationError(
                    f"Failed to claim OCR work after {_CLAIM_MAX_ATTEMPTS} attempts: {exc}"
                ) from exc
            except requests.RequestException as exc:
                raise RenderCommunicationError(f"Failed to claim OCR work: {exc}") from exc

            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise RenderCommunicationError(
                    f"Invalid OCR claim response: response is not valid JSON: {exc}"
                ) from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
                raise RenderCommunicationError(
                    "Invalid OCR claim response: expected an object with a claims list"
                )
            return [self._parse_claim(item, index) for index, item in enumerate(payload["claims"])]

        raise RenderCommunicationError(
            f"Failed to claim OCR work after {_CLAIM_MAX_ATTEMPTS} attempts: {last_exc}"
        )

    def renew(self, claim: WorkerClaim) -> datetime:
        try:
            response = self._session.post(
                f"{self._base_url}/api/pipeline/ocr/{claim.edital_id}/renew",
                headers=self._auth_headers(),
                json={"claim_token": claim.claim_token},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise TransientRenewalError(f"Transient renewal failure: {exc}") from exc

        if response.status_code == 409:
            raise ClaimOwnershipLost("claim renewal rejected")
        if response.status_code >= 500:
            raise TransientRenewalError(f"claim renewal returned HTTP {response.status_code}")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TransientRenewalError(f"Transient renewal failure: {exc}") from exc

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RenderCommunicationError(
                f"Invalid OCR claim renewal response: response is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RenderCommunicationError(
                "Invalid OCR claim renewal response: expected an object"
            )
        expires_at_raw = payload.get("expires_at")
        if not isinstance(expires_at_raw, str) or not expires_at_raw:
            raise RenderCommunicationError(
                "Invalid OCR claim renewal response: expires_at must be an ISO timestamp"
            )
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise RenderCommunicationError(
                "Invalid OCR claim renewal response: expires_at is not ISO-8601"
            ) from exc
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise RenderCommunicationError(
                "Invalid OCR claim renewal response: expires_at must include a timezone"
            )
        return expires_at

    def complete(
        self,
        claim: WorkerClaim,
        markdown: str,
        *,
        max_bytes: int = DEFAULT_MARKDOWN_MAX_BYTES,
    ) -> None:
        markdown_bytes = len(markdown.encode("utf-8"))
        effective_max_bytes = min(DEFAULT_MARKDOWN_MAX_BYTES, max(1, max_bytes))
        if markdown_bytes > effective_max_bytes:
            raise PayloadTooLargeError(
                f"OCR markdown is {markdown_bytes} bytes; maximum is {effective_max_bytes} bytes"
            )
        headers = {
            **self._auth_headers(),
            "X-OCR-Claim-Token": claim.claim_token,
            "Content-Type": "text/plain; charset=utf-8",
        }
        try:
            response = self._session.post(
                f"{self._base_url}/api/pipeline/ocr/{claim.edital_id}/complete",
                headers=headers,
                data=markdown.encode("utf-8"),
                timeout=120,
            )
        except requests.RequestException as exc:
            raise RenderCommunicationError(f"Failed to complete OCR claim: {exc}") from exc

        if response.status_code == 409:
            raise ClaimOwnershipLost("claim completion rejected")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RenderCommunicationError(f"Failed to complete OCR claim: {exc}") from exc

    def fail(self, claim: WorkerClaim, *, error_kind: str, error_message: str) -> None:
        try:
            response = self._session.post(
                f"{self._base_url}/api/pipeline/ocr/{claim.edital_id}/fail",
                headers=self._auth_headers(),
                json={
                    "claim_token": claim.claim_token,
                    "error_kind": error_kind,
                    "error_message": error_message,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RenderCommunicationError(f"Failed to report OCR failure: {exc}") from exc

        if response.status_code == 409:
            raise ClaimOwnershipLost("claim failure report rejected")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RenderCommunicationError(f"Failed to report OCR failure: {exc}") from exc


class LeaseHeartbeat:
    def __init__(
        self,
        api: OCRWorkerApi,
        claim: WorkerClaim,
        interval_seconds: float,
        join_timeout_seconds: float = DEFAULT_HEARTBEAT_JOIN_TIMEOUT_SECONDS,
    ):
        self.api = api.isolated()
        self.claim = claim
        self.interval_seconds = interval_seconds
        self.join_timeout_seconds = join_timeout_seconds
        self._expires_at = claim.expires_at
        self._stop = threading.Event()
        self._ownership_lost = threading.Event()
        self._communication_error: RenderCommunicationError | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            while not self._stop.wait(self.interval_seconds):
                try:
                    self._expires_at = self.api.renew(self.claim)
                except ClaimOwnershipLost:
                    self._ownership_lost.set()
                    return
                except TransientRenewalError as exc:
                    logger.warning(
                        "Transient OCR claim renewal failure for edital=%s: %s",
                        self.claim.edital_id,
                        exc,
                    )
                    if datetime.now(timezone.utc) >= self._expires_at:
                        self._ownership_lost.set()
                        return
                except RenderCommunicationError as exc:
                    logger.error(
                        "Malformed OCR claim heartbeat response for edital=%s: %s",
                        self.claim.edital_id,
                        exc,
                    )
                    self._communication_error = exc
                    self._ownership_lost.set()
                    return
                except Exception:
                    logger.exception(
                        "Unexpected OCR claim heartbeat failure for edital=%s",
                        self.claim.edital_id,
                    )
                    self._ownership_lost.set()
                    return
        finally:
            self.api.close()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._thread.join(timeout=self.join_timeout_seconds)
        if self._thread.is_alive():
            logger.error(
                "OCR claim heartbeat thread did not stop within %.1f seconds for edital=%s",
                self.join_timeout_seconds,
                self.claim.edital_id,
            )

    @property
    def ownership_lost(self) -> bool:
        return self._ownership_lost.is_set()

    @property
    def communication_error(self) -> RenderCommunicationError | None:
        return self._communication_error


class OCRWorker:
    def __init__(
        self,
        *,
        api: OCRWorkerApi,
        downloader: Callable[[str], bytes],
        extractor,
        renew_interval_seconds: float,
        markdown_max_bytes: int = DEFAULT_MARKDOWN_MAX_BYTES,
        heartbeat_join_timeout_seconds: float = DEFAULT_HEARTBEAT_JOIN_TIMEOUT_SECONDS,
    ) -> None:
        self.api = api
        self.downloader = downloader
        self.extractor = extractor
        self.renew_interval_seconds = renew_interval_seconds
        self.markdown_max_bytes = min(DEFAULT_MARKDOWN_MAX_BYTES, max(1, markdown_max_bytes))
        self.heartbeat_join_timeout_seconds = max(0.0, heartbeat_join_timeout_seconds)

    def _fail_remaining_claims(
        self,
        claims: list[WorkerClaim],
        *,
        error_message: str,
    ) -> None:
        if not claims:
            return
        logger.error(
            "Accounting for %d OCR claims after Render communication failure: %s",
            len(claims),
            [claim.edital_id for claim in claims],
        )
        for claim in claims:
            try:
                self.api.fail(
                    claim,
                    error_kind="communication_error",
                    error_message=error_message[:500],
                )
            except ClaimOwnershipLost:
                logger.warning("OCR claim already lost while accounting for edital=%s", claim.edital_id)
            except RenderCommunicationError:
                logger.error("Unable to account for OCR claim edital=%s", claim.edital_id)

    def run(self, *, limit: int) -> int:
        try:
            claims = self.api.claim(limit)
        except RenderCommunicationError:
            logger.exception("Unable to claim OCR work from Render")
            return 1

        for claim_index, claim in enumerate(claims):
            try:
                with LeaseHeartbeat(
                    self.api,
                    claim,
                    self.renew_interval_seconds,
                    self.heartbeat_join_timeout_seconds,
                ) as heartbeat:
                    pdf_bytes = self.downloader(claim.source_url)
                    markdown = asyncio.run(self.extractor.extract(pdf_bytes))
                communication_error = getattr(heartbeat, "communication_error", None)
                if communication_error is not None:
                    raise communication_error
                if not heartbeat.ownership_lost:
                    if len(markdown.encode("utf-8")) > self.markdown_max_bytes:
                        raise PayloadTooLargeError(
                            f"OCR markdown is {len(markdown.encode('utf-8'))} bytes; "
                            f"maximum is {self.markdown_max_bytes} bytes"
                        )
                    self.api.complete(
                        claim,
                        markdown,
                        max_bytes=self.markdown_max_bytes,
                    )
            except ClaimOwnershipLost:
                logger.warning("OCR claim lost before completion for edital=%s", claim.edital_id)
            except RenderCommunicationError as exc:
                logger.exception("Render communication failed while handling edital=%s", claim.edital_id)
                self._fail_remaining_claims(
                    claims[claim_index:],
                    error_message=f"Render communication failure: {exc}",
                )
                return 1
            except Exception as exc:
                try:
                    self.api.fail(
                        claim,
                        error_kind=classify_error(exc),
                        error_message=str(exc)[:500],
                    )
                except ClaimOwnershipLost:
                    logger.warning("OCR claim lost before failure report for edital=%s", claim.edital_id)
                except RenderCommunicationError as report_exc:
                    logger.exception("Render communication failed while reporting failure for edital=%s", claim.edital_id)
                    self._fail_remaining_claims(
                        claims[claim_index:],
                        error_message=f"Render communication failure: {report_exc}",
                    )
                    return 1
        return 0


def classify_error(exc: Exception) -> str:
    if isinstance(exc, DownloadError):
        return "download_error"
    if isinstance(exc, FileValidationError):
        return "invalid_pdf"
    if isinstance(exc, PayloadTooLargeError):
        return "payload_too_large"
    return "extraction_error"


def download_pdf_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: int,
) -> bytes:
    if not is_safe_url(url):
        raise DownloadError(f"Unsafe URL rejected: {url}")

    current_url = url
    with requests.Session() as session:
        for _ in range(6):
            try:
                response = session.get(
                    current_url,
                    timeout=timeout_seconds,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise DownloadError(f"Network error downloading {url}: {exc}") from exc

            if response.status_code in _REDIRECT_STATUS_CODES:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise DownloadError(f"Redirect with no Location header from {current_url}")
                current_url = urljoin(current_url, location)
                if not is_safe_url(current_url):
                    raise DownloadError(f"Redirect to unsafe URL rejected: {current_url}")
                continue

            if response.status_code >= 400:
                response.close()
                raise DownloadError(f"HTTP {response.status_code} for {current_url}")

            chunks: list[bytes] = []
            total = 0
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadError(f"PDF exceeded size limit of {max_bytes} bytes")
                    chunks.append(chunk)
            finally:
                response.close()

            pdf_bytes = b"".join(chunks)
            validate_pdf(pdf_bytes, max_size=max_bytes)
            return pdf_bytes

    raise DownloadError(f"Too many redirects downloading {url}")


def build_worker(settings: WorkerSettings) -> OCRWorker:
    api = OCRWorkerApi(settings.render_app_url, settings.pipeline_secret)
    extractor = PDFMarkdownExtractor(ocr_config=settings.ocr_config)
    downloader = lambda url: download_pdf_bytes(
        url,
        max_bytes=settings.pdf_max_bytes,
        timeout_seconds=settings.download_timeout_seconds,
    )
    return OCRWorker(
        api=api,
        downloader=downloader,
        extractor=extractor,
        renew_interval_seconds=settings.renew_interval_seconds,
        markdown_max_bytes=settings.markdown_max_bytes,
        heartbeat_join_timeout_seconds=settings.heartbeat_join_timeout_seconds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GitHub Actions OCR worker.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum OCR claims to process")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = parse_args()
    settings = WorkerSettings.from_env(limit_override=args.limit if args.limit > 0 else None)
    worker = build_worker(settings)
    return worker.run(limit=settings.limit)


if __name__ == "__main__":
    raise SystemExit(main())
