# B0 Baseline And Release Scope

Status: BLOCKED. UTC start: `2026-09-08T16:28:40Z`. UTC end:
`2026-09-08T16:33:12Z`. Scope is local repository inspection and documentation only;
no hosted mutation, deployment, migration, schedule change, source activation,
or failure injection was performed. A separate read-only review ran from
`2026-09-08T16:42:53Z` through the UTC end recorded in [review.md](review.md).

## Candidate Repositories

| Repository | Candidate branch | Full HEAD | Working tree at observation | Pull request and checks |
|---|---|---|---|---|
| A: `lasalle-notices-automation` | `feature/durable-executor-and-review-hardening` | `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693` | clean | Draft open PR [#29](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation/pull/29), base `master` `d0394d3749c81fee85a224ab10e22448a8d02752`; `backend` and `contract` passed on this observed head on 2026-09-07. Not final-candidate evidence. |
| B: `lasalle-notices-automation-cronjob` | `feature/source-rotation-fairness` | `4211ddf6c99fa4b527f09ff3cad4f86996a1092c` | clean before B0 evidence additions; see qualification below for concurrent documentation edits observed during review | Draft open PR [#8](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/pull/8), base `main` `553c67dcdb593550112470df8c76b0314fae3d4e`; `Worker CI / test` passed on this observed head on 2026-09-08. Not final-candidate evidence. |

The only B changes in this run are this evidence index and B0 documentation.
No source-code or workflow behavior changed.

During the separate review, B also showed concurrent modifications to
`docs/evidence/README.md` and `docs/evidence/STAGING-CONTINUATION-2026-09-08.md`.
They are not attributed to B0, were not reverted, and are excluded from this
run's claims.

## Worktree Qualification

Sibling worktrees were inspected without modification. A's `cnpq-prod` and all
listed B worktrees except one were clean. B worktree
`_worktrees/all-sources-production` was dirty with 10 unrelated changes:
`.github/workflows/pipeline-all-discovery.yml`, `README.md`,
`docs/OPERATIONS.md`, `scripts/discover_all_candidates.py`,
`scripts/discover_dopa_opportunities.py`, `tests/conftest.py`,
`tests/test_discover_all_candidates.py`, `tests/test_dopa_discovery.py`, and
untracked `.github/workflows/pipeline-structured-sources.yml` plus
`tests/test_structured_sources_workflow.py`. Those changes were not read as
candidate behavior, moved, reset, or edited.

## Target And Environment Identity

The author made no current hosted query. The separate reviewer used only public
HTTP GETs and read-only GitHub metadata; no secret value, authenticated API/DB
query, or hosted mutation was used. `Match proven` is deliberately false when
the available observation cannot establish the exact full deployed identity;
it does not assert a mismatch unless the basis says so.

| Identity assertion | Match proven | Basis and qualification |
|---|---:|---|
| Current production A service matches A candidate SHA | false | Public `/` returned `version=2.0.0` and `/health` returned healthy on 2026-09-08; that version does not encode a commit, so exact SHA remains unknown. |
| Current staging A service matches A candidate SHA | false | Public staging `/` returned `version=2.0.0-staging-e9422dc` and `/health` returned healthy. The short label is consistent with the candidate prefix but does not prove the full deployed SHA or runtime configuration. |
| Current scheduled B ref matches B candidate SHA | false | Read-only GitHub metadata showed schedules executing `main` at `553c67dcdb593550112470df8c76b0314fae3d4e`, not candidate `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`. |
| Current staging service namespace is distinct from production | true | Public probes used distinct documented hosts and returned different version labels. This proves neither provider configuration nor database isolation. |
| Current staging DB is distinct from production | false | No current authenticated DB/provider identity query was performed. |
| Static failure-injection target is the documented staging URL | true | `scripts/run_staging_failure_injection.py` hard-codes the staging URL and has a staging-only acknowledgement guard. It was not executed. |
| Local worker environment can identify a hosted target | false | B has no local `.env` or `RENDER_APP_URL`/`PIPELINE_SECRET` environment variable. |
| Local API environment proves a hosted target | false | A's local `.env` exists but no target values were read or used; process environment lacks `DATABASE_URL`, `RENDER_APP_URL`, and `PIPELINE_SECRET`. |

Historical-only observations remain qualified: B's September 8 documents name
a free staging service/DB, schema v3, compatible claim enforcement, and a past
staging API version. They neither identify the current target nor prove
production migration, backup/restore, genuine stale-owner mutation rejection,
or source readiness.

## Writer And Job Inventory

Candidate B contains 39 workflows. Its scheduled paths are the three canonical
group discovery workflows, PNCP discovery, AI, legacy backfill, sync, source
monitor, and catalog parity. Recovery ticks are configured but disabled for
groups A/B/C and PNCP. The monitor is read-only; catalog parity does not ingest.

The separate review established that remote `main` still differs materially:
all 26 repository workflows returned by the GitHub Actions API were active.
Twelve have schedules: all-sources, FAO, Fundacao Grupo Boticario, GOVBR-MMA,
KfW, MSGOV, PNCP, UNEP, WorldBank, AI, backfill, and sync. AI also has a
`workflow_run` trigger after PNCP. The other active writer workflows remain
manually dispatchable. At `2026-09-08T16:44:33Z`, KfW run `34252853146` was in
progress on `main` SHA `553c67dcdb593550112470df8c76b0314fae3d4e` and no run
was queued, waiting, requested, or pending. This is a point-in-time observation,
not a drain or disable action. API-side jobs and Render processes remain unknown.

| Path category | Candidate inventory | Current remote/queue state |
|---|---|---|
| Canonical scheduled discovery writers | `pipeline-discovery-group-a.yml`, `pipeline-discovery-group-b.yml`, `pipeline-discovery-group-c.yml`, `pipeline-pncp-discovery.yml`; all route collection through `run_managed_source.py`/the reusable single-source job | Candidate group workflows do not exist on current `main`. Current active schedules are the nine discovery paths named above and run default-branch code. |
| Scheduled legacy/control writers | `pipeline-backfill.yml`, `pipeline-sync.yml`, and `pipeline-ai.yml`; AI mutates accepted records and can run both hourly and after PNCP | All three workflows are active remotely; current target secret and API-side run state were not inspected. |
| Manual discovery/backfill writers | `pipeline-all-discovery.yml`; 22 `pipeline-*-discovery.yml` fallbacks; direct `pipeline-discovery-source.yml` dispatch; `pipeline-pncp-backfill.yml`; `pipeline-ocr.yml`; legacy `pipeline-ingest.yml`, `pipeline-run.yml`, `pipeline-scrape.yml` | Every corresponding workflow present on `main` is active/dispatchable. The candidate-only source/reusable paths are not deployed. No dispatch was made. B5 must prove default-deny on each relevant route. |
| Read-only/control workflows | `pipeline-source-monitor.yml`, `source-catalog-parity.yml`, and `ci.yml` | Monitor and parity are candidate-only and not active on current `main`; CI is active. They are not proof that discovery is healthy. |
| API-side writers | A executor process; legacy scheduler jobs for scrape, sync, AI, OCR, purge, source-run sweep, and retention; trigger endpoints for scrape, sync, AI, OCR, backfill, ingest, purge, and full run; candidate/opportunity/source-work/OCR mutation routes | Local source paths identified; deployed scheduler flags, executor process identity, `pipeline_runs`, source-work backlog, OCR claims, and other pending API-side work are unknown. |

No path above is treated as inactive merely because its local workflow is
manual-only or a registry source is `paused`/`audit`.

## Python And Isolation Baseline

`py -3.13 --version` returned `Python 3.13.5`. `python --version` returned
`Python 3.11.15`; B's DOX-required test command therefore needs the explicit
`py -3.13` launcher. No old isolated database was assumed available and no
test database was created or mutated. Before B2/B3/B4 test mutation, the
executor must create and prove an isolated PostgreSQL target distinct from
production and staging unless staging mutation is separately authorized.

## First Canary Proposal And Ownership

Proposed candidate only: `brde`, candidate contract, registry owner
`pipeline-discovery-group-a.yml`, 60-minute cadence. It is selected for review
because it is explicitly listed as a candidate in the release plan and uses the
required candidate contract; it is not approved based on `ingest` mode.

| Role | Assignment |
|---|---|
| Named operator | Unassigned; operator must designate before B6. |
| Independent reviewer | Unassigned; must be separate from the audit executor. |
| Observation owner | Unassigned; must be named before B6 alert and daily-fallback checks. |
| Intended window | Unscheduled. Earliest only after B2-B5 are reviewed, two independent BRDE audits pass, frozen B6 staging evidence exists, B7 accepts the exact SHA, and the operator authorizes source/window/rollback. |

## Complete 23-Source Scope

All status values below are release-scope holds, not production health. `B6
owner` means the future named B6 audit/observation owner, currently unassigned.
Evidence is deliberately `none` until independently grounded audits and the
applicable B2-B6 evidence exist.

| Key | Registry mode | Contract | Registry owner | Beta treatment | B6 owner | Evidence | Status |
|---|---|---|---|---|---|---|---|
| bndes | ingest | candidate | group-a | Candidate for review | Unassigned | None | HOLD |
| brde | ingest | candidate | group-a | Proposed candidate only | Unassigned | None | HOLD / proposed |
| fao | ingest | candidate | group-a | Later approved wave only | Unassigned | None | HOLD |
| fapergs | ingest | candidate | group-a | Later approved wave only | Unassigned | None | HOLD |
| govbr_mma_fnma | audit | candidate | group-a | Preserve audit hold | Unassigned | None | HOLD |
| iis_rio | ingest | candidate | group-a | Later approved wave only | Unassigned | None | HOLD |
| canoas | paused | opportunity | group-a | Preserve hold | Unassigned | None | HOLD |
| funbio | audit | opportunity | group-b | Preserve structured gate | Unassigned | None | HOLD |
| fundacao_grupo_boticario | ingest | candidate | group-b | Later approved wave only | Unassigned | None | HOLD |
| govbr_mma | ingest | candidate | group-b | Later approved wave only | Unassigned | None | HOLD |
| govbr_mma_public_calls | audit | candidate | group-b | Preserve audit hold | Unassigned | None | HOLD |
| sema_rs | ingest | candidate | group-b | Later approved wave only | Unassigned | None | HOLD |
| tnc | audit | opportunity | group-b | Preserve structured gate | Unassigned | None | HOLD |
| dopa | paused | opportunity | group-b | Preserve hold | Unassigned | None | HOLD |
| kfw | ingest | candidate | group-c | Later approved wave only | Unassigned | None | HOLD |
| msgov | ingest | candidate | group-c | Later approved wave only | Unassigned | None | HOLD |
| unep | audit | candidate | group-c | Preserve audit hold | Unassigned | None | HOLD |
| worldbank | ingest | candidate | group-c | Later approved wave only | Unassigned | None | HOLD |
| wwf | ingest | candidate | group-c | Later approved wave only | Unassigned | None | HOLD |
| fbds | paused | opportunity | group-c | Preserve hold | Unassigned | None | HOLD |
| finep | paused | opportunity | group-c | Preserve hold | Unassigned | None | HOLD |
| ibama | paused | opportunity | group-c | Preserve hold | Unassigned | None | HOLD |
| pncp | ingest | candidate | PNCP discovery | Later wave; checkpoint/overlap gate | Unassigned | None | HOLD |

The nine historical archive identities remain outside activation scope. Their
current deployed configuration was not inferred from the 23-key registry.

## Commands And Results

All commands below exited `0` unless stated otherwise; no command mutates a
hosted target.

| Command | Result |
|---|---|
| `git status --short; git rev-parse HEAD; git branch --show-current; git worktree list --porcelain` in A and B | Resolved the two full candidate heads, branches, clean initial trees, and registered worktrees. |
| `gh pr view ... --json ...; gh pr checks ...` for A #29 and B #8 | Read-only PR metadata/checks recorded above. |
| `py -3.13 --version; python --version` | Python 3.13.5 via `py`; default `python` is 3.11.15. |
| Static `rg` inventory of A tests/services and B tests/scripts/config/workflows | Located existing coverage and every local workflow path; see scenario map. |
| Redacted `.env`/process-environment presence checks | Established only variable/file presence, never values. |
| Workflow scan and `config/source_schedule.json` parse | Counted 39 workflows and 23 registry sources; identified owners and disabled recovery ticks. |
| Reviewer `gh api .../actions/workflows`; `gh run list --status ...`; `git show origin/main:.github/workflows/...` | Observed 26/26 remote repository workflows active, 12 scheduled writer definitions, current default-branch execution, and the point-in-time pending Actions state. |
| Reviewer public `curl` GETs to production/staging `/` and `/health` | Observed only public version/health fields; no authenticated endpoint or mutation. One initial staging `/` request timed out during wake-up, then `/health` and the retried `/` returned 200. |
| Reviewer 23-key comparison and redaction scan | Exact ordered scope matched, with 23 unique keys; no credential, connection-string, bearer-token, JWT, or raw claim-token value pattern was found. |

## Blockers, Risks, And Next Dependencies

- The separate review is complete, but B0 cannot PASS until the operator
  provides or authorizes current read-only provider/DB identities for
  production and staging, the deployed A process/scheduler/executor flags, the
  GitHub secret target match without revealing its value, and API-side pending
  pipeline/source-work/OCR jobs. GitHub workflow state alone is insufficient.
- The named canary operator, independent reviewer, observation owner, and
  intended window remain unassigned, so B0's exact-owner criterion is not met.
- Existing tests cover portions of B2-B5 but do not constitute the required
  real-worker crash/replay harness, genuine staging takeover, backup/restore,
  default-deny admission proof, two independent audits, or staging visibility.
- Candidate heads are draft PRs; observed checks become stale on later commits.
- Next executable work after review: B1, B4 preparation, and B5 may begin;
  B2 may begin in a proven isolated PostgreSQL environment. B3 remains blocked
  on the B2 contract freeze. B6 remains blocked on B2-B5, named ownership, and
  explicit staging authorization.

## Separate Review

The findings, exact review commands, exit-code qualifications, redaction result,
and disposition are recorded in [review.md](review.md). The reviewer accepted
the 23-key scope and scenario map as a conservative static inventory, corrected
the omitted current GitHub writer state, and did not accept B0 as `PASS`.
