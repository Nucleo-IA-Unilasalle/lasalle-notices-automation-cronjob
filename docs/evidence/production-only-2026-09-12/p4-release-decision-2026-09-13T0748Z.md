# P4 Independent Release Decision - 2026-09-13T07:48Z

## Decision

**ACCEPT for migration-specific P4 and only the enumerated P5 sequence below.**

- Independent reviewer: `/root/p2_review`
- Accountable production operator: `Vitor`
- Selected source and contract: `brde` / `candidate`
- Authorized window: `2026-09-13T08:00:00Z` through `2026-09-13T10:00:00Z`
- Production access or mutation by this reviewer: none

This is an independent P4 approval record. It is not evidence that P5 has
executed, and it does not authorize P6 expansion, a full Supabase disaster
recovery claim, another source, or another contract class.

## Frozen Identities And Scope

I reviewed the exact candidate ranges
`d0394d3749c81fee85a224ab10e22448a8d02752..a5275dae46f223da74dc54d0734051acc66a8a9f`
in Repo A and
`553c67dcdb593550112470df8c76b0314fae3d4e..2e0dd74ee64b999318dea4cc1767df4985b384ee`
in Repo B as specified by the release task.

| Item | Frozen value |
| --- | --- |
| Repo A candidate / rollback ref | `a5275dae46f223da74dc54d0734051acc66a8a9f` / `d0394d3749c81fee85a224ab10e22448a8d02752` |
| Repo B candidate / rollback ref | `2e0dd74ee64b999318dea4cc1767df4985b384ee` / `553c67dcdb593550112470df8c76b0314fae3d4e` |
| PR and checks | Repo A PR 29: draft, clean; `backend` and `contract` passed at approximately 01:20Z-01:21Z. Repo B PR 8: draft, clean; `Worker CI` passed at 07:16:54Z. |
| Source and contract | `brde` / `candidate` only |
| Ownership | Vitor owns Repo A/Render, Repo B/GitHub, database, observation, and rollback |
| Backup reference | P2 bundle `p2-recoverability-20260913T070433Z`; encrypted archive SHA-256 `B81F5E30C5C304942B3A3CBE35436286BBF089D4E10EAC8A5F849ADD2020DA6B`; private location and credentials are intentionally withheld |
| Legacy writers | Exactly the 25 old Repo B writer workflow IDs enumerated in the P3 executable ledger; no unreviewed mass cancellation is authorized |

The P3 final readiness record
(`p3-final-readiness-2026-09-13T0735Z.md`) is authoritative for these frozen
values. Its older point-in-time production observations must be repeated in
P5 step 1; they are not being treated as a drain or as a future guarantee.

## Gate Review

P0 is satisfied by the exact SHA freeze, selected source, named Vitor owner,
independent reviewer, window, corrected evidence index, and the complete
legacy-writer inventory in
`p3-writer-drain-fence-ledger-2026-09-12T2342Z.md`.

P1 is satisfied by
`p1-brde-postrepair-20260913T071540Z/p1-isolated-harness.json`: status `pass`,
no skipped scenarios, a real API and worker subprocess, termination and
successor recovery, submit and finish lost-ACK replay, changed-content replay,
poison backoff/quarantine, aggregate claim cap, and quantitative capacity
gates. The recorded measurements include 51 requests with zero 5xx/timeouts,
warm p95 `31.91 ms`, peak database connections `5/97`, storage headroom
`99.09%`, service throughput `41,437/hour` versus `22/hour` arrival, and RSS
`36 MB`. The harness target was loopback-only disposable PostgreSQL and was
dropped after the run.

P2 is accepted as migration-specific for this additive public-schema release
by the signed bundle in
`p2-recoverability-20260913T070433Z/`. It proves encrypted-backup restore to
an isolated PostgreSQL 17 target, repeat-safe additive migration, counts and
schema/constraints/indexes/extensions, RLS and browser-role denials, admission
stop, expired-claim and pending-work resume, compatible historical Repo B
worker subprocess replay, exit codes and timings, and cleanup/redaction. The
source session's `transaction_read_only=off` is accurately disclosed as an
authorized non-mutating `pg_dump`, not as a read-only role. Supabase-managed
Auth, Storage, Realtime, webhooks, provider configuration, non-public schemas,
managed roles, and platform metadata are an explicit unchanged/out-of-scope
exception; this is not a full platform DR claim.

P3 is satisfied by the final readiness record and executable ledger. The
candidate server-side fence was proved in isolated tests, all 25 old writer
workflow IDs have individually enumerated guarded actions, recovery ticks are
disabled, only group A is prospective for the selected source, and held
sources are filtered before allocation. No production mutation was used to
pass P3.

The two qualifying BRDE audits are:

- `docs/evidence/sources/brde/production-candidate-audit-repair-1/`: independent official
  captures before adapter execution; 2 open FSA records accounted for, 6
  closed FSA records and the closed Palacete section excluded; fidelity exit
  0 and zero blocking exceptions.
- `docs/evidence/sources/brde/production-candidate-audit-repair-2/`: independently prepared
  official captures and adapter run; 2 candidates, 2 open details, 6 closed
  details, one closed Palacete section, zero errors/partial inventory, fidelity
  exit 0, and focused suite `36 passed in 12.46s`.

The two audits agree on the two current open FSA principals and emit no closed
FSA or Palacete document. The repaired selector's host, lifecycle, deadline,
bounded URL normalization, and principal-document checks were reviewed against
the exact Repo B candidate. The first retained audit has an unresolved
per-bundle reviewer placeholder, but its independently prepared evidence is
complete; this P4 record is the required independent review and acceptance of
the pair, while audit slot 2 is separately signed.

The superseded B4 safety criteria are met for this selected migration-specific
scope without reducing their safety standard. The historical diagnostics and
failed pre-repair BRDE artifacts remain diagnostic and are not used as passes.

The code review found no P4-blocking regression in the reviewed ranges. Repo A
enforces closed-beta source/contract identity and strict claim ownership,
fail-closed admission, bounded redirect/DNS/URL handling, and additive
versioned schema security. Repo B defaults to deny, binds the selected source,
and the repaired BRDE selector enforces official-host, lifecycle, deadline,
principal-document, and bounded URL rules. The post-repair regression suites
cover the malformed host/URL, closed Palacete, missing lifecycle, future and
deadline, replay, and denial cases.

## Authorized P5 Actions

Only these actions are authorized, in order, during the exact window above:

1. Revalidate target identity, frozen A/B SHAs, current CI, authorization,
   backup reference, active and pending work, stop limits, and rollback owner.
   Stop on any identity change or active writer.
2. Apply only Repo A's additive v3 migration and verify migration versions,
   the four v3 tables, RLS, ACL revokes, constraints, and indexes. Never drop
   the additive tables during rollback.
3. Configure Repo A closed beta for only `brde` / `candidate`, keep the legacy
   scheduler disabled, merge PR 29, and wait for Render to run the exact A
   SHA.
4. Verify live capabilities, catalog identity, schema, health, strict claims,
   and legacy-route denial. Do not perform failure injection or stale writes.
5. Disable only the 25 individually enumerated old Repo B writer workflows in
   the P3 ledger, reconcile Actions and terminal API states, and cancel only a
   newly appeared run after individual operator review.
6. Keep Repo B default-denied and its allowlist empty, merge PR 8, verify the
   exact B SHA and default-deny behavior, then set
   `CLOSED_BETA_SOURCE_ALLOWLIST=brde` and enable/retain only group A after
   its post-merge workflow identity is revalidated.
7. Run one bounded BRDE canary. Reconcile the two expected current source
   records, candidate/document identities, telemetry, claims, capacity, and
   unchanged replay. Close admission immediately on any stop condition.

## Stops And Rollback

Immediate stops include wrong SHA, target, source, or contract; missing or
ambiguous fence; missing authentication, SSRF protection, or telemetry; any
active old/unknown overlapping writer; stale acceptance, duplicate logical
record, lost pending work, changed user-owned field, unexpected source,
unreconcilable claim/run, or unavailable quantitative limit. The P1 limits are
API 5xx/timeout rate below 1%, warm p95 at or below 1 second, database usage at
or below 70%, storage headroom at or above 20%, and service capacity at least
1.25 times arrival. On a stop, close new admission, preserve evidence, fence
safely, reconcile, and do not attempt an unreviewed destructive restore.

Rollback is B before A only: clear the B allowlist and disable group A; wait
for and reconcile any admitted claim; then clear A's admitted source while
retaining the server fence and additive schema. Restore only to a new isolated
P2 target if separately required, never by overwriting newer production data
with an old dump. The prior refs are Repo B
`553c67dcdb593550112470df8c76b0314fae3d4e` and Repo A
`d0394d3749c81fee85a224ab10e22448a8d02752`.

RR-01 through RR-05 remain open for the broader program: all-source hourly
capacity and 48-hour evidence, production overlap/recovery, collect/drain
split, group/PNCP overlap/recovery, and audits for unselected sources. They
are not blockers for this single-source BRDE P5 canary, but they prohibit
expansion until separately evidenced. P6 remains gated on two real scheduled
executions, daily review, the required soak, and the corresponding decisions.

## Sanitization

A filename-only scan over the new P1-P4 and post-repair BRDE evidence roots
returned `filename_secret_hits=0`. No obvious secret value, raw token,
credential, connection string, dump, or private log is retained in the
sanitized evidence; private backup material remains outside this public bundle.

**Final sign-off:** `/root/p2_review: ACCEPT 2026-09-13 for P4, selected
brde/candidate, exact P5 window 08:00Z-10:00Z, Vitor accountable.`
