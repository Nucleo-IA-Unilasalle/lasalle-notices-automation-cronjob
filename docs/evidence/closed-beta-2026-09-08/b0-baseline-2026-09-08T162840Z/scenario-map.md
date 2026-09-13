# B0 Scenario Map

Status: BLOCKED with static map reviewed. This is a static map at A
`e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693` and B
`4211ddf6c99fa4b527f09ff3cad4f86996a1092c`. `Partial` means useful existing
coverage, not task completion. `Missing` requires a new test or authorized
hosted evidence; it must not be re-labeled as covered by a nearby unit test.

## B2: Takeover And Fencing

| Required scenario | Existing coverage | Gap/status |
|---|---|---|
| Alpha expiry, beta reclaim, new token and generation increase | A `tests/api/test_source_schedule_claims.py::test_expired_lease_is_reclaimable_and_bumps_fencing_generation` | Partial: service-level isolated DB; no complete stale-owner mutation matrix. |
| Stale alpha renew and release rejection | Same A reclaim test; `test_claim_renew_release_complete_advances_due_state` | Partial: no beta-lease usability assertion after every rejected operation. |
| Stale registration, take/finish, checkpoint, candidate and structured submissions have zero side effects | A `tests/services/test_source_work_service.py::test_expired_worker_cannot_finish_after_reclaim`; route round-trip coverage in `tests/api/test_source_work_routes.py` | Missing combined authentic-token test for all listed operations, row/checkpoint/data snapshots, and structured submission. |
| Compatible versus strict supplied-stale credentials and missing legacy header behavior | A `tests/services/test_source_claim_fencing.py`; candidate legacy/invalid tests in `tests/api/test_source_work_routes.py` | Partial: supplied authentic stale token under compatible mode is not shown. |
| Lock-wait race where expiry occurs while alpha blocks and beta takes over | A `test_two_sessions_cannot_both_hold_the_claim` | Missing deterministic lock-wait/transaction-execution authority test. |
| Config-generation or lifecycle invalidates a live claim | A fingerprint test in `tests/services/test_source_claim_fencing.py` | Missing claim invalidation at mutation/transaction boundary. |
| Genuine hosted staging post-takeover rejection and cleanup | B `tests/test_staging_failure_injection_safety.py` guards a staging-only runner | Missing authorized live staging test with a genuine superseded token. Historical runner used fabricated/expiry checks only. |

## B3: Crash, Replay, And Backlog

| Injection boundary | Existing coverage | Gap/status |
|---|---|---|
| Registration committed, process killed before processing | B `tests/test_managed_source.py::test_collection_commits_descriptors_before_cursor` | Missing genuine subprocess restart and eventual claim assertion. |
| Extraction complete, killed before submit | B unit coverage for ambiguous submit and failure classification | Missing real-worker kill/restart and pending-work persistence proof. |
| API accepts submit but response is lost | B `test_submission_headers_fence_managed_workers`, `test_submit_transport_error_is_ambiguous_and_retried_by_server` | Missing controlled accepted-response loss plus accepted logical identity/row-count replay assertions. |
| Submit acknowledged, killed before spool finish | B `test_ambiguous_ack_is_finished_failed_never_accepted` | Missing real acknowledgment/restart reconciliation proof. |
| Finish committed but response lost | B unit handling around finish/error codes | Missing idempotent finish replay integration with no duplicate acceptance/retry corruption. |
| Renewal timeout or hard kill | B `test_renewal_uncertainty_kills_tree_and_releases_failed`, `test_subprocess_death_releases_failed_with_child_exit_code`, `test_deadline_expiry_kills_tree_before_lease_expiry` | Partial: mocked process control; missing genuine worker process tree and recoverable unfinished spool evidence. |
| Batch registration/cursor transaction failure | B `test_partial_inventory_never_advances_checkpoint`, `test_collection_commits_descriptors_before_cursor`; A cursor tests | Partial: no genuine worker/API/PostgreSQL injected transaction rollback harness. |
| Cap, poison item, fresh arrivals, backoff/quarantine, no starvation | B `test_failed_item_does_not_starve_next_item`, cap/defer tests; A work-service quarantine test | Partial: no bounded backlog integration with real worker and fresh-arrival ordering. |
| Unchanged replay, changed-record staging, no redundant OCR | Existing unit/idempotency-oriented coverage only | Missing specified integration harness and documented one-command reproduction. |

## B4: Migration And Recoverability

| Required scenario | Existing coverage | Gap/status |
|---|---|---|
| v1-v2-v3 additive upgrade/repeat safety | A `tests/config/test_schema_release.py`; `tests/services/test_source_work_service.py::test_version_one_upgrade_creates_missing_satellites` | Partial: test coverage does not rehearse the documented command on isolated fixtures through all required checks. |
| Schema constraints, indexes, browser/anonymous restrictions | A schema/startup tests, including version-table RLS assertions | Partial: no consolidated isolated permissions/index rehearsal. |
| Current production version read and named private backup/restore | None in local test suite | Missing; requires explicit authorized production read/backup and approved private isolated restore. |
| Previous deployed worker against additive A and non-destructive worker rollback | API compatibility/error-code route tests | Missing real previous-worker compatibility and drain/fence/resume rehearsal. |

## B5: Default-Off One-Source Admission

| Required scenario | Existing coverage | Gap/status |
|---|---|---|
| Registry covers exactly 23 keys and single canonical ownership | B `tests/test_source_schedule_registry.py::test_registry_covers_exactly_the_23_operational_keys` and group ownership tests | Present for static registry only; not admission control. |
| Group crons/registry parity and no duplicate scheduled fallbacks | B registry cron tests and `tests/test_workflow_static.py::test_canonical_schedule_has_no_duplicate_source_fallbacks` | Partial: current behavior has active `ingest` registry entries; no release-candidate default-deny proof. |
| Default-off telemetry/config and workflow static safety | B `test_instrumented_entrypoints_use_default_off_repository_telemetry_flag`, workflow YAML tests | Partial: telemetry default-off is not source admission. |
| Unset, empty, malformed, unknown source allowlist rejects | None identified | Missing. |
| Non-selected source, manual/backfill/all-source/PNCP bypass attempts reject | Static workflow and PNCP tests only | Missing end-to-end admission tests covering all writer paths. |
| Aggregate cap three across groups/PNCP/manual and one scheduled owner | Registry static ownership tests | Missing staging concurrency proof and explicit default-deny enforcement. |
| Old queued/default-branch jobs disabled, drained, or fenced | None | Missing authorized operational inventory and procedure evidence. |

## B6: First Canary And Visibility

| Required scenario | Existing coverage | Gap/status |
|---|---|---|
| Two independently grounded audits for selected BRDE candidate | B audit tooling/templates and source tests; no BRDE two-cycle evidence | Missing; repository diagnostic output cannot self-certify. |
| Staging candidate path through discovery, registration, extraction/OCR, acceptance, finish, telemetry, and public catalog | B staging runbook documents the path | Missing frozen-code genuine staging execution. |
| Unchanged replay, beta-user visibility, and user-owned fields preserved | Local route/unit coverage only | Missing B6 staging evidence. |
| Healthy empty versus backlog unknown, worker warnings, and monitor delivery | B freshness monitor/static tests and operations documentation | Missing operator receipt and staging behavior evidence. |
| Missed-run/failure alert and recovery, daily human fallback | None as executed evidence | Missing; do not create an automation without authorization. |
| Bounded API/DB/memory/backlog measurements | None as B6 evidence | Missing staging measurements. |

## Estimated Critical Path

The prior 2-4 engineer-day estimate is invalid as a release commitment. The
remaining critical path is: B2 contract/fencing resolution; a new B3 genuine
worker harness; B4 backup/restore access and rehearsal; B5 default-deny across
all writer paths; then two independent audits and B6 staging canary/visibility.
The 23-source program can take weeks. No current map entry closes RR-01 through
RR-05 or approves `brde`.

## Required Isolation Before Mutation

Use `py -3.13` (observed 3.13.5). The default `python` is 3.11.15. Before any
B2/B3/B4 mutation, record the isolated PostgreSQL identity and prove it is not
production or staging. A hosted staging mutation additionally requires the
task's explicit staging authorization and the runner's staging-only guard; it
is not implied by this map.
