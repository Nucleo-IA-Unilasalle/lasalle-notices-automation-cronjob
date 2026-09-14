# P3 Final Writer Drain/Fence Readiness - 2026-09-13T07:35Z

Status: **READY FOR P4 REVIEW; NO PRODUCTION MUTATION EXECUTED**

This record freezes the P3 inputs and assigns the previously open ownership
fields. The executable 25-workflow inventory, guarded commands, reconciliation
queries, stop limits, and B-before-A rollback procedure remain in
[`p3-writer-drain-fence-ledger-2026-09-12T2342Z.md`](p3-writer-drain-fence-ledger-2026-09-12T2342Z.md).

## Frozen Release

| Field | Value |
| --- | --- |
| Repo A candidate | `a5275dae46f223da74dc54d0734051acc66a8a9f` |
| Repo B candidate | `2e0dd74ee64b999318dea4cc1767df4985b384ee` |
| Repo A production before cutover | `d0394d3749c81fee85a224ab10e22448a8d02752` |
| Repo B production before cutover | `553c67dcdb593550112470df8c76b0314fae3d4e` |
| Selected source / contract | `brde` / `candidate` |
| Staffed release window | `2026-09-13T08:00:00Z` through `2026-09-13T10:00:00Z` |
| Accountable production operator | Vitor |
| Repo A/Render, Repo B/GitHub, DB, observation, and rollback owner | Vitor |
| Technical independent reviewer | `/root/p2_review` |
| Authorization | User selected the recommended source, contract, owners, backup route, isolated restore target, and P2-P5 actions in this task. |

Both candidate branches were clean at their code commits and pushed. Repo A PR
29 and Repo B PR 8 are draft with clean merge state. Repo A `backend` and
`contract` checks passed for the frozen A SHA. Repo B `Worker CI` passed for the
frozen B SHA.

## Current Readiness Observations

- At `2026-09-13T07:18:20Z`, Render reported the production API live on
  `master` at the recorded old Repo A SHA. Its admission variables were absent,
  so the candidate fence was not yet installed. Health returned HTTP `200`.
- At `2026-09-13T07:34:57Z`, a production Supabase transaction explicitly set
  `READ ONLY` reported PostgreSQL `17.6`, `transaction_read_only=on`, and no v3
  tables. `pipeline_runs` had only terminal states (`1121 success`, `95 failed`),
  `source_runs` had only terminal states (`86 success`, `33 failed`), and OCR
  claims had only terminal states (`69 completed`, `34 failed`). No payload,
  token, user row, or connection value was read or retained.
- At `2026-09-13T07:35:11Z`, GitHub returned zero queued, waiting, pending, or
  running runs among the 25 inventoried production writer workflow IDs. This is
  a point-in-time readiness observation, not a drain; it must be repeated after
  disabling those workflows and immediately before ownership transfer.
- Candidate recovery ticks remain disabled. The selected BRDE source has only
  group A as its prospective scheduled owner, and every unselected source is
  filtered before runner allocation.

## Accepted Predeployment Evidence

- The exact post-repair P1 harness passed genuine worker termination/recovery,
  submit/finish lost-ACK replay, changed-content replay, poison
  backoff/quarantine, and all quantitative capacity thresholds.
- The migration-specific P2 rehearsal restored the encrypted production
  Supabase public-schema dump, applied the migration twice, checked schema and
  browser-role denial, ran the historical worker as a subprocess, and preserved
  pending work through stop/expiry/resume. Supabase-managed domains are an
  explicit unchanged/out-of-scope exception, not a full-DR claim.
- Two independently prepared post-repair BRDE audits passed with two open FSA
  calls accounted for, six closed FSA calls and the closed Palacete notice
  excluded, and zero blocking fidelity exceptions.

## Authorized P5 Sequence

P4 may authorize only this sequence:

1. Repeat production SHA, CI, Render, database-terminal-state, and GitHub
   open-run preflights. Stop if any identity differs or any writer is active.
2. Apply Repo A's additive v3 migration to production Supabase and verify
   versions, four v3 tables, RLS, ACL revokes, constraints, and indexes. Never
   drop the additive tables during rollback.
3. Set Repo A to closed beta for only `brde` / `candidate`, keep the legacy
   scheduler disabled, merge Repo A PR 29, and wait for Render to deploy the
   exact A SHA.
4. Verify live capabilities, catalog identity, schema, health, strict claim
   enforcement, and legacy-route denial without failure injection or stale
   production writes.
5. Disable the 25 old Repo B writer workflows using the individually enumerated
   IDs in the executable ledger. Re-read and reconcile Actions and terminal API
   states; cancel only an individually reviewed run if a new one appeared.
6. Keep Repo B's allowlist absent/empty, merge Repo B PR 8, verify the exact B
   SHA and default-deny behavior, then set `CLOSED_BETA_SOURCE_ALLOWLIST=brde`.
   Enable/retain only group A as the scheduled owner.
7. Run one bounded BRDE canary, reconcile the two expected current source
   records, candidate/document identities, telemetry, claims, capacity, and
   exact replay. Close admission immediately on any stop condition.

Rollback order is B before A: clear the Repo B allowlist and disable group A,
wait for/reconcile any admitted claim, then clear Repo A's admitted source while
retaining the new server fence and additive schema. Restore only to a new
isolated target under P2; never overwrite newer production data with the dump.

P6 remains time-bound after P5: two real scheduled executions and daily review
precede expansion, followed by the required 48-hour soak and seven-day review.
