# Commands — govbr_mma_fnma technical audit 2026-09-14

Working directory: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob`
UTC session date: 2026-09-14 (local ~17:20–17:30 -03:00 ≈ 20:20–20:30Z)

No credentials used. No production endpoints. No workflows dispatched. No commits. No cookies/headers/tokens stored in evidence.

## Prior session (uncommitted fix + partial evidence, resumed here)

| Step | Command / action | Exit / outcome |
|------|------------------|----------------|
| P1 | Applied source-local fix in `scripts/discover_govbr_mma_fnma_candidates.py` (`_extract_listing_metadata`: past deadline forces `closed` when status was `open`) | uncommitted working-tree change |
| P2 | Added `TestStaleOpenPastDeadline` in `tests/test_govbr_mma_fnma_discovery.py` (2 cases) | uncommitted working-tree change |
| P3 | Captured independent-inventory.json + pre-fix fidelity | FAIL: 1 blocking `authoritative_status_mismatch` (inv=closed, discovery=open); RESULT.md/commands.md never written (session reset) |

## This session (verify + complete evidence)

| Step | Command / action | Exit / outcome | UTC notes |
|------|------------------|----------------|-----------|
| 1 | `py -3.13 --version` | Python 3.13.5 | env check |
| 2 | `git diff -- scripts/discover_govbr_mma_fnma_candidates.py tests/test_govbr_mma_fnma_discovery.py` | reviewed prior fix (~11+46 line uncommitted diff) | read-only |
| 3 | Read pre-fix fidelity `summary.json`/`exceptions.json`/`matches.json`/`report.md` + `independent-inventory.json` | 1 blocking status mismatch; traceability 100% | pre-fix baseline |
| 4 | `py -3.13 -m pytest tests/test_govbr_mma_fnma_discovery.py -q` | **2 failed, 24 passed** — new regression tests used ISO date split as day/month/year (`2026/08/15`); deadline never extracted | initial |
| 5 | Source-local test fix: format fixture dates as `dd/mm/yyyy` via `strftime` (tests only; adapter untouched) | 2 replacements applied | fix |
| 6 | `py -3.13 -m pytest tests/test_govbr_mma_fnma_discovery.py -q` | **26 passed** | post-fix |
| 7 | Live listing fetch via adapter path (`fetch_html_with_retry` + `extract_fnma_links` + `_extract_listing_metadata` + `build_inventory`) | 190449 bytes; 2 PDF entries (1 principal + 1 retificação); listing_meta status=closed deadline=2026-07-13 | ~20:21Z |
| 8 | GET-verify principal + retificação PDFs (Range/first bytes; UA header) | both HTTP 200 `application/pdf` (`%PDF-1.4`, `%PDF-1.7`) | HEAD was 403; GET used |
| 9 | Refresh `independent-inventory.json` to live-observed title/status/deadline/docs | open=0 closed=1 upcoming=0 excluded=0 unknown=0 | evidence write |
| 10 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=<audit evidence dir>/discovery-run SOURCES=govbr_mma_fnma py -3.13 scripts/discover_all_candidates.py` | exit=0; 1 candidate; errors=0; cap_reached=0; built-in fidelity OK | ~20:22Z |
| 11 | `py -3.13 scripts/audit_source_fidelity.py --source-inventory docs/evidence/sources/govbr_mma_fnma/technical-audit-2026-09-14/independent-inventory.json --discovery .../discovery-run/govbr_mma_fnma/discovery.json --out docs/evidence/sources/govbr_mma_fnma/technical-audit-2026-09-14/fidelity` | exit=0; 0 blocking; accounting 100.0% (0/0 open-in-scope); traceability 100.0% (1/1) | ~20:22Z |
| 12 | Copy discovery.json / stats / candidates / source_inventory to evidence root; write commands.md + RESULT.md | evidence complete | |

## Reproduction commands

```powershell
py -3.13 -m pytest tests/test_govbr_mma_fnma_discovery.py -q
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR = Join-Path $env:TEMP ('fnma-audit-' + [guid]::NewGuid().ToString('N'))
$env:SOURCES='govbr_mma_fnma'
py -3.13 scripts/discover_all_candidates.py
py -3.13 scripts/audit_source_fidelity.py --source-inventory docs/evidence/sources/govbr_mma_fnma/technical-audit-2026-09-14/independent-inventory.json --discovery (Join-Path $env:DISCOVERY_AUDIT_DIR 'govbr_mma_fnma/discovery.json') --out docs/evidence/sources/govbr_mma_fnma/technical-audit-2026-09-14/fidelity
```
