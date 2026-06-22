"""Generic download / OCR / submit pipeline shared across cronjob discoverers.

Extracted from ``scripts/discover_pncp_candidates.py``. This module owns
the parts of the pipeline that are not specific to PNCP:

- HTTP download with retry + SSRF guard (delegates to ``pncp_http``)
- Per-run counters (downloaded PDFs, etc.)
- OCR call
- Render submit (POST ``/api/pipeline/candidates``) with batching + retry

The PNCP discoverer still owns the source-specific parts (fetching
records, modality filtering, year eligibility, document priority, the
``/atualizacao`` checkpoint). New per-source discoverers call into the
functions here for download / OCR / submit.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

from pncp_http import DownloadError, download_pncp_pdf


SCRAPE_MAX_PDF_BYTES = int(os.getenv("SCRAPE_MAX_PDF_BYTES", "15000000"))
SCRAPE_MAX_PDFS_PER_RUN = int(os.getenv("SCRAPE_MAX_PDFS_PER_RUN", "5"))

RENDER_SUBMIT_BATCH_SIZE = int(os.environ.get("RENDER_SUBMIT_BATCH_SIZE", "30"))
RENDER_SUBMIT_TIMEOUT = int(os.environ.get("RENDER_SUBMIT_TIMEOUT", "90"))
RENDER_SUBMIT_MAX_ATTEMPTS = int(os.environ.get("RENDER_SUBMIT_MAX_ATTEMPTS", "4"))
RENDER_SUBMIT_BACKOFF_BASE = float(os.environ.get("RENDER_SUBMIT_BACKOFF_BASE", "5"))
RENDER_SUBMIT_MAX_MARKDOWN_CHARS = int(os.environ.get("RENDER_SUBMIT_MAX_MARKDOWN_CHARS", "1000000"))


_pdf_download_counter_lock = threading.Lock()


def pdf_download_limit_reached(stats: dict[str, int]) -> bool:
    return stats.get("pdfs_downloaded", 0) >= SCRAPE_MAX_PDFS_PER_RUN


def record_pdf_download(stats: dict[str, int]) -> None:
    with _pdf_download_counter_lock:
        stats["pdfs_downloaded"] = stats.get("pdfs_downloaded", 0) + 1


def process_candidate(
    candidate: dict[str, Any],
    *,
    extractor: Any,
    max_bytes: int,
    connect_timeout: int = 30,
    read_timeout: int = 120,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """Download a candidate PDF, OCR it, and return a worker_result dict.

    On success the returned dict contains
    ``{"url", "kind", "metadata", "worker_result": {...}}``.
    On failure it contains ``{"url", "metadata", "error": "..."}``.
    """
    url = candidate["url"]
    metadata = candidate.get("metadata", {})
    error_context = {"url": url, "metadata": metadata}

    try:
        dl = download_pncp_pdf(
            url,
            max_bytes=max_bytes,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_attempts=max_attempts,
        )
    except DownloadError as exc:
        print(f"warning: download failed for {url}: {exc}", file=sys.stderr)
        return {**error_context, "error": f"download: {exc}"}

    print(f"Downloaded PDF: {url} ({dl.content_length} bytes)")
    pdf_bytes = dl.content
    try:
        markdown = asyncio.run(extractor.extract(pdf_bytes))
    except Exception as exc:
        print(f"warning: OCR failed for {url}: {exc}", file=sys.stderr)
        return {**error_context, "error": f"ocr: {exc}"}
    finally:
        pdf_bytes = None

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "url": url,
        "kind": candidate.get("kind", "pdf"),
        "metadata": metadata,
        "worker_result": {
            "ocr_markdown": markdown,
            "content_hash": dl.content_hash,
            "content_length": dl.content_length,
            "validated_at": now_iso,
            "validation_outcome": "valid_pdf",
        },
    }


def _is_retryable_response(response: requests.Response) -> bool:
    return response.status_code in (408, 425, 429, 500, 502, 503, 504)


def make_default_ocr_extractor() -> tuple[Any, Any]:
    """Build the default ``(OCRExtractionConfig, PDFMarkdownExtractor)`` pair.

    Centralises the env-driven OCR configuration that ``main()``
    functions previously duplicated per source. Returns a 2-tuple so
    callers can keep the config alive alongside the extractor (useful
    when unit tests want to inspect ``extractor.ocr_config``).

    The values mirror the FastAPI cronjob defaults and honour the same
    env vars (``KREUZBERG_PADDLE_LANGUAGE``,
    ``KREUZBERG_PADDLE_MODEL_TIER``, ``KREUZBERG_USE_GPU``,
    ``KREUZBERG_FORCE_OCR_DEFAULT``, ``KREUZBERG_EXTRACTION_TIMEOUT_SECONDS``).
    """
    from ocr_worker.ocr_extraction_config import OCRExtractionConfig
    from ocr_worker.pdf_markdown_extractor import PDFMarkdownExtractor

    config = OCRExtractionConfig(
        language=os.getenv("KREUZBERG_PADDLE_LANGUAGE", "latin"),
        model_tier=os.getenv("KREUZBERG_PADDLE_MODEL_TIER", "tiny"),
        use_gpu=os.getenv("KREUZBERG_USE_GPU", "false").lower() == "true",
        force_ocr=os.getenv("KREUZBERG_FORCE_OCR_DEFAULT", "false").lower() == "true",
        extraction_timeout_seconds=int(os.getenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", "300")),
    )
    extractor = PDFMarkdownExtractor(ocr_config=config)
    return config, extractor


def _truncate_markdown(candidate: dict[str, Any]) -> dict[str, Any]:
    wr = candidate.get("worker_result")
    if not wr:
        return candidate
    md = wr.get("ocr_markdown", "")
    if len(md) > RENDER_SUBMIT_MAX_MARKDOWN_CHARS:
        candidate = {**candidate, "worker_result": {**wr, "ocr_markdown": md[:RENDER_SUBMIT_MAX_MARKDOWN_CHARS]}}
    return candidate


def _post_batch(
    render_url: str,
    token: str,
    source: str,
    batch: list[dict[str, Any]],
    batch_index: int,
    total_batches: int,
) -> tuple[dict[str, Any] | None, str | None]:
    url = f"{render_url}/api/pipeline/candidates"
    last_error: str | None = None

    for attempt in range(1, RENDER_SUBMIT_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"source": source, "candidates": batch},
                timeout=RENDER_SUBMIT_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"warning: Render submit batch {batch_index}/{total_batches} "
                f"attempt {attempt}/{RENDER_SUBMIT_MAX_ATTEMPTS} failed: {last_error}",
                file=sys.stderr,
            )
            if attempt < RENDER_SUBMIT_MAX_ATTEMPTS:
                time.sleep(RENDER_SUBMIT_BACKOFF_BASE ** attempt)
            continue

        if response.status_code >= 500 or _is_retryable_response(response):
            last_error = f"HTTP {response.status_code}"
            print(
                f"warning: Render submit batch {batch_index}/{total_batches} "
                f"attempt {attempt}/{RENDER_SUBMIT_MAX_ATTEMPTS} returned {last_error}",
                file=sys.stderr,
            )
            if attempt < RENDER_SUBMIT_MAX_ATTEMPTS:
                time.sleep(RENDER_SUBMIT_BACKOFF_BASE ** attempt)
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            last_error = f"HTTP {exc.response.status_code if exc.response is not None else '?'}"
            print(
                f"error: Render submit batch {batch_index}/{total_batches} "
                f"non-retryable failure: {last_error}",
                file=sys.stderr,
            )
            return None, last_error

        try:
            return response.json(), None
        except ValueError:
            return {"status": "accepted"}, None

    return None, last_error


def submit_candidates(
    candidates: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    render_url = os.environ["RENDER_APP_URL"].rstrip("/")
    token = os.environ["PIPELINE_SECRET"]

    valid = [
        _truncate_markdown(c)
        for c in candidates
        if c.get("worker_result") and not c.get("error")
    ]

    batches = [
        valid[i : i + RENDER_SUBMIT_BATCH_SIZE]
        for i in range(0, len(valid), RENDER_SUBMIT_BATCH_SIZE)
    ]
    total_batches = len(batches)

    submitted = 0
    failed_batches: list[str] = []
    last_result: dict[str, Any] | None = None

    for index, batch in enumerate(batches, start=1):
        result, error = _post_batch(render_url, token, source, batch, index, total_batches)
        if error is None:
            submitted += len(batch)
            last_result = result
            print(
                f"Render submit batch {index}/{total_batches}: "
                f"{len(batch)} candidates accepted"
            )
        else:
            failed_batches.append(f"batch {index}/{total_batches} ({len(batch)}): {error}")
            break

    summary = {
        "total": len(candidates),
        "filtered_out": len(candidates) - len(valid),
        "submitted": submitted,
        "failed_batches": len(failed_batches),
        "errors": failed_batches,
        "last_result": last_result,
    }

    if submitted == 0 and failed_batches:
        print(
            f"error: {len(failed_batches)}/{total_batches} Render submit batches failed",
            file=sys.stderr,
        )
    elif failed_batches:
        print(
            f"warning: {len(failed_batches)}/{total_batches} Render submit batches failed",
            file=sys.stderr,
        )

    return summary
