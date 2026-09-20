# UNEP technical audit — commands (2026-09-14)

All commands run from the repository root
(`lasalle-notices-automation-cronjob`) on Windows with `py -3.13` →
Python 3.13.5. Scratch directories lived under
`%TEMP%\unep_audit_20260914\` (outside the repo) and were cleaned up after
copying evidence into `docs/evidence/sources/unep/technical-audit-2026-09-14/`.
No secrets, cookies, tokens, or personal data were used or stored. No Repo A
endpoints, workflows, or production systems were touched.

## 1. Interpreter check

```
py -3.13 --version
# Python 3.13.5
```

## 2. Focused unit tests (before fix)

```
py -3.13 -m pytest tests/test_unep_discovery.py -q
# 24 passed in 6.22s
```

## 3. Independent official-page capture (NOT via repo adapter)

Standalone `requests` + BeautifulSoup script (generic UA; no credentials)
fetched `https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding`
(HTTP 200), enumerated all anchors, classified lifecycle from page text, and
probed the four unique PDFs with bounded GET. Results recorded in
`capture-log.md`. Listing HTML and probe JSON stayed in the temp scratch dir;
only sanitized evidence was copied into this directory.

## 4. Safe audit discovery path (pre-fix)

```
$env:DISCOVERY_AUDIT_ONLY="true"
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\unep_audit_20260914\discovery_audit"
$env:SOURCES="unep"
py -3.13 scripts/discover_all_candidates.py
# unep: discovered 4 candidates
# stats: listings_fetched=1, candidates=4, errors=0, candidate_cap_reached=0
# exit 0
```

## 5. Independent fidelity (pre-fix; fails)

```
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "$env:TEMP\unep_audit_20260914\independent-inventory.json" `
  --discovery "$env:TEMP\unep_audit_20260914\discovery_audit\unep\discovery.json" `
  --out "$env:TEMP\unep_audit_20260914\fidelity-before-fix"
# fidelity failures: 4 blocking exception(s)
# EXIT:1 — extra_submission=4, traceability 0%, accounting 100% (0/0)
```

(`independent-inventory.json` is `[]` — zero open opportunities on the
official entry point.)

## 6. Fix applied (source-local)

Edited only:
- `scripts/discover_unep_candidates.py` — signal regex narrowed to
  `call[\s_-]*for[\s_-]*proposals?|applying[\s_-]*for[\s_-]*funding|request[\s_-]*for[\s_-]*proposals?`;
  dropped `concept note` / `gfc fund`; docstrings updated (module docstring
  made raw to silence SyntaxWarning).
- `tests/test_unep_discovery.py` — updated fixture expectations; added two
  regression tests locking exclusion of the live page's standing
  guidance/concept-note PDFs and of bare `gfc fund` branding.

## 7. Focused unit tests (after fix)

```
py -3.13 -m pytest tests/test_unep_discovery.py -q
# 26 passed in 6.27s
```

## 8. Safe audit discovery path (post-fix)

```
$env:DISCOVERY_AUDIT_ONLY="true"
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\unep_audit_20260914\discovery_audit_after"
$env:SOURCES="unep"
py -3.13 scripts/discover_all_candidates.py
# unep: discovered 0 candidates
# stats: listings_fetched=1, candidates=0, errors=0, candidate_cap_reached=0
# exit 0
```

## 9. Independent fidelity (post-fix; passes)

```
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "$env:TEMP\unep_audit_20260914\independent-inventory.json" `
  --discovery "$env:TEMP\unep_audit_20260914\discovery_audit_after\unep\discovery.json" `
  --out "$env:TEMP\unep_audit_20260914\fidelity-after-fix"
# source fidelity OK: no blocking exceptions
# EXIT:0 — 0 blockers, accounting 100% (0/0), traceability 100% (0/0)
```
