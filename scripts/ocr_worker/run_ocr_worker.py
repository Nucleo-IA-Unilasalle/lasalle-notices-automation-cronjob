from __future__ import annotations

import argparse
import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urljoin

import requests

from ocr_extraction_config import OCRExtractionConfig
from pdf_markdown_extractor import PDFMarkdownExtractor
from file_validation import FileValidationError, validate_pdf
from url_validation import is_safe_url

logger = logging.getLogger(__name__)

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class ClaimOwnershipLost(RuntimeError):
    """Raised when Render rejects a claim operation because ownership changed."""


class DownloadError(RuntimeError):
    """Raised when the worker cannot fetch a PDF safely."""


class RenderCommunicationError(RuntimeError):
    """Raised when the worker cannot communicate with Render reliably."""


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
    ocr_config: OCRExtractionConfig

    @classmethod
    def from_env(cls, *, limit_override: int | None = None) -> "WorkerSettings":
        render_app_url = os.environ["RENDER_APP_URL"].rstrip("/")
        pipeline_secret = os.environ["PIPELINE_SECRET"]
        limit = limit_override or int(os.getenv("OCR_WORKER_MAX_CLAIMS", "5"))
        renew_interval_seconds = float(os.getenv("OCR_WORKER_RENEW_INTERVAL_SECONDS", "60"))
        pdf_max_bytes = int(os.getenv("SCRAPE_MAX_PDF_BYTES", "15000000"))
        download_timeout_seconds = int(os.getenv("AI_SOURCE_RESOLUTION_TIMEOUT_SECONDS", "60"))
        ocr_config = OCRExtractionConfig(
            language=os.getenv("KREUZBERG_PADDLE_LANGUAGE", "latin"),
            model_tier=os.getenv("KREUZBERG_PADDLE_MODEL_TIER", "mobile"),
            use_gpu=os.getenv("KREUZBERG_USE_GPU", "false").lower() == "true",
            force_ocr=os.getenv("KREUZBERG_FORCE_OCR_DEFAULT", "false").lower() == "true",
            extraction_timeout_seconds=int(os.getenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", "300")),
        )
        return cls(
            render_app_url=render_app_url,
            pipeline_secret=pipeline_secret,
            limit=limit,
            renew_interval_seconds=renew_interval_seconds,
            pdf_max_bytes=pdf_max_bytes,
            download_timeout_seconds=download_timeout_seconds,
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

    def claim(self, limit: int) -> list[WorkerClaim]:
        try:
            response = self._session.post(
                f"{self._base_url}/api/pipeline/ocr/claim?limit={limit}",
                headers=self._auth_headers(),
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RenderCommunicationError(f"Failed to claim OCR work: {exc}") from exc

        return [
            WorkerClaim(
                edital_id=item["edital_id"],
                source_url=item["source_url"],
                original_filename=item.get("original_filename"),
                claim_token=item["claim_token"],
                expires_at=datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00")),
            )
            for item in response.json()["claims"]
        ]

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

        return datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00"))

    def complete(self, claim: WorkerClaim, markdown: str) -> None:
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
    def __init__(self, api: OCRWorkerApi, claim: WorkerClaim, interval_seconds: float):
        self.api = api.isolated()
        self.claim = claim
        self.interval_seconds = interval_seconds
        self._expires_at = claim.expires_at
        self._stop = threading.Event()
        self._ownership_lost = threading.Event()
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
        self._thread.join()

    @property
    def ownership_lost(self) -> bool:
        return self._ownership_lost.is_set()


class OCRWorker:
    def __init__(
        self,
        *,
        api: OCRWorkerApi,
        downloader: Callable[[str], bytes],
        extractor,
        renew_interval_seconds: float,
    ) -> None:
        self.api = api
        self.downloader = downloader
        self.extractor = extractor
        self.renew_interval_seconds = renew_interval_seconds

    def run(self, *, limit: int) -> int:
        try:
            claims = self.api.claim(limit)
        except RenderCommunicationError:
            logger.exception("Unable to claim OCR work from Render")
            return 1

        for claim in claims:
            try:
                with LeaseHeartbeat(self.api, claim, self.renew_interval_seconds) as heartbeat:
                    pdf_bytes = self.downloader(claim.source_url)
                    markdown = asyncio.run(self.extractor.extract(pdf_bytes))
                if not heartbeat.ownership_lost:
                    self.api.complete(claim, markdown)
            except ClaimOwnershipLost:
                logger.warning("OCR claim lost before completion for edital=%s", claim.edital_id)
            except RenderCommunicationError:
                logger.exception("Render communication failed while handling edital=%s", claim.edital_id)
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
                except RenderCommunicationError:
                    logger.exception("Render communication failed while reporting failure for edital=%s", claim.edital_id)
                    return 1
        return 0


def classify_error(exc: Exception) -> str:
    if isinstance(exc, DownloadError):
        return "download_error"
    if isinstance(exc, FileValidationError):
        return "invalid_pdf"
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
