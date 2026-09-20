# WorldBank technical audit 2026-09-14 — commands

Working directory: repository root (`lasalle-notices-automation-cronjob`). Interpreter: `py -3.13` (Python 3.13.5 verified with `py -3.13 --version`). No secrets used; no Repo A endpoints called; no workflows dispatched. `PIPELINE_SECRET`/`RENDER_APP_URL` never set.

## 1. Unit tests

```powershell
py -3.13 -m pytest tests/test_worldbank_discovery.py -q
# → 24 passed in 6.24s
```

## 2. Independent capture (NOT via the repo adapter)

Direct HTTP GET of the official listing (PowerShell `HttpWebRequest`, User-Agent `Mozilla/5.0 (compatible; source-audit/1.0)`), saved to temp `%TEMP%\worldbank-audit-2026-09-14\listing.html`; parsed independently with BeautifulSoup for PDF anchors and signal tokens; HEAD checks of both PDF URLs via urllib (`2026-09-14T21:47:56Z`). Results recorded in `capture-log.md` and `independent-inventory.json`.

## 3. Audit-only discovery (safe path)

```powershell
$env:DISCOVERY_AUDIT_ONLY="true"
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\worldbank-audit-2026-09-14\discovery"
$env:SOURCES="worldbank"
py -3.13 scripts/discover_all_candidates.py
# → exit 0; worldbank: discovered 1 candidates; stats: listings_fetched=1,
#   candidates=1, prefilter_rejected=0, year_rejected=0, errors=0,
#   candidate_cap_reached=0, playwright_fallback_used=0
#   orchestrator self-check: "source fidelity OK: no blocking exceptions" (self-vs-self, not evidence)
```

(Scratch dir is outside the repository; audit-only mode requires neither `RENDER_APP_URL` nor `PIPELINE_SECRET`.)

## 4. Independent fidelity verification

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "$env:TEMP\worldbank-audit-2026-09-14\independent-inventory.json" `
  --discovery "$env:TEMP\worldbank-audit-2026-09-14\discovery\worldbank\discovery.json" `
  --out "$env:TEMP\worldbank-audit-2026-09-14\fidelity"
# → exit 0; "source fidelity OK: no blocking exceptions"
# summary: accounting 100.0% (0/0 open-in-scope), traceability 100.0% (1/1),
#   blocking=0, non_blocking=3 (2 missing_optional_metadata for discovery null
#   status/deadline vs inventory values; 1 out_of_scope for the non-signal
#   announcement PDF)
```

## 5. Cleanup

```powershell
Remove-Item -Recurse -Force "$env:TEMP\worldbank-audit-2026-09-14"
```
