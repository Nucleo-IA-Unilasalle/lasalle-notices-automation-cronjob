# RESULT — PNCP source-adapter technical audit (2026-09-14)

RESULT: pass

## Structured fields

- RESULT: pass
- SOURCE: pncp
- EXPECTED CONTRACT: candidate — module=`discover_pncp_candidates`;
  group=pncp; rollout_mode=ingest; schedule_owner=`pipeline-pncp-discovery.yml`;
  interval 60 min; filter_policy=default; detail_limit=20, page_limit=5,
  attachment_limit=25; browser_required=false; catalog active.
  PNCP has its OWN orchestrator path: `run_managed_source.py` accepts
  `scripts/discover_pncp_candidates.py` only for `pncp` (every other key uses
  `discover_all_candidates.py`). Queue identity:
  `numeroControlePNCP`/`sequencialDocumento`. Update watermark advances only
  after complete, uncapped enumeration; partial scans leave the prior
  checkpoint untouched. Official APIs:
  `https://pncp.gov.br/api/consulta/v1/contratacoes/{publicacao|proposta|atualizacao}`,
  docs `https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos`.
  Modalities 6/8/4; anoCompra ≥ 2026; UF filter RS + four federal CNPJs.
- OBSERVED CONTRACT: candidate (no drift) — library dry-run of
  `discover_candidates()` emits PDF candidates with `kind=pdf`,
  metadata keyed by `numeroControlePNCP`/`sequencialDocumento`, principal
  docs filtered to edital / aviso de contratação direta / termo de referência.
  Checkpoint never advanced on the dry-run path. No credential requirement
  for discovery-only library use.
- LIFECYCLE HOLD: none in registry (`rollout_mode=ingest`, catalog active).
  This audit is audit-mode only (discovery without submission). No
  snapshot/RR-05/release-decision change claimed. No catalog lifecycle
  mutation performed. No audit/paused hold removed.
- OFFICIAL INVENTORY (documented bound: RS + modality 4 only,
  publication window 20260913..20260914, capture 2026-09-14T22:25:46Z–
  22:26:49Z): open=15, closed=4, upcoming=11, excluded=0, unknown=0
  (30 unique controls; one page; no page cap). 15/15 open controls have
  principal documents. **Out of bound** (documented failure-signal
  contrast only): modalities 6/8, federal CNPJ sweeps, `/proposta` and
  `/atualizacao`. Full-day multi-modality probe showed open=150 across
  639 RS controls for 20260914 and a 30-day mod6 window of 3076 records /
  62 pages — beyond a single bounded audit under public rate limits.
- DISCOVERY (synchronized dry-run, `stats.json`): emitted=15 open controls
  (47 raw preferred-doc candidates aggregated by control), rejected
  (pre_download_rejected)=0, errors (document_failures)=0, partial=
  `search_failures=2` (read timeouts on `/proposta` + `/atualizacao` only —
  outside the publicação independent bound; publicação pages for mod4
  completed), cap reached: no (candidate_cap_reached=0, page cap not hit
  inside the bound, document lookups 15/100). Year rejections of pre-2026
  records are expected noise on the publicação feed. Time-drift contrast
  ~16 min later emitted 26 open controls (`stats-timedrift-contrast.json`).
- FIDELITY (synchronized): exit code=0; blockers=0; open-record
  accounting=100.0% (15/15); candidate traceability=100.0% (15/15);
  non_blocking exceptions=15 (`missing_optional_metadata` — discovery JSON
  leaves published_at/deadline null; inventory carries them). No hidden
  cap/partial inside the bound. Time-drift contrast: exit 1, 11
  extra_submission (records that became open after the inventory snapshot;
  temporal drift of a live source, not an adapter defect).
- TESTS:
  - `py -3.13 --version` → Python 3.13.5
  - `py -3.13 -m pytest tests/test_pncp_discovery.py tests/test_pncp_filters.py tests/test_pncp_safety.py tests/test_pncp_opportunity_normalization.py tests/test_pncp_backfill.py -q`
    → **108 passed** (baseline and final confirmation)
- CHANGES: none (no adapter/test/fixture edit; no shared-file edit).
- EVIDENCE:
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/capture-log.md
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/capture-summary.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/stats.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/discovery-run-summary.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/full-day-mod-all-summary.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/stats-timedrift-contrast.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/fidelity-timedrift-contrast-summary.json
  - docs/evidence/sources/pncp/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. **High volume / production page caps**: a full RS multi-modality
     lookback window exceeds page_limit and hits the adapter’s
     `PNCP_MAX_PAGES_PER_QUERY=20` / candidate caps by design; watermark
     correctly refuses to advance on capped scans, but each production run
     may only process a prefix (`PNCP_MAX_CANDIDATES_PER_RUN=10` default).
     Independent fidelity against a *full* production window was not
     claimed.
  2. **Public API rate limits (429) and intermittent read timeouts** on
     `/proposta`/`/atualizacao` caused `search_failures` on some dry-run
     retries; the adapter fail-closes partial search into
     `partial_inventory` telemetry and does not advance the watermark on
     incomplete scans (correct), but ops should expect flaky listing
     streams.
  3. **Live temporal drift**: open set changes within minutes on
     publication day; inventory and discovery must be captured tightly
     synchronized or fidelity reports spurious `extra_submission`.
  4. **Bounded representative scope**: only RS + modality 4 +
     publicação was independently inventoried end-to-end. Modalities 6/8,
     federal CNPJs, proposta/atualizacao remain unaudited at full
     inventory depth in this pass.
  5. PNCP candidate contract does not carry published_at/deadline on the
     discovery JSON shape (`missing_optional_metadata` non-blocking);
     full opportunity v2 shadow path exists but was not the audit target.
  6. Two-clean-audit soak and RR-05 remain OPEN; this result does not
     complete them.
- ESCALATION: none. No source-local defect required a fix; no shared
  contract, schema, auth, workflow, admission, or multi-source change was
  needed. If a full-window independent inventory is later required,
  re-run as a dedicated high-volume capture task (not this bounded pass).
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches,
  deploys, submissions, catalog mutations, Repo A calls, or checkpoint
  writes). Dry runs submitted nothing; production checkpoint path was
  never written.

## Ground truth summary (live official source, 2026-09-14)

- Publicação HTTP 200 for bound query → 30 RS Concorrência Eletrônica
  controls over 20260913–20260914 (one page).
- Lifecycle: 15 open / 4 closed / 11 upcoming / 0 excluded / 0 unknown.
- Docs API HTTP 200 × 15 open controls; all 15 expose ≥1 preferred
  principal document (edital / termo de referência family).
- Synchronized discovery dry-run: 15/15 open controls, 0 blockers,
  100% accounting and traceability.
- High-volume contrast: full RS day across mods 6/8/4 = 639 controls /
  150 open — unbounded production-window fidelity not claimed.
