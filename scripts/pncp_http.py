"""Bounded HTTP download for PNCP PDFs with retry and SSRF protection."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

from ocr_worker.file_validation import FileValidationError, validate_pdf
from ocr_worker.url_validation import is_safe_url


_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_PERMANENT_STATUS_CODES = frozenset({404, 410, 422})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_CONNECT_TIMEOUT = 30
_DEFAULT_READ_TIMEOUT = 120
_DEFAULT_MAX_ATTEMPTS = 4
_DEFAULT_BACKOFF_SEQUENCE = (5, 15, 45)
_RETRY_AFTER_CAP = 120


class DownloadError(RuntimeError):
    """Raised when a PDF download fails permanently or after exhausting retries."""


@dataclass(frozen=True)
class DownloadResult:
    """Successful download outcome containing validated PDF bytes."""

    content: bytes
    content_hash: str
    content_length: int


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _backoff_sleep(attempt: int, retry_after_header: str | None) -> None:
    if retry_after_header is not None:
        try:
            delay = min(int(retry_after_header), _RETRY_AFTER_CAP)
        except (ValueError, TypeError):
            delay = _DEFAULT_BACKOFF_SEQUENCE[min(attempt - 1, len(_DEFAULT_BACKOFF_SEQUENCE) - 1)]
    else:
        idx = min(attempt - 1, len(_DEFAULT_BACKOFF_SEQUENCE) - 1)
        delay = _DEFAULT_BACKOFF_SEQUENCE[idx]
    time.sleep(delay)


def download_pncp_pdf(
    url: str,
    *,
    max_bytes: int,
    connect_timeout: int = _DEFAULT_CONNECT_TIMEOUT,
    read_timeout: int = _DEFAULT_READ_TIMEOUT,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> DownloadResult:
    if not is_safe_url(url):
        raise DownloadError(f"Unsafe URL rejected: {url}")

    current_url = url
    last_error: str | None = None

    with requests.Session() as session:
        for attempt in range(1, max_attempts + 1):
            response = None
            try:
                response = session.get(
                    current_url,
                    timeout=(connect_timeout, read_timeout),
                    allow_redirects=False,
                    stream=True,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"Network error: {exc}"
                if attempt < max_attempts:
                    _backoff_sleep(attempt, None)
                    continue
                raise DownloadError(
                    f"Network error after {max_attempts} attempts downloading {url}: {exc}"
                ) from exc
            except requests.RequestException as exc:
                raise DownloadError(f"Request error downloading {url}: {exc}") from exc

            try:
                if response.status_code in _PERMANENT_STATUS_CODES:
                    raise DownloadError(
                        f"Permanent HTTP {response.status_code} for {current_url}"
                    )

                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = response.headers.get("Location")
                    if not location:
                        raise DownloadError(
                            f"Redirect with no Location header from {current_url}"
                        )
                    current_url = urljoin(current_url, location)
                    if not is_safe_url(current_url):
                        raise DownloadError(
                            f"Redirect to unsafe URL rejected: {current_url}"
                        )
                    continue

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    retry_after = response.headers.get("Retry-After")
                    if attempt < max_attempts:
                        _backoff_sleep(attempt, retry_after)
                        continue
                    raise DownloadError(
                        f"Retryable HTTP {response.status_code} after {max_attempts} "
                        f"attempts downloading {url}"
                    )

                if response.status_code >= 400:
                    raise DownloadError(
                        f"HTTP {response.status_code} for {current_url}"
                    )

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadError(
                            f"PDF exceeded size limit of {max_bytes} bytes"
                        )
                    chunks.append(chunk)

                pdf_bytes = b"".join(chunks)
                try:
                    validate_pdf(pdf_bytes, max_size=max_bytes)
                except FileValidationError as exc:
                    raise DownloadError(f"PDF validation failed: {exc}") from exc

                return DownloadResult(
                    content=pdf_bytes,
                    content_hash=_compute_hash(pdf_bytes),
                    content_length=len(pdf_bytes),
                )
            finally:
                if response is not None:
                    response.close()

    raise DownloadError(f"Download failed after {max_attempts} attempts for {url}")
