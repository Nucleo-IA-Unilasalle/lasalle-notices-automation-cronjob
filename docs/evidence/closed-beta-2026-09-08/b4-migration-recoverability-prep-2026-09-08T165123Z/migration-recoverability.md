# B4 Migration And Recoverability Preparation

Status: **BLOCKED**. This is local preparation evidence only. It is not a B4
pass, release approval, production-read authorization, production backup,
hosted worker compatibility result, or permission to migrate any hosted
database.

## Run Identity

- Task: `B4` local/preparation portion.
- Executor: `/root/b4_recovery_prep` (actual session; exact model/effort was not
  exposed to this evidence record).
- Reviewer: not assigned in this run; a separate Sol-high review is still
  required.
- Formal UTC start: `2026-09-08T16:51:23Z`.
- UTC end: `2026-09-08T17:01:36Z`.
- A branch/SHA: `feature/durable-executor-and-review-hardening` at
  `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`.
- B branch/SHA: `feature/source-rotation-fairness` at
  `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`.
- A was clean at the formal observation. B already contained concurrent B0,
  B1, and B5 evidence/implementation edits. This run changed only its new B4
  evidence directory and the shared evidence index; it did not modify A code
  or overwrite concurrent B changes.

## Isolated Target

The successful database checks used a temporary, local PostgreSQL
`16.2 (Ubuntu 16.2-1ubuntu4)` server extracted under WSL `/tmp/b4-pg`, bound
only to `127.0.0.1:65432`. Databases were `b4_chain`, `b4_v2`, and
`b4_restore`. The test URL used only the local `niciniv` role. No hosted URL,
credential, dump, user record, notification, scheduler, or writer was used.

The server was stopped and `/tmp/b4-pg` was removed at the end. Cleanup printed
`SERVER_STOP=PASS` and `TEMP_ROOT_REMOVED=PASS`.

## Commands And Results

Commands below were run from A unless another directory is named. Connection
strings shown here are local synthetic values, not secrets.

1. Environment and initial fallback probe:

   ```powershell
   docker info --format '{{.ServerVersion}}'
   Get-Command psql,pg_dump,pg_restore,initdb,pg_ctl -ErrorAction SilentlyContinue
   py -3.13 --version
   ```

   Result: Docker exit `1`; all five PostgreSQL commands were `NOT_FOUND` on
   Windows; Python was `3.13.5`. An earlier attempt to start Docker Desktop
   timed out after three minutes. Its local log reported an inaccessible stale
   `sailor-ingest.sock`; no reset or socket deletion was attempted.

2. Focused migration/startup/schema tests:

   ```powershell
   $env:DATABASE_URL='postgresql://local_b4:local_b4@127.0.0.1:65432/b4_isolated'
   py -3.13 -m pytest tests/config/test_schema_release.py tests/config/test_db_startup.py tests/config/test_database_docker_schema.py -q
   ```

   Result: exit `0`, `14 passed in 0.75s`.

3. A offline fencing/work-contract tests, with the same model registration used
   by the application:

   ```powershell
   $env:DATABASE_URL='postgresql://local_b4:local_b4@127.0.0.1:65432/b4_isolated'
   py -3.13 -c "from app.schemas.registry import register_models; register_models(); import pytest; raise SystemExit(pytest.main(['tests/services/test_source_claim_fencing.py','tests/models/test_source_work.py','-q']))"
   ```

   Result: exit `0`, `16 passed in 3.12s`. A preceding direct pytest invocation
   without `register_models()` exited `1` with `1 failed, 15 passed` because the
   isolated invocation could not resolve the `ScrapingSource` relationship to
   `Edital`. That invocation-order failure is retained here and was not
   misreported as a product migration failure.

4. B current-worker compatibility-focused unit tests, from B:

   ```powershell
   py -3.13 -m pytest tests/test_managed_source.py tests/test_pipeline_core.py -q
   ```

   Result: exit `0`, `88 passed in 0.74s`. These mocks/unit contracts do not
   identify or execute the previously deployed hosted worker.

5. Release CLI import boundary:

   ```powershell
   py -3.13 -m scripts.migrate_schema --help
   ```

   Result: exit `0`; help returned without a database connection.

6. Temporary PostgreSQL extraction and start, from the workspace root:

   ```bash
   apt-get download postgresql-16=16.2-1ubuntu4 postgresql-client-16=16.2-1ubuntu4 libpq5=16.2-1ubuntu4 libllvm17t64 postgresql-client-common postgresql-common ssl-cert
   dpkg-deb -x <each-downloaded-deb> /tmp/b4-pg/root
   initdb -D /tmp/b4-pg/data --auth=trust --encoding=UTF8 --no-locale
   pg_ctl -D /tmp/b4-pg/data -l /tmp/b4-pg/postgres.log -o "-h 127.0.0.1 -p 65432 -k /tmp/b4-pg/socket" start
   createdb -h 127.0.0.1 -p 65432 b4_chain
   psql -h 127.0.0.1 -p 65432 -d b4_chain -v ON_ERROR_STOP=1 -c "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;"
   ```

   Result: exit `0`; `pg_isready` reported the isolated endpoint accepting
   connections. The first package-download attempt exited `1` because stale
   Ubuntu indexes referenced unavailable `16.14` package URLs; the explicit
   Ubuntu 24.04 base version above succeeded. Packages were extracted only,
   not installed.

7. Empty database v1-v2-v3 chain and repeat safety:

   ```powershell
   $env:DATABASE_URL='postgresql://niciniv@127.0.0.1:65432/b4_chain'
   $env:DB_CONNECT_TIMEOUT_SECONDS='3'
   py -3.13 -m scripts.migrate_schema
   py -3.13 -m scripts.migrate_schema
   ```

   Result: both exits `0`. A read-back returned versions `1,2,3` and 15 base
   tables. The second command completed the application read-only schema
   verification without adding a fourth ledger entry.

8. PostgreSQL catalog assertions used `psql -X -At -v ON_ERROR_STOP=1` against
   `b4_chain` to query `application_schema_versions`, `pg_class`,
   `pg_constraint`, `pg_indexes`, and `has_table_privilege` for `anon` and
   `authenticated`.

   Result: version chain `1,2,3`; RLS `true` on
   `application_schema_versions`, `source_schedule_state`,
   `source_work_items`, and `source_collection_checkpoints`; zero tested tables
   selectable by either browser role; all six required schedule/work CHECK
   constraints and all five required schedule/work indexes present. This is an
   actual PostgreSQL observation, not only `max(version)`.

9. Database-backed schedule/work/cursor tests against `b4_chain`:

   ```powershell
   $env:DATABASE_URL='postgresql://niciniv@127.0.0.1:65432/b4_chain'
   py -3.13 -m pytest tests/api/test_source_schedule_claims.py tests/services/test_source_work_service.py tests/services/test_source_work_cursors.py -q
   ```

   Result: exit `0`, `37 passed in 6.00s`. A prior no-server attempt against
   `127.0.0.1:65432/b4_isolated` exited `1` with `9 passed, 13 skipped,
   15 errors`; all errors were the expected local connection timeout. The
   successful rerun supersedes only that local dependency failure.

10. Synthetic v2 fixture upgrade. `b4_v2` was cloned locally from the migrated
    fixture, version 3 was removed from the ledger, and the four v3 columns plus
    `ck_source_schedule_state_claim_purpose` were removed. Read-back before the
    upgrade was `max(version)=2`, v3 column count `0`.

    ```powershell
    $env:DATABASE_URL='postgresql://niciniv@127.0.0.1:65432/b4_v2'
    py -3.13 -m scripts.migrate_schema
    py -3.13 -m scripts.migrate_schema
    ```

    Result: both exits `0`; after the upgrade `max(version)=3`, all four v3
    columns existed, and the purpose constraint count was `1`. The first fixture
    setup command exited `1` only after completing its DDL because its reporting
    expression used arithmetic instead of command substitution; a separate
    read-back proved the intended v2 state before migration.

11. Local synthetic backup/restore. One `audit` catalog row and one pending
    candidate descriptor were inserted without user data. The exact tool
    sequence was:

    ```bash
    pg_dump -h 127.0.0.1 -p 65432 -Fc -f /tmp/b4-pg/b4-local-synthetic.dump b4_chain
    createdb -h 127.0.0.1 -p 65432 b4_restore
    pg_restore -h 127.0.0.1 -p 65432 -d b4_restore --exit-on-error /tmp/b4-pg/b4-local-synthetic.dump
    ```

    Result: exit `0`; dump duration `50 ms`, restore duration `314 ms`, size
    `70,388` bytes, SHA-256
    `c5df75c0981b2eb1b2a933a7302d89966b56b1aa799df0b6adc6a0f04c0b53fb`.
    Source and restore each had versions `1,2,3`, 15 tables, one fixture source,
    and one pending work item. A subsequent `verify_db_schema()` against
    `b4_restore` exited `0` with `RESTORED_SCHEMA_VERIFY=PASS`. The dump was
    synthetic, temporary, and deleted during cleanup; it is not the required
    named production backup.

## Assertions Versus Observations

Observed locally: the empty chain executes through versions 1, 2, and 3; a
synthetic v2 fixture upgrades to v3; the release command repeats safely on both;
required v2/v3 RLS, constraints, indexes, columns, and browser-role privilege
denials are present; a synthetic pending descriptor survives dump/restore; the
restored schema passes A's startup verifier; 155 focused tests passed across A
and B.

Not observed: any production schema version, production role/default-privilege
configuration, real production counts, production backup, production restore,
hosted notification/scheduler/writer disablement, actual previously deployed
worker, hosted additive compatibility, or admission/drain/fence/resume rollback.

## Blocking Conditions

- **Production version read: BLOCKED.** The current production database identity
  and authorized read-only route were not supplied. No production connection
  was attempted.
- **Production authorization: BLOCKED.** This task explicitly excluded hosted
  systems and did not authorize production reads, backup, restore, migration,
  deployment, schedule changes, or writer changes.
- **Named private backup/restore: BLOCKED.** No approved private storage target,
  named production backup, approved isolated restore target, data-handling
  approval, or owner was supplied. Therefore production migration remains
  blocked regardless of the successful synthetic rehearsal.
- **Hosted previous-worker compatibility: BLOCKED.** B0 did not establish the
  executed hosted/default-branch worker SHA or target API/database identity.
  Unit compatibility checks are not an actual previous deployed worker run.
- **Non-destructive worker rollback: BLOCKED.** Without an authorized hosted
  identity and previous-worker artifact, this run could not stop admission,
  drain/fence writers, deploy the compatible prior worker, or prove preserved
  pending work resumes. No schema downgrade or dump overwrite was attempted.
- **Final B4 rerun: BLOCKED.** The release plan requires another run after B2/B3
  fixes are frozen, plus separate reviewer acceptance.

B4 must not be marked PASS. RR-01 through RR-05 remain OPEN.

## Next Action

The operator must provide or authorize a read-only production identity/version
check, name the production backup and approved private restore location with a
data-handling owner, identify the actual deployed previous worker SHA/artifact,
and authorize the isolated restore and hosted compatibility/rollback rehearsal.
After B2/B3 freeze, rerun the affected local and hosted checks against exact
candidate SHAs, then obtain a separate Sol-high review before any B4 status
change.

## Files Changed

- `docs/evidence/closed-beta-2026-09-08/b4-migration-recoverability-prep-2026-09-08T165123Z/migration-recoverability.md`
- `docs/evidence/closed-beta-2026-09-08/b4-migration-recoverability-prep-2026-09-08T165123Z/SHA256SUMS`
- `docs/evidence/closed-beta-2026-09-08/index.md`

