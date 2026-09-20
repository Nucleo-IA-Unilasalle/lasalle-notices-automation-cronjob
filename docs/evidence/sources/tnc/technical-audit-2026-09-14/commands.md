# TNC Technical Audit — Command Log (2026-09-14)

Session: bounded source-adapter verification for `tnc` (Repo B worker).
Rollout mode **audit** preserved; no production actions.

UTC window: 2026-09-14T20:37Z – 2026-09-14T20:42Z.

## Commands executed

| # | Command | Purpose | Exit | Result |
|---|---------|---------|------|--------|
| 1 | `py -3.13 --version` | Confirm interpreter | 0 | Python 3.13.5 |
| 2 | `py -3.13 -m pytest tests/test_tnc_discovery.py tests/test_tnc_opportunities.py -q` | Offline deterministic tests (pre-fix) | 0 | **26 passed in 6.27s** |
| 3 | Direct HTTP GET `https://www.tnc.org.br/conecte-se/trabalhe-conosco/` | Independent inventory (not via adapter) | 0 | 200, text/html;charset=utf-8, 91671 bytes @ 2026-09-14T20:37:36Z |
| 4 | Direct HTTP GET `https://www.tnc.org.br/conecte-se/comunicacao/noticias/` | News listing signal check | 0 | 200, text/html;charset=utf-8, 616024 bytes @ 2026-09-14T20:37:37Z; 0 signal detail URLs |
| 5 | Independent BeautifulSoup parse of consultancy section | Full block accounting without importing the adapter | 0 | 49 blocks; open=1, expired/closed=48, malformed=0 |
| 6 | Direct HTTP GET open TDR PDF `tdr-metodologiapsa-para.pdf` | Principal document validation | 0 | 200, application/pdf, 140858 bytes, %PDF- magic, SHA-256 `ac35f49cca7ee6d888e6caaa60870bf5c3555877f1a9cfe275abee6ffa733e9d` |
| 7 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=$TEMP/tnc-audit-20260914173850 SOURCES=tnc SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=tnc py -3.13 scripts/discover_all_candidates.py` | Audit-only dry run (pre-fix) | 1 | 49 opportunities emitted; built-in fidelity **2 identity_mismatch** blockers (shared TDR PDF across two fallback IDs) |
| 8 | Edit `scripts/discover_tnc_candidates.py` + `tests/test_tnc_opportunities.py` | Source-local fix: clear shared documents when applying fallback IDs | 0 | Shared TDR kept only as free-text provenance in `source_markdown` |
| 9 | `py -3.13 -m pytest tests/test_tnc_discovery.py tests/test_tnc_opportunities.py -q` | Offline tests after fix | 0 | **26 passed in 6.34s** |
| 10 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=$TEMP/tnc-audit-fixed-20260914174011 SOURCES=tnc SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=tnc py -3.13 scripts/discover_all_candidates.py` | Audit-only dry run (post-fix) | 0 | 49 opportunities; built-in fidelity OK; `per_source_submitted={'tnc': 0}` |
| 11 | `py -3.13 scripts/audit_source_fidelity.py --source-inventory <independent-inventory.json> --discovery <DIR>/tnc/discovery.json --out <fidelity-dir>` | Official fidelity CLI vs independent inventory | 0 | `source fidelity OK: no blocking exceptions`; accounting 100% (1/1 open-in-scope); traceability 100% (49/49) |

## Audit path and the audit hold

- Registry: `config/source_schedule.json` → tnc `submission_contract=opportunity`, `rollout_mode=audit`, group b, owner `pipeline-discovery-group-b.yml`, interval 60, detail_limit=20, page_limit=5, attachment_limit=25, browser_required=false, module `discover_tnc_candidates`.
- Catalog: `config/source_catalog_contract.json` → tnc `catalog_status=active` (catalog lifecycle separate from execution rollout hold).
- **Audit hold preserved.** No workflow dispatch, no repository variable change, no catalog mutation, no snapshot/sign-off edit. AGENTS.md two-audit hold for tnc/funbio is **not** removed by this verification.
- Discovery-only dry run skips submission (`per_source_submitted=0`). Orchestrator does not consult `rollout_mode` inside audit-only mode; the production hold is enforced at the workflow/schedule layer, which was not exercised.

## Defect found and fixed (source-local)

Two distinct expired consultancy blocks on the official page both point to the same TDR PDF
`.../tdr/tdr-empresa-especializada-nap.pdf`. The adapter correctly reassigned distinct
`consultancy:<sha256>` fallback stable IDs and `?consultancy=` canonical URLs, but left the
shared PDF URL on both records' `documents`. Source-fidelity then flagged
`identity_mismatch` (two stable IDs sharing a lower-authority `document_url`) — including
on the built-in self-audit of discovery output. Fix (adapter-only, <15 lines): when applying
fallback identity for a reused TDR URL, clear `documents` and keep the shared URL only as
free-text provenance in `source_markdown`. Regression test asserts empty `documents` and
preserved markdown provenance.

## Safety constraints observed

- No PIPELINE_SECRET / RENDER_API_KEY / DATABASE_URL / Supabase / cookies / tokens read or used.
- No Repo A pipeline/submission/claim/work/scheduler/admin endpoints called.
- No GitHub Actions workflows dispatched; no repository variables mutated; no deploys.
- Catalog lifecycle / audit holds / snapshot sign-off / release-decision files untouched.
- Shared coordinator-owned files (config/*, workflows, OPERATIONS.md, discover_all_candidates.py, audit_source_fidelity.py, source_fidelity.py) read-only; only tnc adapter/tests + tnc evidence written.
- `scripts/run_independent_source_audit.py` was not used as evidence.
- Scratch analysis scripts and captures stored outside the repo under `%TEMP%\tnc-*`.
