# funbio technical audit 2026-09-14 — commands

All commands run from repository root with Python 3.13.5 (`py -3.13 --version` verified). No production endpoints, secrets, cookies, or Repo A APIs were used.

## Interpreter

```text
py -3.13 --version
→ Python 3.13.5
```

## Unit tests (pre-fix baseline)

```text
py -3.13 -m pytest tests/test_funbio_discovery.py -q
→ 23 passed
```

## Independent official capture (direct HTTP only; no repo adapter)

Direct `urllib` GETs of official FUNBIO public pages (User-Agent `funbio-source-audit/1.0` / browser-like Chrome UA):

- `https://chamadas.funbio.org.br/` (listing; Seleções Abertas + Próximas Seleções panels)
- `https://chamadas.funbio.org.br/calendario-chamadas` (SSR shell only; no closed archive in HTML)
- Nine open detail pages (single-segment slugs listed in capture-log.json)
- Regulamento download URLs for each open call

Regulamento downloads return HTTP 200 `text/html` wrappers whose `__NEXT_DATA__.props.pageProps.file` is a base64 PDF. Eight of nine PDFs decoded to `%PDF` magic and were SHA-256 hashed. `fortalecimentoconselhosgestoresg7` download returned HTTP 524 / read timeout on every retry (300 s); its document URL remains inventoried with `renderable=null` (binary validation incomplete).

Results: `docs/evidence/sources/funbio/technical-audit-2026-09-14/independent-inventory.json` and `capture-log.json`.

Accounting: open=9, closed=0, upcoming=0, excluded=1 (privacy PDF), unknown=0. Pagination: 1 listing page; detail cap (20) not reached (9 details).

## Pre-fix audit-only discovery (baseline)

```text
DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=<temp>/funbio_audit_run SOURCES=funbio SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=funbio py -3.13 scripts/discover_all_candidates.py
→ funbio: discovered 6 opportunities (stats records=6, opportunities=6, errors=0)
→ EXIT=0 (orchestrator self-fidelity only compares discovery to its own export; does not detect missing open calls)
```

Missing vs independent inventory: `conselho-ucs-municipais-estaduais`, `planodemanejo-sinalizacao-estadual-municipal`, `usopublico-ucs` (all "Manifestação de Interesse" open cards). Root cause: listing signal-token regex lacked `interesse` / `manifestação`.

## Pre-fix fidelity vs independent inventory (failed)

```text
py -3.13 scripts/audit_source_fidelity.py \
  --source-inventory docs/evidence/sources/funbio/technical-audit-2026-09-14/independent-inventory.json \
  --discovery <pre-fix>/funbio/discovery.json \
  --out <pre-fix-fidelity>
→ exit 1; 3× missing_open (the three Manifestação de Interesse open calls); also 9× renderability_mismatch from inventory rows that claimed renderable=true without type/hash validation (inventory-side artifact, fixed by honest renderable=null / real PDF validation).
```

## Source-local fixes applied

1. `scripts/discover_funbio_candidates.py` — listing signal tokens expanded to include `interesse|manifesta[çc][ãa]o`; deadline stamped `23:59 America/Sao_Paulo` then converted to UTC; first (regulamento) document marked `is_principal`/`is_renderable`.
2. `tests/test_funbio_discovery.py` — regression tests for Manifestação de Interesse discovery, Brasília deadline, principal document, past-deadline closed status.

## Unit tests (post-fix)

```text
py -3.13 -m pytest tests/test_funbio_discovery.py -q
→ 27 passed
```

## Post-fix audit-only discovery

```text
DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=C:\Users\Vitor\AppData\Local\Temp\funbio_audit_postfix SOURCES=funbio SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=funbio py -3.13 scripts/discover_all_candidates.py
→ funbio: discovered 9 opportunities (records=9, opportunities=9, errors=0)
→ EXIT=0
```

## Post-fix fidelity vs independent inventory

```text
py -3.13 scripts/audit_source_fidelity.py \
  --source-inventory docs/evidence/sources/funbio/technical-audit-2026-09-14/independent-inventory.json \
  --discovery C:\Users\Vitor\AppData\Local\Temp\funbio_audit_postfix\funbio\discovery.json \
  --out docs/evidence/sources/funbio/technical-audit-2026-09-14/fidelity
→ source fidelity OK: no blocking exceptions
→ EXIT=0
→ pass=true; blocking=0; inventory_accounting_pct=100.0 (9/9 open-in-scope); candidate_traceability_pct=100.0 (9/9)
```

## Not run / out of scope

- `tests/test_tnc_opportunities.py` — not run; funbio path uses module-local helpers only; no shared opportunity helper edits.
- `scripts/run_independent_source_audit.py` — not treated as evidence.
- No workflow dispatch, no Repo A calls, no commits/pushes.
