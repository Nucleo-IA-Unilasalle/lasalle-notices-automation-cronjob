# P3 Admission Candidate - 2026-09-12T06:11:38Z

Status: **REVIEW / INCOMPLETE**

## Scope

This record covers uncommitted closed-beta admission changes built on Repo A
`e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693` and Repo B
`4211ddf6c99fa4b527f09ff3cad4f86996a1092c`.

Repo A now supplies the authoritative admission decision. Closed beta is the
default, an empty or invalid selected source fails closed, the selected source
must be an active catalog key with one configured submission contract, and
source claims are strict. Source schedule, durable work, candidate/opportunity
submission, legacy pipeline and user-scrape endpoints, queued legacy execution,
and legacy scheduled jobs are fenced. A deselected source may only release with
the no-op cleanup outcome. Durable registration and finish reject the wrong
contract, while take holds pre-cutover work from a different contract.

Repo B's existing default-deny gate is supplemented by source-matrix and PNCP
job filtering. Grouped workflows produce only the configured source and skip an
empty matrix, avoiding runner allocation for non-selected sources. API-side
enforcement remains authoritative if workflow filtering is bypassed.

## Historical Verification At 2026-09-12T06:11:38Z

These totals describe the dirty candidate tree at the timestamp in this
record. They are preserved as historical evidence and are not the current
post-harness or frozen-head verification totals.

- Repo A focused admission, scheduler, executor, configuration, API, and OpenAPI
  contract suite: `126 passed`.
- Repo A database-independent suite:
  `971 passed, 212 skipped, 14 warnings`.
- Repo A isolated PostgreSQL 16 source schedule/work suites: `74 passed`,
  including genuine lease expiry, successor takeover, stale-authority rejection,
  crash retry/quarantine, queue/cursor behavior, and concurrent aggregate claims.
- Repo B full suite: `1068 passed`.
- Repo B workflow YAML parse count: `39` files.
- `git diff --check` passed in both repositories.

An independent code review found three admission gaps during this continuation:
non-dry-run user scrape routes, server-side submission/durable-work contract
binding, and completion release after source deselection. The implementation
and PostgreSQL regressions were extended, and the reviewer confirmed all three
findings resolved with no remaining issue in that recheck.

A later independent review found an additional source-run telemetry admission
gap. The API and worker reporter were subsequently changed to require and send
the selected source's live claim for telemetry start/completion. That later
change is not covered by the historical totals below and requires current
verification before a release decision.

Commands and observed exit codes:

```text
Repo A: .venv/Scripts/python.exe -m pytest -q --ignore=tests/services/test_source_work_service.py --ignore=tests/services/test_source_work_cursors.py
Exit 0: 971 passed, 212 skipped, 14 warnings

Repo A: DATABASE_URL=postgresql://postgres@127.0.0.1:55432/lasalle_test .venv/Scripts/python.exe -m pytest -q tests/api/test_source_schedule_claims.py tests/api/test_source_work_routes.py tests/services/test_source_work_service.py tests/services/test_source_work_cursors.py tests/services/test_ingestion_source_identity.py
Exit 0: 74 passed

Repo B: py -3.13 -m pytest -q
Exit 0: 1068 passed
```

Docker Desktop's backend could not start while handling a locked stale
`sailor-ingest.sock` file. Instead, PostgreSQL 16.15 packages were extracted to
an ephemeral Ubuntu WSL directory without system installation, and the database
tests ran against a scratch schema there. The takeover test verifies that the
stale owner cannot renew, release, register/take/finish durable work, update
checkpoints, or submit candidates/opportunities, and that the successor can
recover the still-pending item after its bounded crash retry window. No
production endpoint or data was used. The temporary server was stopped and its
runtime, package, log, and data directories were removed after verification.

A broader Repo A `pytest -m postgres` attempt was terminated after it stopped
progressing at a cross-module boundary; it is not counted as a pass. The focused
source-reliability PostgreSQL suite above completed cleanly, and the next
isolated run must retain per-module progress/timing evidence while extending the
process-level scenarios.

## Gate Result

P1 remains open because genuine worker-process termination, end-to-end lost-ACK
replay, declared workload measurements, and quantitative capacity thresholds are
incomplete. P3 remains open because the complete production drain/fence action
ledger has not been accepted and the remaining applicable P1 evidence is not
complete. P4-P6 are therefore not authorized. RR-01 through RR-05 remain OPEN.

No production endpoint or data was mutated, no source or workflow was activated,
and no credential value is present in this record.
