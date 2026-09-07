# Hosted Staging Canaries & Capabilities Report — 2026-09-07

- **Execution Date / Window**: `2026-09-07T23:00:49Z` to `2026-09-07T23:01:06Z` (20:00:49 to 20:01:06 America/Sao_Paulo)
- **Target Host**: `https://lasalle-notices-api-staging.onrender.com`
- **Target Service ID**: `srv-d9i41fl8nd3s7397hcig` (Render Web Service)
- **Environment**: Staging (PostgreSQL 17 `lasalle-notices-staging-db`, Python 3.13 on Render, Windows 11 runner)
- **DOX Contract Compliance**: Bound. Zero secrets written to disk or logs; `PIPELINE_SECRET` fetched in-memory via Render REST API.
- **Overall Verdict**: **24 / 24 PASSED (100% Pass Rate, 0 Failed)**.

---

## 1. Executive Summary

This staging canary suite executed end-to-end live testing against the hosted LaSalle Notices staging API to validate:
1. **Capabilities Endpoint & Rollout Flags**: Worker preflight schema parity, authentication boundaries (401/403), and verification that staging currently operates under `ENABLE_DOCUMENTLESS_OPPORTUNITIES=False` and `SOURCE_CLAIM_ENFORCEMENT=compatible`.
2. **Structured Opportunities Canary**: Verification of the source segregation barrier (structured sources cannot submit to legacy candidate route), documentless rollout gating on `/api/pipeline/opportunities`, opportunity model hash integrity, and successful candidate ingestion with rich edge-case attributes (Portuguese accents, unicode, mathematical symbols, emojis, special characters, long text) and duplicate idempotency.
3. **Bounded Body & Payload Hardening**: Enforcement of `PipelineSourceRunBodyLimitMiddleware` (32 KB limit on schedule claims, 512 KB limit on source work returning HTTP 413), candidate payload upper bounds (10,000,000 characters returning HTTP 422), malformed JSON parsing resilience, Pydantic field-level guards (100 KB metadata limit, 100 item candidate limit, extra fields forbidden), and Edge WAF L7 inspection.
4. **Old-Worker Compatibility Window**: Proof that legacy workers omitting `X-Source-Claim` succeed under `SOURCE_CLAIM_ENFORCEMENT=compatible`, invalid/forged claim tokens fail explicitly with HTTP 409 `claim_invalid`, and fenced claim lifecycle (acquire → write → release as noop) functions correctly without altering production schedules.

---

## 2. Test Execution Matrix (24/24 Passed)

| Test ID | Suite | Method | Endpoint | HTTP Status | Verdict | Summary |
|---|---|---|---|:---:|:---:|---|
| **TC-1.1** | Capabilities | `GET` | `/api/pipeline/capabilities` | `200 OK` | **PASS** | Validated capabilities schema: `status=ok`, `documentless_opportunities_enabled=False`, `documentless_opportunity_rollout=disabled`, `source_claim_enforcement=compatible`. |
| **TC-1.2** | Capabilities | `GET` | `/api/pipeline/health` | `200 OK` | **PASS** | Authenticated health matches capabilities schema exactly. |
| **TC-1.3** | Capabilities | `GET` | `/api/pipeline/capabilities` | `401 Unauthorized` | **PASS** | Request without `Authorization` header rejected (`Missing Authorization header`). |
| **TC-1.4** | Capabilities | `GET` | `/api/pipeline/health` | `401 Unauthorized` | **PASS** | Request without `Authorization` header rejected (`Missing Authorization header`). |
| **TC-1.5** | Capabilities | `GET` | `/api/pipeline/capabilities` | `403 Forbidden` | **PASS** | Invalid Bearer secret token rejected (`Invalid pipeline secret`). |
| **TC-1.6** | Capabilities | `GET` | `/api/pipeline/capabilities` | `401 Unauthorized` | **PASS** | Non-Bearer scheme (`Basic`) rejected (`Authorization header must use Bearer scheme`). |
| **TC-2.1** | Structured Opps | `POST` | `/api/pipeline/candidates` | `409 Conflict` | **PASS** | Structured source `finep` rejected at candidate route (`requires the structured opportunity contract`). |
| **TC-2.2** | Structured Opps | `POST` | `/api/pipeline/opportunities` | `409 Conflict` | **PASS** | Documentless opportunity submission rejected while `ENABLE_DOCUMENTLESS_OPPORTUNITIES=False`. |
| **TC-2.3** | Structured Opps | `POST` | `/api/pipeline/opportunities` | `422 Unprocessable` | **PASS** | Tampered SHA-256 hash rejected (`source_content_hash does not match source_markdown`). |
| **TC-2.4** | Structured Opps | `POST` | `/api/pipeline/candidates` | `200 OK` | **PASS** | Candidate with edge-case attributes (diacritics, unicode, emojis, special chars, long text) inserted cleanly. |
| **TC-2.5** | Structured Opps | `POST` | `/api/pipeline/candidates` | `200 OK` | **PASS** | Re-submission of identical candidate recognized as duplicate (`inserted: 0, duplicates: 1`). |
| **TC-3.1** | Bounded Body | `POST` | `/api/pipeline/source-schedule/claims` | `413 Payload Too Large` | **PASS** | 40 KB body rejected by `PipelineSourceRunBodyLimitMiddleware` (> 32 KB limit). |
| **TC-3.2** | Bounded Body | `POST` | `/api/pipeline/source-work` | `413 Payload Too Large` | **PASS** | 600 KB body rejected by `PipelineSourceRunBodyLimitMiddleware` (> 512 KB limit). |
| **TC-3.3** | Bounded Body | `POST` | `/api/pipeline/candidates` | `422 Unprocessable` | **PASS** | 10.88 MB / 11.4M chars payload rejected gracefully (`candidate payload exceeds 10000000 characters`). |
| **TC-3.4** | Bounded Body | `POST` | `/api/pipeline/candidates` | `422 Unprocessable` | **PASS** | Truncated/malformed JSON handled gracefully without server crash or hang. |
| **TC-3.5a**| Bounded Body | `POST` | `/api/pipeline/candidates` | `422 Unprocessable` | **PASS** | Single candidate metadata exceeding 100,000 characters rejected (`metadata exceeds 100000 characters`). |
| **TC-3.5b**| Bounded Body | `POST` | `/api/pipeline/candidates` | `422 Unprocessable` | **PASS** | Candidate batch exceeding 100 items rejected (`at most 100 items`). |
| **TC-3.5c**| Bounded Body | `POST` | `/api/pipeline/candidates` | `422 Unprocessable` | **PASS** | Forbidden extra fields rejected (`extra_forbidden`). |
| **TC-3.8** | Bounded Body | `POST` | `/api/pipeline/candidates` | `403 Forbidden` | **PASS** | Render/Cloudflare Edge WAF intercepted SQL injection attack signature before application layer. |
| **TC-4.1** | Old-Worker Compat | `POST` | `/api/pipeline/candidates` | `200 OK` | **PASS** | Legacy caller omitting `X-Source-Claim` accepted and processed under compatible mode (`inserted: 1`). |
| **TC-4.2** | Old-Worker Compat | `POST` | `/api/pipeline/candidates` | `409 Conflict` | **PASS** | Caller providing invalid/forged claim token strictly rejected (`claim_invalid`). No silent fallback. |
| **TC-4.3a**| Old-Worker Compat | `POST` | `/api/pipeline/source-schedule/claims` | `201 Created` | **PASS** | Acquired 300s collection lease for source `fao` returning unique `claim_token`. |
| **TC-4.3b**| Old-Worker Compat | `POST` | `/api/pipeline/candidates` | `200 OK` | **PASS** | Fenced candidate write under active lease succeeded (`inserted: 1`). |
| **TC-4.3c**| Old-Worker Compat | `POST` | `/api/pipeline/source-schedule/claims/release` | `200 OK` | **PASS** | Released claim with `outcome="noop"`, preserving schedule cadence. |

---

## 3. Detailed Verification Findings

### 3.1 Capabilities & Rollout Flags Verification
Both `GET /api/pipeline/capabilities` and `GET /api/pipeline/health` were queried under valid credentials:
- **Response Payload**:
  ```json
  {
    "status": "ok",
    "documentless_opportunities_enabled": false,
    "documentless_opportunity_rollout": "disabled",
    "source_claim_enforcement": "compatible"
  }
  ```
- **Authentication Perimeter**:
  - Unauthenticated calls (missing `Authorization` header) consistently returned HTTP 401 `{"detail": "Missing Authorization header"}`.
  - Invalid bearer tokens returned HTTP 403 `{"detail": "Invalid pipeline secret"}`.
  - Non-Bearer authorization schemes returned HTTP 401 `{"detail": "Authorization header must use Bearer scheme"}`.

### 3.2 Structured Opportunities Canary & Segregation
- **Segregation Guard**: Submitting structured sources (`ibama`, `tnc`, `funbio`, `dopa`, `canoas`, `finep`, `fbds`) to `/api/pipeline/candidates` was verified: `source="finep"` was blocked with HTTP 409 `{"detail": "Source 'finep' requires the structured opportunity contract"}`.
- **Documentless Opportunity Gate**: Submitting an opportunity to `/api/pipeline/opportunities` without a renderable PDF (`documents: []`) returned HTTP 409 `{"detail": "Documentless opportunity submissions are disabled"}`, confirming that staging accurately enforces rollout flags.
- **Cryptographic Hash Verification**: Tampering with `source_content_hash` resulted in immediate validation failure at the Pydantic model layer (HTTP 422 `Value error, source_content_hash does not match source_markdown`).
- **Edge-Case Attributes**: Candidate submissions containing comprehensive Portuguese diacritics (`áéíóú àèìòù ãõ âêîôû çñ ÁÉÍÓÚ`), Unicode mathematical operators (`≤ ≥ ≠ ± µ π Ω √ ∞ ≈ ∆ ∑ ∏ ∫`), emojis (`🇧🇷 🌲 🔬 ⚡ 🚀 📋 🏛️`), HTML snippets (`<div class="canary">...</div>`), and long text (~3.6 KB) were accepted, persisted, and confirmed without string corruption.
- **Idempotency**: Re-submitting the identical candidate returned HTTP 200 with `outcome="duplicate"`, `duplicates=1`, and `inserted=0`.

### 3.3 Bounded Body & Payload Hardening
- **Middleware Guard**: `PipelineSourceRunBodyLimitMiddleware` actively inspects `/api/pipeline/source-schedule/*`, `/api/pipeline/source-runs`, and `/api/pipeline/source-work`:
  - 40 KB body to `/source-schedule/claims` was rejected before routing with HTTP 413 `{"detail": "Request body exceeds the configured byte limit"}` (threshold: 32 KB).
  - 600 KB body to `/source-work` was rejected before routing with HTTP 413 `{"detail": "Request body exceeds the configured byte limit"}` (threshold: 512 KB).
- **Candidate Submission Bounds**:
  - Request with 11.4M characters (~10.88 MB) was rejected with HTTP 422 `Value error, candidate payload exceeds 10000000 characters` without server hanging or timeout.
  - Candidate metadata exceeding 100,000 characters was rejected with HTTP 422 `Value error, metadata exceeds 100000 characters`.
  - Batch exceeding 100 items was rejected with HTTP 422.
  - Malformed JSON was rejected with HTTP 422 without unhandled 5xx exceptions.
- **Layer 7 Threat Defense**: Injection of SQL attack signatures (`'; DROP TABLE editais; --`) was intercepted at the Edge WAF layer returning HTTP 403 Forbidden (`<title>Blocked</title>`), demonstrating active edge filtering.

### 3.4 Old-Worker Compatibility Window
- **Legacy Compatibility**: Under `SOURCE_CLAIM_ENFORCEMENT=compatible`, callers submitting candidates without the `X-Source-Claim` header succeeded with HTTP 200 (`inserted: 1`).
- **Strict Fencing on Forged Claims**: Supplying an invalid or forged `X-Source-Claim` header failed with HTTP 409 `{"detail": {"reason": "claim_invalid"}}`. Legacy mode does not silently ignore invalid claim tokens.
- **Fenced Claim Lifecycle**:
  1. `POST /api/pipeline/source-schedule/claims` successfully leased `source_key="fao"`.
  2. `POST /api/pipeline/candidates` with `X-Source-Claim: <token>` succeeded with HTTP 200 (`inserted: 1`).
  3. `POST /api/pipeline/source-schedule/claims/release` with `outcome="noop"` released the lease cleanly.

---

## 4. Operational Sign-off Status

- **Staging Canary Status**: **PASSED**.
- **Production State**: Unchanged. Production databases and schedules remain untouched.
- **Release Readiness (RR-01 to RR-05)**: Remain **OPEN** pending independent source ground truth audits and 48-hour soak observation.
