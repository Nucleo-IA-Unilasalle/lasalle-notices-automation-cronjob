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
import json
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

try:
    from ocr_worker.ocr_extraction_config import parse_ocr_timeout
except ModuleNotFoundError:
    # Support importing this module as ``scripts.pipeline_core`` in tests.
    from scripts.ocr_worker.ocr_extraction_config import parse_ocr_timeout


SCRAPE_MAX_PDF_BYTES = int(os.getenv("SCRAPE_MAX_PDF_BYTES", "15000000"))
SCRAPE_MAX_PDFS_PER_RUN = int(os.getenv("SCRAPE_MAX_PDFS_PER_RUN", "5"))


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default

RENDER_SUBMIT_TIMEOUT = int(os.environ.get("RENDER_SUBMIT_TIMEOUT", "90"))
RENDER_SUBMIT_MAX_ATTEMPTS = int(os.environ.get("RENDER_SUBMIT_MAX_ATTEMPTS", "4"))
RENDER_SUBMIT_BACKOFF_BASE = float(os.environ.get("RENDER_SUBMIT_BACKOFF_BASE", "5"))
RENDER_SUBMIT_MAX_MARKDOWN_CHARS = int(os.environ.get("RENDER_SUBMIT_MAX_MARKDOWN_CHARS", "1000000"))
RENDER_SUBMIT_BATCH_SIZE = _positive_env_int("RENDER_SUBMIT_BATCH_SIZE", 5)
RENDER_SUBMIT_MAX_PAYLOAD_CHARS = min(
    9_500_000,
    _positive_env_int("RENDER_SUBMIT_MAX_PAYLOAD_CHARS", 9_500_000),
)
RENDER_CAPABILITIES_PATH = "/api/pipeline/capabilities"
OPPORTUNITY_MARKDOWN_MAX_CHARS = 2_000_000
OPPORTUNITY_ATTACHMENT_MAX_BYTES = int(
    os.environ.get("OPPORTUNITY_ATTACHMENT_MAX_BYTES", "15000000")
)
_PERSISTED_SUBMISSION_OUTCOMES = {"inserted", "updated", "reactivated", "duplicate"}


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

    max_pages = _positive_env_int("OCR_MAX_PDF_PAGES", 50)
    config = OCRExtractionConfig(
        language=os.getenv("KREUZBERG_PADDLE_LANGUAGE", "latin"),
        model_tier=os.getenv("KREUZBERG_PADDLE_MODEL_TIER", "tiny"),
        use_gpu=os.getenv("KREUZBERG_USE_GPU", "false").lower() == "true",
        force_ocr=os.getenv("KREUZBERG_FORCE_OCR_DEFAULT", "false").lower() == "true",
        extraction_timeout_seconds=parse_ocr_timeout(
            os.getenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS")
        ),
        max_pages=max_pages,
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


def _serialized_candidate_chars(candidate: dict[str, Any]) -> int:
    """Match Repo A's candidate-size validator for worker data and metadata."""
    worker_result = candidate.get("worker_result")
    metadata = candidate.get("metadata")
    return sum(
        len(json.dumps(value, ensure_ascii=False, default=str))
        for value in (worker_result, metadata)
        if value
    )


def _build_candidate_batches(
    candidates: list[dict[str, Any]],
) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Build batches that stay below Repo A's aggregate character limit."""
    batches: list[list[dict[str, Any]]] = []
    oversized: list[str] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for candidate in candidates:
        candidate_chars = _serialized_candidate_chars(candidate)
        if candidate_chars > RENDER_SUBMIT_MAX_PAYLOAD_CHARS:
            oversized.append(
                f"candidate {candidate.get('url', '<unknown>')} exceeds "
                f"{RENDER_SUBMIT_MAX_PAYLOAD_CHARS} serialized characters"
            )
            continue
        if current and (
            len(current) >= RENDER_SUBMIT_BATCH_SIZE
            or current_chars + candidate_chars > RENDER_SUBMIT_MAX_PAYLOAD_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(candidate)
        current_chars += candidate_chars
    if current:
        batches.append(current)
    return batches, oversized


def _post_batch(
    render_url: str,
    token: str,
    source: str,
    batch: list[dict[str, Any]],
    batch_index: int | str,
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

        if response.status_code >= 400 and (
            response.status_code >= 500 or _is_retryable_response(response)
        ):
            last_error = f"HTTP {response.status_code}"
            print(
                f"warning: Render submit batch {batch_index}/{total_batches} "
                f"attempt {attempt}/{RENDER_SUBMIT_MAX_ATTEMPTS} returned {last_error}",
                file=sys.stderr,
            )
            if attempt < RENDER_SUBMIT_MAX_ATTEMPTS:
                time.sleep(RENDER_SUBMIT_BACKOFF_BASE ** attempt)
            continue

        if response.status_code >= 400:
            last_error = f"HTTP {response.status_code}"
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


def _submission_outcome(
    payload: Any,
    batch: list[dict[str, Any]],
) -> tuple[int, str | None]:
    """Count Repo A outcomes and surface HTTP-200 per-item validation failures."""
    if not isinstance(payload, dict):
        return 0, "response body is not an object"

    items = payload.get("items")
    if isinstance(items, list):
        if len(items) != len(batch):
            return 0, (
                f"response contains {len(items)} item outcomes for "
                f"{len(batch)} submitted candidates"
            )
        submitted = 0
        invalid_urls: list[str] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return 0, f"item outcome {index} is not an object"
            outcome = item.get("outcome")
            if outcome in _PERSISTED_SUBMISSION_OUTCOMES:
                submitted += 1
            elif outcome == "invalid":
                invalid_urls.append(str(item.get("url") or f"item {index}"))
            else:
                return 0, f"item outcome {index} has unknown outcome {outcome!r}"
        if invalid_urls:
            return submitted, (
                "HTTP 200 returned invalid candidate outcomes for: "
                f"{', '.join(invalid_urls)}"
            )
        return submitted, None

    invalid = payload.get("invalid")
    if isinstance(invalid, int) and invalid > 0:
        accepted = sum(
            int(payload.get(name, 0) or 0)
            for name in _PERSISTED_SUBMISSION_OUTCOMES
            if isinstance(payload.get(name, 0), int)
        )
        return accepted, f"HTTP 200 reported {invalid} invalid candidate outcome(s)"

    # Keep compatibility with older test doubles and deployments that returned
    # only aggregate counters before Repo A added the per-item `items` field.
    # Without an `items` list there is no safe per-item persisted count, so the
    # legacy response is treated as accepting the batch unless it reports
    # invalid rows explicitly.
    return len(batch), None


def _post_batch_with_payload_shrink(
    render_url: str,
    token: str,
    source: str,
    batch: list[dict[str, Any]],
    batch_label: str,
    total_batches: int,
) -> tuple[int, dict[str, Any] | None, list[str]]:
    """Retry a 422 batch as smaller batches instead of repeating the same body."""
    result, error = _post_batch(
        render_url,
        token,
        source,
        batch,
        batch_label,
        total_batches,
    )
    if error is None:
        accepted, outcome_error = _submission_outcome(result, batch)
        if outcome_error is not None:
            return accepted, result, [
                f"batch {batch_label} ({len(batch)}): {outcome_error}"
            ]
        return accepted, result, []
    if error != "HTTP 422" or len(batch) <= 1:
        return 0, result, [f"batch {batch_label} ({len(batch)}): {error}"]

    midpoint = len(batch) // 2
    left_submitted, left_result, left_errors = _post_batch_with_payload_shrink(
        render_url,
        token,
        source,
        batch[:midpoint],
        f"{batch_label}a",
        total_batches,
    )
    right_submitted, right_result, right_errors = _post_batch_with_payload_shrink(
        render_url,
        token,
        source,
        batch[midpoint:],
        f"{batch_label}b",
        total_batches,
    )
    # Preserve the outcome counters from both child requests.  The caller gets
    # one result per logical input batch, so aggregate the recursively split
    # responses before returning it.
    merged_result = dict(right_result or left_result or {})
    merged_counts: dict[str, int] = {}
    for child in (left_result, right_result):
        if not isinstance(child, dict):
            continue
        counts = child.get("outcome_counts")
        if not isinstance(counts, dict):
            counts = child
        for name in ("inserted", "updated", "reactivated", "duplicates", "duplicate", "invalid"):
            value = counts.get(name, 0)
            if isinstance(value, int) and not isinstance(value, bool):
                canonical = "duplicates" if name == "duplicate" else name
                merged_counts[canonical] = merged_counts.get(canonical, 0) + value
    if merged_counts:
        merged_result["outcome_counts"] = merged_counts
    return (
        left_submitted + right_submitted,
        merged_result or None,
        left_errors + right_errors,
    )


def _outcome_counts(result: dict[str, Any] | None) -> dict[str, int]:
    """Read and canonicalize persistence counters from a backend response."""
    if not isinstance(result, dict):
        return {}
    counts = result.get("outcome_counts")
    if not isinstance(counts, dict):
        counts = result
    output: dict[str, int] = {}
    for name in ("inserted", "updated", "reactivated", "invalid"):
        value = counts.get(name, 0)
        if isinstance(value, int) and not isinstance(value, bool):
            output[name] = value
    duplicate = counts.get("duplicates", counts.get("duplicate", 0))
    if isinstance(duplicate, int) and not isinstance(duplicate, bool):
        output["duplicates"] = duplicate
    return output


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

    batches, oversized_errors = _build_candidate_batches(valid)
    total_batches = len(batches)

    submitted = 0
    failed_batches: list[str] = list(oversized_errors)
    last_result: dict[str, Any] | None = None
    outcome_counts = {name: 0 for name in ("inserted", "updated", "reactivated", "duplicates", "invalid")}

    for index, batch in enumerate(batches, start=1):
        accepted, result, errors = _post_batch_with_payload_shrink(
            render_url,
            token,
            source,
            batch,
            str(index),
            total_batches,
        )
        submitted += accepted
        if result is not None:
            last_result = result
            for name, value in _outcome_counts(result).items():
                outcome_counts[name] += value
        if not errors:
            print(
                f"Render submit batch {index}/{total_batches}: "
                f"{accepted} candidates accepted"
            )
        else:
            failed_batches.extend(errors)

    summary = {
        "total": len(candidates),
        "filtered_out": len(candidates) - len(valid) + len(oversized_errors),
        "submitted": submitted,
        "failed_batches": len(failed_batches),
        "errors": failed_batches,
        "last_result": last_result,
        "outcome_counts": outcome_counts,
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
    source_markdown = (
        str(opportunity.get("source_markdown") or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )
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


class CapabilityPreflightError(RuntimeError):
    """Raised when Repo A cannot report the structured submission capability."""


def _has_renderable_pdf(opportunity: dict[str, Any]) -> bool:
    documents = opportunity.get("documents")
    if not isinstance(documents, list):
        return False
    return any(
        document.get("document_kind") == "pdf" and document.get("is_renderable") is True
        for document in documents
        if isinstance(document, dict)
    )


def _read_documentless_capability(payload: Any) -> bool:
    """Parse only Repo A's exact capabilities response contract."""
    expected_keys = {
        "status",
        "documentless_opportunities_enabled",
        "documentless_opportunity_rollout",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise CapabilityPreflightError(
            "Repo A capabilities response does not match the exact contract"
        )
    if payload["status"] != "ok":
        raise CapabilityPreflightError(
            "Repo A capabilities response status must be 'ok'"
        )

    enabled = payload["documentless_opportunities_enabled"]
    rollout = payload["documentless_opportunity_rollout"]
    if type(enabled) is not bool:
        raise CapabilityPreflightError(
            "Repo A documentless_opportunities_enabled must be a boolean"
        )
    if not isinstance(rollout, str) or rollout not in {"enabled", "disabled"}:
        raise CapabilityPreflightError(
            "Repo A documentless_opportunity_rollout must be 'enabled' or 'disabled'"
        )
    expected_rollout = "enabled" if enabled else "disabled"
    if rollout != expected_rollout:
        raise CapabilityPreflightError(
            "Repo A documentless_opportunity_rollout does not match "
            "documentless_opportunities_enabled"
        )
    return enabled


def _oversized_opportunity_fields(opportunity: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    source_markdown = opportunity.get("source_markdown")
    if isinstance(source_markdown, str) and len(source_markdown) > OPPORTUNITY_MARKDOWN_MAX_CHARS:
        fields.append("source_markdown")

    documents = opportunity.get("documents")
    if isinstance(documents, list):
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            extracted_markdown = document.get("extracted_markdown")
            if (
                isinstance(extracted_markdown, str)
                and len(extracted_markdown) > OPPORTUNITY_MARKDOWN_MAX_CHARS
            ):
                fields.append(f"documents[{index}].extracted_markdown")
    return fields


def _preflight_documentless_opportunities(
    render_url: str,
    token: str,
) -> bool:
    url = f"{render_url}{RENDER_CAPABILITIES_PATH}"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=RENDER_SUBMIT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise CapabilityPreflightError(
                f"Repo A capabilities preflight returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise CapabilityPreflightError(
                f"Repo A capabilities preflight returned invalid JSON: {exc}"
            ) from exc
        return _read_documentless_capability(payload)
    except CapabilityPreflightError:
        raise
    except requests.RequestException as exc:
        raise CapabilityPreflightError(
            f"Repo A capabilities preflight failed: {type(exc).__name__}: {exc}"
        ) from exc


def submit_opportunities(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    """Submit strict opportunities while preflighting documentless support once."""
    render_url = os.environ["RENDER_APP_URL"].rstrip("/")
    token = os.environ["PIPELINE_SECRET"]
    submitted = 0
    errors: list[str] = []
    outcomes: list[dict[str, Any]] = []
    outcome_counts = {name: 0 for name in ("inserted", "updated", "reactivated", "duplicates", "invalid")}

    oversized_by_index = {
        index: _oversized_opportunity_fields(opportunity)
        for index, opportunity in enumerate(opportunities, start=1)
    }
    oversized_by_index = {
        index: fields for index, fields in oversized_by_index.items() if fields
    }
    eligible_opportunities = [
        opportunity
        for index, opportunity in enumerate(opportunities, start=1)
        if index not in oversized_by_index
    ]

    documentless_enabled: bool | None = None
    if any(not _has_renderable_pdf(opportunity) for opportunity in eligible_opportunities):
        try:
            documentless_enabled = _preflight_documentless_opportunities(render_url, token)
        except CapabilityPreflightError as exc:
            documentless_enabled = False
            preflight_error = str(exc)
        else:
            preflight_error = (
                "Repo A capabilities preflight reports documentless opportunity "
                "submissions are disabled"
                if not documentless_enabled
                else ""
            )
    else:
        preflight_error = ""

    for index, opportunity in enumerate(opportunities, start=1):
        oversized_fields = oversized_by_index.get(index)
        if oversized_fields:
            fields = ", ".join(oversized_fields)
            errors.append(
                f"opportunity {index}/{len(opportunities)}: {fields} exceeds "
                f"Repo A's {OPPORTUNITY_MARKDOWN_MAX_CHARS}-character limit"
            )
            continue
        if not _has_renderable_pdf(opportunity) and documentless_enabled is False:
            errors.append(
                f"opportunity {index}/{len(opportunities)}: {preflight_error}"
            )
            continue
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
        outcome = result or {"outcome": "accepted"}
        outcomes.append(outcome)
        vocabulary = outcome.get("outcome")
        if vocabulary in {"inserted", "updated", "reactivated", "invalid"}:
            outcome_counts[vocabulary] += 1
        elif vocabulary == "duplicate":
            outcome_counts["duplicates"] += 1
    return {
        "total": len(opportunities),
        "submitted": submitted,
        "failed": len(errors),
        "errors": errors,
        "outcomes": outcomes,
        "outcome_counts": outcome_counts,
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
