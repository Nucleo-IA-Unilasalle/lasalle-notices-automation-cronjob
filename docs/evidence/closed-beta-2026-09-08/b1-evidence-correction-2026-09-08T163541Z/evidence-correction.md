# B1 Evidence Correction

Status: **REVIEW**. Executor: `/root/b1_evidence` (actual session; assigned
model identity was not available to this record). Reviewer: Terra high,
separate session required. UTC start: `2026-09-08T16:35:41Z`; UTC end:
`2026-09-08T16:39:18Z`. This run changed documentation only. No hosted
system, database, allowlist, schedule, deployment, source, or lease state was
mutated.

## Scope and source qualification

The B0 evidence remains `REVIEW`, not `PASS`, and was consumed only for scope
and candidate-head context: [B0 baseline](../b0-baseline-2026-09-08T162840Z/baseline.md),
[B0 scenario map](../b0-baseline-2026-09-08T162840Z/scenario-map.md). The
September 8 continuation and its JSON are historical staging observations, not
new B2 evidence. The original runner output
[`failure_injection_results.json`](../../failure_injection_results.json) is
preserved byte-for-byte as historical output; its `all_probe_gates_passed`
field means only that the runner's narrow assertions passed.

The corrected interpretation is:

| Observation | What the artifact supports | What it does not support |
|---|---|---|
| Unknown source `empraba` returned 404 | Admission exclusion for an unregistered key | Takeover fencing |
| Four claims produced 3x 201 and 1x `capacity_full` 409 | Aggregate admission exclusion at the observed boundary | Stale-owner fencing or cleanup guarantees |
| Beta-style request with a mismatched token returned `claim_missing` 409 | Fabricated/mismatched-token rejection in that request sequence | Rejection of an authentic superseded alpha credential |
| Alpha renewal after its short lease expired returned `claim_expired` 409 | Expiry rejection; a later claim was reclaimable | Genuine alpha-after-beta takeover fencing |
| Release responses and post-probe `due` reads showed no live claims | Observed restoration/best-effort cleanup for this completed run | A general guaranteed-cleanup invariant under process/control-plane failure |

No artifact records the required B2 sequence in which alpha is deterministically
expired, beta reclaims the same source, and alpha then attempts renew, release,
work, checkpoint, candidate, or structured mutation. Therefore no genuine
post-takeover stale-owner fencing claim is made, and no release gate is closed.

## Historical wording corrections

- [`STAGING-CONTINUATION-2026-09-08.md`](../../STAGING-CONTINUATION-2026-09-08.md)
  now names admission exclusion, fabricated-token rejection and expiry
  rejection separately, and explicitly says the beta takeover sequence was not
  exercised.
- [`README.md`](../../README.md) replaces “guaranteed cleanup” with observed
  restoration and best-effort failure semantics.
- The historical JSON and prior detailed report remain retained; they are not
  rewritten as a new run or promoted to an acceptance result.

## Commands and results

All commands were local/read-only except writing this evidence and the two
wording corrections above. Exit codes are recorded explicitly.

| Command | Result |
|---|---|
| `Get-Content plans/source-reliability/AGENTS.md; Get-Content plans/source-reliability/CLOSED-BETA-RELEASE-PLAN-2026-09-08.md; Get-Content HANDOFF-SOURCE-RELIABILITY-CONTINUATION-2026-09-08.md` | Exit 0; applicable contracts and historical continuation read. |
| `Get-Content lasalle-notices-automation-cronjob/AGENTS.md` | Exit 0; Repo B evidence and staging safety contract read. |
| `Get-Content docs/evidence/README.md; Get-Content docs/evidence/STAGING-CONTINUATION-2026-09-08.md; Get-Content docs/evidence/failure_injection_results.json` | Exit 0; historical index, continuation and runner JSON inspected. |
| `git -C lasalle-notices-automation-cronjob status --short` | Exit 0; pre-existing untracked B0 evidence plus this B1 run observed; unrelated changes preserved. |
| `git -C lasalle-notices-automation-cronjob diff --check` | Exit 0; no whitespace errors. |
| Link and redaction scan recorded below | Exit 0; all local Markdown targets resolved and sensitive-pattern scan found no matches in B1 evidence or changed historical Markdown. |

## Validation

Markdown links in the changed files and the B1 report were resolved against
their containing directories with a local PowerShell link-target check: `0`
missing local targets. External GitHub links were syntactically retained and
not fetched. A bounded scan for `Authorization`, bearer tokens, `PIPELINE_SECRET`,
`RENDER_API_KEY`, private-key headers, connection-string credentials, raw claim
tokens, and local absolute paths returned `0` matches in the B1 run and changed
Markdown. This is not a zero-leak guarantee for the entire repository.

## Reviewer handoff and remaining risk

Terra should review the full B1 diff, verify that each historical assertion is
supported by the retained JSON/report, rerun the link and redaction checks, and
keep this run at `REVIEW` unless independently accepted. B2 remains the next
dependency for authentic takeover fencing and zero-side-effect stale mutation
assertions. B0, RR-01 through RR-05, source audits, crash/replay, recoverability,
default-deny admission and production readiness remain open.

### Files changed by B1

- `docs/evidence/README.md`
- `docs/evidence/STAGING-CONTINUATION-2026-09-08.md`
- `docs/evidence/closed-beta-2026-09-08/index.md`
- `docs/evidence/closed-beta-2026-09-08/b1-evidence-correction-2026-09-08T163541Z/evidence-correction.md`
