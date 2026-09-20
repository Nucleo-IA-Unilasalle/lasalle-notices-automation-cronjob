# UNEP technical audit — 2026-09-14

RESULT: fixed

Shell access was available this session (`py -3.13` → Python 3.13.5). A
small source-local defect was confirmed against the live official entry page
and fixed with regression tests; independent fidelity now passes.

## Defect (confirmed, pre-fix)

The official entry page
`https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding`
is the GFC Fund "Applying for funding" landing page (server-rendered, HTTP
200). Independent capture found **zero open opportunities**: the second
application round launched 30 September 2025 and **closed 15 December 2025**;
Stage-2 full proposals were due mid-June 2026; no third round is advertised.
The page permanently links **4 standing PDFs** on `wedocs.unep.org`: three
GFC Fund scope-guidance translations (EN/FR/SP) and one Stage-1 concept-note
template.

The adapter's signal regex still included the generic tokens `concept note`
and `gfc fund`, so the safe audit path emitted **4 false-positive
candidates** (all four standing PDFs). Independent fidelity against an empty
open-opportunity inventory returned **exit 1** with 4× `extra_submission` and
candidate traceability 0% (`fidelity-before-fix/`,
`discovery-before-fix.json`).

## Fix (source-local, ≤150 lines / 2 production files)

- `scripts/discover_unep_candidates.py`: narrowed the signal regex to
  open-call tokens only —
  `call for proposals|applying for funding|request for proposals` —
  dropping generic `gfc fund` branding and the standing `concept note`
  template. Docstrings updated; module docstring made raw (SyntaxWarning).
- `tests/test_unep_discovery.py`: updated fixture expectations; added two
  regression tests locking the exclusion of the live page's guidance /
  concept-note PDFs and of bare `gfc fund` branding while still discovering
  call-for-proposals PDFs.

## Post-fix verification

- Focused tests: `py -3.13 -m pytest tests/test_unep_discovery.py -q` →
  **26 passed** (was 24 before fix).
- Safe audit path (`DISCOVERY_AUDIT_ONLY=true`, `SOURCES=unep`): **0
  candidates**, `errors=0`, `candidate_cap_reached=0`.
- Independent fidelity vs `independent-inventory.json` (`[]`): **exit 0**,
  0 blocking exceptions, inventory accounting **100%**, candidate
  traceability **100%** (healthy empty 0/0), no hidden cap/partial
  (`fidelity/`).

## Lifecycle / holds

Catalog lifecycle for unep remains **active**; no holds were changed,
removed, or modified. Registry entry (`config/source_schedule.json`) and
catalog contract were not edited. Shared coordinator-owned files were
read-only. Pre-existing working-tree changes to other sources were preserved
untouched.

## Residual risks

- The source currently has no open opportunities; production runs will
  legitimately report 0 candidates. When UNEP launches a third round, the
  adapter will only emit candidates if the new call's PDF anchors carry an
  open-call token (`call for proposals`, `request for proposals`, or
  `applying for funding`). If the round is advertised only via the same
  standing concept-note template or via wording such as "call for
  applications", discovery would miss it — a deliberate scope decision; a
  future audit should extend the signal set (or add lifecycle parsing) when
  a new round is observed.
- The adapter has no deadline/lifecycle parsing of page prose; closed-round
  exclusion currently relies on the signal-token narrowing. A future round
  page shape that reuses open-call wording on closed material could
  reintroduce false positives.
- wedocs.unep.org bitstream URLs redirect plain HTTP clients to DSpace SPA
  item pages (`text/html`) rather than streaming PDFs; discovery is
  unaffected (listing anchors are server-rendered), but PDF download/OCR of
  a future open call may need DSpace-aware fetch handling — out of scope for
  this discovery audit.

## Structured result

RESULT: fixed
SOURCE: unep
EXPECTED CONTRACT: candidate (config/source_schedule.json `submission_contract`),
  module discover_unep_candidates, group c, rollout_mode audit, schedule_owner
  pipeline-discovery-group-c.yml, interval 60min, detail_limit 20, page_limit 5,
  attachment_limit 25, browser_required false, filter_policy default;
  catalog_status active; official entry point
  https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding
OBSERVED CONTRACT: candidate — discovery runs offline-safe audit path; emits
  PDF candidates only; after fix emits 0 candidates with errors=0 and no cap;
  no opportunity/structured contract observed (matches candidate contract).
LIFECYCLE HOLD: none; catalog lifecycle for unep remains active; no holds
  changed, removed, or modified.
OFFICIAL INVENTORY: open 0, closed 1 (GFC Fund second round: launched
  30 Sep 2025, concept-note stage closed 15 Dec 2025, Stage-2 due mid-June
  2026), upcoming 0, excluded 4 unique standing PDFs (3× scope guidance
  EN/FR/SP + 1 concept-note template on wedocs.unep.org), unknown 0; no
  pagination; no HTTP errors on the listing; independent-inventory.json = []
  (zero open opportunities on the entry point).
DISCOVERY: emitted 0 (post-fix; pre-fix was 4 false positives), rejected n/a
  (no separate reject counter; filtering is extractor-level), errors 0,
  partial false, cap reached false (candidate_cap_reached=0).
FIDELITY: exit code 0 (post-fix; pre-fix against same inventory was exit 1
  with 4 extra_submission), blockers 0, accounting 100% (0/0), traceability
  100% (0/0).
TESTS: `py -3.13 -m pytest tests/test_unep_discovery.py -q` → 26 passed
  (6.27s) after fix; 24 passed before fix. Full suite not re-run (out of
  bounded scope); no shared-contract files touched.
CHANGES:
  - scripts/discover_unep_candidates.py — drop `concept note`/`gfc fund` from
    open-call signal regex; update docstrings (false-positive fix).
  - tests/test_unep_discovery.py — updated fixture expectations; two
    regression tests for standing-PDF exclusion and branding-token exclusion.
  - docs/evidence/sources/unep/technical-audit-2026-09-14/* — full evidence
    package (inventory, discovery copies, fidelity before/after, logs).
EVIDENCE: docs/evidence/sources/unep/technical-audit-2026-09-14/
  (RESULT.md, capture-log.md, commands.md, independent-inventory.json,
  discovery.json, stats.json, discovery-before-fix.json, stats-before-fix.json,
  fidelity/, fidelity-before-fix/)
RISKS: see Residual risks above — no open calls currently; future rounds
  advertised without open-call wording would need a deliberate signal/lifecycle
  extension.
ESCALATION: none — defect was isolated to unep signal filtering, fixed within
  source-local bounds.
PRODUCTION ACTIONS: none
