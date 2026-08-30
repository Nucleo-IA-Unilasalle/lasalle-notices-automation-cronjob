"""Static contract checks for GitHub Actions workflows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

SCHEDULES = {
    "pipeline-ai.yml": "16 * * * *",
    "pipeline-all-discovery.yml": "8 * * * *",
    "pipeline-backfill.yml": "23 11 * * 6",
    "pipeline-fao-discovery.yml": "12 * * * *",
    "pipeline-fundacao-grupo-boticario-discovery.yml": "17 * * * *",
    "pipeline-govbr-mma-discovery.yml": "50 * * * *",
    "pipeline-kfw-discovery.yml": "28 * * * *",
    "pipeline-msgov-discovery.yml": "38 * * * *",
    "pipeline-pncp-discovery.yml": "05 * * * *",
    "pipeline-sync.yml": "37 * * * *",
    "pipeline-unep-discovery.yml": "45 * * * *",
    "pipeline-worldbank-discovery.yml": "55 * * * *",
}

MANUAL_SOURCE_FALLBACKS = {
    "pipeline-bndes-discovery.yml",
    "pipeline-brde-discovery.yml",
    "pipeline-fapergs-discovery.yml",
    "pipeline-funbio-discovery.yml",
    "pipeline-iis-rio-discovery.yml",
    "pipeline-sema-rs-discovery.yml",
    "pipeline-tnc-discovery.yml",
    "pipeline-wwf-discovery.yml",
}

PDF_WORKFLOWS = {
    "pipeline-all-discovery.yml",
    "pipeline-bndes-discovery.yml",
    "pipeline-brde-discovery.yml",
    "pipeline-fao-discovery.yml",
    "pipeline-fapergs-discovery.yml",
    "pipeline-funbio-discovery.yml",
    "pipeline-fundacao-grupo-boticario-discovery.yml",
    "pipeline-govbr-mma-discovery.yml",
    "pipeline-iis-rio-discovery.yml",
    "pipeline-kfw-discovery.yml",
    "pipeline-msgov-discovery.yml",
    "pipeline-pncp-backfill.yml",
    "pipeline-pncp-discovery.yml",
    "pipeline-sema-rs-discovery.yml",
    "pipeline-tnc-discovery.yml",
    "pipeline-unep-discovery.yml",
    "pipeline-worldbank-discovery.yml",
    "pipeline-wwf-discovery.yml",
}


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), path
    return document


def _trigger(document: dict[str, Any]) -> dict[str, Any]:
    # PyYAML's YAML 1.1 resolver reads the GitHub Actions key `on` as True.
    value = document.get("on", document.get(True, {}))
    return value if isinstance(value, dict) else {}


def _walk(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _env_values(document: dict[str, Any], name: str) -> list[Any]:
    values = []
    for key, value in _walk(document):
        if key == "env" and isinstance(value, dict) and name in value:
            values.append(value[name])
    return values


def _uses_values(document: dict[str, Any]) -> list[str]:
    return [value for key, value in _walk(document) if key == "uses" and isinstance(value, str)]


def test_all_workflows_parse_with_read_only_permissions_and_concurrency() -> None:
    assert len(WORKFLOWS) == 26
    for path in WORKFLOWS:
        document = _load(path)
        assert document["permissions"] == {"contents": "read"}, path.name
        concurrency = document["concurrency"]
        assert isinstance(concurrency, dict), path.name
        assert isinstance(concurrency.get("group"), str) and concurrency["group"], path.name
        assert concurrency["cancel-in-progress"] is False, path.name
        jobs = document.get("jobs")
        assert isinstance(jobs, dict) and jobs, path.name
        for job_name, job in jobs.items():
            assert isinstance(job, dict), f"{path.name}:{job_name}"
            assert isinstance(job.get("timeout-minutes"), int), f"{path.name}:{job_name}"


def test_all_action_references_are_commit_sha_pinned() -> None:
    for path in WORKFLOWS:
        for reference in _uses_values(_load(path)):
            action, separator, revision = reference.partition("@")
            assert separator and action.startswith("actions/"), f"{path.name}: {reference}"
            assert SHA_RE.fullmatch(revision), f"{path.name}: {reference}"


def test_canonical_schedule_has_no_duplicate_source_fallbacks() -> None:
    for path in WORKFLOWS:
        schedules = _trigger(_load(path)).get("schedule", [])
        crons = [entry.get("cron") for entry in schedules if isinstance(entry, dict)]
        if path.name in SCHEDULES:
            assert crons == [SCHEDULES[path.name]], path.name
        elif path.name in MANUAL_SOURCE_FALLBACKS:
            assert crons == [], path.name


def test_instrumented_entrypoints_use_default_off_repository_telemetry_flag() -> None:
    instrumented = {
        "pipeline-all-discovery.yml": "python scripts/discover_all_candidates.py",
        "pipeline-pncp-discovery.yml": "python scripts/discover_pncp_candidates.py",
    }
    expected = "${{ vars.SOURCE_RUN_REPORTING_ENABLED || 'false' }}"
    for name, command in instrumented.items():
        document = _load(WORKFLOW_DIR / name)
        steps = [step for job in document["jobs"].values() for step in job["steps"]]
        matching = [step for step in steps if step.get("run") == command]
        assert len(matching) == 1, name
        assert matching[0]["env"]["SOURCE_RUN_REPORTING_ENABLED"] == expected, name
        assert _env_values(document, "SOURCE_RUN_REPORTING_ENABLED") == [expected], name


def test_pdf_workflows_declare_the_per_run_safety_cap() -> None:
    for name in PDF_WORKFLOWS:
        values = _env_values(_load(WORKFLOW_DIR / name), "SCRAPE_MAX_PDFS_PER_RUN")
        assert values == ["5"], name


def test_ocr_timeout_and_entrypoint_semantics_are_explicit() -> None:
    for path in WORKFLOWS:
        if path.name == "pipeline-ocr.yml" or path.name in PDF_WORKFLOWS:
            values = _env_values(_load(path), "KREUZBERG_EXTRACTION_TIMEOUT_SECONDS")
            assert values and set(values) == {"300"}, path.name

    document = _load(WORKFLOW_DIR / "pipeline-ocr.yml")
    assert "workflow_dispatch" in _trigger(document)
    assert "schedule" not in _trigger(document)
    serialized = document.__repr__()
    assert "python scripts/ocr_worker/run_ocr_worker.py --limit 5" in serialized
    assert _env_values(document, "PADDLE_PDX_CACHE_HOME") == ["/home/runner/.paddlex"]
    assert ".paddlex" in serialized


def test_backfill_limits_and_shared_concurrency_are_explicit() -> None:
    backfill = _load(WORKFLOW_DIR / "pipeline-pncp-backfill.yml")
    inputs = _trigger(backfill)["workflow_dispatch"]["inputs"]
    for name in ("claim_limit", "process_limit"):
        assert inputs[name]["type"] == "number"
        assert "1-100" in inputs[name]["description"]
    assert backfill["concurrency"]["group"] == "pipeline-trigger"
    assert _load(WORKFLOW_DIR / "pipeline-ocr.yml")["concurrency"]["group"] == "pipeline-trigger"


def test_sync_uses_dedicated_concurrency_and_waits_for_terminal_run_status() -> None:
    path = WORKFLOW_DIR / "pipeline-sync.yml"
    document = _load(path)
    workflow = path.read_text(encoding="utf-8")

    assert document["concurrency"]["group"] == "pipeline-sync"
    assert "/api/pipeline/runs?job_name=${PIPELINE_STEP}" in workflow
    assert "run_id=$(jq -r '.run_id // empty' response.json)" in workflow
    assert "success|skipped" in workflow
    assert "failed)" in workflow


def test_ocr_worker_requirements_are_pinned() -> None:
    requirements = (
        WORKFLOW_DIR.parents[1] / "requirements-ocr-worker.txt"
    ).read_text(encoding="utf-8")
    requirement_lines = [
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert requirement_lines
    assert all("==" in line for line in requirement_lines)


def test_timeout_and_thread_limitation_are_documented() -> None:
    readme = (WORKFLOW_DIR.parents[1] / "README.md").read_text(encoding="utf-8")
    operations = (WORKFLOW_DIR.parents[1] / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    for document in (readme, operations):
        assert "KREUZBERG_EXTRACTION_TIMEOUT_SECONDS" in document
        assert "300" in document
        assert "to_thread" in document
