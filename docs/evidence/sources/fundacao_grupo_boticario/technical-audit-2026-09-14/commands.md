# Commands — fundacao_grupo_boticario technical audit 2026-09-14

All commands run from repository root with `py -3.13` (Python 3.13.5). No production endpoints, secrets, or Repo A APIs were used.

## Interpreter check

```powershell
py -3.13 --version
# Python 3.13.5
```

## Unit tests

```powershell
py -3.13 -m pytest tests/test_fundacao_grupo_boticario_discovery.py -q
# 15 passed in ~6s
```

## Independent inventory capture (not via adapter)

Ad-hoc capture scripts (not committed as production code):

- Direct HTTP listing/detail probes with `requests` + BeautifulSoup signal-token filter.
- Playwright Chromium rendering of listing + both detail pages; PDF-anchor scan; lifecycle quotes.

Playwright Chromium binaries already present (`chromium ok`); no install required.

Artifacts: `independent-inventory.json`, `capture-log.md`, `capture-log.json`.

## Audit-only discovery

```powershell
$audit = Join-Path $env:TEMP ("fgb_audit_" + [guid]::NewGuid().ToString("N"))
$env:DISCOVERY_AUDIT_ONLY = 'true'
$env:DISCOVERY_AUDIT_DIR = $audit
$env:SOURCES = 'fundacao_grupo_boticario'
py -3.13 scripts/discover_all_candidates.py
# discovered 0 candidates
# stats: listings_fetched=1, details_fetched=2, candidates=0, errors=0, candidate_cap_reached=0, playwright_fallback_used=0
# exit 0
```

Copy `$audit/fundacao_grupo_boticario/discovery.json` → `docs/evidence/sources/fundacao_grupo_boticario/technical-audit-2026-09-14/discovery.json`.

## Fidelity

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/fundacao_grupo_boticario/technical-audit-2026-09-14/independent-inventory.json `
  --discovery <AUDIT_DIR>/fundacao_grupo_boticario/discovery.json `
  --out docs/evidence/sources/fundacao_grupo_boticario/technical-audit-2026-09-14/fidelity
# source fidelity OK: no blocking exceptions
# exit 0
```

Summary: accounting 100% (0 open in-scope), traceability 100% (0 candidates), 0 blocking exceptions.

## Non-actions

- No commits, pushes, workflow dispatches, or catalog lifecycle edits.
- `scripts/run_independent_source_audit.py` was not treated as evidence.
- No adapter code changes were required.
