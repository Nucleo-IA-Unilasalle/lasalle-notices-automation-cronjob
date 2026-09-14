# Local API Compatibility

This phase began only after restore validation. The Repo A API ran against the disposable PostgreSQL target on loopback, with no production URL or external writer credentials.

## Writer And Scheduler Fences

The API process used:

- `SOURCE_ADMISSION_MODE=closed_beta`
- `SOURCE_ADMISSION_SOURCE=bndes`
- `SOURCE_ADMISSION_CONTRACT=candidate`
- `SOURCE_CLAIM_ENFORCEMENT=strict`
- `ENABLE_SCHEDULER=false`
- `SOURCE_RUN_MAINTENANCE_ENABLED=false`
- `SOURCE_RUN_REPORTING_ENABLED=false`
- `RENDER_APP_URL=loopback-only`

Startup logged `Background scheduler disabled via settings`; the API bound to `127.0.0.1` only. No scheduler, maintenance, reporting, notification, production worker, or external writer process was started. The legacy-worker compatibility phase used a separate API process with the same loopback-only target and a local fixture HTTP server.

## Admission And Stop

The real API returned:

| Probe | Result |
| --- | --- |
| capabilities | HTTP `200` |
| closed-beta mode/source/contract | `closed_beta` / `bndes` / `candidate` |
| legacy pipeline trigger | HTTP `409`, `legacy_pipeline_disabled` |
| wrong source | HTTP `409`, `source_not_admitted` |
| missing claim | HTTP `409`, `claim_missing` |
| valid claim | HTTP `201` |
| durable registration | HTTP `200` |
| take | HTTP `200`; two items, revision `1` each |

The API was then stopped normally. Direct access to the isolated target expired two item leases and one schedule claim to model worker termination; no production state was involved.

## Resume And Non-Destructive Release

On restart, a stale claim was rejected with HTTP `409`. A new claim succeeded with HTTP `201`, and taking work returned both preserved item IDs. Accepted finish and deferred finish each returned HTTP `200`; a no-op release returned HTTP `200`. The final isolated state was:

- item 1: `accepted`, attempts `2`, revision `1`, no error;
- item 2: `pending`, attempts `1`, revision `1`, no error;
- live schedule claims: `0`.

The final v3 workload counts were `application_schema_versions=3`, `source_collection_checkpoints=0`, `source_schedule_state=1`, and `source_work_items=2`. This demonstrates pending work survives API stop and is retaken after lease expiry. The release path was non-destructive: it did not delete the accepted or pending record. No destructive rollback was attempted.

## Browser Roles

Disposable `anon` and `authenticated` roles were tested against each v3 table. For every role/table pair, direct `SELECT` and `INSERT DEFAULT VALUES` probes exited `1` with permission denied, and no rows were inserted:

```text
anon|application_schema_versions|select_exit=1|insert_exit=1
anon|source_collection_checkpoints|select_exit=1|insert_exit=1
anon|source_schedule_state|select_exit=1|insert_exit=1
anon|source_work_items|select_exit=1|insert_exit=1
authenticated|application_schema_versions|select_exit=1|insert_exit=1
authenticated|source_collection_checkpoints|select_exit=1|insert_exit=1
authenticated|source_schedule_state|select_exit=1|insert_exit=1
authenticated|source_work_items|select_exit=1|insert_exit=1
```

## Historical Worker Subprocess

The historical Repo B BNDES entry point `discover_bndes_candidates.main` from revision `553c67dcdb593550112470df8c76b0314fae3d4e` was launched twice as a child Python process. It connected only to the loopback API and fetched a deterministic PDF from `127.0.0.1:63340`; no real source or OCR provider was contacted. The fixture extractor is an integration seam, so this is not a real OCR claim.

| Run | Process exit | Worker outcome | Final logical rows |
| --- | ---: | --- | --- |
| 1 | 0 | `inserted=1`, `updated=0`, `duplicates=0` | 1 candidate, 1 edital, 1 document |
| 2 | 0 | `inserted=0`, `updated=1`, `duplicates=0` | 1 candidate, 1 edital, 1 document |

The second run updated the same logical record rather than creating a duplicate. Final worker-scoped counts were one candidate, one edital, and one document; the document status was `processed`.
