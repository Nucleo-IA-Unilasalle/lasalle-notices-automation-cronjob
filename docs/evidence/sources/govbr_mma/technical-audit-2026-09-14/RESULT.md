# RESULT — govbr_mma source-adapter technical audit (2026-09-14)

RESULT: fixed

## Structured fields

- RESULT: fixed
- SOURCE: govbr_mma
- EXPECTED CONTRACT: candidate — module=`discover_govbr_mma_candidates`;
  group=b; rollout_mode=ingest; schedule_owner=`pipeline-discovery-group-b.yml`;
  interval 60 min; filter_policy=default; detail_limit=20, page_limit=5,
  attachment_limit=25; browser_required=false; catalog active. Official
  listing: `https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais`
  (Plone `#content-core #parent-fieldname-text`; detail pages scanned for
  `.pdf` anchors; min year 2026 via `GOVBR_MMA_MIN_NOTICE_YEAR`; default
  `is_likely_edital` prefilter). Distinct from `govbr_mma_fnma` and
  `govbr_mma_public_calls` — those adapters were not touched.
- OBSERVED CONTRACT: candidate (post-fix) — audit-only orchestrator path
  (`scripts/discover_all_candidates.py`, SOURCES=govbr_mma) emits PDF
  candidates with `kind=pdf`, metadata.source=`govbr_mma`, no contract drift.
  Adapter still requires RENDER_APP_URL/PIPELINE_SECRET only on the
  submit path (not exercised).
- LIFECYCLE HOLD: none in registry (rollout_mode=ingest, catalog active).
  This audit is audit-mode only (discovery without submission). No
  snapshot/RR-05/release-decision change claimed. No catalog lifecycle
  mutation performed.
- OFFICIAL INVENTORY: open=0, closed=10, upcoming=0, excluded=5
  (subset of the 10 closed rows carrying explicit
  `reason_code=out_of_scope` for prefilter/year-guard exclusions),
  unknown=0. The only substantive public call on the listing is the
  2017 Chamamento Público de Locação de Imóvel (proposal deadline
  20/01/2017 per edital item 7.1; result notices published) — closed
  as of 2026-09-14. No open 2026+ calls found on the official listing
  or its one-level detail pages. Year subpages (compras-diretas 2016/2018/2020,
  atas 2017/2018/2020) hold only historical PDFs (all years < 2026).
- DISCOVERY (post-fix, `stats-postfix.json`): emitted=5, rejected
  (prefilter=4, year=1), errors=0, partial=false, cap_reached=false
  (details_fetched=5 ≤ detail_limit 20; candidates=5 ≤ attachment/candidate
  caps; no pagination cap on the single-page listing).
- FIDELITY: exit code=0; blockers=0; inventory accounting=100.0%
  (0/0 open-in-scope — zero open rows require emission);
  candidate traceability=100.0% (5/5); non-blocking exceptions=11
  (5× `out_of_scope` for correctly excluded errata/resultado/portaria
  documents + 6× `missing_optional_metadata` for status/deadline fields
  the candidate contract does not carry). No hidden cap/partial.
- TESTS:
  - `py -3.13 --version` → Python 3.13.5
  - Pre-fix: `py -3.13 -m pytest tests/test_govbr_mma_discovery.py -q`
    → 21 passed in 0.26s
  - Post-fix: `py -3.13 -m pytest tests/test_govbr_mma_discovery.py -q`
    → 22 passed in 0.26s (new `test_skips_dead_resolveuid_stubs`)
- CHANGES:
  1. `scripts/discover_govbr_mma_candidates.py` — in
     `extract_govbr_mma_detail_urls`, skip canonical URLs containing
     `/resolveuid/`. Root cause: the live MMA listing still carries a
     Plone UID stub ("PLANO ANUAL DE CONTRATAÇÕES 2020" →
     `resolveuid/d15fde…`) that HTTP 404s; the shared transport counted
     that as `errors=1`, and the audit orchestrator correctly failed the
     run as a partial inventory (EXIT=1, "inventory is partial"). Real
     edital sections on this listing are always linked by canonical path.
  2. `tests/test_govbr_mma_discovery.py` — added
     `test_skips_dead_resolveuid_stubs` regression (resolveuid anchor
     dropped; valid sibling detail kept).
- EVIDENCE:
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/capture-log.txt
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/stats-prefix.json
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/stats-postfix.json
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/candidates-postfix.json
  - docs/evidence/sources/govbr_mma/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. The 5 emitted candidates are all PDFs of the closed 2017 chamamento
     (URLs contain no year token, so the year guard passes them through
     with `extracted_year=null` — documented pass-through behaviour of
     plan §9). In ingest mode these would be OCR'd and submitted as
     candidate records without a status field; Repo A dedupe/hash
     limits repeat damage, but the source produces no genuinely open
     calls today. Operators should treat govbr_mma as a low-yield source
     until a new edital appears.
  2. Detail pages with zero PDFs (licitações, compras-diretas,
     ata-de-registro-de-preco) are navigational indexes; if MMA adds a
     2026+ edital as a direct PDF on the listing or as a new detail page,
     discovery will pick it up on the next 60-min run — no code change
     needed. Conversely, a new edital nested two levels deep (index →
     year → detail) would NOT be found (single-level crawl, by design).
  3. The year guard extracts the **max** year token from the URL; a
     future URL containing both an old and a new year could be mis-scoped.
     Not observed on the live listing today.
  4. The resolveuid skip is deliberately narrow (`/resolveuid/` in the
     canonical path). If MMA ever publishes a real detail page under a
     path containing that substring (unlikely), it would be skipped.
  5. Independent inventory is a point-in-time capture (2026-09-14T20:28Z–20:35Z).
     Two-clean-audit soak and RR-05 remain OPEN; this result does not
     complete them.
- ESCALATION: none.
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches,
  deploys, submissions, catalog mutations, or Repo A calls).

## Ground truth summary (live official page, 2026-09-14)

- Listing HTTP 200, `#content-core #parent-fieldname-text` present.
- Internal detail links: licitações, compras-diretas, ata-de-registro-de-preço,
  chamamento-público-locação-de-imóvel, portarias + 1 dead resolveuid stub
  (fixed out of the crawl set).
- Chamamento Público Locação de Imóvel: 9 PDFs, all HTTP 200
  application/pdf. Edital text: proposals until 20/01/2017 → closed.
  Result notices (3× aviso-resultado + errata) confirm conclusion.
- Portarias: 1 PDF (Portaria 220/2016, Equipe de Pregão) — year-guard
  rejected (2016 < 2026).
- Zero open opportunities on the official source as of capture time.
