from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from configure_source_routes import (
    UnsafeRouteError,
    parse_source_list,
    resolve_routes,
)
from discover_all_candidates import SOURCE_MODULES


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "configure_source_routes.py"
WORKFLOWS = ROOT / ".github" / "workflows"


def test_parse_source_list_normalizes_case_whitespace_and_duplicates() -> None:
    assert parse_source_list(" FUNBIO, tnc,funbio ,, FINEP ") == [
        "funbio",
        "tnc",
        "finep",
    ]


def test_schedule_defaults_to_dedicated_legacy_routes() -> None:
    config = resolve_routes(
        event_name="schedule",
        requested_sources=None,
        approved_opportunity_sources=None,
        audit_only=False,
    )

    assert "funbio" not in config.sources.split(",")
    assert "tnc" not in config.sources.split(",")
    assert config.funbio_route == "legacy"
    assert config.tnc_route == "legacy"
    assert config.opportunity_sources == ""


def test_schedule_moves_only_approved_sources_to_structured_route() -> None:
    config = resolve_routes(
        event_name="schedule",
        requested_sources=None,
        approved_opportunity_sources=" finep, FUNBIO, tnc ",
        audit_only=False,
    )

    assert config.sources.split(",")[:2] == ["funbio", "tnc"]
    assert config.funbio_route == "structured"
    assert config.tnc_route == "structured"
    assert config.opportunity_sources == "finep,funbio,tnc"


def test_removing_source_immediately_restores_only_its_legacy_route() -> None:
    config = resolve_routes(
        event_name="schedule",
        requested_sources=None,
        approved_opportunity_sources="funbio",
        audit_only=False,
    )

    assert config.funbio_route == "structured"
    assert config.tnc_route == "legacy"
    assert "funbio" in config.sources.split(",")
    assert "tnc" not in config.sources.split(",")


def test_manual_audit_needs_no_approval_and_disables_opportunity_routes() -> None:
    config = resolve_routes(
        event_name="workflow_dispatch",
        requested_sources="funbio,tnc",
        approved_opportunity_sources="funbio,tnc",
        audit_only=True,
    )

    assert config.sources == "funbio,tnc"
    assert config.audit_only == "true"
    assert config.opportunity_sources == ""


def test_manual_submission_rejects_legacy_cutover_source() -> None:
    with pytest.raises(UnsafeRouteError, match="funbio"):
        resolve_routes(
            event_name="workflow_dispatch",
            requested_sources="funbio",
            approved_opportunity_sources="",
            audit_only=False,
        )


def test_manual_submission_allows_approved_structured_source() -> None:
    config = resolve_routes(
        event_name="workflow_dispatch",
        requested_sources="funbio",
        approved_opportunity_sources="funbio",
        audit_only=False,
    )

    assert config.sources == "funbio"
    assert config.opportunity_sources == "funbio"


def test_cli_writes_github_outputs_without_render_credentials(
    tmp_path: Path,
) -> None:
    output = tmp_path / "github-output.txt"
    env = {
        "EVENT_NAME": "workflow_dispatch",
        "REQUESTED_SOURCES": "funbio,tnc",
        "APPROVED_OPPORTUNITY_SOURCES": "",
        "AUDIT_ONLY": "true",
        "GITHUB_OUTPUT": str(output),
    }

    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "RENDER_APP_URL" not in env
    assert "PIPELINE_SECRET" not in env
    assert json.loads(proc.stdout)["audit_only"] == "true"
    assert "sources=funbio,tnc\n" in output.read_text(encoding="utf-8")


def _step_block(workflow: str, start: str, end: str) -> str:
    return workflow.split(start, 1)[1].split(end, 1)[0]


def test_unified_audit_step_has_no_render_secrets() -> None:
    workflow = (WORKFLOWS / "pipeline-all-discovery.yml").read_text(
        encoding="utf-8"
    )
    audit_step = _step_block(
        workflow,
        "- name: Run audit-only unified discovery",
        "- name: Run submission-enabled unified discovery",
    )
    submit_step = _step_block(
        workflow,
        "- name: Run submission-enabled unified discovery",
        "- name: Verify source fidelity artifacts",
    )

    assert "secrets.RENDER_APP_URL" not in audit_step
    assert "secrets.PIPELINE_SECRET" not in audit_step
    assert "secrets.RENDER_APP_URL" in submit_step
    assert "secrets.PIPELINE_SECRET" in submit_step


@pytest.mark.parametrize(
    ("workflow_name", "source", "route_output"),
    [
        ("pipeline-funbio-discovery.yml", "funbio", "funbio_route"),
        ("pipeline-tnc-discovery.yml", "tnc", "tnc_route"),
    ],
)
def test_dedicated_workflow_submits_only_on_legacy_route(
    workflow_name: str,
    source: str,
    route_output: str,
) -> None:
    workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")

    assert "python scripts/configure_source_routes.py" in workflow
    assert (
        f"steps.routes.outputs.{route_output} == 'legacy'" in workflow
    )
    assert f"discover_{source}_candidates.py" in workflow
    assert SOURCE_MODULES[source] == f"discover_{source}_candidates"


def test_only_expected_workflows_route_funbio_or_tnc() -> None:
    route_files = {
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if "FUNBIO" in path.read_text(encoding="utf-8")
        or "TNC" in path.read_text(encoding="utf-8")
    }

    assert route_files == {
        "pipeline-all-discovery.yml",
        "pipeline-funbio-discovery.yml",
        "pipeline-tnc-discovery.yml",
    }
