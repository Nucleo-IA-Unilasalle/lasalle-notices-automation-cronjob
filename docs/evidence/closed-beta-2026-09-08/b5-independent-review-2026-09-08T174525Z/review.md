# B5 Independent Default-Deny Review

Status: REVIEW, CHANGES REQUIRED. This is a separate local/offline review of
the B5 implementation. It is not staging proof, source activation, a hosted
mutation, release approval, or permission to change GitHub workflows.

- Task: B5
- Reviewer: `/root/b5_independent_review`, separate from executor
  `/root/b5_default_deny`
- Review rigor requested: xhigh; exact model identity was not exposed to the
  evidence process
- Repository B baseline SHA: `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`
- Repository B branch: `feature/source-rotation-fairness`
- UTC start/end: `2026-09-08T17:45:25Z` / `2026-09-08T17:57:42Z`
- Scope: dirty local B candidate worktree only; existing edits were preserved

## Findings

1. High, blocking acceptance: the candidate workflow graph is guarded, but the
   admission check is not an authority boundary for old refs, already-started
   jobs, direct writer CLIs, or API-side legacy writers. In
   `scripts/pipeline_core.py:422-425`, `X-Source-Claim` is optional when
   `SOURCE_CLAIM_TOKEN` is absent. Nineteen discovery submitter modules plus the
   PNCP backfill and OCR worker remain directly mutation-capable and do not
   import `beta_admission`. Current candidate workflows put the managed wrapper
   or always-denying preflight before their write steps, but B0 separately
   observed active remote `main` legacy schedules and an in-progress old-main
   writer. A workflow-only gate cannot stop a run whose workflow snapshot is
   already executing, a dispatch from an older ref, or Repo A's own scheduler.
   Before activation, use an A-first server-side admission/fencing boundary or
   an equivalently proven credential/environment restriction, then cancel or
   drain old Actions runs, prevent old-ref legacy dispatch, reconcile API-side
   pending/running work, and verify the deployed SHA. The exact mechanism and
   human owner remain unassigned.
2. Medium: `scripts/run_managed_source.py:40` accepts either child script for
   every source and reaches `SourceControl` construction at line 64 without
   checking the pair. The isolated probe proved that admitted source `bndes`
   can reach the claim boundary with `discover_pncp_candidates.py`. Current
   workflow arguments are correct, so this is a latent boundary-integrity defect
   rather than a demonstrated hosted bypass. Bind `pncp` exclusively to the
   PNCP script and all non-PNCP keys exclusively to the all-source script before
   constructing `SourceControl`; add both mismatch directions to tests.
3. Medium, test gate: the current focused and full Python 3.13 suites fail one
   test. `tests/test_beta_admission.py:30-32` expects the candidate-contract
   denial for `finep`, but `finep` is currently `paused`, so the newer held-mode
   check correctly denies it first. This is a stale test expectation, not a
   production permissiveness defect. Safest fix: retain the real-registry test
   for the held denial, and test the candidate-contract branch with a patched
   validated registry entry whose mode is `ingest` and contract is
   `opportunity`; do not weaken or reorder production checks merely to satisfy
   the assertion.
4. Blocking PASS only: no hosted staging overlap proved the aggregate cap of
   three, exact claim ownership, or exactly one scheduled owner for the selected
   beta source. No authorized drain/fence exercise proved that old default-branch
   writers cannot overlap the candidate. B5 therefore remains `REVIEW` even
   after local fixes.

## Accepted Local Scope

All 39 workflow YAML files parsed. The final route inventory classified 25
managed discovery workflows, three group callers, eight always-denied legacy
workflows, and three read-only/CI workflows. Every current candidate writer step
is preceded by or contained within the admission boundary; no writer step uses
`continue-on-error`. The separate WWF audit-only discovery lacks writer
credentials and returns before OCR/submission. The 23-key registry and its one
declared owner per source remain intact, and recovery ticks remain disabled.

These are static candidate observations. Per-group `max-parallel: 3` is not an
aggregate cross-workflow proof and does not replace Repo A capacity enforcement.

## Verification

| Command/artifact | Result |
|---|---|
| `py -3.13 -m pytest tests/test_beta_admission.py tests/test_managed_source.py tests/test_source_schedule_registry.py tests/test_workflow_static.py -q` | Exit 1: 1 failed, 71 passed. Failure is the stale `finep` denial-message expectation described above. |
| `py -3.13 -m pytest -q` | Exit 1: 1 failed, 1056 passed in 140.75 seconds; same failure only. |
| Repository YAML parse command from `AGENTS.md` | Exit 0: all 39 workflows parsed. |
| `actionlint` | Not run because it is not installed; this is recorded rather than silently treated as a pass. |
| Run-local route inventory | Two over-strict review-harness attempts failed on WWF's artifact-only audit and were preserved. Corrected rerun exited 0 with all 39 routes classified. |
| Managed source/script mismatch probe | Exit 0: mismatch reached the mocked `SourceControl` constructor; no network or credential access occurred. |
| Direct-writer surface probe | Exit 0: 19 discovery submitters, PNCP backfill, and OCR lack a module-level beta gate; no secret value was used or recorded. |
| `git diff --check` | Exit 0 before this review document was added. |

## Disposition

Independent acceptance is withheld. Fix the stale test and source/script pair
validation, rerun focused and full suites, and obtain a separate review of those
fixes. Then complete authorized staging aggregate-cap/ownership proof and a
named operational drain/fence plan for old/default-branch and API-side writers.
Do not mark B5 `PASS` until those linked checks and separate acceptance exist.

No credential, connection string, bearer/JWT value, raw claim token, personal
data, production row, or dump is present in this run directory.
