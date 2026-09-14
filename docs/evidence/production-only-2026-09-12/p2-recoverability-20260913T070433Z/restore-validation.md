# Restore Validation

Operator: **Vitor**, approved data-handling, backup, and restore operator.

## Revisions And Source

- Repo A exact HEAD: `a5275dae46f223da74dc54d0734051acc66a8a9f`
- Repo B exact HEAD: `2e0dd74ee64b999318dea4cc1767df4985b384ee`
- Historical Repo B worker source revision exercised: `553c67dcdb593550112470df8c76b0314fae3d4e`
- Source: production Supabase public-schema logical dump created by an
  authorized, non-mutating `pg_dump` operation; URL and service identifier
  redacted. The source session reported `transaction_read_only=off`, so the
  connection is not represented as a read-only role.
- Archive format: 7-Zip AES-256 encrypted custom-format PostgreSQL dump.
- Archive SHA-256: `B81F5E30C5C304942B3A3CBE35436286BBF089D4E10EAC8A5F849ADD2020DA6B`
- Archive size: `52185571` bytes.

## Restore Phase

Start: `2026-09-13T07:06:37.5233392Z`

End: `2026-09-13T07:06:50.9161610Z`

Duration: `13.393` seconds

A fresh `postgres:17-alpine` target was created with a loopback-only host binding. The target reported server major `17` (`170011`) and `pg_is_in_recovery=false`. The encrypted archive was tested and extracted only inside the disposable target workflow, then restored with `pg_restore --clean --if-exists --single-transaction --no-owner --no-privileges`. Archive test, extraction, and restore all exited `0`.

The pre-migration baseline contained these 11 public tables and rows:

| Table | Rows |
| --- | ---: |
| `ai_processing_attempts` | 854 |
| `audit_logs` | 244 |
| `editais` | 484 |
| `edital_documents` | 2102 |
| `ocr_processing_claims` | 103 |
| `pipeline_runs` | 1215 |
| `scrape_candidates` | 9303 |
| `scraping_sources` | 32 |
| `source_runs` | 117 |
| `user_editais` | 508 |
| `users` | 11 |

The pre-migration fingerprints were columns `99c2d7a7ff9afecc1a0bf8761da3116d`, constraints `4a710c034412372174e6e9ee826cc71e`, indexes `d235bc6e59f3e2952fb8a0a46c862eed`, extensions `ecb9f3167403a85e4f264a2064f579e3`, and relations `c914ab4b5dc6a9ca22f8f04600fb8ef0`.

## Migration And Post-State

Repo A migration run 1 exited `0` in `1.490` seconds. Run 2 exited `0` in `0.735` seconds. The second run was repeat-safe; no duplicate v3 rows or migration error occurred.

Post-migration rows were:

| Table | Rows |
| --- | ---: |
| `ai_processing_attempts` | 854 |
| `application_schema_versions` | 3 |
| `audit_logs` | 244 |
| `editais` | 484 |
| `edital_documents` | 2102 |
| `ocr_processing_claims` | 103 |
| `pipeline_runs` | 1215 |
| `scrape_candidates` | 9303 |
| `scraping_sources` | 32 |
| `source_collection_checkpoints` | 0 |
| `source_runs` | 117 |
| `source_schedule_state` | 0 |
| `source_work_items` | 0 |
| `user_editais` | 508 |
| `users` | 11 |

The post-migration fingerprints were columns `0dcb4b82f18770c05e9546eedfe0ebc8`, constraints `93eb7f99a4c88df703acb66d659c6f25`, indexes `15f0a42b37f778d5ebd47622c06ca6b8`, extensions `ecb9f3167403a85e4f264a2064f579e3`, and relations `e34deba933cfa11760864265a3d61bb1`.

The exact v3 tables and baseline counts were `application_schema_versions=3`, `source_collection_checkpoints=0`, `source_schedule_state=0`, and `source_work_items=0`. Their required columns (the `NO` nullability entries), constraints, indexes, and extension inventory are enumerated in [schema-inventory.txt](schema-inventory.txt). The v3 constraints include the checkpoint foreign key and composite primary key; schedule-state uniqueness/foreign key and claim atomicity, purpose, and generation checks; and work-item foreign key, bounds, contract, and status checks. The target had only `plpgsql` extension `1.0`.

## Security And Isolation

RLS was `true` for each v3 table: `application_schema_versions`, `source_collection_checkpoints`, `source_schedule_state`, and `source_work_items`. ACL inspection reported `public=false`, `anon=false`, and `authenticated=false` for each. No application/browser role was granted write access. See [api-compatibility.md](api-compatibility.md) for the executed role probes.

The API and worker phases were separate from restore validation. No production metadata query was needed. After all checks, the disposable target and volume were torn down and plaintext/temp artifacts were securely deleted; only the previously retained encrypted archive, its DPAPI-bound escrow, and sanitized manifest remain outside the repositories.
