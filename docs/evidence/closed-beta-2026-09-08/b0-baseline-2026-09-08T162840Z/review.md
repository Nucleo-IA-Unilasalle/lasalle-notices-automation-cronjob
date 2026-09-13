# B0 Separate Review

Status: BLOCKED. Reviewer: `/root/b0_review`, separate from executor
`/root/b0_baseline`; model assignment was not independently observable. UTC
start: `2026-09-08T16:42:53Z`. UTC end: `2026-09-08T16:59:23Z`.
This review performed local reads, public HTTP GETs, and read-only GitHub API
queries only. It made no hosted mutation, workflow dispatch, deployment,
migration, schedule change, source activation, database query, or failure
injection.

## Findings

1. Blocker: the original writer inventory omitted the current deployed GitHub
   Actions shape. Remote `main` is `553c67dcdb593550112470df8c76b0314fae3d4e`,
   all 26 repository workflows are active, and 12 have schedule triggers. The
   candidate's 39-workflow/group registry is not the current scheduled shape.
   Current main scheduled discovery runs execute all-sources, seven named
   non-PNCP source workflows, and PNCP; AI, backfill, and sync are additional
   scheduled writers. AI also follows successful PNCP through `workflow_run`.
   The corrected baseline now separates candidate inventory from remote state.
2. Blocker: current production/staging database identities, deployed A runtime
   processes and scheduler flags, the GitHub secret target match, and API-side
   pending pipeline/source-work/OCR state remain unknown. Public service probes
   and GitHub workflow metadata cannot establish them. This fails B0's
   environment-isolation and complete-current-writer prerequisites.
3. Blocker: the proposed `brde` canary still has no named operator,
   independent reviewer, observation owner, or intended window. Recording each
   role as unassigned is truthful but does not satisfy B0's exact-owner pass
   criterion.
4. High: the original identity table labeled unobserved matches `false`, which
   could be read as a proven mismatch. The corrected table asks whether an
   exact match is proven and states when false means unknown versus the observed
   default-branch SHA mismatch.
5. Medium: the original `SHA256SUMS` entry for mutable `../index.md` did not
   match before review and would be invalidated by every later task update. B0's
   manifest now hashes only its three immutable run-local Markdown artifacts.
   B1's manifest has the same shared-index design and is stale after this B0
   disposition update; B1's owner must correct it separately. No B1-owned
   artifact was edited by this review.
6. Accepted static evidence: both candidate SHAs/PR heads and checks were
   independently re-observed; the candidate registry exactly matches the plan's
   ordered 23 unique keys; source mode, contract, and owner rows match
   `config/source_schedule.json`; cited scenario tests exist; gaps remain
   conservatively labeled partial or missing. No RR is closed and `brde` remains
   an unapproved proposal with all human roles unassigned.
7. Redaction: no credential, connection string, bearer/JWT value, raw claim
   token, personal data, or production dump was found in this evidence tree.
   Public repository/PR/run links, public service hosts, SHAs, and variable
   names are not secret values.

## Point-In-Time Observations

| Observation | Result |
|---|---|
| A candidate | Branch `feature/durable-executor-and-review-hardening`, SHA `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`; draft PR #29 remains open with `backend` and `contract` successful on that head. |
| B candidate | Branch `feature/source-rotation-fairness`, SHA `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`; draft PR #8 remains open with `test` successful on that head. |
| Default branches | A `master` is `d0394d3749c81fee85a224ab10e22448a8d02752`; B `main` is `553c67dcdb593550112470df8c76b0314fae3d4e`. |
| Remote B workflows | 26 repository workflow paths returned; all 26 state `active`. The candidate has 39 local workflow files; 13 are candidate-only. |
| Scheduled B definitions on current main | `pipeline-ai`, `pipeline-all-discovery`, `pipeline-backfill`, FAO, Fundacao Grupo Boticario, GOVBR-MMA, KfW, MSGOV, PNCP, sync, UNEP, and WorldBank. |
| Pending Actions at `2026-09-08T16:44:33Z` | KfW schedule run `34252853146` in progress on B main SHA; zero queued, waiting, requested, or pending runs. State is transient and must be refreshed before transfer. |
| Public production service | `/` returned HTTP 200 with `version=2.0.0`; `/health` returned HTTP 200 healthy. Exact deployed SHA and DB are not exposed. |
| Public staging service | Initial cold `/` timed out; `/health` then returned HTTP 200 healthy and retrying `/` returned HTTP 200 with `version=2.0.0-staging-e9422dc`. Exact full SHA, config, and DB are not proven. |

## Commands And Results

All commands exited 0 unless qualified. Commands printed no secret values.

| Command | Result |
|---|---|
| `git status --short --branch; git rev-parse HEAD; git branch --show-current` in A and B | Candidate branches/SHAs revalidated. B first showed concurrent B1 documentation changes plus the untracked B0 tree. By final verification, concurrent B5 work included 33 modified pipeline workflows, admission/managed-source code, and tests; all were preserved and excluded from B0. |
| `git worktree list --porcelain` and `git -C <literal worktree> status --short --branch` in A/B | All registered worktrees checked. Only B `all-sources-production` had the 10 unrelated changes already qualified by the author. |
| `gh pr view 29 ...` in A and `gh pr view 8 ...` in B | Current draft/open PR base/head/check metadata matched the baseline. |
| `gh api repos/.../actions/workflows --paginate` | Returned 26 B repository workflows, all active. |
| `gh run list --status in_progress|queued|waiting|requested|pending ...` | Produced the timestamped Actions state above. A separate 100-run read showed scheduled executions use B main SHA, not the candidate SHA. |
| `git ls-tree` and `git show origin/main:.github/workflows/<file>` | Counted 26 current-main and 39 candidate workflows and extracted the 12 current-main schedules without checkout or edits. |
| PowerShell parse of `config/source_schedule.json` against the plan's explicit key list | Expected 23, actual 23, unique 23, exact ordered match true, no differences. |
| `curl.exe` public GETs to production/staging `/` and `/health` | Results above. The first staging root GET exited 28 after 60 seconds; later staging health/root GETs exited 0. |
| `rg` sensitive-value patterns over the evidence tree | No match; ripgrep exit 1 was handled as the expected clean result. |
| Markdown relative-link check and `Get-FileHash`/`Get-Content SHA256SUMS` verification | Completed after final edits; local links resolved and all three run-local B0 hashes matched. The mutable shared index is intentionally not in B0's manifest. |

## Disposition And Next Tasks

B0 is not accepted as `PASS`. Missing input: authorized read-only provider/DB
and deployed-runtime observations for both targets, API-side pending work, and
named canary operator/reviewer/observation owner/window. Next action: the
operator must provide those assignments and sanitized identity-match booleans,
or explicitly authorize a read-only operator with suitable access.

B1 evidence correction, B4 local preparation, and B5 design/implementation are
executable without hosted mutation. B2 is executable only against a newly
proved isolated PostgreSQL target. B3 waits for the B2 contract freeze. B6
waits for B2-B5, named operator/reviewer/observation owner, two independent
audits, and explicit staging-mutation authorization.
