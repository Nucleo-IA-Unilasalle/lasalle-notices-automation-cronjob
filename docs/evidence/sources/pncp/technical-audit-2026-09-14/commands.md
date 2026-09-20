# PNCP technical audit — commands (2026-09-14)

All commands run from repository root on Windows with Python 3.13.5
(`py -3.13 --version` verified). No secrets, cookies, tokens, or production
endpoints were used. No Repo A pipeline endpoints were called. No workflows
were dispatched. Nothing was committed or pushed. Scratch lived under
`%TEMP%\pncp_audit_*\` (outside the repository) and is removed at session end.

## 1. Focused unit tests

```
py -3.13 -m pytest tests/test_pncp_discovery.py tests/test_pncp_filters.py tests/test_pncp_safety.py tests/test_pncp_opportunity_normalization.py tests/test_pncp_backfill.py -q
```

Result: **108 passed** (twice: baseline and final confirmation).

## 2. Independent official inventory (NOT via the repo adapter)

Ad-hoc read-only script under `%TEMP%\pncp_audit_*\` (`capture_inventory_mod4.py`):

- Direct GET `https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao`
  with `uf=RS`, `codigoModalidadeContratacao=4`, `dataInicial=20260913`,
  `dataFinal=20260914`, `pagina=1`, `tamanhoPagina=50` → HTTP 200,
  totalRegistros=30, one page, **30 unique controls**.
- Lifecycle classified independently (see capture-log.md): open=15, closed=4,
  upcoming=11, excluded=0, unknown=0.
- Docs API per open control → HTTP 200 × 15; 15/15 have principal documents;
  SHA-256 of sampled PDF bytes recorded.

Structured inventory: `independent-inventory.json`.

Contrast (not ground truth): full-day multi-modality probe
(`full-day-mod-all-summary.json`) enumerated 639 RS controls for 20260914
across mods 6/8/4 (open=150) and hit hard open/doc caps → failure signal for
unbounded windows.

## 3. Safe local audit / dry-run discovery (PNCP-specific path)

PNCP does **not** go through `scripts/discover_all_candidates.py`.
`DISCOVERY_AUDIT_ONLY` is not implemented inside
`scripts/discover_pncp_candidates.py` (`_main_impl` requires
RENDER_APP_URL/PIPELINE_SECRET only on the submit/managed path).

**Documented safe local audit path used here:** library invocation of
`discover_candidates()` only, with:

- `PNCP_UPDATE_CHECKPOINT_PATH` pointed at a temp file (never production
  `.cache/pncp_update_checkpoint.json`, which does not exist in the tree).
- `SOURCE_WORK_ENABLED` / `SOURCE_DRAIN_ONLY` / `RENDER_APP_URL` /
  `PIPELINE_SECRET` unset.
- Runtime (in-process only, no file edits) bound to the independent inventory:
  `PNCP_DEFAULT_MODALITY_CODES=("4",)`, `FEDERAL_CNPJS=()`,
  `PNCP_LOOKBACK_DAYS=1`, `PNCP_PROPOSTA_FORWARD_DAYS=1`,
  `PNCP_MAX_CANDIDATES_PER_RUN=200`, `PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN=100`.
- Explicit asserts: no production checkpoint before/after; dry-run does not
  call `main` / `submit_candidates` / `_save_update_checkpoint`.

```
py -3.13 %TEMP%\pncp_audit_*\discovery_dryrun.py %TEMP%\pncp_audit_*\discovery_run3
```

Synchronized result (`stats.json` / `discovery-run-summary.json`):
records=15, document_lookups=15, candidates=47 raw → 15 aggregated open
controls, document_failures=0, candidate_cap_reached=0,
checkpoint_written=false. `search_failures=2` were read timeouts on
`/proposta` and `/atualizacao` under public rate limiting; those endpoints
are outside the independent publicação bound. Publicação enumeration for the
bound completed (pages completed for mod4).

A later time-drift contrast run (~16 minutes after inventory) enumerated 26
open controls (`stats-timedrift-contrast.json`); fidelity against the frozen
inventory then reports 11 `extra_submission` (records that opened after the
inventory snapshot) — temporal drift of a live high-volume source, not an
adapter defect. Primary fidelity uses the synchronized run.

## 4. Independent fidelity audit

```
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/pncp/technical-audit-2026-09-14/independent-inventory.json `
  --discovery docs/evidence/sources/pncp/technical-audit-2026-09-14/discovery.json `
  --out docs/evidence/sources/pncp/technical-audit-2026-09-14/fidelity
```

Result (synchronized run): **EXIT=0** — `source fidelity OK: no blocking
exceptions`. Summary: pass=true, total_blocking_exceptions=0,
inventory_accounting_pct=100.0 (15/15 open-in-scope),
candidate_traceability_pct=100.0 (15/15), non_blocking_exception_count=15
(`missing_optional_metadata` for published_at/deadline the candidate
discovery JSON shape leaves null — inventory carries them).

Time-drift contrast: EXIT=1, 11 extra_submission (expected; see §3).

## 5. Source-local fixes

**None.** No defect was found inside `scripts/discover_pncp_candidates.py`,
`scripts/pncp_filters.py`, or `scripts/pncp_http.py` that is source-local and
reproducible against the synchronized independent bound. Lifecycle filtering,
principal-document selection, candidate identity
(`numeroControlePNCP`/`sequencialDocumento`), page-cap watermark semantics,
and fail-closed empty-search handling all behaved as contracted. No files
under the pncp adapter/tests were modified.

## Hygiene

- No cookies/headers/personal data/tokens stored in evidence.
- Scratch scripts and raw captures live under `%TEMP%\pncp_audit_*\` and are
  removed at the end of the session.
- `scripts/run_independent_source_audit.py` was NOT used as evidence.
- Production PNCP checkpoint was never read from or written to
  `.cache/pncp_update_checkpoint.json`.
