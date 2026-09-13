# B5 Default-Deny Beta Schedule Isolation

Status: REVIEW. This is local/offline implementation evidence only, not a
hosted mutation, source activation, staging run, or release approval.

- Task: B5
- Executor: `/root/b5_default_deny`
- Required reviewer: separate Sol xhigh pass, not yet assigned
- Repository B baseline SHA: `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`
- Repository B branch: `feature/source-rotation-fairness`
- Repository A SHA: not resolved in this B-only run; no A mutation was made
- Start/end (UTC): `2026-09-08T16:34:00Z` / `2026-09-08T16:58:42Z`
- Target: local B worktree only

## Assertions And Results

`CLOSED_BETA_SOURCE_ALLOWLIST` is now mandatory at the managed-worker boundary.
It must be exactly one known ingest-mode candidate-contract registry key. Unset,
empty, whitespace/comma malformed, unknown, held, structured-contract, and
non-selected values return exit code 2 before a `SourceControl` client is
constructed. The registry remains the 23-key catalog and lifecycle source; the
temporary beta allowlist does not alter its `rollout_mode` values.

All source discovery workflows now invoke `run_managed_source.py`, including
manual source fallbacks and the formerly all-source workflow. The latter accepts
exactly one selected source and otherwise exits before discovery. PNCP discovery
is fenced by the same managed boundary. Legacy API writer routes (AI, backfill,
ingest, OCR, PNCP backfill, run, scrape, and sync) run a preflight that always
blocks them in closed beta because their current Repo A endpoints have no
verified source-claim admission contract.

The existing source registry still assigns one `schedule_owner` per 23 key and
the three group workflows retain `max-parallel: 3`. This is static coverage,
not proof of the cross-workflow aggregate cap or lease ownership in staging.

## Commands

```text
py -3.13 -m pytest tests/test_beta_admission.py tests/test_managed_source.py tests/test_source_schedule_registry.py tests/test_workflow_static.py -q
exit 0: 71 passed in 1.30s

py -3.13 -m pytest -q
exit 0: 1055 passed in 141.39s

py -3.13 scripts/beta_admission.py --source bndes
exit 2 (unset allowlist)

CLOSED_BETA_SOURCE_ALLOWLIST=bndes py -3.13 scripts/beta_admission.py --source brde
exit 2 (non-selected source)

CLOSED_BETA_SOURCE_ALLOWLIST=bndes py -3.13 scripts/beta_admission.py --source bndes
exit 0 (selected source)

CLOSED_BETA_SOURCE_ALLOWLIST=bndes py -3.13 scripts/beta_admission.py --source bndes --legacy-route
exit 2 (legacy route blocked)

git diff --check
exit 0
```

## Remaining Risks And Dependencies

- Repo A must provide or explicitly document fenced admission for any retained
  legacy trigger before that route can be re-enabled; B cannot make its direct
  endpoints source-safe on its own.
- No hosted staging claim, aggregate-cap, queued-job drain, or default-branch
  workflow state was mutated or observed here. B6/B7 need those explicit
  staged and operational checks.
- Before enabling a repository variable, disable/drain or fence old queued and
  default-branch jobs, verify the deployed B SHA, retain recovery ticks off,
  and select one source with exactly one scheduled owner. A malformed variable
  remains fail-closed but should be corrected rather than treated as a canary.
