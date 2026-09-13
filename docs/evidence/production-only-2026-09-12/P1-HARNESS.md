# P1 Isolated Harness

This runbook describes the process-level P1 release gate. It is an isolated
check, not a production smoke test or a production approval record.

## Scope

`scripts/run_p1_isolated_harness.py` starts Repo A with Uvicorn and starts real
Repo B worker subprocesses using `scripts/source_control.py`. It creates a
random PostgreSQL schema, runs the schema migration and a disposable source
catalog, then drops only that schema in `finally`.

The database guard accepts only PostgreSQL URLs whose host is `localhost`,
`127.0.0.1`, or `::1`. It rejects SQLite, remote hosts, and database names
containing production or hosted-environment markers. No production endpoint,
credential, source activation, or hosted staging target is permitted.

## Invocation

Run from the Repo B checkout with a disposable local PostgreSQL database:

```text
py -3.13 scripts/run_p1_isolated_harness.py \
  --database-url postgresql://postgres@127.0.0.1:55432/lasalle_test \
  --api-repo ../lasalle-notices-automation \
  --api-python ../lasalle-notices-automation/.venv/Scripts/python.exe \
  --output-dir docs/evidence/production-only-2026-09-12/p1-harness-<run> \
  --arrival-rate-per-hour 22 \
  --storage-budget-bytes 1073741824
```

The storage allowance and arrival rate must be declared from the disposable
environment being measured. Omitting the storage allowance intentionally leaves
the storage gate blocked. The JSON report is sanitized and contains no claim
tokens or pipeline secrets; retain it with `summary.txt` as the machine and
human-readable evidence pair.

## Scenarios

- `worker_termination_and_recovery` kills a real worker after registration,
  expires its lease in the disposable schema, and verifies successor takeover,
  durable pending rows, and completion.
- `lost_submit_ack_replay_idempotency` commits a candidate while discarding the
  HTTP response, kills the worker, and verifies exact replay returns a duplicate
  without creating a second edital or document.
- `lost_finish_ack_replay` commits a finish while discarding its response and
  retries the exact finish request before lease takeover. A non-2xx response is
  a release blocker even when the row was already accepted.
- `changed_content_replay` registers and accepts one stable source identity,
  registers a newer content snapshot, and verifies revision increment, in-place
  candidate/document update, and one logical accepted record.
- `poison_backoff_and_quarantine` fails the oldest poison fixture, verifies the
  next eligible descriptor proceeds while the poison row is backed off, then
  exhausts the bounded attempts and verifies quarantine with its error code.
- `capacity` starts four real claim workers against the shared cap, expects one
  `capacity_full` rejection, drains disjoint descriptor fixtures, and records
  warm catalog p95, aggregate worker request failures, active claims, usable DB
  connections, database size, process RSS, completion time, and measured
  service rate.

The capacity API is started in legacy mode solely to exercise the shared
aggregate lease pool across disposable fixture sources. It does not represent
the closed-beta production admission configuration; the closed-beta API is
checked separately before correctness scenarios run.

## Gate Semantics

The harness exits zero only when every scenario passes and all quantitative
checks pass: API 5xx/timeout rate below 1%, warm catalog p95 at or below one
second, peak connections at or below 70% of confirmed usable connections,
storage headroom at or above 20%, and measured drain capacity at or above 1.25x
the declared arrival rate. Unknown measurements remain blocked rather than
being inferred.

## Local Validation

The offline harness tests and the focused Repo B suite cover the safety guard,
redaction, threshold behavior, subprocess/API wiring, and report contract. The
latest disposable PostgreSQL smoke run passed all five correctness scenarios
and capacity after Repo A made accepted finish acknowledgement replay
idempotent. A prior run correctly exposed the missing behavior as
`409 work_conflict`; that result must remain part of the review history rather
than being treated as a pass.
