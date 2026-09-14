# P2 Recoverability Attempt: 20260913T070433Z

Decision: **ACCEPT for migration-specific P2**.

This immutable, sanitized evidence bundle records a bounded P2 rehearsal performed by Vitor, the approved data-handling, backup, and restore operator. The source was a production Supabase public-schema logical dump created by an authorized, non-mutating `pg_dump` operation. The source session itself reported `transaction_read_only=off`, so this record does not mislabel the credential as a read-only database role. No production database write, deployment, scheduler change, Render change, GitHub change, or source-workflow change was performed.

The attempt is split into two independent phases:

1. **Restore validation:** decrypt/extract the retained AES-256 archive into a fresh loopback-only PostgreSQL 17 target, restore the public schema/data, inventory the pre-migration state, apply Repo A's additive v3 migration twice, and inventory the post-migration state.
2. **Local API compatibility:** start the Repo A API against only that target with closed-beta admission and all schedulers/telemetry writers disabled; exercise admission, stop, lease expiry, resume, release semantics, permissions, and the historical Repo B worker as an actual subprocess using a loopback fixture server.

The bounded checks passed. This acceptance is limited to the additive public-schema migration. It is not full disaster-recovery evidence: Supabase-managed Auth, Storage, Realtime, webhooks, provider configuration, roles/ownership, and other non-public internals were intentionally excluded and are not claimed as restored. Production cutover, drain, rollback, and a real OCR run were not performed.

Independent reviewer `/root/p2_review`, 2026-09-13: **ACCEPT for
migration-specific P2**, limited to the additive public-schema migration. The
evidence demonstrates authorized encrypted-backup restore to an isolated target,
repeat-safe migration, schema/security validation, compatible historical-worker
recovery, admission stop, pending-work resume, cleanup, and redacted evidence.
Supabase-managed Auth/Storage/Realtime/platform metadata and production
cutover/drain/rollback remain out of scope and separately gated.

Evidence files:

- [decision.md](decision.md): scope, result, and release decision.
- [restore-validation.md](restore-validation.md): isolated restore, migration, schema, security, and cleanup results.
- [api-compatibility.md](api-compatibility.md): local API, stop/resume, admission, permissions, and real worker subprocess results.
- [exit-code-ledger.md](exit-code-ledger.md): phase timings and exit codes.
- [schema-inventory.txt](schema-inventory.txt): complete pre/post table, row, column/nullability, constraint, index, extension, and fingerprint inventory.

The retained encrypted archive is identified only by its SHA-256 and size in the restore report. Private paths, credentials, service identifiers, claim tokens, and plaintext dump contents are intentionally absent from this public evidence.
