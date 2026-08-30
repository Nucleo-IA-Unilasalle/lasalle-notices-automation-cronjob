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
- The source-transparency contract target is Repo A commit `a0f4175731f0fa4b3e0007b4d7f0348203847770`. This is a tested code target, not a claim that it is deployed. Verify the live OpenAPI contract and seeded catalog before enabling telemetry; if the target moves, rerun the compatibility checks and update this reference.
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
- `requirements-ocr-worker.txt` pins runtime dependencies, including `lxml` for BeautifulSoup's XML/RDF feed parsing. CI installs the same dependency file as production discovery workflows.

## Verification

- Full worker suite: `py -3.13 -m pytest -q`
- Workflow and OCR semantics: `py -3.13 -m pytest tests/test_workflow_static.py -q`
- Source-fidelity CLI coverage: `py -3.13 -m pytest tests/test_source_fidelity.py -q`
- YAML parse smoke check: `py -3.13 -c "import pathlib, yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]"`

## Child DOX Index

This repository currently has no child `AGENTS.md` files. Keep this root
contract current when adding a durable documentation, workflow, or test
boundary.

## Telemetry

- `scripts/source_run_reporting.py` implements the `contract_version=1` source
  run protocol: authenticated `POST /api/pipeline/source-runs` followed by a
  `PATCH` of the returned run. It reports inventory, scope, policy rejection,
  downloads/OCR, submission outcomes, errors, fidelity blockers, and the v1
  stats allowlist shared with the backend.
- Audit-only orchestration runs the offline fidelity verifier against its
  inventory/discovery artifacts before terminal telemetry. Blocking findings
  or an incomplete verifier fail closed; parser counters alone are not proof
  that an audit passed. Structured submission failures use the submitter's
  `failed` count; candidate submissions use `failed_batches`.
- `SOURCE_RUN_REPORTING_ENABLED` defaults to `false` and is the rollback lever;
  disabled telemetry does not change ingestion. `RENDER_APP_URL` and
  `PIPELINE_SECRET` configure callbacks.
- The canonical all-source and PNCP discovery workflows read the telemetry
  flag from the GitHub repository variable of the same name. Enable it only
  after Repo A's source-run contract and source catalog are deployed and
  verified; older standalone discoverers do not report source runs.

## Worker CI

- `.github/workflows/ci.yml` is the Worker CI workflow. The repository has 26
  workflows and runs the offline Python 3.13 test suite with read-only
  permissions, pinned actions, bounded concurrency, and a 20-minute timeout.
