# Repo B Contract

## Purpose

Repo B is the trusted GitHub Actions worker for discovery, bounded download,
text/OCR extraction, source-fidelity auditing, and submission to the Repo A
FastAPI service.

## Ownership

- Repo A is `lasalle-notices-automation`, the FastAPI backend and contract source of truth.
- Repo B is `lasalle-notices-automation-cronjob`, the worker and workflow repository.
- Do not edit Repo A from this repository. Coordinate any API or DTO change in Repo A first.
- Repo A `docs/README.md` owns the cross-repository product and architecture
  handbook; this repository's `docs/OPERATIONS.md` owns exact worker schedules,
  limits, rollout checks, and rollback procedures.

## Local Contracts

- Repo A has no URL-level API version prefix. The deployed `APP_VERSION` identifies the backend deployment; worker compatibility is defined by Repo A's deployed OpenAPI artifact and worker-facing Pydantic models, not by a Repo B version.
- The current coordinated Repo A baseline is `master` commit `f8762de3d45d8301a0836074f0af74eedd3a97ea`. If the deployed contract moves, verify the worker against the new Repo A commit and update this reference.
- Candidate submissions use authenticated `POST /api/pipeline/candidates` with `Authorization: Bearer $PIPELINE_SECRET` and the `source` plus `candidates` payload defined by Repo A.
- Structured submissions use authenticated `POST /api/pipeline/opportunities`. The worker must preserve source identity, timezone-aware timestamps, normalized source Markdown, SHA-256 content hashes, and validated document metadata. Documentless submissions remain disabled on Repo A by default until the deployment flag is coordinated.
- OCR claim, renew, complete, and fail requests use the same Bearer pipeline secret plus the claim token required by Repo A. Do not invent alternate headers or endpoint paths.
- `pipeline-sync.yml` owns the dedicated non-canceling `pipeline-sync` concurrency group and must poll the accepted `run_id` to a terminal pipeline status before reporting success.
- Repo A's OpenAPI artifact and contract tests are authoritative. The local worker tests mirror payload shapes and do not replace Repo A validation.

## Work Guidance

- Keep workflows explicit and fail-loud: use `permissions: contents: read`, commit-SHA-pinned actions, a non-canceling concurrency group, and a job timeout for every workflow job.
- Keep discovery, PDF-byte, per-run PDF, OCR-page, attachment, and submission-payload caps explicit in workflow environments and documentation.
- Scheduled workflows must have one canonical path per source. Manual-only workflows are rollback, audit, backfill, or per-source fallback paths and must remain documented as such.
- Tests must be offline and deterministic. Do not call production endpoints from tests; use the workflow-pinned Python 3.13 interpreter.

## Verification

- Full worker suite: `py -3.13 -m pytest -q`
- Workflow and OCR semantics: `py -3.13 -m pytest tests/test_workflow_static.py -q`
- Source-fidelity CLI coverage: `py -3.13 -m pytest tests/test_source_fidelity.py -q`
- YAML parse smoke check: `py -3.13 -c "import pathlib, yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]"`

## Child DOX Index

This repository currently has no child `AGENTS.md` files. Keep this root
contract current when adding a durable documentation, workflow, or test
boundary.
