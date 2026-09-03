from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests

if __package__:
    _SCRIPTS_DIR = Path(__file__).resolve().parent
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    from . import pipeline_core
else:
    import pipeline_core


DEFAULT_PNCP_BACKFILL_CLAIM_LIMIT = 20
DEFAULT_PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN = 20
MAX_PNCP_BACKFILL_LIMIT = 100
RENDER_CLAIM_TIMEOUT = int(os.getenv("RENDER_CLAIM_TIMEOUT", "60"))


def _validate_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer between 1 and 100")
    if not 1 <= value <= MAX_PNCP_BACKFILL_LIMIT:
        raise ValueError(f"{name} must be between 1 and {MAX_PNCP_BACKFILL_LIMIT}")
    return value


def resolve_backfill_limits(claim_limit: int, process_limit: int) -> tuple[int, int]:
    claim_limit = _validate_limit("claim_limit", claim_limit)
    process_limit = _validate_limit("process_limit", process_limit)
    if claim_limit > process_limit:
        raise ValueError("claim_limit must be less than or equal to process_limit")
    return claim_limit, process_limit


def _env_limit(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer between 1 and 100") from exc


def fetch_claimed_candidates(
    *,
    render_url: str,
    token: str,
    limit: int,
) -> list[dict[str, Any]]:
    _validate_limit("claim_limit", limit)
    response = requests.post(
        f"{render_url.rstrip('/')}/api/pipeline/candidates/backfill/claim",
        headers={"Authorization": f"Bearer {token}"},
        params={"source": "pncp", "limit": limit, "active_only": "true"},
        timeout=RENDER_CLAIM_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("Render claim response field 'candidates' must be a list")
    return [
        {
            "url": str(item["url"]),
            "kind": str(item.get("kind") or "pdf"),
            "metadata": item.get("metadata") or {},
        }
        for item in candidates
        if isinstance(item, dict) and item.get("url")
    ]


def run_backfill(
    *,
    render_url: str,
    token: str,
    claim_limit: int,
    process_limit: int,
) -> int:
    claim_limit, process_limit = resolve_backfill_limits(claim_limit, process_limit)
    candidates = fetch_claimed_candidates(
        render_url=render_url,
        token=token,
        limit=claim_limit,
    )
    stats: dict[str, int] = {
        "claimed": len(candidates),
        "processed": 0,
        "ocr_successes": 0,
        "ocr_failures": 0,
        "pdfs_downloaded": 0,
    }
    print(f"PNCP backfill claim stats: {stats}")
    if not candidates:
        print("No active PNCP pending candidates claimed")
        return 0

    _ocr_config, extractor = pipeline_core.make_default_ocr_extractor()
    processed: list[dict[str, Any]] = []

    for candidate in candidates:
        if len(processed) >= process_limit:
            stats["processing_cap_reached"] = 1
            break
        if pipeline_core.pdf_download_limit_reached(stats):
            stats["pdf_download_cap_reached"] = 1
            break
        result = pipeline_core.process_candidate(
            candidate,
            extractor=extractor,
            max_bytes=pipeline_core.SCRAPE_MAX_PDF_BYTES,
        )
        processed.append(result)
        stats["processed"] = len(processed)
        if result.get("worker_result"):
            pipeline_core.record_pdf_download(stats)
            stats["ocr_successes"] += 1
        else:
            stats["ocr_failures"] += 1

    print(f"PNCP backfill processing stats: {stats}")
    submit_result = pipeline_core.submit_candidates(processed, source="pncp")
    print(f"Render candidate submission: {submit_result}")

    if stats["claimed"] > 0 and submit_result.get("submitted", 0) == 0:
        print("error: claimed PNCP candidates but submitted none", file=sys.stderr)
        return 1
    if submit_result.get("failed_batches", 0) > 0:
        return 1
    return 0


def main() -> int:
    render_url = os.environ.get("RENDER_APP_URL")
    token = os.environ.get("PIPELINE_SECRET")
    if not render_url:
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not token:
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2
    try:
        claim_limit, process_limit = resolve_backfill_limits(
            _env_limit("PNCP_BACKFILL_CLAIM_LIMIT", DEFAULT_PNCP_BACKFILL_CLAIM_LIMIT),
            _env_limit(
                "PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN",
                DEFAULT_PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN,
            ),
        )
    except ValueError as exc:
        print(f"error: invalid PNCP backfill limits: {exc}", file=sys.stderr)
        return 2
    return run_backfill(
        render_url=render_url,
        token=token,
        claim_limit=claim_limit,
        process_limit=process_limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
