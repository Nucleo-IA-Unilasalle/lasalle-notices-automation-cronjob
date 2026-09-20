# Canoas Technical Audit — Command Log (2026-09-14)

Session: bounded source-adapter verification for `canoas` (Repo B worker).
Rollout mode **paused** preserved; no production actions.

UTC window: 2026-09-14T20:20Z – 2026-09-14T20:25Z.

## Commands executed

| # | Command | Purpose | Exit | Result |
|---|---------|---------|------|--------|
| 1 | `py -3.13 --version` | Confirm interpreter | 0 | Python 3.13.5 |
| 2 | `py -3.13 -m pytest tests/test_canoas_discovery.py -q` | Offline deterministic tests | 0 | **11 passed in 0.25s** |
| 3 | Direct HTTP: diary-by-day for 12/13/14-09-2026 | Independent inventory (not via adapter) | 0 | 200×3; `{}` / `{}` / full edition 3930 (48 pubs) |
| 4 | Direct HTTP: publication-file/140919 | Principal PDF for signal row | 0 | 200, application/pdf, 74674 bytes |
| 5 | Direct HTTP: wp-json licitações searches (`319 2026`, `edital 319`) | WP resolution check | 0 | 200; empty for 2026; only 2021/2022 pregão pages |
| 6 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=$TEMP/canoas-audit-20260914202500 SOURCES=canoas SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=canoas py -3.13 scripts/discover_all_candidates.py` | Audit-only dry run (no submit) | 0 | opportunities=1, errors=0, caps=0; built-in fidelity OK; per_source_submitted={'canoas': 0} |
| 7 | `py -3.13 scripts/audit_source_fidelity.py --source-inventory docs/evidence/sources/canoas/technical-audit-2026-09-14/independent-inventory.json --discovery docs/evidence/sources/canoas/technical-audit-2026-09-14/discovery.json --out docs/evidence/sources/canoas/technical-audit-2026-09-14/fidelity` | Official fidelity CLI vs independent inventory | 0 | `source fidelity OK: no blocking exceptions`; accounting 100% (0/0 open-in-scope); traceability 100% (1/1) |

## Audit-only path and the paused hold

- Registry: `config/source_schedule.json` → canoas `submission_contract=opportunity`, `rollout_mode=paused`, group a, owner `pipeline-discovery-group-a.yml`, interval 60, detail_limit=20, page_limit=5, attachment_limit=25, browser_required=false.
- Catalog: `config/source_catalog_contract.json` → canoas `catalog_status=active` (catalog lifecycle separate from execution rollout hold).
- **Paused hold preserved.** No workflow dispatch, no repository variable change, no catalog mutation, no snapshot/sign-off edit.
- Discovery-only dry run is possible without ingestion: `DISCOVERY_AUDIT_ONLY=true` + `DISCOVERY_AUDIT_DIR` runs discovery and offline fidelity and skips submission (`per_source_submitted=0`). The orchestrator does **not** consult `rollout_mode=paused` inside audit-only mode; the production hold is enforced at the workflow/schedule layer, which was not exercised.

## Safety constraints observed

- No PIPELINE_SECRET / RENDER_API_KEY / DATABASE_URL / Supabase / cookies / tokens read or used.
- No Repo A pipeline/submission/claim/work/scheduler/admin endpoints called.
- No GitHub Actions workflows dispatched; no repo variables mutated; no deploys.
- Catalog lifecycle / audit holds / snapshot sign-off / release-decision files untouched.
- Shared coordinator-owned files read-only; only canoas evidence written (no adapter defect → no code change).
- `scripts/run_independent_source_audit.py` was not used as evidence.
