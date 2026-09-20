# govbr_mma_public_calls technical audit 2026-09-14 — commands

All commands run from repository root on Windows PowerShell with Python 3.13.5.
No Repo A endpoints, secrets, cookies, or production mutations were used.

## 1. Interpreter check

```powershell
py -3.13 --version
# Python 3.13.5
```

## 2. Unit tests (offline fixtures)

```powershell
py -3.13 -m pytest tests/test_govbr_mma_public_calls_discovery.py -q
# 25 passed in 6.31s
```

## 3. Independent official inventory (NOT the repo adapter)

Direct `requests` + BeautifulSoup capture of the official listing
(`_tmp_pc_capture.py` is a throwaway independent script, not repo evidence).
Single listing page; no pagination API. Detail pages for year≥2026 non-related
links were GET-verified.

```powershell
py -3.13 _tmp_pc_capture.py _tmp_pc_audit
# counts={'open': 0, 'closed': 0, 'upcoming': 0, 'excluded': 15, 'unknown': 1}
# inventory records=1 errors=0
```

Capture provenance (UTC):

- Listing GET 2026-09-14T20:30:31Z — HTTP 200 `text/html;charset=utf-8`
  `https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico`
- CONASQ news detail GET 2026-09-14T20:30:34Z — 302 →
  `/acl_users/credentials_cookie_auth/require_login` (HTTP 200 on login wall;
  page body “Conteúdo Restrito”; no principal PDFs).
- Resultado GM/MMA Nº 1/2026 — editorial related document (excluded).
- 14× 2025-year listing links — excluded by min-year 2026.

## 4. Audit-only discovery (repo orchestrator)

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR="$PWD\_tmp_pc_discovery_audit"
$env:SOURCES='govbr_mma_public_calls'
py -3.13 scripts/discover_all_candidates.py
# EXIT=0
# govbr_mma_public_calls: discovered 0 candidates
# (listings_fetched=1, details_fetched=1, candidates=0, year_rejected=14, errors=0)
```

## 5. Adapter inventory path (direct, for provenance)

```powershell
py -3.13 -c "from discover_govbr_mma_public_calls_candidates import _discover_candidates_and_inventory, _write_audit_artifacts; ..."
# inventory 1 record (CONASQ, status=unknown, reason_code=unresolved_news_lead)
# candidates 0
```

## 6. Source fidelity CLI

Primary fidelity gate: independent inventory vs orchestrator discovery.json.

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory _tmp_pc_audit\independent-inventory.json `
  --discovery _tmp_pc_discovery_audit\govbr_mma_public_calls\discovery.json `
  --out _tmp_pc_fidelity
# EXIT=0
# pass=true; blocking=0; accounting 100.0% (0/0 open-in-scope); traceability 100.0% (0/0)
```

Cross-check: independent inventory vs adapter `source_inventory.json`
(includes `unresolved_news_lead` provenance record) also EXIT=0, pass=true.

## 7. Evidence copy

Artifacts copied under
`docs/evidence/sources/govbr_mma_public_calls/technical-audit-2026-09-14/`
without cookies/headers/tokens/credentials.
