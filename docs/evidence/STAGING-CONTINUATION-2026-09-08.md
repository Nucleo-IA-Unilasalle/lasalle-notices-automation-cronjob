# Staging Continuation - 2026-09-08 UTC (post preflight)

RR-01 through RR-05 remain OPEN. This is staging integration evidence, not
release approval, audit acceptance, or production authorization. No production
merge, deployment, activation, or source-hold change occurred.

## CI refresh

- B `feature/source-rotation-fairness` HEAD `cb35c26`, working tree clean
  except the new evidence below. Draft PR #8 OPEN, still draft.
- Post-push Worker CI run `34174720281` completed `success` at
  `2026-09-08T00:55:14Z` (previously pending). This closes the pending check
  from the prior handoff; it does not close release gates.
- A `feature/durable-executor-and-review-hardening` HEAD `e9422dc` unchanged.
  Draft PR #29 OPEN, still draft; backend/contract checks passing at run
  `34160920016`.

## Read-only preflight (re-verified)

- Render service `srv-d9i41fl8nd3s7397hcig`: free, `not_suspended`, repo
  `lasalle-notices-automation`, branch `staging/opportunity-sources`,
  automatic deployment enabled.
- Deployment `dep-dafiamh7lnhs73fppjfg`: `live` at full A SHA
  `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`.
- Replacement DB `dpg-dafi9egu01pc73ait7gg-a`: `available`, free,
  PostgreSQL 17, expires `2026-10-07T20:55:22.077452Z`.
- External allowlist count `0` (empty) before and after this continuation,
  verified via GET before mutation and via PATCH-response plus GET after
  cleanup. No broad allowlist was ever added.
- Staging env identity (read via Render REST, credentials in memory only):
  DATABASE_URL hostname matches the replacement DB, dbname
  `lasalle_notices_staging_db_dzcn`; `APP_VERSION=2.0.0-staging-e9422dc`;
  `ENABLE_SCHEDULER=false`; `SOURCE_RUN_MAINTENANCE_ENABLED=false`;
  `SOURCE_TRANSPARENCY_ENABLED=true`;
  `SOURCE_CLAIM_ENFORCEMENT=compatible`; frontend
  `https://lasalle-notices-staging.onrender.com`; `PIPELINE_SECRET` present.
  Config identity only, not content reconciliation.
- Staging API: `/health` 200 `healthy`; `/` version
  `2.0.0-staging-e9422dc`; `/api/pipeline/capabilities` and
  `/api/pipeline/health` 200 `compatible`, documentless disabled.
- Pinned catalog parity passed; all 39 workflow YAML files parsed.
- Live + pinned catalog parity passed first try in this continuation
  (prior turn needed one retry; that cause remains not established).
- BRDE/BNDES snapshot structural validation passed, each reporting two TODO
  audits and no correlated runs. Not audit acceptance.

## Fresh SQL schema-v3 verification (resolved)

Prior direct SQL verification had failed (EOF / SSL-TLS-required) with the
allowlist empty. With explicit user authorization for a temporary operator
/32, the following staging-only path was executed with guaranteed cleanup:

- Saved prior allowlist via GET: empty (`[]`). Abort rule: non-empty prior
  aborts without mutation to avoid clobbering.
- Refused `0.0.0.0/0`; only `177.4.239.248/32` with a dated auto-remove
  description was permitted.
- `PATCH /v1/postgres/dpg-dafi9egu01pc73ait7gg-a` added the /32: response
  showed count `1` containing the operator CIDR.
- Waited 20 s for firewall propagation.
- Fetched `/connection-info` in memory only (never printed); used the
  external connection string with `sslmode=require` in memory.
- Read-only query `SELECT max(version) FROM application_schema_versions`
  returned `3`; `is_schema_v3: True`.
- `finally` restored `PATCH {"ipAllowList": []}`: cleanup response count
  `0`, follow-up GET verified empty. Credentials stayed in memory; only
  counts, booleans, and the version integer were emitted.

## Corrected failure-injection probes (staging-only)

Runner `scripts/run_staging_failure_injection.py` (fixed staging URL,
requires `--allow-live-staging-mutation` plus
`STAGING_FAILURE_INJECTION_ACK=staging-only`).

- Attempt 1 at `2026-09-08T01:19:54Z`: FAILED fail-closed, exit 1, no
  artifact. Task 1 reported 0 admitted / 0 rejected (cold-start timeouts);
  Task 2 raised `ReadTimeout` (20 s) against the staging API. Free-tier cold
  start is the suspected cause, not established as the sole cause.
  Post-attempt read-only `due` check showed `live_claim: False` for
  `brde`, `fapergs`, `iis_rio`, `worldbank`, `fao`, `bndes`: no dangling
  leases left by the failed attempt.
- Warmed the service (`/health`, `/`, authenticated `due` + capabilities).
- Attempt 2 at `2026-09-08T01:21:35Z`: PASSED, exit 0. Task 1 (3 admitted /
  1 `capacity_full` / clean noop releases): pass. Task 2 stale-owner fencing
  (`empraba` 404, alpha 201, beta 409 `claim_active` x2, invalid renew 409
  `claim_missing`, alpha release 200 accepted): pass. Task 3 lease
  expiry/renewal (extend verified, release accepted, post-expiry renew 409
  `claim_expired`, reclaim 201 + release 200): pass. Cleanup succeeded.
- Sanitized artifact: `docs/evidence/failure_injection_results.json`
  (claim tokens stored as `[REDACTED sha256:...]`; bounded scan found no
  pipeline-secret, Render API-key, private-key, or local-path material).
- Post-probe `due` check: `live_claim: False` for all involved sources. No
  staging leases retained.

These probes establish live admission/fencing/expiry behavior only. They do
not prove worker crash/replay, lost-ACK after acceptance, backlog
persistence, capacity/latency SLOs, image-only OCR, independent audits,
UI/monitoring, or soak. All such gates remain open.

## Offline checks this continuation

- `git diff --check`: passed.
- `tests/test_staging_failure_injection_safety.py`: 8 passed.
- Full B suite not rerun (B code unchanged since `cb35c26`; only new
  evidence added). A tests not rerun (A unchanged).

## Still open (unchanged)

Worker crash/restart/replay/lost-ACK/backlog tests; structured and
documentless canaries; image-only OCR on GitHub Actions; independent complete
inventories and two reviewed cycles per source; capacity/UI/monitoring gates;
separately supervised free-only durable executor; A-first
migration/deployment; final-wave 48 h observation and seven-day review. Green
local/CI/probe results cannot close those gates. All paused/audit holds
preserved.
