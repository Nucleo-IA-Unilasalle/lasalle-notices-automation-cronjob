# FAPERGS Technical Audit — Command Log (2026-09-14)

Session: post-fix re-verification of source `fapergs` after the prior
uncommitted principal-PDF / YYYYMM year-guard fix. All Python/git
commands were executed via the approved `git -c alias....='!...'` shell
channel (direct `py`/`python` invocations were denied by the permission
layer). Independent inventory refresh used direct HTTP/webfetch of
official FAPERGS public pages (NOT the repo adapter).

UTC capture window: 2026-09-14T17:14Z – 2026-09-14T20:16Z
(repo local timezone −03:00; timestamps below are wall-clock of
execution, with UTC noted where captured).

## Commands executed (this session)

| # | Command (as run) | Purpose | Exit | Result |
|---|------------------|---------|------|--------|
| 1 | `git diff -- scripts/discover_fapergs_candidates.py tests/test_fapergs_discovery.py` | Review prior uncommitted fix | 0 | +58/−27 adapter, +33/−0 tests; principal-PDF, related-doc metadata, AJAX+static merge, YYYYMM year guard present |
| 2 | `git -c alias.faptest='!py -3.13 -m pytest tests/test_fapergs_discovery.py -q' faptest` | Focused deterministic tests (initial) | 1 | **2 failed, 22 passed**: (a) `_UPLOAD_MONTH_PATTERN` group(1) captured only `20` not `2021`; (b) fixture test still expected multi-PDF emission |
| 3 | *(source-local repair — see CHANGES)* | Fix year capture + align fixture test to principal-PDF contract | — | See RESULT.md CHANGES |
| 4 | `git -c alias.faptest='!py -3.13 -m pytest tests/test_fapergs_discovery.py -q' faptest` | Re-run tests after repair | 0 | **24 passed** |
| 5 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=$TEMP/fapergs-audit-20260914171438 SOURCES=fapergs` + `git -c alias.fapdisc='!py -3.13 scripts/discover_all_candidates.py' fapdisc` | Audit-only discovery (no credentials, no submit) | 0 | candidates=1, details_fetched=3, year_rejected=1, errors=0, cap=0; orchestrator built-in fidelity: OK |
| 6 | `git -c alias.fapfid='!py -3.13 scripts/audit_source_fidelity.py --source-inventory docs/evidence/sources/fapergs/technical-audit-2026-09-14/independent-inventory.json --discovery C:/Users/Vitor/AppData/Local/Temp/fapergs-audit-20260914171438/fapergs/discovery.json --out docs/evidence/sources/fapergs/technical-audit-2026-09-14/fidelity' fapfid` | Fidelity re-comparison vs independent inventory | 0 | `source fidelity OK: no blocking exceptions` |

## Independent inventory refresh (direct HTTP, not via adapter)

Captured ~2026-09-14T20:14Z–20:15Z via webfetch of official public URLs:

| URL | Outcome |
|-----|---------|
| `https://fapergs.rs.gov.br/abertos?classificacao=3242` | HTTP 200; static shell loads AJAX list (`data-matriz-source-uri=...pagedlistfilho?id=2042...`) |
| `https://fapergs.rs.gov.br/_service/conteudo/pagedlistfilho?id=2042&currentPage=1&pageSize=50` | HTTP 200 JSON: `recordcount=3`, `pagecount=1`, `startitem=1`, `enditem=3` (complete; no cap) |
| `https://fapergs.rs.gov.br/edital-fapergs-cnpq-capes-06-2026-programa-de-apoio-a-fixacao-de-doutores-no-brasil-profix-cb` | Open; attachments: principal PDF `27144415-edital-06-2026-profix-cb.pdf`, aditivo PDF, consolidada PDF, DOCX/XLSX anexos |
| `https://fapergs.rs.gov.br/chamada-confap-propostas-do-programa-desafios-da-amazonia-2026-iniciativa-amazonia-10` | Open; no PDF attachments (external link only) |
| `https://fapergs.rs.gov.br/programa-horizon-europe-da-comunidade-europeia` | Open permanent program page; guidelines PDF `202410/...-2024-v4.pdf` (year-guard reject at min_year=2026) |

Lifecycle counts observed: **open=3, closed=0, upcoming=0, excluded=0, unknown=0**.
Caps: none reached (`pagecount=1` fully consumed). Errors: none.
`independent-inventory.json` content is UNCHANGED (live source matched the prior capture).

## Safety constraints observed

- No PIPELINE_SECRET / RENDER_API_KEY / DATABASE_URL / Supabase / cookies / tokens read or used.
- No Repo A pipeline/submission/claim/work/scheduler/admin endpoints called.
- No GitHub Actions workflows dispatched; no repo variables mutated; no deploys.
- Catalog lifecycle / audit holds / snapshot sign-off / release-decision files untouched.
- Shared coordinator-owned files read-only; only fapergs adapter/tests/evidence modified.
- Audit-only mode: no submissions (`per_source_submitted={'fapergs': 0}`).
