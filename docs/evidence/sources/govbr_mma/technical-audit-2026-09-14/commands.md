# govbr_mma technical audit — commands (2026-09-14)

All commands run from repository root on Windows with Python 3.13.5
(`py -3.13 --version` verified). No secrets, cookies, tokens, or production
endpoints were used. No Repo A pipeline endpoints were called. No workflows
were dispatched. Nothing was committed or pushed.

## 1. Focused unit tests (pre-fix baseline)

```
py -3.13 -m pytest tests/test_govbr_mma_discovery.py -q
```

Result: `21 passed in 0.26s` (pre-fix; no resolveuid regression test yet).

## 2. Independent official-page capture (NOT via the repo adapter)

Ad-hoc read-only script (`_tmp_mma_capture.py`, temporary; not part of the
repository) using `requests` + `BeautifulSoup` directly:

- GET `https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais`
  → HTTP 200, `text/html;charset=utf-8`, 184527 bytes, 2026-09-14T20:28:39Z.
- Enumerated anchors in `#content-core #parent-fieldname-text`: 6 internal
  detail URLs (one is a dead Plone `resolveuid/<sha>` stub → HTTP 404
  `application/json`), plus external/mailto links (dropped).
- Bounded GET of each internal detail (detail cap 25; only 6 exist):
  - `licitacoes/licitacoes` → 200; no PDFs under the editais prefix.
  - `compras-diretas` → 200; year index 2020/2018/2016 only (no direct PDFs).
  - `ata-de-registro-de-preco` → 200; year index 2020/2018/2017 only.
  - `chamamento-publico-locacao-de-imovel/chamamento-publico-locacao-de-imovel`
    → 200; 9 PDFs (all HTTP 200 `application/pdf`, sizes recorded in
    capture-log.txt).
  - `portarias/portarias` → 200; 1 PDF (Portaria 220/2016).
  - `resolveuid/d15fde...` → 404 (dead "PLANO ANUAL DE CONTRATAÇÕES 2020" stub).
- Year subpages under compras-diretas/… and ata-…/… (2016–2020) inspected
  separately: historical PDFs only, all years < 2026; adapter does not
  recurse there (single-level crawl) which matches the min-year policy.
- Principal edital PDF downloaded and text-extracted with `pypdf` (16 pages):
  item 7.1 sets proposal deadline **20/01/2017 18h Brasília** → status
  `closed` as of 2026-09-14; result notices (`aviso-resultado-*`) confirm the
  process concluded.

Raw timeline: `capture-log.txt`. Structured inventory:
`independent-inventory.json`.

## 3. Pre-fix audit-only discovery (repo orchestrator)

```
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR='C:\...\lasalle-notices-automation-cronjob\_tmp_mma_audit_20260914'
$env:SOURCES='govbr_mma'
$env:PYTHONPATH='scripts'
py -3.13 scripts/discover_all_candidates.py
```

Result: **EXIT=1** — `error: discovery reported 1 error(s) for 'govbr_mma';
inventory is partial`. Stats (`stats-prefix.json`): listings_fetched=1,
details_fetched=6, candidates=5, prefilter_rejected=4, year_rejected=1,
**errors=1** (dead resolveuid detail 404). Pre-fix self-fidelity of its own
discovery.json was clean, but the orchestrator correctly failed closed on the
partial inventory.

## 4. Source-local fix

`scripts/discover_govbr_mma_candidates.py` — `extract_govbr_mma_detail_urls`
now skips canonical paths containing `/resolveuid/` (dead Plone UID stubs).
`tests/test_govbr_mma_discovery.py` — added
`TestExtractGovbrMmaDetailUrls.test_skips_dead_resolveuid_stubs`.

## 5. Post-fix unit tests

```
py -3.13 -m pytest tests/test_govbr_mma_discovery.py -q
```

Result: `22 passed in 0.26s` (21 pre-existing + 1 new regression).

## 6. Post-fix audit-only discovery

```
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR='C:\...\lasalle-notices-automation-cronjob\_tmp_mma_audit_20260914_postfix'
$env:SOURCES='govbr_mma'
$env:PYTHONPATH='scripts'
py -3.13 scripts/discover_all_candidates.py
```

Result: **EXIT=0**. Stats (`stats-postfix.json`): listings_fetched=1,
details_fetched=5, candidates=5, prefilter_rejected=4, year_rejected=1,
errors=0, candidate_cap_reached=0. Orchestrator-internal fidelity
(self inventory vs self discovery) also OK.

## 7. Independent fidelity audit

```
py -3.13 scripts/audit_source_fidelity.py \
  --source-inventory docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/independent-inventory.json \
  --discovery docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/discovery.json \
  --out docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/fidelity
```

Result: **EXIT=0** — `source fidelity OK: no blocking exceptions`.
Summary: pass=true, total_blocking_exceptions=0,
inventory_accounting_pct=100.0 (0/0 open-in-scope),
candidate_traceability_pct=100.0 (5/5),
non_blocking_exception_count=11 (5× out_of_scope + 6×
missing_optional_metadata for status/deadline fields the candidate contract
does not carry).

## Hygiene

- No cookies/headers/personal data stored in evidence.
- Temporary capture scripts (`_tmp_mma_*`) left in working tree as scratch;
  not part of the production adapter change.
- `scripts/run_independent_source_audit.py` was NOT used as evidence.
