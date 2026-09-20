# RESULT — msgov source-adapter technical audit (2026-09-14)

RESULT: fixed

## Structured fields

- RESULT: fixed
- SOURCE: msgov
- EXPECTED CONTRACT: candidate — module=`discover_msgov_candidates`;
  group=c; rollout_mode=ingest; schedule_owner=`pipeline-discovery-group-c.yml`;
  interval 60 min; filter_policy=default; detail_limit=20, page_limit=5,
  attachment_limit=25; browser_required=TRUE (Playwright); catalog active.
  Official entry point: `https://editaisms.prosas.com.br` (Prosas web
  component listing for the Mato Grosso do Sul “Editais” portal;
  client-id public; open tab = `inscricoes_abertas`).
- OBSERVED CONTRACT: candidate (post-fix) — audit-only orchestrator path
  (`scripts/discover_all_candidates.py`, SOURCES=msgov) emits PDF
  candidates with `kind=pdf`, metadata.source=`msgov`, stable
  canonical_url/source_record_id, status=`open`; no contract drift.
  Adapter still requires RENDER_APP_URL/PIPELINE_SECRET only on the
  submit path (not exercised).
- LIFECYCLE HOLD: none in registry (rollout_mode=ingest, catalog active).
  This audit is audit-mode only (discovery without submission). No
  snapshot/RR-05/release-decision change claimed. No catalog lifecycle
  mutation performed.
- OFFICIAL INVENTORY: open=29 (PDFs across 23 editais), closed=125,
  upcoming=0, excluded=0, unknown=0 (capture 2026-09-14T20:49Z–21:12Z;
  open API HTTP 200 one page of size 100; closed API HTTP 200 pages 1–2;
  3 open editais have null deadline / continuous flow; UI open tab
  renders only 20 of 23 with next-page control present in shadow DOM).
- DISCOVERY (post-fix, `stats-postfix.json`): emitted=29, rejected
  (non-PDF filter)=0 counted separately (annexes no longer candidates),
  errors=0, partial=false, cap_reached=false (details_fetched=23 =
  full open set; candidates=29 ≤ cap 50; listings paginated to include
  page-2 ids 16859/16862/17087). Pre-fix (`stats-prefix.json`):
  candidates=50, candidate_cap_reached=1 — 29 `.doc` annexes crowded
  out 8 real PDFs (partial inventory).
- FIDELITY: exit code=0; blockers=0; open-record accounting=100.0%
  (29/29); candidate traceability=100.0% (29/29);
  non_blocking exceptions=29 (`missing_optional_metadata` for
  deadline/status the candidate contract does not carry on discovery);
  no hidden cap/partial post-fix. Match method=stable_id for all 29.
- TESTS:
  - `py -3.13 --version` → Python 3.13.5
  - Pre-fix: `py -3.13 -m pytest tests/test_msgov_discovery.py -q`
    → 9 passed in 0.20s
  - Post-fix: `py -3.13 -m pytest tests/test_msgov_discovery.py -q`
    → 14 passed in 0.26s (5 new: pagination, stable identity ×2,
    PDF filter ×2; base listing test updated so `.doc` is no longer a
    candidate)
- CHANGES:
  1. `scripts/discover_msgov_candidates.py` —
     (a) **Listing pagination**: walk the Prosas next-page control in the
     `prosas-listagem-editais` shadow DOM up to `MSGOV_MAX_LISTING_PAGES`
     (default 5 = registry page_limit). Root cause: the component renders
     20 editais per page; the open set was 23, so ids 16859/16862/17087
     were never visited and their PDFs never became candidates.
     (b) **Stable candidate identity**: `_stable_pdf_identity` strips
     Oracle preauthenticated `/p/<token>/` path segments and query
     strings; surfaced as `metadata.canonical_url` /
     `metadata.source_record_id` (and `status=open`) so discovery
     artifacts are comparable across runs while `candidate["url"]`
     keeps the signed download href.
     (c) **PDF-only candidate filter**: `_is_pdf_candidate_href` drops
     explicit office/archive suffixes even on amazonaws/objectstorage
     hosts. Root cause of the pre-fix cap: the historical
     `or "amazonaws.com" in href` catch-all admitted `.doc` annexes that
     only ever failed magic-byte validation later; 29 docs + 21 PDFs
     hit the cap of 50 and dropped 8 PDFs (partial inventory).
  2. `tests/test_msgov_discovery.py` — multi-page fake harness
     (`listing_pages`); regression tests
     `TestListingPagination.test_collects_detail_urls_across_listing_pages`,
     `TestStablePdfIdentity` (×2), `TestPdfCandidateFilter` (×2);
     base listing test updated: `.doc` annex rejected at discovery.
- EVIDENCE:
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/capture-log.md
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/stats-prefix.json
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/stats-postfix.json
  - docs/evidence/sources/msgov/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. Oracle objectstorage preauthenticated `/p/<token>/` URLs expire;
     discovery re-fetches fresh signed hrefs each run, so `candidate["url"]`
     is only valid shortly after discovery. The stable identity used for
     audit matching is independent of the token (by design).
  2. Prosas UI page size (20) is a component default; if it changes, the
     adapter still walks next-page up to 5 pages (100 editais) which
     matches registry page_limit=5. A future open set >100 would need a
     page_limit bump.
  3. The non-PDF filter is extension-based; a PDF hosted without a
     `.pdf` suffix on S3/objectstorage still passes via the host
     catch-all, but an annex renamed to look like a PDF would be emitted
     (magic-byte check still rejects at download).
  4. Three open editais (16859/16862/17087) have null deadlines
     (continuous flow); discovery does not carry deadlines under the
     candidate contract (non-blocking `missing_optional_metadata` only).
  5. Independent inventory is a point-in-time capture (2026-09-14T20:49Z–
     21:12Z). Two-clean-audit soak and RR-05 remain OPEN; this result
     does not complete them.
- ESCALATION: none.
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches,
  deploys, submissions, catalog mutations, or Repo A calls). Audit-only
  dry runs submitted nothing.

## Ground truth summary (live official source, 2026-09-14)

- Listing HTTP 200; Prosas `inscricoes_abertas` API HTTP 200 → 23 open.
- Closed-tab API HTTP 200 → 125 closed.
- UI open tab renders 20/23 with working next-page control (shadow DOM).
- All 23 open details expose ≥1 PDF after Complementares expand.
- Zero upcoming / excluded / unknown on the official source at capture time.
