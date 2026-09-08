"""Persist discovery before spending the remaining job budget on OCR.

Cursor coverage (versioned, scope-bound; ``cursor_version=1``):

- PNCP scope ``pncp-updates-v1``: search pagination position (pages
  attempted/completed per endpoint, truncation flag), record position
  (enumerated vs registered), and attachment position (document lookups
  completed, documents selected). The update watermark advances only after
  complete enumeration and registration; partial scans leave it unchanged.
- Finep scope ``finep-pages-v1``: paginated API position (pages completed,
  last page, page size) plus enumerated/registered counts.
- Every other adapter uses no cursor (no checkpoint claim) or the generic
  envelope on the ``default`` scope, which is a monotonic watermark only
  and carries NO pagination guarantee.

Remaining gaps (honest): only PNCP and Finep report adapter-aware
positions. All other adapters re-enumerate from the start each cycle and
rely on stable-identity dedup; their cursors, where present, are
watermarks, not proof that every record was enumerated. PNCP streams
seven query windows (proposta plus publicacao/atualizacao per modality);
partial scans replay from the last complete watermark, not persisted
per-stream offsets. Finep records only complete page coverage and rescans
from page 1 because new calls can shift publication order. The server
additionally bounds ``records_registered`` against the spool row count, a
coarse prefix guard, not per-identity proof.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import time

import pipeline_core
from source_control import SourceControl, lease_expired


CURSOR_VERSION = 1
PNCP_SCOPE = "pncp-updates-v1"
FINEP_SCOPE = "finep-pages-v1"


def scope_for_adapter(source):
    """Collection scope a source's register/checkpoint calls must use.

    Mirrors SOURCE_SCOPES in scripts/source_control.py: the supervisor claims
    with the same scope so the server pins claim_scope correctly. Keep both
    mappings in sync (tested by tests/test_managed_source.py).
    """
    return {"pncp": PNCP_SCOPE, "finep": FINEP_SCOPE}.get(source, "default")


def enabled():
    return os.environ.get("SOURCE_WORK_ENABLED") == "true"


def build_pncp_cursor(*, last_successful_update, records_enumerated=0,
                      records_registered=0, document_lookups_completed=0,
                      documents_selected=0, search_pages_completed=0,
                      search_truncated=False, complete=False):
    """Versioned PNCP pagination/record/attachment position."""
    return {
        "cursor_version": CURSOR_VERSION,
        "adapter": "pncp",
        "scope": PNCP_SCOPE,
        "last_successful_update": last_successful_update,
        "records_enumerated": int(records_enumerated),
        "records_registered": int(records_registered),
        "document_lookups_completed": int(document_lookups_completed),
        "documents_selected": int(documents_selected),
        "search_pages_completed": int(search_pages_completed),
        "search_truncated": bool(search_truncated),
        "complete": bool(complete),
    }


def build_finep_cursor(*, pages_completed, last_page=None, page_size=0,
                       records_enumerated=0, records_registered=0,
                       cycle_started_at=None, complete=False):
    """Versioned Finep pagination position for one collection cycle."""
    return {
        "cursor_version": CURSOR_VERSION,
        "adapter": "finep",
        "scope": FINEP_SCOPE,
        "pages_completed": sorted(set(int(p) for p in pages_completed)),
        "last_page": None if last_page is None else int(last_page),
        "page_size": int(page_size),
        "records_enumerated": int(records_enumerated),
        "records_registered": int(records_registered),
        "cycle_started_at": cycle_started_at,
        "complete": bool(complete),
    }


def build_generic_cursor(source, scope="default", *, records_registered=0,
                         complete=False, cycle_started_at=None):
    """Monotonic watermark envelope for adapters without pagination tracking."""
    return {
        "cursor_version": CURSOR_VERSION,
        "adapter": source,
        "scope": scope,
        "records_registered": int(records_registered),
        "cycle_started_at": cycle_started_at,
        "complete": bool(complete),
    }


def parse_collection_cursor(cursor):
    """Return (is_versioned, adapter, scope) without raising on legacy rows.

    Legacy watermark dicts (for example a bare ``last_successful_update``)
    report ``(False, None, None)``: readable, resumable only as a time
    watermark, never as pagination position.
    """
    if not isinstance(cursor, dict):
        return (False, None, None)
    if cursor.get("cursor_version") != CURSOR_VERSION:
        return (False, None, None)
    return (True, cursor.get("adapter"), cursor.get("scope"))


def load_cursor(source, scope):
    """Best-effort read of the stored cursor for a scope; {} when absent."""
    try:
        return SourceControl(source).work("checkpoint", scope=scope).get("cursor") or {}
    except Exception:
        return {}


def _advance_cursor(client, contract, scope, cursor):
    client.work("register", contract=contract, items=[], scope=scope, cursor=cursor)


# Preflight only: the supervisor remains the hard stop. Below this floor the
# drain refuses to take new work so a doomed download/OCR cycle cannot start.
DRAIN_MIN_SECONDS = 420


def remaining_drain_seconds():
    """Seconds left in the job budget, or None when no deadline is published."""
    raw = os.environ.get("SOURCE_DEADLINE_EPOCH")
    if not raw:
        return None
    try:
        return float(raw) - time.time()
    except (TypeError, ValueError):
        return None


def _error_code_from_error(error):
    prefix = str(error).split(":", 1)[0].strip().lower()
    if prefix in ("download", "ocr"):
        return prefix + "_failed"
    return "processing_failed"


def _submission_accepted(submit_result, submitted_count):
    counts = submit_result.get("outcome_counts") or {}
    return (
        submit_result.get("submitted", 0) == submitted_count
        and not counts.get("invalid")
        and not submit_result.get("failed_batches")
        and not submit_result.get("failed")
    )


def _record_submission(reporter, result):
    counts = result.get("outcome_counts") or {}
    reporter.record_submission_outcomes(**{
        key: counts.get(key, 0)
        for key in ("inserted", "updated", "reactivated", "duplicates")
    })


def _drain_candidate(client, source, item, extractor_pair, stats, reporter):
    _config, extractor = extractor_pair
    payload = item["payload"]
    try:
        result = pipeline_core.process_candidate(
            payload, extractor=extractor, max_bytes=pipeline_core.SCRAPE_MAX_PDF_BYTES)
    except Exception as exc:
        print(f"warning: candidate processing failed for {source}: {exc}", file=sys.stderr)
        return ("failed", "processing_failed")
    error = result.get("error")
    if error:
        code = _error_code_from_error(error)
        if code in {"download_failed", "ocr_failed"}:
            key = "ocr_failures" if code == "ocr_failed" else "download_failures"
            reporter.metrics.stats[key] = reporter.metrics.stats.get(key, 0) + 1
            reporter.record_downloads(int(code == "ocr_failed"), 0)
        return ("failed", code)
    if result.get("worker_result"):
        # Only a successful download+OCR consumes the shared per-run PDF cap,
        # mirroring the legacy loop's record_pdf_download placement.
        pipeline_core.record_pdf_download(stats)
        reporter.record_downloads(1, 1)
    try:
        submit_result = pipeline_core.submit_candidates([result], source=source)
    except Exception as exc:
        # The HTTP call may have reached Repo A before failing: the ACK is
        # ambiguous, so the item is failed server-side and retried after
        # backoff; the idempotent submission dedups on reprocessing.
        print(f"warning: candidate submission failed for {source}: {exc}", file=sys.stderr)
        return ("failed", "submission_failed")
    _record_submission(reporter, submit_result)
    if _submission_accepted(submit_result, 1):
        return ("accepted", None)
    return ("failed", "submission_failed")


def _opportunity_deferred(processed, stats):
    if stats.get("pdf_download_cap_reached"):
        return True
    return any(
        document.get("validation_outcome") == "download_cap_reached"
        for document in processed.get("documents", [])
    )


def _opportunity_failed(processed):
    for document in processed.get("documents", []):
        outcome = str(document.get("validation_outcome") or "")
        if outcome.endswith("_validation_failed"):
            return True
    return False


def _drain_opportunity(source, item, extractor_pair, stats, reporter):
    _config, extractor = extractor_pair
    keys = ("documents_downloaded", "ocr_succeeded", "download_failures", "ocr_failures")
    before = {key: stats.get(key, 0) for key in keys}
    try:
        processed = pipeline_core.process_opportunity(
            item["payload"], extractor=extractor, stats=stats)
    except Exception as exc:
        print(f"warning: opportunity processing failed for {source}: {exc}", file=sys.stderr)
        return ("failed", "processing_failed")
    finally:
        delta = {key: stats.get(key, 0) - before[key] for key in keys}
        reporter.record_downloads(delta["documents_downloaded"], delta["ocr_succeeded"])
        for key in ("download_failures", "ocr_failures"):
            reporter.metrics.stats[key] = reporter.metrics.stats.get(key, 0) + delta[key]
    if _opportunity_deferred(processed, stats):
        # Cap-deferred snapshots stay pending: submitting a partial document
        # set could overwrite already accepted complete documents in Repo A.
        return ("deferred", None)
    if _opportunity_failed(processed):
        # A partial attachment snapshot is never submitted. Refined code
        # (was the coarse "download_failed"): the trigger is any
        # *_validation_failed attachment outcome — download, OCR, size-cap,
        # or archive-inspection failure — not just a download error, and it
        # must not be conflated with candidate-path download failures.
        return ("failed", "attachment_validation_failed")
    try:
        submit_result = pipeline_core.submit_opportunities([processed])
    except Exception as exc:
        print(f"warning: opportunity submission failed for {source}: {exc}", file=sys.stderr)
        return ("failed", "submission_failed")
    _record_submission(reporter, submit_result)
    if _submission_accepted(submit_result, 1):
        return ("accepted", None)
    return ("failed", "submission_failed")


def drain(source, reporter, stats):
    """Drain pending spooled work for one source, one item at a time.

    Returns the number of items finished as ``failed``. Deferred and accepted
    items are not failures. Refuses to start (and re-checks before each take)
    when the remaining job budget is below ``DRAIN_MIN_SECONDS``; OCR state is
    initialized lazily, only when a first item is actually processed.

    The run-wide PDF cap (``pipeline_core.pdf_download_limit_reached`` /
    ``record_pdf_download``) is enforced exactly like the legacy
    non-durable loop: checked before taking work and again after taking a
    candidate item, recorded only for successful extractions. When the cap
    is reached the taken candidate is finished as ``deferred`` (it stays
    pending, no error code), ``cap_reached`` is set in the reporter metrics,
    and the drain stops — mirroring the opportunity cap-deferred semantics.
    """
    metrics_stats = reporter.metrics.stats
    remaining = remaining_drain_seconds()
    if remaining is not None and remaining < DRAIN_MIN_SECONDS:
        metrics_stats["cap_reached"] = True
        return 0
    if pipeline_core.pdf_download_limit_reached(stats):
        # The shared per-run PDF budget is already spent: no take, no OCR
        # initialization. Remaining items keep their pending status.
        metrics_stats["cap_reached"] = True
        return 0
    failures = 0
    extractor_pair = None
    client = SourceControl(source)
    while True:
        remaining = remaining_drain_seconds()
        if remaining is not None and remaining < DRAIN_MIN_SECONDS:
            metrics_stats["cap_reached"] = True
            break
        batch = client.work("take", limit=1)
        items = batch.get("items") or []
        if not items:
            break
        item = items[0]
        contract = item.get("contract")
        if contract == "opportunity":
            if extractor_pair is None:
                extractor_pair = pipeline_core.make_default_ocr_extractor()
            outcome, error_code = _drain_opportunity(source, item, extractor_pair, stats, reporter)
        else:
            if pipeline_core.pdf_download_limit_reached(stats):
                # The shared PDF budget was consumed by a previous item: the
                # candidate stays pending (no error code) and the drain stops,
                # mirroring the opportunity cap-deferred semantics.
                outcome, error_code = "deferred", None
            else:
                if extractor_pair is None:
                    extractor_pair = pipeline_core.make_default_ocr_extractor()
                outcome, error_code = _drain_candidate(client, source, item, extractor_pair, stats, reporter)
        if outcome == "failed":
            failures += 1
            reporter.record_error(error_code if error_code in {
                "download_failed", "ocr_failed", "submission_failed"
            } else "scraping_failed")
            if error_code == "submission_failed":
                metrics_stats["submission_failures"] = metrics_stats.get("submission_failures", 0) + 1
        if outcome == "deferred":
            # A cap was hit while processing (opportunity) or before processing
            # (candidate): stop taking work so remaining items keep their
            # pending status for a future run.
            metrics_stats["cap_reached"] = True
            client.work("finish", item_id=item["id"], revision=item["revision"],
                        outcome=outcome, error_code=error_code)
            break
        client.work("finish", item_id=item["id"], revision=item["revision"],
                    outcome=outcome, error_code=error_code)
    return failures


def register_collection(source, contract, records, stats, scope="default", cursor=None,
                        cursor_builder=None):
    client = SourceControl(source)
    # One bounded descriptor per request: a lost response can be replayed by
    # stable identity. The cursor never advances beyond the last acknowledged
    # registration: any descriptor failure stops the run before any cursor
    # write, and every cursor write below covers only the acked prefix.
    acked = 0
    try:
        for record in records:
            client.work("register", contract=contract, items=[record], scope=scope)
            acked += 1
            if cursor_builder is not None:
                prefix = cursor_builder(acked, False)
                if prefix is not None:
                    _advance_cursor(client, contract, scope, prefix)
    except Exception:
        return False
    partial = any(stats.get(key) for key in (
        "section_parse_failed", "inventory_parse_failed", "detail_parse_failures", "detail_parse_failed",
        "search_failures", "document_failures", "search_result_cap_reached", "detail_cap_reached", "candidate_cap_reached",
        "partial_inventory", "page_cap_reached",
    ))
    if partial:
        return False
    final = cursor_builder(acked, True) if cursor_builder is not None else cursor
    if final is None and scope == FINEP_SCOPE:
        pages = stats.get("finep_pages_completed") or []
        last_page = stats.get("finep_last_page")
        if not last_page or len(pages) != last_page or pages != list(range(1, len(pages) + 1)):
            return False
        final = build_finep_cursor(
            pages_completed=pages, last_page=last_page,
            page_size=stats.get("finep_page_size", 0),
            records_enumerated=stats.get("records", len(records)),
            records_registered=acked, complete=True,
            cycle_started_at=datetime.now(timezone.utc).isoformat(),
        )
    if final is None:
        # No adapter-aware position to claim: record an honest monotonic
        # watermark (cycle timestamp plus this run's registered prefix size),
        # never a pagination guarantee.
        final = build_generic_cursor(
            source, scope, records_registered=acked, complete=True,
            cycle_started_at=datetime.now(timezone.utc).isoformat())
    try:
        _advance_cursor(client, contract, scope, final)
    except Exception:
        # Descriptors are safely spooled; the cursor simply lags and the
        # next cycle re-enumerates (dedup by stable identity). Never report
        # a complete collection whose cursor is unconfirmed.
        return False
    marker = os.environ.get("SOURCE_COLLECTION_COMPLETE_FILE")
    if marker:
        Path(marker).touch()
    return True


def clear_collection_complete_marker():
    """Best-effort removal of the collection-success marker.

    A drain aborted by a lost lease must not leave the marker behind: the
    supervisor reads it to release the claim with a success outcome, and an
    aborted run is not a success. The server keeps every unfinished item
    pending, so the next cycle re-registers (dedup by stable identity) and
    drains again.
    """
    marker = os.environ.get("SOURCE_COLLECTION_COMPLETE_FILE")
    if not marker:
        return
    try:
        Path(marker).unlink(missing_ok=True)
    except OSError:
        pass


def abort_drain_on_lease_conflict(exc):
    """Handle a mid-drain :class:`AdmissionConflict` at the drain call site.

    A lease-fencing conflict (schedule claim expired/lost, or the
    ``X-Source-Claim`` submission fencing rejected the token) is reported as
    one stderr line with no traceback, and the collection-success marker is
    removed so the supervisor cannot release the claim as a success. Returns
    ``True`` so the caller exits with code 1. Any other conflict reason
    returns ``False`` and keeps its existing propagation behavior.
    """
    if not lease_expired(exc):
        return False
    print(
        f"drain aborted: source lease expired mid-drain ({exc.reason}); "
        "server keeps work pending",
        file=sys.stderr,
    )
    clear_collection_complete_marker()
    return True
