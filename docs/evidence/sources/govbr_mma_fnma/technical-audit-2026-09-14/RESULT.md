# govbr_mma_fnma technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: govbr_mma_fnma
EXPECTED CONTRACT: candidate; module=discover_govbr_mma_fnma_candidates; group=a; rollout audit; schedule_owner=pipeline-discovery-group-a.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; single official listing `https://www.gov.br/mma/pt-br/composicao/secex/dfre/fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1`; TDR excluded by default (source-local opt-in only); min year 2026
OBSERVED CONTRACT: candidate — post-fix audit-only discovery emits exactly the one principal edital PDF for Edital FNMA 1/2026 – Iniciativa ArborizaCidades with authoritative status=closed (application deadline 2026-07-13 already past as of 2026-09-14 despite residual open/prorrogação wording on the page); retificação PDF is related document metadata, never a standalone candidate
LIFECYCLE HOLD: none in registry (rollout_mode=audit / catalog active). Audit-mode only (discovery without ingestion). No snapshot/RR-05/release-decision change claimed.
OFFICIAL INVENTORY: open=0, closed=1, upcoming=0, excluded=0, unknown=0
DISCOVERY: emitted=1, rejected=0 (prefilter=0, year=0), errors=0, partial=false, cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (open-in-scope denominator=0; no open rows required), traceability%=100.0 (1/1)
TESTS: `py -3.13 -m pytest tests/test_govbr_mma_fnma_discovery.py -q` → 26 passed (24 pre-existing + 2 `TestStaleOpenPastDeadline` regression)
CHANGES:
- scripts/discover_govbr_mma_fnma_candidates.py — (prior uncommitted session fix, retained) in `_extract_listing_metadata`, when a deadline is extracted and status is `open`, force `status="closed"` if `deadline < today(UTC)`; addresses authoritative_status_mismatch from stale open wording after the application window
- tests/test_govbr_mma_fnma_discovery.py — (prior uncommitted session) added `TestStaleOpenPastDeadline` (past deadline overrides open wording → closed; future deadline stays open); (this session) fixed fixture date formatting: ISO date was incorrectly split as day/month/year producing `YYYY/MM/DD`; now formatted as `dd/mm/yyyy` via `strftime`
- docs/evidence/sources/govbr_mma_fnma/technical-audit-2026-09-14/independent-inventory.json — refreshed to live-observed title (en-dash), status=closed, deadline=2026-07-13, principal+retificação document_urls
EVIDENCE: docs/evidence/sources/govbr_mma_fnma/technical-audit-2026-09-14/{RESULT.md,commands.md,independent-inventory.json,discovery.json,stats-postfix.json,candidates-postfix.json,discovery-source-inventory.json,discovery-run/,fidelity/}
RISKS: the past-deadline→closed rule only applies when a deadline was successfully extracted; a page that retains open wording without any parseable deadline would still emit status=unknown/open wording path — FNMA page currently always states a deadline with prorrogação text. Listing remains single-page; a future multi-page/multi-edital expansion may need per-block metadata rather than whole-content-root status. Residual risk is Portuguese wording drift on gov.br pages.
ESCALATION: none
PRODUCTION ACTIONS: none

## Ground truth (live official page, 2026-09-14)

- Official listing: `https://www.gov.br/mma/pt-br/composicao/secex/dfre/fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1` (single page; page_limit not approached).
- Principal edital: Edital FNMA 1/2026 – Iniciativa ArborizaCidades; publication stage 07/05/2026; proposal window originally until 6 July, prorrogada até 13/7/2026 23h59 (Brasília) → deadline 2026-07-13 (past → closed).
- Related document (not a candidate): `RetificaodoEditaln01de2026IniciativaArborizaCidades.pdf` (retificação — new municipalities in Anexos X–XVIII).
- Document URLs GET-verified HTTP 200 application/pdf.
- No open/upcoming editais on the page; evaluation/homologation stages in Quadro 2 are process stages, not open call windows.
- No TDR PDFs currently listed; min-year guard 2026 drops any pre-2026 links if present.

## Pre-fix baseline (retained for provenance)

- Prior session independent-inventory recorded the same record as `closed` (deadline 2026-07-13) while the then-current adapter emitted `open` from residual "prorroga/abert" wording.
- Pre-fix fidelity: pass=false; blocking `authoritative_status_mismatch` ×1 (field=status, inventory=closed, discovery=open); candidate_traceability 100% (1/1); inventory accounting 100% (0/0 open-in-scope).
- Post-fix (this session): same inventory vs fresh discovery → status closed=closed, deadline match, zero blockers, pass=true.
