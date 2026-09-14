# P4 Release Amendment - 2026-09-14T18:23Z

## Decision

**ACCEPT with a mandatory ACL-repair gate before deployment.** This amendment
keeps the staffed window `2026-09-14T18:10:00Z` through
`2026-09-14T20:10:00Z`, selected `brde` / `candidate`, and accountable
operator `Vitor`. It replaces the Repo A release SHA with
`419673a90cfd6feb192d505c6cd9a43d4d9ae251`; Repo B remains release head
`00e0930a95bef847faf993cd4064918181d80e1e`.

No production access or mutation was performed by this reviewer.

## Security Stop And Repair Review

The first additive migration succeeded, but its post-check found default
`anon`/`authenticated` grants on the three new empty work tables despite RLS.
No Repo A application or Repo B worker was deployed. Those grants are not an
acceptable final state, so the operator must run the corrected migration from
Repo A `419673a...` and verify ACL denial on all four internal tables before
any API deployment or worker activation. If any grant remains, stop, preserve
evidence, and do not continue.

The exact Repo A patch
`a5275dae46f223da74dc54d0734051acc66a8a9f..419673a90cfd6feb192d505c6cd9a43d4d9ae251`
was reviewed. It adds a hardcoded four-table internal allowlist and a helper
that re-enables RLS, revokes `PUBLIC`, and conditionally revokes `anon` and
`authenticated` on every migration run, including an already-versioned
database. The focused independent review reports `5` focused tests and `39`
configuration tests passed; the A `backend` and `contract` checks passed.
Identifiers are fixed constants, not caller input. The separate repair
transaction is safe and idempotent, but a failed repair must be retried and
must not be followed by deployment without the privilege probe.

The Repo B delta from executable code SHA
`2e0dd74ee64b999318dea4cc1767df4985b384ee` to release head `00e0930...` is
committed P1-P4 and BRDE documentation/evidence only; no worker or selector
code changed. The existing P1, migration-specific P2, P3 refresh, and two
post-repair BRDE audits therefore remain applicable after the A patch.

## Authorized Amendment

Only the prior P5 sequence, amended as follows, is authorized in the stated
window:

1. Revalidate target identity, A `419673a...`, B `00e0930...`, CI,
   authorization, backup, active/pending work, stop limits, and rollback owner.
2. Run the corrected A additive migration/reassertion. Verify migration
   versions, four v3 tables, RLS, and `PUBLIC`/`anon`/`authenticated` ACL
   denial on all four internal tables. This verification is a hard gate.
3. Only after step 2 passes, deploy A closed-beta for `brde` / `candidate`,
   verify the exact A SHA, capabilities, schema, strict claims, health, and
   legacy-route denial, then perform the existing exact 25-writer drain/fence.
4. Keep B default-denied, deploy/verify exact B release head
   `00e0930...`, then set `CLOSED_BETA_SOURCE_ALLOWLIST=brde`, retain only
   group A, and run one bounded BRDE canary with the existing reconciliation.

No stale writes, failure injection, broad cancellation, other source, other
contract, P6 expansion, or destructive rollback is authorized. Immediate
stops remain wrong identity/target/source/contract, any missing ACL or fence,
active overlapping writer, stale/duplicate/lost-pending/user-field change,
missing auth/SSRF/telemetry, unreconcilable run, or exceeded P1 limits.

Rollback remains B before A: clear B allowlist and disable group A, reconcile
claims, then clear A admission while retaining the fence and additive schema;
use only an isolated P2 target, never an old dump over newer data. Prior refs
remain Repo A `d0394d3749c81fee85a224ab10e22448a8d02752` and Repo B
`553c67dcdb593550112470df8c76b0314fae3d4e`.

**Final sign-off:** `/root/p2_review: ACCEPT 2026-09-14 P4 amendment for A
419673a90cfd6feb192d505c6cd9a43d4d9ae251 and B
00e0930a95bef847faf993cd4064918181d80e1e, contingent on successful ACL
repair/probe before deployment, brde/candidate, 18:10Z-20:10Z, Vitor.`
