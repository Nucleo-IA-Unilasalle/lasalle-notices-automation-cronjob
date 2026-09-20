# DOPA technical audit commands (2026-09-14)

Working directory: repository root (`lasalle-notices-automation-cronjob`).
Scratch directory outside the repo: `%TEMP%\dopa_audit_b_20260914`.
No `PIPELINE_SECRET` / `RENDER_APP_URL` / GitHub secrets used. No Repo A endpoints called. No workflows dispatched.

## Interpreter check

```powershell
py -3.13 --version
# Python 3.13.5
```

## Offline unit tests (pre and post fix)

```powershell
py -3.13 -m pytest tests/test_dopa_discovery.py -q
# pre-fix baseline: 12 passed
# post-fix: 17 passed
```

## Independent official capture (not via repo adapter)

```powershell
py -3.13 "$env:TEMP\dopa_audit_b_20260914\capture_independent.py" "$env:TEMP\dopa_audit_b_20260914"
```

- Direct `urllib` GET of `busca-avancada` for 2026-09-12..2026-09-14 `escopo=executivo` (HTTP 200, application/json, 145 rows).
- Direct GET of all 145 `conteudo/{id}/detalhes` endpoints (all HTTP 200).
- Outputs: `raw-search-rows.json`, `capture-log.json`, `accounting.json`, `independent-inventory-draft.json` (scratch).

Ground-truth open set and post-act exclusions were then reviewed against detail bodies and written to `independent-inventory.json` (145 records; open=5).

## Audit-only discovery (paused hold preserved)

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\dopa_audit_b_20260914\discovery_run_final2"
$env:SOURCES='dopa'
$env:SUBMISSION_CONTRACT='opportunity'
$env:OPPORTUNITY_SOURCES='dopa'
$env:MIN_NOTICE_YEAR='2026'
$env:SOURCE_RUN_REPORTING_ENABLED='false'
py -3.13 scripts/discover_all_candidates.py
# exit 0; dopa: discovered 5 opportunities
# stats: records=145 details_fetched=10 opportunities=5 policy_rejected=140
#        search_result_cap_reached=0 detail_cap_reached=0 candidate_cap_reached=0
#        errors=0 detail_failures=0
```

`DISCOVERY_AUDIT_ONLY=true` bypasses rollout holds by design (discovery + offline fidelity only; no ingestion, no submission, no telemetry side effects with reporting disabled). The registry `rollout_mode=paused` hold for dopa remains enforced at the workflow/schedule layer (`pipeline-discovery-group-b.yml`); this audit does not change it.

## Independent fidelity (pre-fix FAIL)

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "$env:TEMP\dopa_audit_b_20260914\independent-inventory.json" `
  --discovery "$env:TEMP\dopa_audit_b_20260914\discovery_run\dopa\discovery.json" `
  --out "$env:TEMP\dopa_audit_b_20260914\fidelity_prefix"
# exit 1
# accounting 40.0% (2/5); traceability 100%; blockers: missing_open=3, authoritative_status_mismatch=1
```

## Independent fidelity (post-fix PASS)

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "docs/evidence/sources/dopa/technical-audit-2026-09-14/independent-inventory.json" `
  --discovery "docs/evidence/sources/dopa/technical-audit-2026-09-14/discovery.json" `
  --out docs/evidence/sources/dopa/technical-audit-2026-09-14/fidelity
# exit 0
# accounting 100.0% (5/5); traceability 100% (5/5); total_blocking_exceptions=0
```

## Cleanup

Scratch directory `%TEMP%\dopa_audit_b_20260914` is temporary; sanitized copies live under `docs/evidence/sources/dopa/technical-audit-2026-09-14/`.
