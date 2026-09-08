# Staging Failure Injection & Fencing Report — 2026-09-07

**Execution Timestamp**: `2026-09-07T22:59:31Z` to `2026-09-07T23:00:07Z`
**Target Environment**: Hosted Staging API (`https://lasalle-notices-api-staging.onrender.com`)
**Database**: Reported hosted staging PostgreSQL 17 (`lasalle-notices-staging-db`); distinct database identity was not independently verified by this probe.
**Service ID**: `srv-d9i41fl8nd3s7397hcig`
**Executor**: Windows 11 / Python 3.13 local runner
**Status**: **Historical observation: 3/3 probe checks reported passed**

---

## Executive Summary

A targeted lease-admission, fencing, and expiry probe was executed against the
hosted staging API. The recorded HTTP responses support the narrow outcomes
below; this was not a load test, a crash test, a database integrity audit, or a
production readiness sign-off.

1. **Aggregate Concurrency Limit Gate**: **PASSED**. Exactly 3 concurrent source claims were admitted (`HTTP 201`), and the 4th concurrent request was rejected with `HTTP 409 Conflict` (`reason: "capacity_full"`). All 3 leases were subsequently released cleanly with `outcome: "noop"` (`HTTP 200 OK`).
2. **Stale-Owner Fencing Gate**: **PASSED**.
   - Unseeded source rejection verified on `empraba`: returned `HTTP 404 Not Found` (`"detail": "Unknown source_key: empraba"`), confirming catalog boundary protection.
   - Distributed mutual exclusion verified on active source `fao`: Primary owner (`owner-alpha`) acquired lease (`HTTP 201`); concurrent acquisition attempts by `owner-beta` both without force (`force=False`) and with force (`force=True`) were strictly rejected (`HTTP 409`, `reason: "claim_active"`).
   - Tamper/Mismatched Token rejection verified: renewal attempt with mismatched token rejected (`HTTP 409`, `reason: "claim_missing"`).
   - Clean lease release by `owner-alpha` verified (`HTTP 200 OK`).
3. **Lease Expiry / Renewal Verification Gate**: **PASSED**.
   - Renewal with active token successfully extended lease duration from initial expiry to updated timestamp (`HTTP 200 OK`).
   - Expired lease renewal strictly rejected with `HTTP 409 Conflict` (`reason: "claim_expired"`).
   - Automatic lease reclaim by subsequent owner after expiration verified (`HTTP 201 Created`).
   - Clean lease release verified (`HTTP 200 OK`).

---

## Detailed Test Logs & Execution Steps

### Task 1: Aggregate Concurrency Limit (Boundary Test)

- **Objective**: Prove that the global server-side concurrency ceiling (`MAX_CONCURRENT_SOURCE_RUNS = 3`) is strictly enforced across parallel workers.
- **Methodology**: Dispatched 4 concurrent HTTP POST requests to `/api/pipeline/source-schedule/claims` across distinct worker threads targeting 4 distinct catalog sources: `brde`, `fapergs`, `iis_rio`, `worldbank`.
- **Request Parameters**: `lease_seconds = 120`, `owner = "failure-injection-test"`, `force = True`, `scope = "default"`, `purpose = "collection"`.

#### Execution Results

| Thread / Target Source | HTTP Status | Response Latency | Result Payload / Reason Code | Evaluation |
|---|---|---|---|---|
| `brde` | **201 Created** | 375.87 ms | `claim_token` issued (generation 4, `expires_at`: `2026-09-07T23:01:31Z`) | **Admitted (1/3)** |
| `fapergs` | **201 Created** | 289.56 ms | `claim_token` issued (generation 2, `expires_at`: `2026-09-07T23:01:31Z`) | **Admitted (2/3)** |
| `worldbank` | **201 Created** | 296.57 ms | `claim_token` issued (generation 2, `expires_at`: `2026-09-07T23:01:31Z`) | **Admitted (3/3)** |
| `iis_rio` | **409 Conflict** | 658.66 ms | `{"detail": {"reason": "capacity_full", "message": "Source capacity is occupied"}}` | **Rejected (Boundary Enforced)** |

#### Cleanup / Lease Release

All 3 admitted claims were released sequentially via `POST /api/pipeline/source-schedule/claims/release`:
- `brde`: `HTTP 200 OK` (`{"accepted": true}` in 280.50 ms)
- `fapergs`: `HTTP 200 OK` (`{"accepted": true}` in 315.71 ms)
- `worldbank`: `HTTP 200 OK` (`{"accepted": true}` in 288.64 ms)

**Probe Verdict**: **PASSED** (admission count: 3, rejection count: 1,
rejection reason: `capacity_full`, and three accepted `noop` release responses).
The probe did not query the database after release, so it does not establish a
general "zero orphan leases" invariant.

---

### Task 2: Stale-Owner Fencing

- **Objective**: Verify that an active lease cannot be hijacked by an uncoordinated worker, invalid/mismatched tokens cannot renew a lease, and catalog identity fails closed on unregistered sources.

#### Step 2A: Catalog Contract Boundary (`empraba`)
- **Action**: Attempted claim acquisition on unseeded source `empraba` with `owner="owner-alpha"`, `lease_seconds=120`.
- **Request**: `POST /api/pipeline/source-schedule/claims`
- **Response**: `HTTP 404 Not Found`
- **Payload**: `{"detail": "Unknown source_key: empraba"}`
- **Analysis**: Validated fail-closed security. The scheduling layer refuses to coordinate or create lease records for any source key not explicitly registered in Repo A's catalog table `ScrapingSource`.

#### Step 2B: Protocol Fencing Verification (`fao`)
The full multi-owner fencing lifecycle was executed against active source `fao`:

1. **Owner-Alpha Initial Claim**:
   - `POST /api/pipeline/source-schedule/claims` with `owner="owner-alpha"`, `lease_seconds=120`, `force=True`.
   - **Response**: `HTTP 201 Created`
   - **Payload**: `claim_token` issued (generation 2, `expires_at`: `2026-09-07T23:01:33Z`).
2. **Owner-Beta Acquisition Attempt (`force=False`)**:
   - `POST /api/pipeline/source-schedule/claims` with `owner="owner-beta"`, `force=False`.
   - **Response**: `HTTP 409 Conflict`
   - **Payload**: `{"detail": {"reason": "claim_active", "message": "Source already has a live claim"}}`
3. **Owner-Beta Acquisition Attempt (`force=True`)**:
   - `POST /api/pipeline/source-schedule/claims` with `owner="owner-beta"`, `force=True`.
   - **Response**: `HTTP 409 Conflict`
   - **Payload**: `{"detail": {"reason": "claim_active", "message": "Source already has a live claim"}}`
   - **Significance**: In this sequence, `force=True` did not preempt the active lease. This is consistent with the intended rule that force bypasses scheduled interval timing (`not_due`), but one sequence is not universal proof of every interleaving.
4. **Owner-Beta Unauthorized Renewal Attempt**:
   - `POST /api/pipeline/source-schedule/claims/renew` with `owner="owner-beta"`, mismatched token `invalid-mismatched-fencing-token-beta-12345`.
   - **Response**: `HTTP 409 Conflict`
   - **Payload**: `{"detail": {"reason": "claim_missing", "message": "No active claim for this source"}}`
   - **Significance**: The mismatched renewal was rejected in this sequence. The HTTP response does not independently establish the database implementation or prove rejection for every unauthorized-extension attempt.
5. **Owner-Alpha Clean Release**:
   - `POST /api/pipeline/source-schedule/claims/release` with valid token, `outcome="noop"`.
   - **Response**: `HTTP 200 OK`
   - **Payload**: `{"accepted": true, "config_generation": 0}`

**Probe Verdict**: **PASSED** for the exercised request sequence. It demonstrates
mutual exclusion and invalid-token rejection for this live staging observation;
it is not exhaustive proof of all fencing interleavings.

---

### Task 3: Lease Expiry / Renewal Verification

- **Objective**: Verify that valid renewals extend active leases, expired leases reject late renewals, and expired leases are automatically reclaimable by new workers without operator intervention.
- **Target Source**: `bndes`

#### Step 3A: Active Lease Extension
1. **Initial Short-Lease Claim**:
   - `POST /api/pipeline/source-schedule/claims` with `owner="renewal-test-owner"`, `lease_seconds=30`.
   - **Response**: `HTTP 201 Created`
   - **Initial Expiry (`T1`)**: `2026-09-07T23:00:04.576890Z`
2. **Lease Extension via Renewal**:
   - `POST /api/pipeline/source-schedule/claims/renew` with active token, `lease_seconds=120`.
   - **Response**: `HTTP 200 OK`
   - **Updated Expiry (`T2`)**: `2026-09-07T23:01:34.876147Z`
   - **Verification**: `T2 > T1` (Expiry deadline successfully extended forward by 90.3 seconds).
3. **Clean Release**:
   - `POST /api/pipeline/source-schedule/claims/release` with `outcome="noop"`.
   - **Response**: `HTTP 200 OK` (`{"accepted": true}`).

#### Step 3B: Expired Lease Fencing & Automatic Reclaim
1. **Short Lease Claim**:
   - Acquired 30-second claim with `owner="expiry-fencer-alpha"`.
   - **Response**: `HTTP 201 Created`.
2. **Lease Expiration Sleep**:
   - Worker paused for 31 seconds, permitting the wall clock to pass the lease expiration deadline.
3. **Post-Expiry Renewal Attempt**:
   - Stale worker attempted renewal on the expired token: `POST /api/pipeline/source-schedule/claims/renew`.
   - **Response**: `HTTP 409 Conflict`
   - **Payload**: `{"detail": {"reason": "claim_expired", "message": "Claim lease expired"}}`
   - **Significance**: The server returned `claim_expired`, and the subsequent owner acquired a new claim. This is consistent with the expired claim no longer blocking acquisition; no database inspection was recorded to confirm internal token-hash cleanup.
4. **Post-Expiry Reclaim by New Owner**:
   - New worker (`owner="expiry-fencer-beta"`) submitted a fresh claim request: `POST /api/pipeline/source-schedule/claims` (`lease_seconds=60`, `force=True`).
   - **Response**: `HTTP 201 Created`
   - **Payload**: New valid `claim_token` issued (generation 7).
5. **Final Cleanup**:
   - Cleanly released new lease with `outcome="noop"` (`HTTP 200 OK`).

**Probe Verdict**: **PASSED** for this single expiry/reclaim sequence. It shows
that this expired lease was rejected and then reclaimed; it does not measure
recovery behavior under process crashes, network partitions, or sustained load.

---

## Gate Results Summary

| Gate ID | Description | HTTP Status Codes | Observed Reason Codes | Status |
|---|---|---|---|---|
| **GATE-1** | Aggregate Concurrency Ceiling (Boundary = 3) | `201`, `409`, `200` | `capacity_full` | **PASSED** |
| **GATE-2** | Stale-Owner Fencing & Catalog Boundary | `404`, `201`, `409`, `200` | `claim_active`, `claim_missing` | **PASSED** |
| **GATE-3** | Lease Renewal Extension & Expiry Fencing | `201`, `200`, `409` | `claim_expired` | **PASSED** |

---

## Compliance & Security Assertions

- **Credential handling**: The runner retrieved `PIPELINE_SECRET` in memory.
  The saved report contains no raw secret or claim token. The original
  machine-local JSON result was not retained in this public repository, so this
  document is an execution summary rather than independently replayable raw
  evidence.
- **Cleanup evidence**: The recorded release requests returned HTTP 200 with
  `accepted: true`. No post-run database inspection was recorded; do not infer
  zero lingering locks, zero backlog, or absence of unrelated staging activity.
- **Scope**: Calls targeted the hosted staging URL, not a production URL. Distinct
  database identity was not independently verified by this probe. It did not
  measure Render rate limits, cold-start behavior, bandwidth, or free-tier
  capacity.

## Re-run Safety

The current runner is intentionally fail-closed. It cannot target an arbitrary
URL and performs no network request unless both an explicit
`--allow-live-staging-mutation` argument and
`STAGING_FAILURE_INJECTION_ACK=staging-only` are supplied. Its deterministic
offline tests cover that guard and evidence redaction. A re-run changes staging
lease state only; it must not be used as a production check.
