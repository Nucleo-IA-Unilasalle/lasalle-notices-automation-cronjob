# P4 Refresh Decision - 2026-09-14T18:15Z

## Decision

**ACCEPT for the exact P5 sequence below.** This refresh replaces the prior
P4 window with `2026-09-14T18:10:00Z` through `2026-09-14T20:10:00Z` and
authorizes the actual Repo B release head
`00e0930a95bef847faf993cd4064918181d80e1e`.

- Independent reviewer: `/root/p2_review`
- Accountable operator, observer, and rollback owner: `Vitor`
- Selected source and contract: `brde` / `candidate`
- Production access or mutation by this reviewer: none

This is P4 approval only. It is not evidence that P5 has executed and does
not authorize P6 expansion, another source or contract class, full Supabase
platform disaster recovery, or any action outside the listed sequence.

## Identity And Refresh Review

The exact A range reviewed remains
`d0394d3749c81fee85a224ab10e22448a8d02752..a5275dae46f223da74dc54d0734051acc66a8a9f`.
The exact B range previously reviewed remains
`553c67dcdb593550112470df8c76b0314fae3d4e..2e0dd74ee64b999318dea4cc1767df4985b384ee`.
The new B release-head delta
`2e0dd74ee64b999318dea4cc1767df4985b384ee..00e0930a95bef847faf993cd4064918181d80e1e`
was inspected and is documentation/evidence only under `docs/`; it changes
no worker or selector code. Therefore the previously reviewed B code SHA
remains the executable code identity, while `00e0930...` is the exact release
head that must be verified after merge/deployment.

The refreshed P3 record
`p3-refresh-2026-09-14T1811Z.md` records a PASS and no production mutation:

- Render still served old Repo A `d0394d...`, health `200`, with scheduler
  disabled and candidate admission keys absent.
- Both PRs were clean; Repo A PR 29 retained its successful checks and Repo B
  PR 8 at `00e0930...` had `Worker CI` pass at `2026-09-14T18:07:39Z`.
- The exact 25 old writer workflow IDs had zero queued, waiting, pending,
  requested, or running runs in the latest 100-run observation.
- The operator-collected Supabase observation was read-only:
  PostgreSQL `17.6`, `transaction_read_only=on`, all four v3 tables absent,
  and only terminal states in existing run/claim tables. No payload, token,
  user row, or connection value was retained.

These are point-in-time observations and are required to be repeated in P5
step 1 immediately before any mutation.

## Gate Acceptance

P0 is accepted from the frozen SHAs, named ownership, selected source/window,
corrected evidence index, and the complete 25-workflow inventory and guarded
commands in `p3-writer-drain-fence-ledger-2026-09-12T2342Z.md`.

P1 is accepted from the post-repair real API/worker subprocess harness:
termination and successor recovery, lost submit/finish ACK replay,
changed-content replay, poison backoff/quarantine, aggregate cap, and all
quantitative capacity limits passed with no skipped scenario on disposable
loopback PostgreSQL. Recorded capacity was 0 5xx/timeouts, warm p95
`31.91 ms`, database `5/97`, storage headroom `99.09%`, and service rate
`41,437/hour` versus `22/hour` arrival.

P2 is accepted as migration-specific for this additive public-schema release
by `p2-recoverability-20260913T070433Z/`. It proves encrypted restore to an
isolated PostgreSQL 17 target, repeat-safe migration, counts/schema/
constraints/indexes/extensions, RLS and browser-role denial, admission stop,
pending resume, historical-worker subprocess replay, timings/exit codes, and
cleanup/redaction. The authorized `pg_dump` session's
`transaction_read_only=off` is disclosed accurately and is not a read-only
role claim. Supabase-managed Auth, Storage, Realtime, webhooks, provider
configuration, non-public schemas, managed roles, and platform metadata remain
an explicit out-of-scope exception; no full-platform DR claim is made.

P3 is accepted from the refreshed record above and the unchanged executable
ledger. The candidate fence, held-source filtering, disabled recovery ticks,
25 exact writer actions, stop limits, and B-before-A rollback remain unchanged.

The two post-repair BRDE audit bundles remain qualifying and were run against
the unchanged executable B code SHA `2e0dd74...`:

- `docs/evidence/sources/brde/production-candidate-audit-repair-1/` passed
  with two open FSA records accounted for, six closed FSA records and the
  closed Palacete section excluded, fidelity exit `0`, and zero blockers.
- `docs/evidence/sources/brde/production-candidate-audit-repair-2/` passed
  with the same two candidates, six closed details, one closed Palacete
  section, zero errors/partial inventory, fidelity exit `0`, and `36 passed`.

Both audits independently validate host, lifecycle, deadline, bounded URL,
principal-document, and selector behavior. Since the new B delta is evidence
only, no source-code requalification is required for `00e0930...`; the release
head still requires the exact post-merge SHA verification below.

## Authorized P5 Sequence

Only these actions are authorized, in order, within the stated window:

1. Revalidate target identity, A `a5275dae...`, B
   `00e0930a95bef847faf993cd4064918181d80e1e`, current CI, authorization,
   backup reference, active/pending work, stop limits, and Vitor's rollback
   ownership. Stop on any identity change or active writer.
2. Apply only Repo A's additive v3 migration and verify versions, four v3
   tables, RLS, ACL revokes, constraints, and indexes. Never drop additive
   tables during rollback.
3. Configure Repo A closed beta for only `brde` / `candidate`, keep the legacy
   scheduler disabled, merge PR 29, and wait for Render to run exact A SHA.
4. Verify live capabilities, catalog identity, schema, health, strict claims,
   and legacy-route denial. Do not use failure injection or stale writes.
5. Disable only the 25 individually enumerated old Repo B writer workflows in
   the ledger, reconcile Actions and terminal API states, and cancel only a
   newly appeared run after individual operator review.
6. Keep B default-denied and its allowlist empty, merge PR 8 at the approved
   release head, verify the exact B SHA `00e0930...` and default-deny behavior,
   then set `CLOSED_BETA_SOURCE_ALLOWLIST=brde` and enable/retain only group A
   after its post-merge workflow identity is revalidated.
7. Run one bounded BRDE canary and reconcile the two expected current source
   records, candidate/document identities, telemetry, claims, capacity, and
   unchanged replay. Close admission immediately on any stop condition.

## Stop And Rollback Limits

Stop on wrong SHA/target/source/contract, missing or ambiguous fence,
missing authentication/SSRF protection/telemetry, active old or unknown
overlapping writer, stale acceptance, duplicate logical record, lost pending
work, changed user-owned field, unexpected source, unreconcilable claim/run,
or unavailable quantitative limit. P1 limits remain API 5xx/timeout below 1%,
warm p95 at or below 1 second, database at or below 70%, storage headroom at
or above 20%, and service capacity at least 1.25 times arrival. On stop,
close admission, preserve evidence, fence safely, reconcile, and do not use an
unreviewed destructive restore.

Rollback is B before A only: clear the B allowlist and disable group A; wait
for and reconcile admitted claims; then clear A's admitted source while
retaining the server fence and additive schema. If recovery is required, use a
new isolated P2 target, never an old dump over newer production data. Prior
refs are Repo B `553c67dcdb593550112470df8c76b0314fae3d4e` and Repo A
`d0394d3749c81fee85a224ab10e22448a8d02752`.

RR-01 through RR-05 remain open for all-source capacity/soak, production
overlap/recovery, collect/drain split, group/PNCP overlap, and unselected
source audits. They are not blockers for this one-source BRDE canary, but no
expansion is authorized until separately evidenced.

## Sanitization And Sign-Off

The B release-head delta contains evidence/docs only. A filename-only scan of
the P1-P4 and BRDE evidence roots returned `filename_secret_hits=0`; no
obvious secret value, raw token, credential, connection string, dump, or
private log is retained in the sanitized evidence.

**Final sign-off:** `/root/p2_review: ACCEPT 2026-09-14 for refreshed P4,
Repo B release head 00e0930a95bef847faf993cd4064918181d80e1e, brde/candidate,
window 18:10Z-20:10Z, Vitor accountable.`
