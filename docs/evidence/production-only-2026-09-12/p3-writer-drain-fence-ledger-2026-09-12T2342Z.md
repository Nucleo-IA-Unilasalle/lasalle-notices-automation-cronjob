# P3 Writer Drain/Fence Readiness Ledger - 2026-09-12T23:42Z

Status: **REVIEW / INCOMPLETE - NOT PRODUCTION APPROVAL**

This is the sanitized, executable-readiness record for the production-only P3
gate. It inventories the old Repo B default-branch writers, the candidate
worker paths, and the Repo A API, scheduler, and executor surfaces. The
commands are split into read-only preflight and mutation sections. No command
in this record was used to mutate production, dispatch a workflow, cancel a
run, disable a workflow, stop a process, change a repository variable, deploy,
or change a database.

The ledger is a procedure, not evidence that P3 passed. P3 cannot pass until
the missing owners, approvals, frozen release identities, independently
accepted P1 evidence, and immediate pre-transfer observations are supplied.

## Record And Scope

| Field | Recorded value |
|---|---|
| Executor | `/root/p3_ledger` |
| Read-only observation time | `2026-09-12T23:42:37Z` |
| GitHub repository | `Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob` |
| Repo B production ref | `main` at `553c67dcdb593550112470df8c76b0314fae3d4e` |
| Repo B candidate ref | `feature/source-rotation-fairness` at `4211ddf6c99fa4b527f09ff3cad4f86996a1092c` |
| Repo A production ref | `master` at `d0394d3749c81fee85a224ab10e22448a8d02752` |
| Repo A candidate ref | `feature/durable-executor-and-review-hardening` at `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693` |
| Candidate working-tree status | Both candidate repositories contain uncommitted changes; these SHAs do not identify the resulting candidate. |
| Candidate source | `<fill exact approved source>`; `brde` was only a prior proposal, not an approval. |
| Candidate contract | `<fill exact approved contract>`; the first-wave target is normally `candidate`. |
| Release window | `<fill UTC start/end>` |
| Production operator | `<assign named Repo A/Render and Repo B/GitHub operators>` |
| Independent reviewer | `<assign named reviewer>` |
| Observation owner | `<assign named owner>` |
| Backup/data-handling owner | `<assign named owner and private backup reference>` |
| Mutation status | Not executed by this record. P4 approval is required before P5 mutations. |

The production SHAs, candidate SHAs, selected source, contract, window, and
owners must be re-read immediately before P4 and again immediately before P5.
A new commit, deployment, manual dispatch, or schedule occurrence invalidates
the affected observation.

## Read-Only Baseline

The following observations were obtained without changing GitHub, Render, or
the database:

| Surface | Observation at `2026-09-12T23:42Z` | Limitation |
|---|---|---|
| Repo B workflow records | GitHub returned 27 active records: 26 paths under `.github/workflows/` plus the dynamic Dependabot workflow. | `active` does not prove that a run is idle or that an old ref cannot run. |
| Repo B `main` runs | The latest 100 sampled runs were on `main` at SHA `553c67dcdb593550112470df8c76b0314fae3d4e`; no non-completed run was returned for `main`. | A point-in-time empty Actions sample is not a drain, does not cover API-side work, and does not prevent a new schedule or dispatch. |
| Repo B all-ref queue | No non-completed run was found in the read performed for `main`; old refs and a run created after the read remain possible. | Re-read immediately before every mutation and after every drain action. |
| Production schema finding | The live production read-only schema check reported `application_schema_versions`, `source_work_items`, and `source_schedule_state` absent. The additive schema migration is therefore required before candidate durable-work admission. | This is a schema finding, not an empty-queue or empty-backlog claim. No durable-work or schedule-claim rows from those absent tables were read. |
| Candidate workflow tree | 39 local workflow files: 25 managed discovery paths, 3 group callers, 8 legacy-denied paths, and 3 passive/read-only paths. | The candidate tree is dirty and is not a frozen deploy artifact. |
| Candidate recovery registry | Group recovery crons `37/47/57 * * * *` and PNCP recovery `35 * * * *` are present but `recovery_enabled: false`. | Verify the deployed candidate after merge; a local registry is not a production control plane. |
| Repo B PR | PR #8 is draft, head `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`, base `main`, check `test` successful, merge state `CLEAN`. | A draft PR and a successful check are not release approval. |
| Repo A PR | PR #29 is draft, head `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`, base `master`, checks `backend` and `contract` successful, merge state `CLEAN`. | A draft PR and a successful check are not release approval. |

### Current `main` scheduled writers

All 12 entries below were observed as active scheduled writers on the current
remote `main` definition. The exact schedule is the one currently in the
remote file; the run event may also be a manual dispatch or a dependent
`workflow_run` event.

| Workflow path | Workflow ID | Schedule/event | Current write behavior | P3 treatment |
|---|---:|---|---|---|
| `.github/workflows/pipeline-pncp-discovery.yml` | `291103111` | `05 * * * *` plus manual | Direct `python scripts/discover_pncp_candidates.py`; submits PNCP candidates/opportunities through the old path. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-all-discovery.yml` | `300592815` | `08 * * * *` plus manual | Direct `python scripts/discover_all_candidates.py`; can traverse multiple sources. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-fao-discovery.yml` | `300592819` | `12 * * * *` plus manual | Direct FAO discovery and submission. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-ai.yml` | `276848607` | `16 * * * *`, after PNCP completion, plus manual | Calls `POST /api/pipeline/ai`; old `workflow_run` dependency can start after a PNCP run. | Disable exact workflow; server fence API trigger and reconcile any accepted run. |
| `.github/workflows/pipeline-fundacao-grupo-boticario-discovery.yml` | `300592822` | `17 * * * *` plus manual | Direct FGB discovery and submission. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-kfw-discovery.yml` | `300592825` | `28 * * * *` plus manual | Direct KfW discovery and submission. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-sync.yml` | `276848613` | `37 * * * *` plus manual | Calls `POST /api/pipeline/sync` and polls `GET /api/pipeline/runs`. | Disable exact workflow; server fence trigger and reconcile pipeline rows. |
| `.github/workflows/pipeline-msgov-discovery.yml` | `300592826` | `38 * * * *` plus manual | Direct MSGOV discovery and submission. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-unep-discovery.yml` | `300592829` | `45 * * * *` plus manual | Direct UNEP discovery and submission/audit behavior from old main. | Disable exact workflow; server fence any submission. |
| `.github/workflows/pipeline-govbr-mma-discovery.yml` | `300592823` | `50 * * * *` plus manual | Direct GOVBR-MMA discovery and submission. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-worldbank-discovery.yml` | `300592830` | `55 * * * *` plus manual | Direct WorldBank discovery and submission. | Disable exact workflow; server fence old and already-started runs. |
| `.github/workflows/pipeline-backfill.yml` | `276848608` | `23 11 * * 6` plus manual | Calls `POST /api/pipeline/backfill`. | Disable exact workflow; server fence trigger and reconcile legacy rows. |

`pipeline-ai.yml` also has a `workflow_run` trigger after the PNCP workflow;
disabling its cron alone is insufficient. The current latest-run sample had
completed successes, failures, skipped runs, and a cancelled PNCP run; those
conclusions do not establish that the database is drained.

### Current `main` manual and direct writers

The following active paths are not all scheduled, but a user or an old-ref
caller can start them. Every path is included in the explicit disable set in
the mutation section. A wrapper-level deny on the candidate branch cannot
fence a process already running this old definition.

| Workflow path | Workflow ID | Trigger | Direct command or API writer |
|---|---:|---|---|
| `.github/workflows/pipeline-bndes-discovery.yml` | `300592817` | Manual | Direct BNDES discovery/submission. |
| `.github/workflows/pipeline-brde-discovery.yml` | `300592818` | Manual | Direct BRDE discovery/submission. |
| `.github/workflows/pipeline-fapergs-discovery.yml` | `300592820` | Manual | Direct FAPERGS discovery/submission. |
| `.github/workflows/pipeline-funbio-discovery.yml` | `300592821` | Manual | Direct FUNBIO discovery/submission on old main. |
| `.github/workflows/pipeline-iis-rio-discovery.yml` | `300592824` | Manual | Direct IIS-Rio discovery/submission. |
| `.github/workflows/pipeline-sema-rs-discovery.yml` | `300592827` | Manual | Direct SEMA-RS discovery/submission. |
| `.github/workflows/pipeline-tnc-discovery.yml` | `300592828` | Manual | Direct TNC discovery/submission on old main. |
| `.github/workflows/pipeline-wwf-discovery.yml` | `300592831` | Manual | Direct WWF discovery/submission on old main. |
| `.github/workflows/pipeline-ingest.yml` | `290007218` | Manual | `POST /api/pipeline/ingest?source=pncp&candidate_limit=25&download_limit=5`. |
| `.github/workflows/pipeline-ocr.yml` | `291456203` | Manual | `python scripts/ocr_worker/run_ocr_worker.py --limit 5`; claims and completes OCR work. |
| `.github/workflows/pipeline-pncp-backfill.yml` | `302429479` | Manual | `python scripts/backfill_pncp_pending_candidates.py`; claims and submits pending PNCP candidates. |
| `.github/workflows/pipeline-run.yml` | `276848609` | Manual | `POST /api/pipeline/run`. |
| `.github/workflows/pipeline-scrape.yml` | `276848610` | Manual | `POST /api/pipeline/scrape?mode=bs4&sources=pncp`. |

There are 25 operational writer workflow IDs in the remote `main` definition.
The passive `ci.yml` (`346113518`) and dynamic Dependabot record are excluded
from the writer disable set. `ci.yml` does not ingest or submit production
data.

## Candidate Repo B Inventory

The candidate tree has one writer contract: a source-specific managed wrapper
must acquire the Repo A source lease before its child process can submit. Repo A
remains the authority; candidate filtering only prevents unselected jobs from
allocating a full worker child.

### Scheduled candidate ownership

| Candidate workflow | Trigger | Matrix/child behavior | Writer status before explicit activation |
|---|---|---|---|
| `.github/workflows/pipeline-discovery-group-a.yml` | `07 * * * *` plus manual | Reads the registry and emits only the one selected `ingest` source from `bndes`, `brde`, `fao`, `fapergs`, `govbr_mma_fnma`, `iis_rio`, or `canoas`; empty matrix skips the reusable child. | Default-denied; group job may start but no child is allocated for an empty/held selection. |
| `.github/workflows/pipeline-discovery-group-b.yml` | `17 * * * *` plus manual | Sources: `funbio`, `fundacao_grupo_boticario`, `govbr_mma`, `govbr_mma_public_calls`, `sema_rs`, `tnc`, or `dopa`; same matrix filtering. | Default-denied; only the selected source can reach the managed child. |
| `.github/workflows/pipeline-discovery-group-c.yml` | `27 * * * *` plus manual | Sources: `kfw`, `msgov`, `unep`, `worldbank`, `wwf`, `fbds`, `finep`, or `ibama`; same matrix filtering. | Default-denied; only the selected source can reach the managed child. |
| `.github/workflows/pipeline-pncp-discovery.yml` | `05 * * * *` plus manual | Runs only when `CLOSED_BETA_SOURCE_ALLOWLIST == 'pncp'`; uses the PNCP managed wrapper, checkpoint, and candidate contract. | Default-denied unless PNCP is explicitly selected and Repo A agrees. |

The group matrix `max-parallel: 3` is only a per-group runner bound. It is not
the aggregate capacity contract. Repo A advisory key `910012` and its hard cap
of three active source claims are authoritative. Recovery schedules remain
disabled in the candidate registry: group recovery at `37/47/57` and PNCP
recovery at `35` have `recovery_enabled: false`.

### Managed and manual candidate writers

The following paths are all candidate branch writer surfaces. Manual fallbacks
are not schedule owners. Unless a row says `audit-only`, its non-audit path
can submit when the source is admitted, the contract matches, and the Repo A
claim succeeds.

| Workflow path | Source/contract | Trigger and execution path |
|---|---|---|
| `.github/workflows/pipeline-discovery-source.yml` | Required `source`; registry contract | Reusable `workflow_call` plus manual dispatch; runs `python scripts/run_managed_source.py --source "$DISCOVERY_SOURCE" scripts/discover_all_candidates.py`. |
| `.github/workflows/pipeline-all-discovery.yml` | One explicit source; candidate or structured contract | Manual only; rejects empty/multi-source input. `audit_only=true` is non-submitting; a non-audit run is a writer through the managed wrapper. |
| `.github/workflows/pipeline-bndes-discovery.yml` | `bndes` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-brde-discovery.yml` | `brde` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-canoas-discovery.yml` | `canoas` / `opportunity`, paused | Manual fallback; structured contract, audit-only default, managed wrapper. |
| `.github/workflows/pipeline-dopa-discovery.yml` | `dopa` / `opportunity`, paused | Manual fallback; structured contract, audit-only default, managed wrapper. |
| `.github/workflows/pipeline-fao-discovery.yml` | `fao` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-fapergs-discovery.yml` | `fapergs` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-fbds-discovery.yml` | `fbds` / `opportunity`, paused | Manual fallback; structured contract, audit-only default, managed wrapper. |
| `.github/workflows/pipeline-finep-discovery.yml` | `finep` / `opportunity`, paused | Manual fallback; structured contract, audit-only default, managed wrapper. |
| `.github/workflows/pipeline-funbio-discovery.yml` | `funbio` / `opportunity`, audit | Manual fallback; structured contract, managed wrapper; non-audit is held by the registry. |
| `.github/workflows/pipeline-fundacao-grupo-boticario-discovery.yml` | `fundacao_grupo_boticario` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-govbr-mma-discovery.yml` | `govbr_mma` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-govbr-mma-fnma-discovery.yml` | `govbr_mma_fnma` / `candidate`, audit | Manual fallback; managed wrapper; registry keeps ingestion held. |
| `.github/workflows/pipeline-govbr-mma-public-calls-discovery.yml` | `govbr_mma_public_calls` / `candidate`, audit | Manual fallback; managed wrapper; registry keeps ingestion held. |
| `.github/workflows/pipeline-ibama-discovery.yml` | `ibama` / `opportunity`, paused | Manual fallback; structured contract, audit-only default, managed wrapper. |
| `.github/workflows/pipeline-iis-rio-discovery.yml` | `iis_rio` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-kfw-discovery.yml` | `kfw` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-msgov-discovery.yml` | `msgov` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-pncp-discovery.yml` | `pncp` / `candidate` | Scheduled/manual dedicated path; managed PNCP wrapper and checkpoint. |
| `.github/workflows/pipeline-sema-rs-discovery.yml` | `sema_rs` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-tnc-discovery.yml` | `tnc` / `opportunity`, audit | Manual fallback; structured contract, managed wrapper; registry keeps ingestion held. |
| `.github/workflows/pipeline-unep-discovery.yml` | `unep` / `candidate`, audit | Manual fallback; managed wrapper; registry keeps ingestion held. |
| `.github/workflows/pipeline-worldbank-discovery.yml` | `worldbank` / `candidate` | Manual fallback; managed all-candidates wrapper. |
| `.github/workflows/pipeline-wwf-discovery.yml` | `wwf` / `candidate` | Manual fallback; audit branch runs `python scripts/discover_wwf_candidates.py --audit-dir ...` without OCR/submission; non-audit branch uses the managed wrapper. |

The source registry contains exactly 23 keys. `pipeline-discovery-source.yml`,
`pipeline-all-discovery.yml`, and the 23 source-specific paths account for 25
managed discovery paths; the three group callers allocate those paths from the
candidate schedule. The 23 keys and current registry modes are:

| Mode | Sources |
|---|---|
| `ingest` | `bndes`, `brde`, `fao`, `fapergs`, `fundacao_grupo_boticario`, `govbr_mma`, `iis_rio`, `kfw`, `msgov`, `pncp`, `sema_rs`, `worldbank`, `wwf` |
| `audit` | `funbio`, `govbr_mma_fnma`, `govbr_mma_public_calls`, `tnc`, `unep` |
| `paused` | `canoas`, `dopa`, `fbds`, `finep`, `ibama` |

No mode or UI label is a server-side fence. The selected source must be one
active Repo A catalog key, and its contract must match both admission
configuration values before a writer is enabled.

### Candidate legacy and passive paths

The candidate retains eight legacy/control files so that old interfaces remain
visible and fail closed. Each starts with
`python scripts/beta_admission.py --source pncp --legacy-route`, which denies
closed-beta execution. This is a defense in depth check, not a fence for old
refs or direct processes.

| Workflow path | Current candidate trigger | Legacy action after the deny gate |
|---|---|---|
| `.github/workflows/pipeline-ai.yml` | `16 * * * *`, after PNCP, manual | `POST /api/pipeline/ai` |
| `.github/workflows/pipeline-backfill.yml` | `23 11 * * 6`, manual | `POST /api/pipeline/backfill` |
| `.github/workflows/pipeline-ingest.yml` | Manual | `POST /api/pipeline/ingest?source=pncp&candidate_limit=25&download_limit=5` |
| `.github/workflows/pipeline-ocr.yml` | Manual | `python scripts/ocr_worker/run_ocr_worker.py --limit 5` |
| `.github/workflows/pipeline-pncp-backfill.yml` | Manual | `python scripts/backfill_pncp_pending_candidates.py` |
| `.github/workflows/pipeline-run.yml` | Manual | `POST /api/pipeline/run` |
| `.github/workflows/pipeline-scrape.yml` | Manual | `POST /api/pipeline/scrape?mode=bs4&sources=pncp` |
| `.github/workflows/pipeline-sync.yml` | `37 * * * *`, manual | `POST /api/pipeline/sync`, then `GET /api/pipeline/runs` |

Candidate passive paths are not ingestion writers:

| Workflow path | Trigger | Behavior |
|---|---|---|
| `.github/workflows/ci.yml` | Push and pull request | Offline tests and contract checks. |
| `.github/workflows/pipeline-source-monitor.yml` | Every 15 minutes plus manual | Read-only freshness check; fails closed on auth/schema/network errors. |
| `.github/workflows/source-catalog-parity.yml` | Push to `main`, daily schedule, manual | Read-only catalog parity comparison. |

## Queue, Ref, Lease, And Recovery Semantics

These behaviors determine why the disable and server-fence actions are both
required:

1. `gh workflow disable` prevents the normal workflow from accepting future
   schedule/manual dispatches, but it does not cancel a run already queued or
   running and does not rewrite a run's checked-out commit.
2. A run already started from `main` or another old ref retains the workflow
   definition and child command it checked out. An old ref can also be
   dispatched explicitly with `gh workflow run ... --ref <old-ref>` if the
   caller has permission. Do not use such dispatches for testing production.
3. Actions concurrency `queue: max` and `cancel-in-progress: false` preserve
   queued work rather than fencing it. A matrix can have one child per source;
   group `max-parallel: 3` does not prove the global bound.
4. The managed wrapper claims one source for 300 seconds, renews about every
   60 seconds, reserves cleanup time, kills its child process tree on deadline
   or renewal uncertainty, and releases only a recorded outcome. These are
   candidate-worker guarantees; they do not control old direct scripts.
5. Repo A is the authority. In closed beta, candidate/opportunity submissions,
   durable source work, and schedule claims require a valid current
   `X-Source-Claim`; missing, stale, wrong-source, wrong-contract, or
   deselected completion is rejected. Legacy trigger routes are disabled and
   reject rather than silently falling back.
6. Cancelling a GitHub run does not roll back a submission or undo a database
   write. Every cancelled, terminated, or unexpectedly completed run needs a
   reconciliation against pipeline runs, source telemetry, durable work,
   claims, accepted records, and checkpoints.
7. Recovery ticks are disabled in the candidate registry and must remain off
   until separately reviewed. No held source may obtain a new enabled route.
   A recovery route, if later approved, is drain-only and must not advance a
   collection checkpoint or be treated as a second schedule owner.

## Direct CLI Surface

The following commands are the only intended candidate worker entry points,
and they must run through an approved candidate workflow with a matching
source, contract, and Repo A claim:

```text
python scripts/run_managed_source.py --source <approved-source> scripts/discover_all_candidates.py
python scripts/run_managed_source.py --source pncp scripts/discover_pncp_candidates.py
```

The following unmanaged production invocations are forbidden, including from
an old checkout, a Render shell, a local shell with production credentials, or
a manually edited Actions run:

```text
python scripts/discover_all_candidates.py
python scripts/discover_bndes_candidates.py
python scripts/discover_brde_candidates.py
python scripts/discover_fao_candidates.py
python scripts/discover_fapergs_candidates.py
python scripts/discover_funbio_candidates.py
python scripts/discover_fundacao_grupo_boticario_candidates.py
python scripts/discover_govbr_mma_candidates.py
python scripts/discover_govbr_mma_fnma_candidates.py
python scripts/discover_govbr_mma_public_calls_candidates.py
python scripts/discover_ibama_candidates.py
python scripts/discover_iis_rio_candidates.py
python scripts/discover_kfw_candidates.py
python scripts/discover_msgov_candidates.py
python scripts/discover_pncp_candidates.py
python scripts/discover_sema_rs_candidates.py
python scripts/discover_tnc_candidates.py
python scripts/discover_unep_candidates.py
python scripts/discover_worldbank_candidates.py
python scripts/discover_wwf_candidates.py
python scripts/backfill_pncp_pending_candidates.py
python scripts/ocr_worker/run_ocr_worker.py --limit <N>
```

The structured modules `scripts/discover_canoas_opportunities.py`,
`scripts/discover_dopa_opportunities.py`, `scripts/discover_fbds_opportunities.py`,
and `scripts/discover_finep_opportunities.py` are imported by the orchestrator;
they are not direct CLI paths. `discover_wwf_candidates.py --audit-dir` is an
audit artifact path only when its audit branch is used exactly as documented;
it is not permission to invoke its writer mode directly.

Read-only local diagnostics that do not call production mutation endpoints are:

```text
python scripts/build_source_matrix.py --group <a|b|c> --format github
python scripts/check_source_catalog_parity.py --live
python scripts/check_source_freshness.py
python scripts/run_independent_source_audit.py ...
python scripts/audit_source_fidelity.py ...
```

`scripts/run_staging_failure_injection.py` is staging-only and is forbidden
against production even if its guard variables are present. No production
failure injection, forced expiry, stale-owner takeover, deliberate crash, or
synthetic alert test is part of P3.

## Repo A Writer Inventory

Repo A is the FastAPI contract and database owner. The following route groups
must be covered by the A-first deployment and read-only capability check.

| API route group | Methods/routes | Writer or read-only role | Fence/drain treatment |
|---|---|---|---|
| Source telemetry | `POST /api/pipeline/source-runs`; `PATCH /api/pipeline/source-runs/{run_id}` | Writes `source_runs` telemetry; not an ingestion authority. | Keep reporting disabled on old workers until the deployed telemetry contract/catalog is verified; decide whether any existing telemetry writer needs a separate owner. A telemetry row is not proof of an admitted source run. |
| Legacy triggers | `POST /api/pipeline/scrape`, `/sync`, `/ai`, `/ocr`, `/backfill`, `/ingest`, `/purge`, `/run` | Creates/dispatches legacy `pipeline_runs` or invokes legacy work. | Closed-beta `_require_legacy_pipeline_access` must reject. Verify capabilities after A deploy; no old trigger is an allowed compatibility fallback. |
| Legacy OCR claims | `POST /api/pipeline/ocr/claim`; `POST /api/pipeline/ocr/{edital_id}/renew`, `/complete`, `/fail` | Mutates `ocr_processing_claims` and OCR state. | Rejected as part of legacy access in closed beta; drain or terminate old OCR worker before ownership transfer. |
| PNCP backfill claim | `POST /api/pipeline/candidates/backfill/claim` | Claims old pending candidate work. | Admission and source fence require PNCP plus the current claim/contract; old backfill script must not run during transfer. |
| Candidate submit | `POST /api/pipeline/candidates` | Inserts/updates candidate submissions. | `_fence_source_submission` requires current `X-Source-Claim` and the admitted candidate contract. Reconcile accepted/updated/duplicate outcomes. |
| Opportunity submit | `POST /api/pipeline/opportunities` | Inserts/updates structured opportunities. | Requires current claim and matching `opportunity` contract; structured sources remain held unless explicitly approved. |
| Durable source work | `POST /api/pipeline/source-work` | Registers/takes/finishes source spool items and checkpoints. | Requires current claim, source scope, generation, and contract. A stale or deselected owner cannot finish or advance a checkpoint. |
| Schedule claims | `POST /api/pipeline/source-schedule/claims`, `/renew`, `/release` | Creates/renews/releases per-source claim leases. | Claim is the single schedule authority; stale renew/release/work returns a conflict. Deselect cleanup may only be a no-op release. |
| Read-only admission | `GET /api/pipeline/capabilities` and `/health` | Reports mode, admitted source/contract, strict claim, and legacy state. | Required post-A fence assertion; do not activate B if any value is missing, ambiguous, or incompatible. |
| Read-only run/work state | `GET /api/pipeline/runs`; `GET /api/pipeline/source-schedule/catalog`, `/due`, `/recovery-candidates` | Captures pipeline, catalog, due, and recovery state. | Required immediate pre-transfer and post-drain observations; save only sanitized private evidence. |

The regular user/catalog routes such as `POST /editais/sync` and review/edit
updates are outside this worker drain. They remain normal authenticated user
operations and must not be disabled as a side effect of the P3 worker fence.

### Repo A scheduler

`app/scheduler.py` contains these possible process writers:

| Job | Configuration/behavior | P3 action |
|---|---|---|
| `scheduled_scrape_job` | Legacy scheduled scrape; skipped in closed beta. | Confirm `ENABLE_SCHEDULER=false` and closed-beta mode on the deployed API. |
| `scheduled_sync_job` | Legacy hourly sync; skipped in closed beta. | Same verification; no production schedule mutation from this ledger. |
| `scheduled_ai_job` | Legacy AI schedule; skipped in closed beta. | Same verification; reconcile any existing `pipeline_runs`. |
| `scheduled_ocr_job` | Legacy OCR schedule; skipped in closed beta. | Same verification; old OCR process still needs process-level discovery/drain. |
| `scheduled_purge_job` | Legacy Saturday purge; skipped in closed beta. | Same verification; do not use it as a release cleanup. |
| `scheduled_source_run_sweep_job` | Maintenance sweep when `SOURCE_RUN_MAINTENANCE_ENABLED` is true; can mark hanging telemetry stale. | Not an ingestion writer, but it is a DB writer. Assign an owner and record whether it remains enabled during transfer. |
| `scheduled_source_run_retention_job` | Maintenance retention deletion; normally weekly. | Not an ingestion writer. Leave only under the reviewed data-retention owner; no unreviewed production deletion. |

`ENABLE_SCHEDULER=false` is required for the worker-only topology. The API
startup path is read-only schema verification; schema migration is a separate
approved action. The maintenance flag is not equivalent to legacy scheduler
disable and must be recorded separately.

### Repo A executor

The separately supervised process is expected to run as:

```text
python -m scripts.run_pipeline_executor
```

It takes advisory lock `910010`, reads running legacy `pipeline_runs`, and in
closed beta finalizes legacy work as failed rather than dispatching it. The
process identity, host, PID, supervisor, deployed SHA, and whether it is
currently running were not proven by this ledger. The Repo A/Render operator
must identify the process read-only, stop/disable the old executor before
transfer if it exists, and verify that no replacement process can be started
from an old image or environment.

## P3 Action Ledger

| Action | Exact evidence/action required | Owner | Approval/state |
|---|---|---|---|
| Freeze candidate identity | Record final A/B commit SHAs, branches/tags, dirty-tree result, candidate PR checks, selected source, contract, target services, and UTC window. | Release operator + independent reviewer | **OPEN**; current candidate trees are dirty. |
| Disable old Repo B workflows | Revalidate the 25 exact IDs below, then disable every old operational workflow. Keep CI/Dependabot passive. | Repo B/GitHub operator | **PREPARED, NOT EXECUTED**; P4 approval required. |
| Drain/cancel Actions work | Capture all queued/running/waiting/requested/pending run IDs immediately before disable; do not mass-cancel. Cancel only individually approved IDs, then watch terminal state. | Repo B run owner | **OPEN**; current sample had no non-completed `main` run, but no future guarantee. |
| Fence old refs | Deploy A first and verify strict closed-beta capability. Old submissions without a current claim must return a conflict; legacy triggers must reject. | Repo A/Render operator | **OPEN**; isolated process/lost-ACK evidence exists, but the frozen candidate and production fence are not approved or deployed. |
| Discover direct worker PIDs | Run the read-only process discovery on the actual Render/worker host and record command, PID, parent, image SHA, and owner privately. | Repo A/Render and Repo B operators | **OPEN**; production process identity unknown. |
| Stop legacy executor/OCR/CLI processes | After identity match and approval, terminate only the recorded legacy PID/process tree; verify it does not restart. | Named process owner | **UNASSIGNED, NOT EXECUTED**. |
| Capture API/DB state | Run the sanitized API GETs and read-only aggregate SQL immediately before transfer; retain private IDs/counts, no payloads/tokens. | Observation owner + DB owner | **OPEN**; no production DB query performed for this ledger. |
| Schema prerequisite | Apply the separately approved additive migration that creates/verifies `application_schema_versions`, `source_work_items`, and `source_schedule_state`, then repeat schema and aggregate preflight. | Repo A/DB operator | **BLOCKED/OPEN**; the live check reported all three absent. Do not represent absent tables as zero work or proceed with candidate durable-work admission. |
| Reconcile after drain | Compare pipeline runs, source runs, source work statuses, schedule claims, OCR claims, accepted records, and checkpoints before/after. Cancellation is not rollback. | Observation owner | **OPEN**; exact evidence location/owner missing. |
| Verify scheduler/executor settings | Verify deployed A `SOURCE_ADMISSION_MODE=closed_beta`, one selected source, matching contract, effective strict claim, `ENABLE_SCHEDULER=false`, and executor process state. | Repo A/Render operator | **OPEN**; deployed env and process not observed. |
| Verify candidate recovery | Verify deployed B registry has recovery disabled and only one schedule owner for the selected source; held sources have no enabled writer. | Repo B operator | **OPEN**; local registry is disabled, deployment not present. |
| Activate one source | Only after A fence, old writer drain, B default-deny deployment, and P4/P5 approval, set exactly one matching allowlist value and enable only the approved candidate schedule. | Release operator | **NOT AUTHORIZED** by P3. |
| P1 prerequisites | Review the isolated real-process termination, lost-ACK/replay, changed-content, poison/backoff, declared workload, quantitative capacity, and genuine image-only OCR evidence against the frozen heads. | P1 owner + reviewer | **EVIDENCE PRESENT / NOT ACCEPTED**; the isolated checks passed, but the working trees were not frozen and no independent P1 acceptance is recorded. |

### Coordinated rollback constraint

Candidate Repo B deliberately blocks every legacy workflow before it calls the
API. Rolling only Repo A back to legacy mode therefore does not restore legacy
processing and must not be presented as a complete rollback. The reviewed
rollback sequence must close the candidate allowlist, disable the candidate
group/PNCP schedule, drain or cancel only named runs, restore Repo B to the
P4-approved compatible prior ref, verify that ref and its workflow inventory,
and only then roll Repo A back to the approved compatible prior ref if needed.
The inverse order can leave old API writers reachable while candidate worker
ownership is unresolved.

The current prior refs are Repo B
`553c67dcdb593550112470df8c76b0314fae3d4e` and Repo A
`d0394d3749c81fee85a224ab10e22448a8d02752`. They are identity inputs, not
authorization. P4 must replace this paragraph with the exact reviewed commit,
merge/revert, Render deployment, workflow enable/disable, owner, stop, and
verification actions for the frozen candidate. Never roll back the additive
schema by dropping tables or overwrite newer production data with an old dump.
The read-only pinned-ref preflight in [`docs/OPERATIONS.md`](../../OPERATIONS.md)
was run locally for the four legacy entry workflows at the current prior B ref
and passed; it does not replace P4 approval or verify a future deployed ref.

## Read-Only Preflight Commands

Run these commands from the appropriate operator environment immediately before
any P5 mutation. They are read-only with respect to GitHub, the API, and the
database. Do not print or persist secrets, bearer values, claim tokens, raw
payloads, URLs containing credentials, or production record contents. Store
sanitized output in approved private evidence, not this repository.

### GitHub identity, workflow, and run preflight

```powershell
$ErrorActionPreference = 'Stop'
$Repo = 'Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob'
$ExpectedMain = '553c67dcdb593550112470df8c76b0314fae3d4e'
$ExpectedCandidate = '4211ddf6c99fa4b527f09ff3cad4f86996a1092c'
$ObservedAt = Get-Date -AsUTC -Format 'yyyy-MM-ddTHH:mm:ssZ'
Write-Output "observed_at=$ObservedAt"

git ls-remote "https://github.com/$Repo.git" refs/heads/main refs/heads/feature/source-rotation-fairness
$workflows = gh api "repos/$Repo/actions/workflows?per_page=100" | ConvertFrom-Json
$workflows.workflows |
  Select-Object id, path, state, created_at, updated_at |
  Sort-Object path |
  Format-Table -AutoSize

$mainRuns = gh api "repos/$Repo/actions/runs?branch=main&per_page=100" | ConvertFrom-Json
$unexpected = @($mainRuns.workflow_runs | Where-Object {
  $_.head_branch -ne 'main' -or $_.head_sha -ne $ExpectedMain
})
if ($unexpected.Count -gt 0) {
  throw 'The sampled main runs are not all on the expected production SHA.'
}
$mainRuns.workflow_runs |
  Select-Object id, name, status, conclusion, event, head_sha, head_branch, created_at, updated_at |
  Format-Table -AutoSize

foreach ($status in @('queued', 'in_progress', 'waiting', 'requested', 'pending')) {
  $result = gh api "repos/$Repo/actions/runs?branch=main&status=$status&per_page=100" | ConvertFrom-Json
  [pscustomobject]@{ status = $status; count = @($result.workflow_runs).Count }
}

gh pr view 8 --repo $Repo --json number,state,isDraft,baseRefName,headRefName,headRefOid,statusCheckRollup,mergeStateStatus
```

The exact old-writer ID map to assert against the workflow response is:

```powershell
$ExpectedWriterIds = [ordered]@{
  '.github/workflows/pipeline-ai.yml' = 276848607
  '.github/workflows/pipeline-all-discovery.yml' = 300592815
  '.github/workflows/pipeline-backfill.yml' = 276848608
  '.github/workflows/pipeline-bndes-discovery.yml' = 300592817
  '.github/workflows/pipeline-brde-discovery.yml' = 300592818
  '.github/workflows/pipeline-fao-discovery.yml' = 300592819
  '.github/workflows/pipeline-fapergs-discovery.yml' = 300592820
  '.github/workflows/pipeline-funbio-discovery.yml' = 300592821
  '.github/workflows/pipeline-fundacao-grupo-boticario-discovery.yml' = 300592822
  '.github/workflows/pipeline-govbr-mma-discovery.yml' = 300592823
  '.github/workflows/pipeline-iis-rio-discovery.yml' = 300592824
  '.github/workflows/pipeline-ingest.yml' = 290007218
  '.github/workflows/pipeline-kfw-discovery.yml' = 300592825
  '.github/workflows/pipeline-msgov-discovery.yml' = 300592826
  '.github/workflows/pipeline-ocr.yml' = 291456203
  '.github/workflows/pipeline-pncp-backfill.yml' = 302429479
  '.github/workflows/pipeline-pncp-discovery.yml' = 291103111
  '.github/workflows/pipeline-run.yml' = 276848609
  '.github/workflows/pipeline-scrape.yml' = 276848610
  '.github/workflows/pipeline-sema-rs-discovery.yml' = 300592827
  '.github/workflows/pipeline-sync.yml' = 276848613
  '.github/workflows/pipeline-tnc-discovery.yml' = 300592828
  '.github/workflows/pipeline-unep-discovery.yml' = 300592829
  '.github/workflows/pipeline-worldbank-discovery.yml' = 300592830
  '.github/workflows/pipeline-wwf-discovery.yml' = 300592831
}
$remoteByPath = @{}
foreach ($workflow in $workflows.workflows) { $remoteByPath[$workflow.path] = [int64]$workflow.id }
foreach ($path in $ExpectedWriterIds.Keys) {
  if (-not $remoteByPath.ContainsKey($path) -or $remoteByPath[$path] -ne $ExpectedWriterIds[$path]) {
    throw "Workflow identity changed or is missing: $path"
  }
}
```

Do not treat a successful identity assertion as permission to mutate. It only
proves that the IDs are still the IDs reviewed in this record.

### Repo A API preflight

Run only from an authorized operator shell. The command prints a projected
capability/catalog view, not raw response bodies. `PIPELINE_SECRET` is read
from the process environment and is never echoed or recorded.

```powershell
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($env:PROD_API_URL) -or
    [string]::IsNullOrWhiteSpace($env:PIPELINE_SECRET)) {
  throw 'Set PROD_API_URL and PIPELINE_SECRET in the operator environment; never put either value in this record.'
}
$base = $env:PROD_API_URL.TrimEnd('/')
$headers = @{ Authorization = "Bearer $env:PIPELINE_SECRET" }

$cap = Invoke-RestMethod -Method Get -Uri "$base/api/pipeline/capabilities" -Headers $headers
[pscustomobject]@{
  endpoint = '/api/pipeline/capabilities'
  source_admission_mode = $cap.source_admission_mode
  admitted_source = $cap.admitted_source
  admitted_contract = $cap.admitted_contract
  source_claim_enforcement = $cap.source_claim_enforcement
  legacy_pipeline_triggers_enabled = $cap.legacy_pipeline_triggers_enabled
} | Format-List

$catalog = Invoke-RestMethod -Method Get -Uri "$base/api/pipeline/source-schedule/catalog" -Headers $headers
@($catalog.items | Select-Object source_key, catalog_status, expected_interval_minutes, max_run_minutes) |
  Format-Table -AutoSize

$due = Invoke-RestMethod -Method Get -Uri "$base/api/pipeline/source-schedule/due" -Headers $headers
@($due.items | Select-Object source_key, catalog_status, next_due_at, retry_after_at, live_claim, recovery_pending, config_generation) |
  Format-Table -AutoSize

$recovery = Invoke-RestMethod -Method Get -Uri "$base/api/pipeline/source-schedule/recovery-candidates" -Headers $headers
@($recovery.items | Select-Object source_key, catalog_status, next_due_at, retry_after_at, live_claim, recovery_pending, config_generation) |
  Format-Table -AutoSize

$runs = Invoke-RestMethod -Method Get -Uri "$base/api/pipeline/runs?limit=100" -Headers $headers
@($runs | Select-Object id, job_name, status, step, started_at, completed_at) |
  Format-Table -AutoSize
```

If the deployed response shape differs from the frozen OpenAPI contract, stop
instead of printing an unprojected response or guessing a property. The
required assertions are:
closed-beta mode, exactly one selected active source, matching contract,
strict claim enforcement, legacy disabled, no unexpected due/recovery owner,
and no unknown running legacy pipeline.

### Production database aggregate preflight

Use an authorized read-only connection only. The SQL intentionally selects
counts, states, source keys, and timestamps; it never selects payloads,
claim-token hashes, cursors, user fields, document contents, or secrets.

```powershell
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($env:PRODUCTION_READONLY_DATABASE_URL)) {
  throw 'Set PRODUCTION_READONLY_DATABASE_URL to the approved private read-only connection; never print its value.'
}
$env:PGSSLMODE = 'require'
$sql = @"
BEGIN;
SET TRANSACTION READ ONLY;

SELECT 'pipeline_runs' AS surface, status::text AS state, COUNT(*) AS rows,
       MIN(started_at) AS oldest_started_at, MAX(started_at) AS newest_started_at
  FROM pipeline_runs GROUP BY status ORDER BY state;

SELECT 'source_runs' AS surface, s.source_key, sr.status AS state,
       sr.trigger_kind, COUNT(*) AS rows, MIN(sr.started_at) AS oldest_started_at,
       MAX(sr.started_at) AS newest_started_at
  FROM source_runs sr JOIN scraping_sources s ON s.id = sr.source_id
 GROUP BY s.source_key, sr.status, sr.trigger_kind
 ORDER BY s.source_key, state, sr.trigger_kind;

SELECT 'source_work_items' AS surface, s.source_key, swi.contract,
       swi.status AS state, COUNT(*) AS rows,
       MIN(swi.first_pending_at) FILTER (WHERE swi.status = 'pending') AS oldest_pending_at,
       MAX(swi.attempts) AS max_attempts
  FROM source_work_items swi JOIN scraping_sources s ON s.id = swi.source_id
 GROUP BY s.source_key, swi.contract, swi.status
 ORDER BY s.source_key, swi.contract, state;

SELECT 'source_schedule_state' AS surface, s.source_key,
       COUNT(*) FILTER (WHERE ss.claim_token_hash IS NOT NULL) AS active_claims,
       COUNT(*) FILTER (WHERE ss.claim_token_hash IS NOT NULL AND ss.claim_expires_at < now()) AS expired_claims,
       MIN(ss.claim_expires_at) FILTER (WHERE ss.claim_token_hash IS NOT NULL) AS earliest_claim_expiry
  FROM source_schedule_state ss JOIN scraping_sources s ON s.id = ss.source_id
 GROUP BY s.source_key ORDER BY s.source_key;

SELECT 'ocr_processing_claims' AS surface, status, COUNT(*) AS rows,
       COUNT(*) FILTER (WHERE status = 'claimed' AND expires_at < now()) AS expired_claims,
       MIN(expires_at) FILTER (WHERE status = 'claimed') AS earliest_claim_expiry
  FROM ocr_processing_claims GROUP BY status ORDER BY status;

ROLLBACK;
"@
psql $env:PRODUCTION_READONLY_DATABASE_URL --no-psqlrc --tuples-only --csv --command $sql
```

The DB owner must confirm the deployed schema contains the named tables before
running the aggregate. If a table is absent, stop and record the schema
identity instead of changing it or silently dropping a query. The current live
finding is that `application_schema_versions`, `source_work_items`, and
`source_schedule_state` are absent; an approved additive migration is required
before these aggregates or any candidate durable-work route can be treated as
available. Do not report the absence as zero pending/running work. Production
database counts are private evidence and must be redacted before any durable
record is added here.

### Process preflight

Run on the actual service/runner host, not only the development workstation.
Both commands are read-only. The Render/Linux command is the authoritative
one if the executor or worker is hosted there.

```text
ps -eo pid=,ppid=,etimes=,args= | grep -E 'run_pipeline_executor|discover_|run_managed_source|run_ocr_worker|backfill_pncp' | grep -v grep
```

On a Windows operator workstation, use:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_pipeline_executor|discover_|run_managed_source|run_ocr_worker|backfill_pncp' } |
  Select-Object ProcessId, ParentProcessId, CreationDate, ExecutablePath, CommandLine
```

Record only a private process identity, parent, command class, deployed image
SHA, supervisor, and owner. Do not record environment variables, bearer
values, claim tokens, or full credential-bearing command lines.

## Mutation Commands - Not Executed

Every block in this section is intentionally guarded and must remain unrun by
P3 evidence collection. P4 approval must identify the exact action, owner,
window, stop condition, and rollback/reconciliation record before the guard is
changed. Re-run all read-only preflight commands after changing the guard and
before each individual mutation.

### Disable the reviewed old workflows

This guard validates identity only. It does not disable anything while
`$P4_APPROVED` is `$false`.

```powershell
$ErrorActionPreference = 'Stop'
$P4_APPROVED = $false
if (-not $P4_APPROVED) { throw 'P4 approval is required; no workflow was disabled.' }
$Repo = 'Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob'
$workflows = gh api "repos/$Repo/actions/workflows?per_page=100" | ConvertFrom-Json
$ExpectedWriterIds = [ordered]@{
  '.github/workflows/pipeline-ai.yml' = 276848607
  '.github/workflows/pipeline-all-discovery.yml' = 300592815
  '.github/workflows/pipeline-backfill.yml' = 276848608
  '.github/workflows/pipeline-bndes-discovery.yml' = 300592817
  '.github/workflows/pipeline-brde-discovery.yml' = 300592818
  '.github/workflows/pipeline-fao-discovery.yml' = 300592819
  '.github/workflows/pipeline-fapergs-discovery.yml' = 300592820
  '.github/workflows/pipeline-funbio-discovery.yml' = 300592821
  '.github/workflows/pipeline-fundacao-grupo-boticario-discovery.yml' = 300592822
  '.github/workflows/pipeline-govbr-mma-discovery.yml' = 300592823
  '.github/workflows/pipeline-iis-rio-discovery.yml' = 300592824
  '.github/workflows/pipeline-ingest.yml' = 290007218
  '.github/workflows/pipeline-kfw-discovery.yml' = 300592825
  '.github/workflows/pipeline-msgov-discovery.yml' = 300592826
  '.github/workflows/pipeline-ocr.yml' = 291456203
  '.github/workflows/pipeline-pncp-backfill.yml' = 302429479
  '.github/workflows/pipeline-pncp-discovery.yml' = 291103111
  '.github/workflows/pipeline-run.yml' = 276848609
  '.github/workflows/pipeline-scrape.yml' = 276848610
  '.github/workflows/pipeline-sema-rs-discovery.yml' = 300592827
  '.github/workflows/pipeline-sync.yml' = 276848613
  '.github/workflows/pipeline-tnc-discovery.yml' = 300592828
  '.github/workflows/pipeline-unep-discovery.yml' = 300592829
  '.github/workflows/pipeline-worldbank-discovery.yml' = 300592830
  '.github/workflows/pipeline-wwf-discovery.yml' = 300592831
}
$remoteByPath = @{}
foreach ($workflow in $workflows.workflows) { $remoteByPath[$workflow.path] = [int64]$workflow.id }
foreach ($path in $ExpectedWriterIds.Keys) {
  if (-not $remoteByPath.ContainsKey($path) -or $remoteByPath[$path] -ne $ExpectedWriterIds[$path]) {
    throw "Workflow identity changed or is missing: $path"
  }
}
$pending = gh api "repos/$Repo/actions/runs?per_page=100" | ConvertFrom-Json
$open = @($pending.workflow_runs | Where-Object {
  $_.status -in @('queued', 'in_progress', 'waiting', 'requested', 'pending') -and
  $_.workflow_id -in @($ExpectedWriterIds.Values)
})
if ($open.Count -gt 0) {
  throw 'Open writer runs exist. Record and individually approve their run IDs before any disable/cancel action.'
}
Write-Output 'Identity and open-run preflight passed. Stop here and review before executing one disable command at a time.'
```

After the guarded identity check succeeds and the reviewer signs the exact
list, execute one explicit command at a time, recording its exit code:

```text
gh workflow disable 276848607 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-ai.yml
gh workflow disable 300592815 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-all-discovery.yml
gh workflow disable 276848608 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-backfill.yml
gh workflow disable 300592817 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-bndes-discovery.yml
gh workflow disable 300592818 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-brde-discovery.yml
gh workflow disable 300592819 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-fao-discovery.yml
gh workflow disable 300592820 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-fapergs-discovery.yml
gh workflow disable 300592821 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-funbio-discovery.yml
gh workflow disable 300592822 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-fundacao-grupo-boticario-discovery.yml
gh workflow disable 300592823 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-govbr-mma-discovery.yml
gh workflow disable 300592824 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-iis-rio-discovery.yml
gh workflow disable 290007218 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-ingest.yml
gh workflow disable 300592825 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-kfw-discovery.yml
gh workflow disable 300592826 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-msgov-discovery.yml
gh workflow disable 291456203 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-ocr.yml
gh workflow disable 302429479 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-pncp-backfill.yml
gh workflow disable 291103111 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-pncp-discovery.yml
gh workflow disable 276848609 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-run.yml
gh workflow disable 276848610 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-scrape.yml
gh workflow disable 300592827 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-sema-rs-discovery.yml
gh workflow disable 276848613 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-sync.yml
gh workflow disable 300592828 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-tnc-discovery.yml
gh workflow disable 300592829 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-unep-discovery.yml
gh workflow disable 300592830 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-worldbank-discovery.yml
gh workflow disable 300592831 --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob  # pipeline-wwf-discovery.yml
```

Do not disable `ci.yml` or Dependabot as part of this writer drain. The
workflow IDs must be revalidated immediately before use; never assume a copied
ID remains valid after a repository migration or workflow recreation.

### Cancel individually approved runs

The current observation supplied no run IDs. Never use a blanket cancellation
loop. Populate the list only from a fresh preflight, after the run owner and
reviewer approve each ID and its reason.

```powershell
$ErrorActionPreference = 'Stop'
$P4_APPROVED = $false
if (-not $P4_APPROVED) { throw 'P4 approval is required; no run was cancelled.' }
$Repo = 'Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob'
$ApprovedRunIds = @() # Replace only with individually reviewed numeric IDs.
if ($ApprovedRunIds.Count -eq 0) { throw 'No individually approved run IDs; refusing cancellation.' }
foreach ($runId in $ApprovedRunIds) {
  if ([string]$runId -notmatch '^[0-9]+$') { throw "Invalid run ID: $runId" }
  gh run cancel $runId --repo $Repo
}
```

Use `gh run cancel --force` only for a named run when the run owner has
approved the stronger action and the normal cancel did not terminate it. A
cancelled run still requires the API/DB reconciliation described above.

### Stop a verified legacy process

The process owner must first match the PID to the read-only process output and
record the supervisor/restart behavior. This guarded Linux template is not to
be run with an unreviewed PID:

```sh
set -eu
P4_APPROVED=false
[ "$P4_APPROVED" = true ] || { echo 'P4 approval is required; no process stopped.'; exit 1; }
LEGACY_PID='<replace-with-the-individually-reviewed-numeric-pid>'
case "$LEGACY_PID" in
  ''|*[!0-9]*) echo 'PID must be numeric'; exit 1 ;;
esac
ps -p "$LEGACY_PID" -o pid=,ppid=,etimes=,args=
kill -TERM "$LEGACY_PID"
sleep 5
ps -p "$LEGACY_PID" -o pid=,ppid=,etimes=,args= || true
```

Use the Render/service supervisor's stop control when it owns the process;
otherwise a child-only `kill` can leave a restart loop or orphaned process.
The owner must verify no old executor, OCR worker, direct CLI, or old Action
runner remains able to submit after the A fence.

### Deploy and verify the server-side fence

Render deployment is an operator-only control-plane action and is intentionally
not represented by an unreviewed CLI mutation here. The A operator must deploy
the exact frozen Repo A SHA first, record the actual Render SHA, apply only the
approved additive migration, and run the read-only capabilities/catalog/DB
preflight. Do not activate B or probe stale-owner behavior in production if any
of these are false:

```text
mode == closed_beta
admitted_source == the one P4-approved active source
admitted_contract == the P4-approved contract
strict_claim_enforced == true
legacy_pipeline_enabled == false
deployed_sha == the frozen Repo A SHA
schema == the reviewed compatible schema
```

If the deployed fence is absent, ambiguous, or at an unexpected SHA, stop new
admission, preserve evidence, and follow the reviewed rollback/recovery owner.
Do not make a production write to test the fence.

### Candidate variable and schedule activation

Keep `CLOSED_BETA_SOURCE_ALLOWLIST` empty or invalid while B is deployed and
the old writer drain is incomplete. Only after the A fence, old-run
reconciliation, B SHA verification, and P4/P5 approval may the operator set
one exact source. The command below is a guarded template; it was not run:

```powershell
$ErrorActionPreference = 'Stop'
$P5_APPROVED = $false
if (-not $P5_APPROVED) { throw 'P5 approval is required; source remains default-denied.' }
$Repo = 'Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob'
$SelectedSource = '<replace-with-exact-approved-source-key>'
$AllowedSources = @('bndes','brde','fao','fapergs','fundacao_grupo_boticario','govbr_mma','iis_rio','kfw','msgov','pncp','sema_rs','worldbank','wwf')
if ($SelectedSource -notin $AllowedSources) { throw 'Selected source is not an approved candidate-contract ingest key.' }
gh variable set CLOSED_BETA_SOURCE_ALLOWLIST --repo $Repo --body $SelectedSource
```

After the candidate merge, re-query workflow identities. Do not reuse the old
ID for a newly created group workflow. Enable exactly the approved group or
PNCP workflow only after review; if PNCP is the selected source, its existing
workflow ID must be revalidated before an explicit `gh workflow enable`. A
candidate schedule becoming active on merge is not source activation while the
allowlist is empty, but it still must be checked for unexpected runs.

## Immediate Reconciliation And Stop Conditions

The observation owner must capture the following immediately before A/B
ownership transfer and immediately after drain/fence actions:

| Reconciliation surface | Required comparison |
|---|---|
| GitHub Actions | Every queued/running/waiting/requested/pending run ID, workflow path, ref, SHA, event, started time, and terminal conclusion; no unknown writer remains. |
| Legacy pipeline runs | `pipeline_runs` status/step/job and timestamps; no unexpected running legacy row or newly accepted legacy trigger. |
| Source telemetry | `source_runs` running/terminal status by source and trigger; telemetry is not accepted as ingestion proof. |
| Durable source work | Pending/accepted/quarantined counts, oldest pending timestamp, attempts/error categories, and contract by source; no item is silently deleted. |
| Schedule claims | Active claim source, owner, generation, expiry, and config fingerprint; no stale owner can renew/release/work. Never record raw token/hash. |
| OCR claims | Claimed/expired/completed/failed counts and any worker identity available through private evidence. |
| Accepted catalog data | Counts and source identity/content hashes for any records touched during the window; do not copy production payloads into this repository. |
| Checkpoints | Scope and watermark before/after; no old or recovery writer advances a checkpoint unexpectedly. |
| Capacity and telemetry | API errors/timeouts, p95, DB connections, storage, memory, backlog, service rate, and completion time against the reviewed P1 thresholds. |

Stop immediately and close new admission if any of the following occurs:

- A stale, missing, wrong-source, wrong-contract, or legacy write is accepted.
- A duplicate logical record, changed user-owned field, or lost pending item is observed.
- An old/ref-unknown workflow, process, or schedule owner remains able to overlap.
- A workflow starts from an unexpected SHA, target, source, or contract.
- An API/server fence is absent, authentication/SSRF protection is ambiguous,
  or telemetry is missing for an admitted run.
- A cancellation or process termination leaves unknown work that cannot be
  reconciled from the private observations.
- Any P1 capacity threshold is exceeded or quantitative capacity evidence is
  unavailable for the proposed concurrency.

Do not attempt a destructive restore or an unreviewed cleanup. Preserve the
private evidence and invoke the named P2 recovery and rollback owners.

## Unresolved Ownership And Approval Details

The following values are required before P3 can be accepted and are currently
unassigned or unproven:

1. Final immutable Repo A and Repo B candidate SHAs after the dirty working
   trees are committed, plus the exact intended merge/deploy order.
2. One approved candidate-contract source and matching contract, with every
   other source explicitly held; `brde` is not approved merely because it was
   proposed in earlier evidence.
3. Named Repo B GitHub operator with permission to disable workflows and a
   separate run owner authorized to cancel individual runs.
4. Named Repo A/Render operator who can identify and stop the executor, OCR,
   and any direct worker process, including the process supervisor and restart
   policy.
5. Named observation owner and independent reviewer, a UTC release window,
   approved private read-only DB route, and backup/data-handling owner.
6. Actual deployed Repo A SHA, schema migration result, admission environment,
   `ENABLE_SCHEDULER` value, maintenance decision, and candidate B SHA after
   deployment.
7. An approved additive schema migration and post-migration verification for
   `application_schema_versions`, `source_work_items`, and
   `source_schedule_state`; the live check found all three absent. No claim in
   this ledger treats those absent tables as having been read or empty.
8. Immediate pre-transfer aggregate counts and sanitized run IDs; the current
   empty Actions sample is not a substitute for API/database evidence.
9. Independent acceptance of the genuine P1 worker termination, lost-ACK
   replay, workload, and quantitative-capacity evidence for the frozen heads,
   including the bounded genuine image-only OCR fixture, against the frozen
   dependency and code heads.
10. Reviewed stop, rollback, reconciliation, and notification actions for an
   unexpected stale write, duplicate, lost item, or overlapping owner.

Until these are recorded and approved, P3 remains **REVIEW / INCOMPLETE** and
P4-P6 remain unauthorized. This ledger records readiness work only; it does
not authorize a deployment, workflow enablement, source activation, database
migration, cancellation, process termination, or production test.
