# SEMA-RS technical audit — commands executed (2026-09-14)

All commands run from the repository root
(`lasalle-notices-automation-cronjob`) on Windows with the workflow-pinned
`py -3.13` interpreter. No production endpoints, secrets, or GitHub
automation were touched.

## 0. Interpreter check

```powershell
py -3.13 --version
# Python 3.13.5
```

## 1. Baseline unit tests (pre-fix)

```powershell
py -3.13 -m pytest tests/test_sema_rs_discovery.py -q
# 23 passed in 54.28s
```

## 2. Independent official capture (direct HTTP, not via the repo adapter)

A standalone script under `_tmp_sema_audit/capture_independent.py` (not
importing any repo module except stdlib/requests/bs4) swept:

- `GET https://www.sema.rs.gov.br/busca/lista-data-table?currentPage={1..}&pageSize=20&form[palavraschave]=edital&form[ordem]=RECENTES`
- `GET https://www.sema.rs.gov.br/busca/lista-data-table?currentPage={1..}&pageSize=20&form[palavraschave]=chamada&form[ordem]=RECENTES`
- `GET https://www.sema.rs.gov.br/residuos-solidos`
- every signal-matched detail URL from the listings

Bounded probes (404s expected): `/editais`, `/edital`, `/chamadas-publicas`,
`/noticias`. Bounded lifecycle probes: `/fundo-estadual-de-protecao-e-bem-estar-animal`,
`/programa-biogas-rs`, `/programa-energia-forte-no-campo-5-fase`,
`/outorga-aguas-subterraneas`.

```powershell
py -3.13 _tmp_sema_audit/capture_independent.py
# edital: pages=2 recordcount=29 pagecount=2; chamada: pages=1 recordcount=5 pagecount=1
# static: 10 same-host PDFs (+4 off-host statutes); details: 2 URLs, 0+25 PDFs
```

Outputs: `_tmp_sema_audit/capture_raw.json` (raw, local only) → sanitized
`capture-log.md` and `independent-inventory.json` under
`docs/evidence/sources/sema_rs/technical-audit-2026-09-14/`.

## 3. Audit-only discovery (pre-fix, for defect evidence)

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR=(Resolve-Path '_tmp_sema_audit').Path + '\discovery_run1'
$env:SOURCES='sema_rs'
py -3.13 scripts/discover_all_candidates.py
# sema_rs: discovered 8 candidates (listings_fetched=0, details_fetched=1,
#   prefilter_rejected=2, year_rejected=4, errors=0)
# exit=0
```

Defects evidenced by run1 + independent capture:

1. **Pagination premature stop** — keyword `edital` page 1 has 20 articles /
   0 signal-matched anchors; the real detail URLs are on page 2
   (`pagecount=2`). `_paginate_keyword` broke on the first empty-extraction
   page, so the AJAX path never reached any detail page
   (`listings_fetched=0`). Had an open call appeared on page 2+, it would
   have been silently missed.
2. **Year-guard blind to `/YYYYMM/` folders and percent-encoding** —
   `/upload/arquivos/202307/…pdf` extracted no year (folder ignored) and
   `Lei%20n%C2%BA%2009.921.pdf` extracted the false year 2009 from the
   `%2009` encoding boundary.
3. **Static-page sweep emitted non-calls** — the `residuos-solidos` sweep
   used the generic PDF collector: 8 emitted candidates were guidance
   reports / investment-plan PDFs plus one off-host statute PDF
   (`ww3.al.rs.gov.br/.../Lei%20n%C2%BA%206.503.pdf`), and the one real
   signal PDF (Edital de Chamada Pública → `materia1309752.pdf`) sits in a
   panel whose sibling link is "Resultado Final" (call concluded).

Pre-fix fidelity (independent inventory vs run1 discovery):

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory _tmp_sema_audit/independent-inventory.json `
  --discovery _tmp_sema_audit/discovery_run1/sema_rs/discovery.json `
  --out _tmp_sema_audit/fidelity_prefix
# fidelity failures: 16 blocking exception(s); exit=1
# extra_submission=8, identity_mismatch=8
```

## 4. Source-local fixes (scripts/discover_sema_rs_candidates.py + tests)

- `_extract_year_from_url`: percent-decode before scanning; add
  `/YYYYMM/` upload-folder pattern (`_UPLOAD_MONTH_PATTERN`).
- `_fetch_keyword_listing_html`: return `(body, pagecount)` from the JSON
  envelope.
- `_paginate_keyword`: stop on server `pagecount`, article-free placeholder
  bodies, stale pages, consecutive failures, or the per-keyword page cap;
  report per-keyword yield.
- `extract_static_service_pdf_urls` / `_extract_static_service_pdf_urls_from_soup`:
  same-host, signal-token, skip panels with closure markers
  (`Resultado Final` / `encerrad…`); wired into the static sweep via
  `discover_pdf_urls_on_page(..., extractor=...)`.
- `tests/test_sema_rs_discovery.py`: `pagecount` support in the listing
  mock; new regression classes `TestPaginationContinuation`,
  `TestYearFolderExtraction`, `TestStaticServiceExtractor`.

## 5. Unit tests (post-fix)

```powershell
py -3.13 -m pytest tests/test_sema_rs_discovery.py -q
# 34 passed in 27.39s

py -3.13 -m pytest tests/test_discover_all_candidates.py tests/test_source_fidelity.py -q
# 133 passed in 5.31s
```

## 6. Audit-only discovery (post-fix)

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR=(Resolve-Path '_tmp_sema_audit').Path + '\discovery_run2'
$env:SOURCES='sema_rs'
py -3.13 scripts/discover_all_candidates.py
# sema_rs: discovered 0 candidates (listings_fetched=1, details_fetched=3,
#   prefilter_rejected=0, year_rejected=25, errors=0, candidate_cap_reached=0)
# exit=0
```

Zero emissions are the correct lifecycle result for 2026-09-14: every
official call found is closed (2024 Delta do Jacuí; 2022-2023 Tainhas
archive; concluded Comunidade de Prática chamada with Resultado Final;
concluded Fundo animal council/habilitação calls; pre-2026 Biogás archive)
and every non-call static PDF is filtered.

## 7. Fidelity audit (post-fix)

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/sema_rs/technical-audit-2026-09-14/independent-inventory.json `
  --discovery docs/evidence/sources/sema_rs/technical-audit-2026-09-14/discovery.json `
  --out docs/evidence/sources/sema_rs/technical-audit-2026-09-14/fidelity
# source fidelity OK: no blocking exceptions; exit=0
# inventory_accounting_pct=100.0 (0/0 in-scope), candidate_traceability_pct=100.0 (0/0),
# total_blocking_exceptions=0, non_blocking_exception_count=4 (out_of_scope x4)
```

## Not run / not used

- `scripts/run_independent_source_audit.py` — not used as evidence.
- No Repo A endpoints, no GitHub Actions dispatches, no deployments, no
  commits or pushes.
