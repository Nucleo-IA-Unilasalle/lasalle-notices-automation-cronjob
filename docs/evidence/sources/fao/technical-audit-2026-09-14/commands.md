# FAO technical audit — commands (2026-09-14)

Working directory: repository root of `lasalle-notices-automation-cronjob`.
Shell: PowerShell via py -3.13 (Python 3.13.5 verified). No production
endpoints, secrets, or Repo A pipeline APIs were used.

## Environment / preflight

```powershell
py -3.13 --version
# Python 3.13.5
git status --porcelain
git rev-parse --short HEAD
# 42ec28c  (working tree already had other-source edits; fao-only files touched here)
```

## Focused tests (pre-fix baseline)

```powershell
py -3.13 -m pytest tests/test_fao_discovery.py -q
# 15 passed in 6.22s
```

Browser binaries were already available; no `playwright install` was required.

## Independent HTTP capture (NOT via repo adapter)

```powershell
# Entry page + related BSF pages: plain requests GET, User-Agent source-audit/1.0
# Full details in capture-log.md (status, final URL, content-type, UTC times).
# Principal PDF GETs with SHA-256: nb780en, no028en, cc3636en (see capture-log.md).
```

## Independent inventory

```powershell
# docs/evidence/sources/fao/technical-audit-2026-09-14/independent-inventory.json
# Content: []  (zero open opportunities on the official entry page)
```

## Safe audit path — BEFORE fix (defect evidence)

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR='C:\Users\Vitor\AppData\Local\Temp\fao-audit-unfixed-20260914'
$env:SOURCES='fao'
py -3.13 scripts/discover_all_candidates.py
# exit 0; fao: discovered 3 candidates; playwright_fallback_used=0
# discovery.json contained nb780en.pdf, no028en.pdf, cc3636en.pdf

py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/fao/technical-audit-2026-09-14/independent-inventory.json `
  --discovery C:\Users\Vitor\AppData\Local\Temp\fao-audit-unfixed-20260914\fao\discovery.json `
  --out C:\Users\Vitor\AppData\Local\Temp\fao-audit-unfixed-20260914\fao\fidelity-indep
# exit 1; 3 blocking exceptions (extra_submission); traceability 0%; accounting 100%
```

## Fix applied (source-local)

```text
scripts/discover_fao_candidates.py
  - signal regex: dropped `funding[\s_-]*strategy|resolution`
  - docstrings updated (module + extract_fao_pdf_urls)
tests/test_fao_discovery.py
  + test_excludes_strategy_and_resolution_governance_pdfs
  + test_official_funding_page_fixture_yields_no_governance_pdfs
```

## Focused tests — AFTER fix

```powershell
py -3.13 -m pytest tests/test_fao_discovery.py -q
# 17 passed in 6.24s
```

## Safe audit path — AFTER fix

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR='C:\Users\Vitor\AppData\Local\Temp\fao-audit-fixed-20260914'
$env:SOURCES='fao'
py -3.13 scripts/discover_all_candidates.py
# exit 0; fao: discovered 0 candidates; errors=0; candidate_cap_reached=0;
# playwright_fallback_used=1 (BS4 empty → Playwright also found 0)
```

## Independent fidelity — AFTER fix

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/fao/technical-audit-2026-09-14/independent-inventory.json `
  --discovery C:\Users\Vitor\AppData\Local\Temp\fao-audit-fixed-20260914\fao\discovery.json `
  --out docs/evidence/sources/fao/technical-audit-2026-09-14/fidelity
# exit 0; 0 blocking exceptions; inventory accounting 100%; candidate traceability 100%
```

## Artifacts written under evidence

```text
docs/evidence/sources/fao/technical-audit-2026-09-14/
  independent-inventory.json
  discovery.json                 (post-fix)
  stats.json
  discovery-before-fix.json
  stats-before-fix.json
  fidelity/                      (post-fix, exit 0)
  fidelity-before-fix/           (pre-fix, exit 1)
  capture-log.md
  commands.md                    (this file)
  RESULT.md
```

No cookies, headers, personal data, credentials, or raw tokens are stored in
evidence. No Repo A pipeline/submission endpoints were called. No GitHub
Actions were dispatched. Catalog lifecycle and holds were not modified.
