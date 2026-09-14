# P4 Release Amendment - 2026-09-14T18:52Z

## Decision

**ACCEPT for the remaining current window, with the exact Repo B head and
default-deny sequence below.** The window remains
`2026-09-14T18:10:00Z` through `2026-09-14T20:10:00Z`; the selected source is
`brde` / `candidate`; `Vitor` remains accountable. Repo A is
`419673a90cfd6feb192d505c6cd9a43d4d9ae251`; Repo B is
`2b91ee58e09a77cb5cd5b9b3760048832ef5aa12`.

No production access or mutation was performed by this reviewer.

## Default-Deny Delta

The `00e0930` default-deny probe correctly started no discovery job but failed
the overall workflow on an empty matrix. The two reviewed fixes first add the
closed-beta sentinel (`edcefab`), then handle an empty allowlist before the
strict source-matrix builder (`2b91ee5`). For an empty allowlist, each group
emits a non-executing sentinel and `admitted=false`; the discover job is
guarded by `admitted == 'true'`. A valid allowlist whose source is outside the
group also becomes a non-executing sentinel. Malformed or nonempty invalid
values still invoke the strict builder and fail closed.

The exact B delta from release head
`00e0930a95bef847faf993cd4064918181d80e1e` to
`2b91ee58e09a77cb5cd5b9b3760048832ef5aa12` changes only the three group
workflow matrices and their static tests. The sentinel cannot reach a worker
because the reusable discovery job requires `admitted == 'true'`. Independent
review accepted the fix; 52 focused tests passed, YAML parse and diff checks
passed, and PR 9 Worker CI passed in 3m8s.

Repo A `419673a...` is live with ACL and fence probes passed. The exact 25 old
writer workflows are disabled, and four individually reviewed runs were
canceled and reconciled. These are operator-collected production observations;
the preactivation identity and active-run checks remain mandatory before any
further action.

## Authorized Remaining P5 Actions

Only the prior P5 sequence, with this B replacement, remains authorized before
`20:10:00Z`:

1. Revalidate live A `419673a...`, B
   `2b91ee58e09a77cb5cd5b9b3760048832ef5aa12`, CI, ACL/fence, authorization,
   backup, pending work, and run reconciliation. Stop on any mismatch or
   active unknown writer.
2. Keep B default-denied and the allowlist empty while deploying/verifying the
   exact B head. Confirm empty and malformed nonempty allowlists do not start
   a discovery job and that only a valid selected source can set admission.
3. Set `CLOSED_BETA_SOURCE_ALLOWLIST=brde`, retain only group A after its
   workflow identity is revalidated, and run one bounded BRDE canary with the
   previously approved reconciliation, telemetry, capacity, and replay checks.

All prior A migration/ACL verification, strict claims, 25-writer fence, stop
limits, and B-before-A rollback requirements remain in force. Stop on any
wrong identity/target/source/contract, missing fence or ACL denial, unexpected
worker, duplicate/lost-pending/stale write, missing auth/SSRF/telemetry,
unreconciled run, or exceeded P1 limit. No other source or contract, failure
injection, broad cancellation, P6 expansion, or destructive restore is
authorized.

Rollback remains B before A: clear B allowlist and disable group A, reconcile
claims, then clear A admission while retaining the fence and additive schema;
use only an isolated P2 target, never an old dump over newer data. Prior refs
remain Repo A `d0394d3749c81fee85a224ab10e22448a8d02752` and Repo B
`553c67dcdb593550112470df8c76b0314fae3d4e`.

**Final sign-off:** `/root/p2_review: ACCEPT 2026-09-14 P4 amendment for A
419673a90cfd6feb192d505c6cd9a43d4d9ae251 and B
2b91ee58e09a77cb5cd5b9b3760048832ef5aa12, default-deny fix reviewed,
brde/candidate, remaining window through 20:10Z, Vitor.`
