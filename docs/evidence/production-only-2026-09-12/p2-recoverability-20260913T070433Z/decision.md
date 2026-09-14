# P2 Decision

**Result: ACCEPT for migration-specific P2**

## PASS

- A retained, encrypted public-schema candidate restored successfully to a fresh PostgreSQL 17.11 target bound to loopback only.
- The Repo A additive v3 migration completed successfully on the restored target and completed successfully a second time without changing the migration result.
- Pre/post schema inventories include table counts, row counts, all columns with nullability, constraints, indexes, extensions, and fingerprints. See [schema-inventory.txt](schema-inventory.txt).
- The target had RLS enabled on all four v3 data/control tables and no `public`, `anon`, or `authenticated` table ACL grants. Direct role probes denied both `SELECT` and `INSERT` for every v3 table.
- Closed-beta admission, API stop, expired-lease recovery, pending-work resume, accepted/deferred finish, and non-destructive release semantics passed against the isolated API/DB.
- The historical Repo B BNDES worker was launched as a subprocess from its recorded source revision, used only a loopback fixture server and isolated API, exited 0 twice, and produced one logical candidate, edital, and document. The first run inserted and the replay updated the same logical record.
- The target container, volume, plaintext extraction, temporary scripts, worker checkout, target credential escrow, and private run logs were removed after verification. The unrelated pre-existing container was not touched.

## Scope Exception And Residual Limits

- This was not a full Supabase disaster-recovery proof. Auth, Storage, Realtime, webhooks, provider configuration, non-public schemas, managed roles/ownership, and platform configuration were outside the additive public-schema release and were not restored or validated.
- No production drain/fence, production rollback, deployment, or production writer replay was executed. Those remain release-gate actions for the authorized operator.
- The worker fixture used a deterministic extractor so this evidence does not claim real OCR correctness or provider availability.

The operator accepts the unchanged Supabase-managed domains as outside this
additive public-schema release. The evidence supports the P2 migration-specific
restore and compatibility gate, not full platform disaster recovery or production
cutover approval.

Independent reviewer `/root/p2_review`, 2026-09-13: **ACCEPT for
migration-specific P2**, limited to the additive public-schema migration. The
evidence demonstrates authorized encrypted-backup restore to an isolated target,
repeat-safe migration, schema/security validation, compatible historical-worker
recovery, admission stop, pending-work resume, cleanup, and redacted evidence.
Supabase-managed Auth/Storage/Realtime/platform metadata and production
cutover/drain/rollback remain out of scope and separately gated.
