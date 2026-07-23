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
import hashlib
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

from archive_validation import ArchiveLimits, inspect_zip_archive
from pncp_http import DownloadError, download_pncp_pdf
from scraper_transport import request_with_safe_redirects


SCRAPE_MAX_PDF_BYTES = int(os.getenv("SCRAPE_MAX_PDF_BYTES", "15000000"))
SCRAPE_MAX_PDFS_PER_RUN = int(os.getenv("SCRAPE_MAX_PDFS_PER_RUN", "5"))

RENDER_SUBMIT_BATCH_SIZE = int(os.environ.get("RENDER_SUBMIT_BATCH_SIZE", "30"))
RENDER_SUBMIT_TIMEOUT = int(os.environ.get("RENDER_SUBMIT_TIMEOUT", "90"))
RENDER_SUBMIT_MAX_ATTEMPTS = int(os.environ.get("RENDER_SUBMIT_MAX_ATTEMPTS", "4"))
RENDER_SUBMIT_BACKOFF_BASE = float(os.environ.get("RENDER_SUBMIT_BACKOFF_BASE", "5"))
RENDER_SUBMIT_MAX_MARKDOWN_CHARS = int(os.environ.get("RENDER_SUBMIT_MAX_MARKDOWN_CHARS", "1000000"))
OPPORTUNITY_ATTACHMENT_MAX_BYTES = int(
    os.environ.get("OPPORTUNITY_ATTACHMENT_MAX_BYTES", "15000000")
)


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


def _download_attachment(url: str, *, max_bytes: int) -> bytes:
    """Download an attachment through the shared redirect and SSRF guard."""
    response = request_with_safe_redirects(
        method="GET",
        url=url,
        timeout=RENDER_SUBMIT_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > max_bytes:
        response.close()
        raise ValueError("attachment exceeds configured compressed-size limit")
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("attachment exceeds configured compressed-size limit")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


def process_opportunity(
    opportunity: dict[str, Any],
    *,
    extractor: Any,
    stats: dict[str, int],
) -> dict[str, Any]:
    """Validate and OCR source-owned attachments for one opportunity."""
    processed_documents: list[dict[str, Any]] = []
    source_markdown = str(opportunity.get("source_markdown") or "").strip()
    for descriptor in opportunity.get("documents", []):
        document = dict(descriptor)
        url = str(document.get("url") or "")
        kind = document.get("document_kind")
        try:
            if kind == "pdf":
                if pdf_download_limit_reached(stats):
                    stats["pdf_download_cap_reached"] = 1
                    document.update(
                        is_principal=False,
                        is_renderable=False,
                        validation_outcome="download_cap_reached",
                    )
                else:
                    result = process_candidate(
                        {"url": url, "kind": "pdf", "metadata": {}},
                        extractor=extractor,
                        max_bytes=SCRAPE_MAX_PDF_BYTES,
                    )
                    worker = result.get("worker_result")
                    if worker:
                        record_pdf_download(stats)
                        document.update(
                            content_hash=worker["content_hash"],
                            content_length=worker["content_length"],
                            is_renderable=True,
                            validation_outcome="valid_pdf",
                            validated_at=worker["validated_at"],
                            extracted_markdown=worker["ocr_markdown"],
                        )
                    else:
                        document.update(
                            is_principal=False,
                            is_renderable=False,
                            validation_outcome="pdf_validation_failed",
                        )
            elif kind == "zip":
                archive_bytes = _download_attachment(
                    url, max_bytes=OPPORTUNITY_ATTACHMENT_MAX_BYTES
                )
                inspection = inspect_zip_archive(
                    archive_bytes,
                    limits=ArchiveLimits(
                        max_compressed_bytes=OPPORTUNITY_ATTACHMENT_MAX_BYTES
                    ),
                )
                extracted_sections: list[str] = []
                for member in inspection.pdf_members:
                    markdown = asyncio.run(extractor.extract(member.content))
                    extracted_sections.append(
                        f"## Arquivo: {member.filename}\n\n{markdown.strip()}"
                    )
                document.update(
                    content_hash=hashlib.sha256(archive_bytes).hexdigest(),
                    content_length=len(archive_bytes),
                    is_principal=False,
                    is_renderable=False,
                    validation_outcome=inspection.outcome,
                    validated_at=datetime.now(timezone.utc).isoformat(),
                    extracted_markdown="\n\n".join(extracted_sections) or None,
                    archive_evidence=inspection.to_evidence(),
                )
            else:
                document.update(is_renderable=False)
        except Exception as exc:
            document.update(
                is_principal=False,
                is_renderable=False,
                validation_outcome=f"{kind or 'attachment'}_validation_failed",
                validation_error=str(exc)[:500],
            )
            stats["attachment_failures"] = stats.get("attachment_failures", 0) + 1
        processed_documents.append(document)

    backend_documents = [
        {
            key: value
            for key, value in document.items()
            if key not in {"archive_evidence", "validation_error"}
        }
        for document in processed_documents
    ]
    principal_seen = False
    for document in backend_documents:
        if document.get("is_renderable") and not principal_seen:
            document["is_principal"] = True
            principal_seen = True
        elif document.get("is_principal"):
            document["is_principal"] = False

    normalized = {
        **opportunity,
        "source_markdown": source_markdown,
        "source_content_hash": hashlib.sha256(
            source_markdown.encode("utf-8")
        ).hexdigest(),
        "documents": backend_documents,
        "_attachment_diagnostics": processed_documents,
    }
    return normalized


def submit_opportunities(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    """Submit strict opportunity payloads one-by-one for identity-safe retries."""
    render_url = os.environ["RENDER_APP_URL"].rstrip("/")
    token = os.environ["PIPELINE_SECRET"]
    submitted = 0
    errors: list[str] = []
    outcomes: list[dict[str, Any]] = []
    for index, opportunity in enumerate(opportunities, start=1):
        payload = {
            key: value
            for key, value in opportunity.items()
            if not key.startswith("_")
        }
        result, error = _post_opportunity(
            render_url, token, payload, index, len(opportunities)
        )
        if error:
            errors.append(error)
            continue
        submitted += 1
        outcomes.append(result or {"outcome": "accepted"})
    return {
        "total": len(opportunities),
        "submitted": submitted,
        "failed": len(errors),
        "errors": errors,
        "outcomes": outcomes,
    }


def _post_opportunity(
    render_url: str,
    token: str,
    payload: dict[str, Any],
    index: int,
    total: int,
) -> tuple[dict[str, Any] | None, str | None]:
    url = f"{render_url}/api/pipeline/opportunities"
    last_error: str | None = None
    for attempt in range(1, RENDER_SUBMIT_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                timeout=RENDER_SUBMIT_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"opportunity {index}/{total}: {type(exc).__name__}: {exc}"
        else:
            if response.status_code < 400:
                try:
                    return response.json(), None
                except ValueError:
                    return {"status": "accepted"}, None
            if not _is_retryable_response(response):
                return None, f"opportunity {index}/{total}: HTTP {response.status_code}"
            last_error = f"opportunity {index}/{total}: HTTP {response.status_code}"
        if attempt < RENDER_SUBMIT_MAX_ATTEMPTS:
            time.sleep(RENDER_SUBMIT_BACKOFF_BASE ** attempt)
    return None, last_error
