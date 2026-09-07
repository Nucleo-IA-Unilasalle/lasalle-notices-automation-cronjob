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
- `config/source_schedule.json` is the declarative execution registry: one owner group per source, validated fail-closed by `scripts/build_source_matrix.py` and the registry coverage tests. Group ownership changes go through the registry, never by editing workflow crons directly. Registry entries carry `schedule_owner`, `interval_minutes`, `filter_policy`, and `detail/page/attachment` limits; `tnc`/`funbio` use the structured `opportunity` contract with `audit` rollout until two clean audits pass.
- `scripts/source_control.py` is the bounded authenticated claim/renew/release/work client for the A schedule/spool (advisory 910012, max 3 concurrent claims; 300 s leases); `scripts/run_managed_source.py` supervises one source with a central claim, 60s renewals, a 20-minute job budget minus setup and 120s cleanup reserve, and process-tree kill on deadline/renewal uncertainty. `scripts/durable_source_work.py` registers descriptors before OCR and drains one item at a time with a 420s preflight and lazy OCR init (256 KiB/item, 1000 items/source, 32 MiB aggregate, 16 KiB cursor; attempts/backoff/quarantine; public backlog DTO is nullable with unknown distinct from empty). The drain enforces the run-wide PDF cap for candidate items like the legacy loop (checked before take/processing, recorded only on successful extraction; a capped candidate is finished `deferred`, stays pending, and sets cap-reached telemetry). Failure finishes use Repo A's spool `error_code` vocabulary: candidate `download_failed`/`ocr_failed`, partial attachment snapshots `attachment_validation_failed` (any `*_validation_failed` attachment outcome, never conflated with candidate download failures), unexpected exceptions `processing_failed`, submission/ACK failures `submission_failed`; codes are additive over the legacy four, so deploy Repo A before the worker (a new-code finish against an older server 422s and aborts that drain run; the server keeps the item pending). A lease-fencing 409 mid-drain (`claim_expired`/`claim_missing`/`claim_invalid` in `LEASE_EXPIRED_REASONS`) is reported by every drain call site as one stderr line, exit code 1, no traceback, and removes the collection-success marker so the supervisor cannot release the claim as a success; the server keeps all unfinished items pending. `SOURCE_DRAIN_ONLY=true` (with `SOURCE_WORK_ENABLED=true`) skips discovery and drains the existing spool; supervisor recovery ticks remain disabled pending admission semantics.
- Collection cursors are scope watermarks (for example PNCP `last_successful_update`), not pagination guarantees; a capped listing can repeat its prefix. PNCP queue identity uses `numeroControlePNCP`/`sequencialDocumento` (legacy `pncp_control_number`/`pncp_document_sequence` accepted).
- PNCP advances its update watermark only after complete, uncapped enumeration and acknowledged registration; partial scans leave the prior checkpoint untouched. Historical versioned incomplete checkpoints are ignored on read. Finep emits `finep-pages-v1` page metadata only after full page/record coverage, never a generic cursor in that scope.
- `scripts/check_source_catalog_parity.py` with `config/source_catalog_contract.json` gates pinned A-manifest parity offline and live comparison on main push/daily/manual (pins older than 14 days rejected; 39th workflow `source-catalog-parity.yml`). Paused registry entries are explicit local execution holds reported separately, not healthy coverage.
- The per-source reusable job (`pipeline-discovery-source.yml`) serializes scheduled and manual runs of the same source through the `discovery-<source>` lock; all 22 manual fallbacks run the same instrumented orchestrator path with the same lock. `SUBMISSION_CONTRACT` enforces no silent candidate fallback for structured sources; `OPPORTUNITY_SOURCES` comes from the repository variable (explicit opt-in), not auto-derived.
- The all-source workflow rotates source priority by `SOURCE_ROTATION_OFFSET` (workflow run number). Multi-source ingest is rejected fail-closed; production ingest uses one source per job via the group matrix. Reaching the shared PDF cap does not stop discovery of remaining sources: each reports warning/cap-reached telemetry and defers processing. Manual runs default to offset zero.
- Tests must be offline and deterministic. Do not call production endpoints from tests; use the workflow-pinned Python 3.13 interpreter.
- Staging/evidence lives in `docs/STAGING-RUNBOOK.md` (in-progress checklist) and `docs/evidence/` (dated observed results, index, snapshot validation, independent-audit template, per-source folders and 48 h template). Recorded deployment/contract probes do not complete source audits or soak; RR-01 through RR-05 stay OPEN and paused/audit holds are preserved. Hosted staging uses the existing staging API/frontend and an isolated free database; never substitute production credentials or data to unblock it.
- Release cutover is A-first: explicitly migrate to schema v3, verify compatibility and live parity, then transfer schedule ownership. Merging group workflows to `main` activates cron configuration, not dormant code. Standard rollback preserves telemetry, pending work and accepted records; callback disabling is emergency-only with an explicit observability incident. Staging checks must never replace production repository secrets.
- Live parity compares all pinned operational identities exactly. The nine explicitly named historical archive identities may appear outside the 23-source pin only with archived lifecycle and null cadence/timeout; unknown extra keys and changed archive configuration fail closed.
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
- The canonical group, all-source, PNCP, and per-source fallback workflows read the telemetry
  flag from the GitHub repository variable of the same name. Enable it only
  after Repo A's source-run contract and source catalog are deployed and
  verified.
- `pipeline-source-monitor.yml` runs the read-only freshness check every 15 minutes via `scripts/check_source_freshness.py`; it never triggers ingestion and fails closed on auth/schema/network errors.
- Durable drains report per-source download/OCR counters, acknowledged insertion/update/duplicate outcomes and classified failures; a spool finish is not a second submission. ZIP telemetry counts one downloaded attachment and one successful extraction only when its PDF members finish. Freshness monitoring requires both a recent timezone-aware timestamp and `health_status=healthy`; other recent states are listed as `unhealthy` and fail the check.

## Worker CI

- `.github/workflows/ci.yml` is the Worker CI workflow. The repository has 39
  workflows and runs the offline Python 3.13 test suite with read-only
  permissions, pinned actions, bounded concurrency, and a 20-minute timeout.
