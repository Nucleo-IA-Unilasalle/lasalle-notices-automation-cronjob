# FAO technical audit — 2026-09-14

RESULT: fixed

Shell access was available this session (`py -3.13` → Python 3.13.5). The
prior blocked markers are replaced by this completed audit. A small
source-local defect was confirmed against the live official entry page and
fixed with regression tests; independent fidelity now passes.

## Defect (confirmed, pre-fix)

The official entry page
`https://www.fao.org/plant-treaty/areas-of-work/funding/` is the **Funding
Strategy policy page** (server-rendered, HTTP 200), not an open-call
listing. Independent capture found **zero** open/closed/upcoming
opportunities and six on-host `.pdf` anchors that are strategy/resolution
governance documents.

The adapter's signal regex still included `funding strategy` and
`resolution`, so the safe audit path emitted **3 false-positive
candidates** (nb780en.pdf, no028en.pdf, cc3636en.pdf). Independent
fidelity against an empty open-opportunity inventory returned **exit 1**
with 3× `extra_submission` and candidate traceability 0%
(`fidelity-before-fix/`, `discovery-before-fix.json`).

## Fix (source-local, ≤150 lines / 2 production files)

- `scripts/discover_fao_candidates.py`: narrowed the signal regex to
  open-call tokens only —
  `call for proposals|request for proposals|expression of interest|eoi|procurement` —
  dropping `funding strategy` and `resolution`. Docstrings updated.
- `tests/test_fao_discovery.py`: two regression tests locking the
  exclusion of strategy/resolution governance PDFs (including the live
  page's anchor set) while still discovering call-for-proposals PDFs.

## Post-fix verification

- Focused tests: `py -3.13 -m pytest tests/test_fao_discovery.py -q` → **17 passed**.
- Safe audit path (`DISCOVERY_AUDIT_ONLY=true`, `SOURCES=fao`): **0
  candidates**, `errors=0`, `candidate_cap_reached=0`,
  `playwright_fallback_used=1` (BS4 empty → Playwright ran, also found 0).
- Independent fidelity vs `independent-inventory.json` (`[]`): **exit 0**,
  0 blocking exceptions, inventory accounting **100%**, candidate
  traceability **100%** (healthy empty 0/0), no hidden cap/partial
  (`fidelity/`).

## Lifecycle / holds

Catalog lifecycle for fao remains **active**; no holds were changed,
removed, or modified. Registry entry (`config/source_schedule.json`) was
not edited. Shared coordinator-owned files were read-only. Pre-existing
working-tree changes to other sources (fapergs, govbr_mma_fnma, iis_rio)
were preserved untouched.

## Residual risks

- The source still has no open opportunities; production runs will
  legitimately report 0 candidates. If ITPGRFA later publishes a new call
  (e.g. a sixth BSF cycle) on a page other than the funding listing, the
  adapter will not see it until the listing URL or discovery logic is
  extended — a product/scope decision, not a regression of this fix.
- Related BSF pages were probed for provenance only (fifth cycle closed
  29 Jul 2022); they remain outside the configured entry point.
- Playwright fallback still runs when BS4 yields zero PDFs (by design for
  `browser_required=TRUE`); with the narrowed signals this is expected on
  the current page.

## Structured result

RESULT: fixed
SOURCE: fao
EXPECTED CONTRACT: candidate (config/source_schedule.json `submission_contract`),
  module discover_fao_candidates, group a, rollout_mode ingest, schedule_owner
  pipeline-discovery-group-a.yml, interval 60min, detail_limit 20, page_limit 5,
  attachment_limit 25, browser_required TRUE (Playwright), filter_policy default;
  catalog_status active; official entry point
  https://www.fao.org/plant-treaty/areas-of-work/funding/
OBSERVED CONTRACT: candidate — discovery runs offline-safe audit path; emits
  PDF candidates only; after fix emits 0 candidates with errors=0 and no cap;
  Playwright fallback invoked only when BS4 finds no open-call PDFs; no
  opportunity/structured contract observed (matches candidate contract).
LIFECYCLE HOLD: none; catalog lifecycle for fao remains active; no holds
  changed, removed, or modified.
OFFICIAL INVENTORY: open 0, closed 0, upcoming 0, excluded 4 unique on-host PDFs
  (nb780en, no028en, cc3636en, cc3626en — strategy/resolution/engagement
  governance materials), unknown 0; no pagination; no HTTP errors;
  independent-inventory.json = [] (zero open opportunities on the entry page).
DISCOVERY: emitted 0 (post-fix; pre-fix was 3 false positives), rejected n/a
  (no separate reject counter; filtering is extractor-level), errors 0,
  partial false, cap reached false (candidate_cap_reached=0).
FIDELITY: exit code 0 (post-fix; pre-fix against same inventory was exit 1 with
  3 extra_submission), blockers 0, accounting 100% (0/0), traceability 100% (0/0).
TESTS: `py -3.13 -m pytest tests/test_fao_discovery.py -q` → 17 passed (6.24s)
  after fix; 15 passed before fix. Full suite not re-run (out of bounded scope);
  no shared-contract files touched.
CHANGES:
  - scripts/discover_fao_candidates.py — drop `funding strategy`/`resolution`
    from open-call signal regex; update docstrings (false-positive fix).
  - tests/test_fao_discovery.py — two regression tests for governance-PDF
    exclusion and live-page zero-signal shape.
  - docs/evidence/sources/fao/technical-audit-2026-09-14/* — full evidence
    package (inventory, discovery copies, fidelity before/after, logs).
EVIDENCE: docs/evidence/sources/fao/technical-audit-2026-09-14/
  (RESULT.md, capture-log.md, commands.md, independent-inventory.json,
  discovery.json, stats.json, discovery-before-fix.json, stats-before-fix.json,
  fidelity/, fidelity-before-fix/)
RISKS: see Residual risks above — no open calls currently; future calls hosted
  off the listing URL would require a deliberate scope change.
ESCALATION: none — defect was isolated to fao signal filtering, fixed within
  source-local bounds.
PRODUCTION ACTIONS: none
