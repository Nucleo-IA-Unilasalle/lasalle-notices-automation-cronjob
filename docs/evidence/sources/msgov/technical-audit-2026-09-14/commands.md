# msgov technical audit — commands (2026-09-14)

All commands run from repository root on Windows with Python 3.13.5
(`py -3.13 --version` verified). No secrets, cookies, tokens, or production
endpoints were used. No Repo A pipeline endpoints were called. No workflows
were dispatched. Nothing was committed or pushed.

## 1. Focused unit tests (pre-fix baseline)

```
py -3.13 -m pytest tests/test_msgov_discovery.py -q
```

Result: `9 passed in 0.20s`.

## 2. Independent official inventory (NOT via the repo adapter)

Ad-hoc read-only scripts under `%TEMP%\msgov_audit\` (scratch; outside the
repository):

- Direct GET `https://editaisms.prosas.com.br` → HTTP 200,
  `text/html; charset=utf-8`, 20929 bytes, 2026-09-14T20:49:53Z. Page is a
  Prosas web-component shell (`prosas-listagem-editais`, client-id public).
- Anonymous OAuth: `POST https://prosas.com.br/auth/oauth2/token`
  (`grant_type=client_credentials`, public client id from the page HTML)
  → HTTP 200; token held in memory only, never written to evidence.
- Open enumeration: `GET …/third_party/oportunidades/inscricoes_abertas`
  with incentivador filter, `page[size]=100` → HTTP 200,
  `application/vnd.api+json`, **23 items** (one page).
- Closed enumeration: `GET …/third_party/oportunidades` with
  `data_limite_inscricao_sem_rascunho < now` filter, pages 1–2 →
  HTTP 200, **125 items**.
- Independent Playwright walk of the live open tab confirmed the UI
  renders only 20 of 23 (pagination buttons present in shadow DOM;
  ids 16859/16862/17087 only on page 2).
- Detail API per open id (`include=…arquivos…`) → HTTP 200 × 23;
  113 arquivos total (29 PDFs). Independent Playwright detail pass
  (expand `prosas-box-container-dropdown` + wait) confirmed ≥1 PDF
  anchor on every open detail page.

Structured inventory: `independent-inventory.json` (open=29 PDFs across
23 editais, closed=125, upcoming=0, excluded=0, unknown=0).

## 3. Pre-fix audit-only discovery (repo orchestrator)

```
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR='C:\Users\Vitor\AppData\Local\Temp\msgov_audit\discovery_run'
$env:SOURCES='msgov'
$env:PYTHONPATH='scripts'
py -3.13 scripts/discover_all_candidates.py
```

Result: **EXIT=0** but stats show `candidates=50`, `candidate_cap_reached=1`
(`stats-prefix.json`): listings_fetched=1, details_fetched=23, errors=0.
Post-fix analysis: 21 PDFs + 29 `.doc` annexes consumed the cap of 50 and
**8 real PDFs were dropped** (partial inventory). The pre-fix adapter also
never paginated the listing (caught by the independent UI/API cross-check;
detail_fetched=23 only after the pagination fix — the pre-fix run here
benefited from a race where the component briefly exposed enough anchors,
but the 50-cap truncation is the hard failure observed).

## 4. Source-local fixes

`scripts/discover_msgov_candidates.py`:

1. **Listing pagination** — walk the Prosas next-page control
   (`_CLICK_NEXT_PAGE_SCRIPT`) up to `MSGOV_MAX_LISTING_PAGES` (default 5 =
   registry `page_limit`). Without this, open editais beyond the first
   20-rendered page were invisible to discovery.
2. **Stable candidate identity** — `_stable_pdf_identity` strips Oracle
   preauthenticated `/p/<token>/` segments and query strings; exposed as
   `metadata.canonical_url` / `metadata.source_record_id` so audit
   artifacts are comparable across runs while `candidate["url"]` keeps the
   signed download href.
3. **PDF-only candidate filter** — `_is_pdf_candidate_href` drops explicit
   office/archive suffixes (`.doc`, `.docx`, `.xlsx`, …) even on
   amazonaws/objectstorage hosts. The historical
   `or "amazonaws.com" in href` catch-all admitted annexes that later only
   failed magic-byte validation, polluted the candidate set, and pushed
   real PDFs past the run cap.

`tests/test_msgov_discovery.py`:

- Updated the base listing test: `.doc` annex is no longer a candidate.
- Added `TestPdfCandidateFilter` (rejects doc/xlsx; accepts pdf and
  extensionless S3).
- Added `TestStablePdfIdentity` (token/query stripping; metadata contract).
- Added `TestListingPagination` (two-page fake; page-2 edital collected).
- Fake Playwright harness gained `listing_pages` multi-page support.

## 5. Post-fix unit tests

```
py -3.13 -m pytest tests/test_msgov_discovery.py -q
```

Result: `14 passed in 0.26s`.

## 6. Post-fix audit-only discovery

```
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR='C:\Users\Vitor\AppData\Local\Temp\msgov_audit\discovery_postfix'
$env:SOURCES='msgov'
$env:PYTHONPATH='scripts'
py -3.13 scripts/discover_all_candidates.py
```

Result: **EXIT=0**. Stats (`stats-postfix.json`): listings_fetched=1,
details_fetched=23, candidates=**29**, errors=0, candidate_cap_reached=0.

## 7. Independent fidelity audit

```
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/msgov/technical-audit-2026-09-14/independent-inventory.json `
  --discovery docs/evidence/sources/msgov/technical-audit-2026-09-14/discovery.json `
  --out docs/evidence/sources/msgov/technical-audit-2026-09-14/fidelity
```

Result: **EXIT=0** — `source fidelity OK: no blocking exceptions`.
Summary: pass=true, total_blocking_exceptions=0,
inventory_accounting_pct=100.0 (29/29 open-in-scope PDFs),
candidate_traceability_pct=100.0 (29/29), non_blocking_exception_count=29
(`missing_optional_metadata` for deadline/status fields the candidate
contract does not carry on the discovery side — inventory has them).

## Hygiene

- No cookies/headers/personal data/tokens stored in evidence.
- Scratch scripts and raw captures live under `%TEMP%\msgov_audit\` (outside
  the repository) and are removed at the end of the session.
- `scripts/run_independent_source_audit.py` was NOT used as evidence.
