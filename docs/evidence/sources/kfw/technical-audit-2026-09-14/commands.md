# KfW technical audit 2026-09-14 — commands

Working directory: repository root (`lasalle-notices-automation-cronjob`). Interpreter: `py -3.13` (Python 3.13.5 verified with `py -3.13 --version`). No secrets used; no Repo A endpoints called; no workflows dispatched.

## 1. Unit tests

```powershell
py -3.13 -m pytest tests/test_kfw_discovery.py -q
# → 16 passed in 6.20s
```

## 2. Independent capture (NOT via the repo adapter)

Direct HTTP GET of the official listing (urllib, User-Agent `Mozilla/5.0 (compatible; source-audit/1.0)`), saved to temp `listing.html`; parsed independently with BeautifulSoup for PDF anchors and signal tokens; Playwright chromium render of the same page (`pw_capture.py` in temp) for JS-parity; HEAD/ranged-GET checks of all 15 PDF URLs (`check_pdfs.py` / `recheck_pdfs.py` in temp). Results recorded in `capture-log.md` and `independent-inventory.json`.

## 3. Audit-only discovery (safe path)

```powershell
$env:DISCOVERY_AUDIT_ONLY="true"
$env:DISCOVERY_AUDIT_DIR="C:\Users\Vitor\AppData\Local\Temp\kfw-audit-2026-09-14\discovery"
$env:SOURCES="kfw"
py -3.13 scripts/discover_all_candidates.py
# → exit 0; kfw: discovered 2 candidates; stats: listings_fetched=1, details_fetched=1,
#   candidates=2, errors=0, candidate_cap_reached=0, playwright_fallback_used=0
#   orchestrator self-check: "source fidelity OK: no blocking exceptions" (self-vs-self, not evidence)
```

(Scratch dir is outside the repository; `RENDER_APP_URL`/`PIPELINE_SECRET` never set — audit-only mode requires neither.)

## 4. Independent fidelity verification

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "C:\Users\Vitor\AppData\Local\Temp\kfw-audit-2026-09-14\independent-inventory.json" `
  --discovery "C:\Users\Vitor\AppData\Local\Temp\kfw-audit-2026-09-14\discovery\kfw\discovery.json" `
  --out "C:\Users\Vitor\AppData\Local\Temp\kfw-audit-2026-09-14\fidelity"
# → exit 0; "source fidelity OK: no blocking exceptions"
# summary: accounting 100.0% (0/0 open-in-scope), traceability 100.0% (2/2),
#   blocking=0, non_blocking=13 (out_of_scope dispositions for non-signal PDFs)
```

Note: an initial fidelity run exited 1 with 4 blocking exceptions (2 extra_submission + 2 identity_mismatch) because the draft inventory used slug `source_record_id` values while discovery emits the PDF URL as `source_record_id` (adapter identity contract). Fixed in the inventory (IDs aligned to canonical URL); no adapter change needed.

## 5. Cleanup

```powershell
Remove-Item -Recurse -Force "C:\Users\Vitor\AppData\Local\Temp\kfw-audit-2026-09-14"
```
