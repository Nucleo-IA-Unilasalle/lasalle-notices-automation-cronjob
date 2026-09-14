# P5 Production Cutover And BRDE Canary - 2026-09-14

## Decision

**CANARY AND REPLAY PASS; P5 SCHEDULED-EXECUTION CONDITION PENDING.** The
P4-authorized `brde` / `candidate` production cutover and bounded manual canary
completed inside the `2026-09-14T18:10:00Z` through `20:10:00Z` window. Repo A
`419673a90cfd6feb192d505c6cd9a43d4d9ae251` and executable Repo B
`2b91ee58e09a77cb5cd5b9b3760048832ef5aa12` are the production identities.
Vitor is the accountable operator, observer, and rollback owner.

This record does not close P5. The cutover plan requires two actual scheduled
executions before P5 closes and P6 begins. P6 then requires the 48-hour soak
and seven-day operating review. No source other than BRDE and no contract other
than `candidate` is authorized.

## Target And Migration

- Render service `lasalle-notices-api` deploy `dep-dak3tc61egvs739fb4i0`
  became live at `2026-09-14T18:38:58Z` from exact Repo A SHA `419673a...`.
  The first deploy of that SHA used stale build cache and served the previous
  runtime; the operator stopped before activation and used Render's explicit
  clear-cache deploy. The replacement was verified before Repo B activation.
- The only production database was Supabase `Editais`; the Render
  `DATABASE_URL` host was the Supabase pooler. No Render Postgres database was
  used, restored, or mutated.
- The first additive migration verification exposed Supabase default browser
  grants on the new internal tables. No app or worker was activated, and all
  new operational tables were empty. Repo A `419673a...` made the migration
  repeat-safe while enabling RLS and revoking `PUBLIC`, `anon`, and
  `authenticated` access on all four internal tables.
- The corrected migration completed with schema version `3`. Final read-only
  verification found RLS enabled on `application_schema_versions`,
  `source_runs`, `source_schedule_state`, and `source_work_items`, with zero
  browser-role or PUBLIC table grants.

## Admission And Writer Transfer

- Live `/health` returned `healthy`; authenticated pipeline health returned
  `source_admission_ready=true`, `closed_beta`, admitted source `brde`, contract
  `candidate`, strict claim enforcement, and legacy pipeline triggers disabled.
- Render retained `ENABLE_SCHEDULER=false`. The live source-schedule catalog
  contained 32 entries and reported BRDE active with a 60-minute interval.
- Four old-ref runs that appeared during deployment were individually reviewed
  and canceled: `34881885915`, `34881780381`, `34881363341`, and
  `34881287884`. All reached terminal state.
- The exact 25 legacy writer workflow IDs from the P3 ledger were disabled.
  Reconciliation then found zero open old-writer runs and only terminal legacy
  API states: pipeline `103 failed / 1128 success`, source
  `33 failed / 99 success`, and OCR `69 completed / 34 failed`.
- Repo B group A workflow `358096532` remained the only enabled scheduled
  ingestion owner. Groups B and C were disabled, the repository allowlist was
  exactly `brde`, and Repo A remained the authoritative server fence.
- Default-deny probe `34883655686` at exact Repo B SHA `2b91ee5...` succeeded:
  its matrix completed and the discovery job was skipped. The earlier
  `34882484233` failure is retained because it exposed an empty-matrix workflow
  defect; commits `edcefab` and `2b91ee5` repaired it before activation.

## Canary And Replay

The bounded production canary was GitHub Actions run
`34883807324` at exact Repo B SHA `2b91ee5...`. It completed successfully from
`2026-09-14T18:56:01Z` through `18:58:08Z`:

- inventory `2`, in scope `2`, policy rejected `0`;
- two official principal PDFs downloaded and two submissions acknowledged;
- inserted `2`, updated `0`, reactivated `0`, errors `0`, fidelity blockers
  `0`, and no partial inventory or cap;
- the two canonical URL SHA-256 values were
  `ff4879089d368a850ae93f86e418c0546268e841cde6d7b7ef03beafc498e4da`
  and
  `40fde66e0121d92ab4e5cea91a698369300d42be116bd819cb7e2cb68215cd59`,
  exactly matching the two independently audited open FSA notice URLs;
- post-canary database reconciliation verified principal-PDF content SHA-256
  values
  `055efd07f544d3ef166b1bf74ae552906ad1a96f2dd3c9a83f6389f26696471e`
  (`426,122` bytes) and
  `bc35bb3d2f3d7f92f89a3af5a09f1a2a56d4a09f71d5b95696e5296a956a9eac`
  (`427,088` bytes), exactly matching both independent audit inventories;
- the six closed FSA details and closed Palacete section were not admitted.

The unchanged replay was run `34884405336` at the same SHA. It completed
successfully from `2026-09-14T19:01:56Z` through `19:03:37Z`. Source telemetry
reported inventory `2`, in scope `2`, downloads `0`, submissions `0`, all
write-outcome counters `0`, errors `0`, and fidelity blockers `0`.

Post-replay read-only reconciliation found exactly three historical-plus-current
BRDE candidates, three editais, and three documents, unchanged from the
post-canary counts. Both new durable items remained `accepted`, the single
schedule row had no active claim, one checkpoint remained, and no non-BRDE
candidate was discovered after activation. There was no duplicate logical
record, lost pending work, stale acceptance, or unexpected source.

## Quantitative Limits

- A 30-request authenticated health sample had zero failures. After five
  warm-up requests, the 25-sample warm p95 was `937.43 ms`, median
  `927.96 ms`, and maximum `953.65 ms`, within the `1 s` stop limit.
- Supabase reported `15 / 60` database connections (`25%`), within the `70%`
  limit.
- Database size was `148,384,915` bytes. Against Supabase's
  [documented free project database quota](https://supabase.com/docs/guides/platform/database-size)
  of 500 MB, headroom was about `70%`, above the `20%` stop limit.
- Canary discovery completed in 60 seconds and replay discovery in 39 seconds,
  both below the 20-minute job budget and 30-minute source limit. P1's accepted
  isolated capacity ratio remained `41,437/hour` service versus `22/hour`
  arrival, above the required `1.25x` ratio.

## Remaining Gate

P5 remains active and incomplete. GitHub's `07 * * * *` schedule remains
enabled for group A, and the first scheduler tick had not appeared by
`2026-09-14T19:10:37Z`; scheduled workflows may be delayed by GitHub. Manual
canary and replay runs are not represented as scheduled evidence. P6 has not
begun. Expansion and RR-01 through RR-05 remain open until their separate
evidence requirements are met.

No credential value, connection string, claim token, production payload, or
user-owned field is retained in this record.
