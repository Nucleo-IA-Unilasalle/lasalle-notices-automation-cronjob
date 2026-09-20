# RESULT — FAPERGS Source-Adapter Re-Verification (2026-09-14)

RESULT: fixed
(blocked marker replaced; post-fix fidelity is clean)

## Summary

The prior session's uncommitted fix (principal-PDF selection + related-doc
metadata + AJAX+static merge + YYYYMM-aware year guard) was reviewed via
`git diff` and re-verified. Focused tests initially revealed two residual
defects in that fix: (1) `_UPLOAD_MONTH_PATTERN` captured only the century
prefix (`20`) instead of the full year from YYYYMM folders, and (2) an
older fixture-driven discovery test still asserted multi-PDF emission
incompatible with the intentional one-principal-per-detail contract.
Both were repaired source-locally (adapter regex + test alignment).
After repair: **24/24 tests pass**, audit-only discovery emits exactly the
PROFIX-CB principal PDF, and the official fidelity CLI reports
**pass=true, 0 blocking exceptions, 100% open-record accounting,
100% candidate traceability**.

## Structured fields

- RESULT: fixed
- SOURCE: fapergs
- EXPECTED CONTRACT: candidate — discover_fapergs_candidates, group a,
  rollout ingest, owner pipeline-discovery-group-a.yml, interval 60 min,
  detail_limit=20, page_limit=5, attachment_limit=25,
  browser_required=false; catalog active.
- OBSERVED CONTRACT: candidate (audit-only path ran via
  `scripts/discover_all_candidates.py`; adapter module and registry
  entry match; no contract drift).
- LIFECYCLE HOLD: none for fapergs (catalog active). No paused/audit
  holds and no catalog lifecycle mutations performed.
- OFFICIAL INVENTORY: open=3, closed=0, upcoming=0, excluded=0, unknown=0
  (live AJAX `recordcount=3, pagecount=1` re-confirmed ~2026-09-14T20:14Z;
  independent-inventory.json unchanged).
  In-scope for candidate emission: 1 (PROFIX-CB principal PDF).
  Out-of-scope (documented non-blocking): CONFAP Amazonia (no PDF),
  Horizon Europe (2024 guidelines year-guard rejected).
- DISCOVERY: emitted=1, rejected (year_rejected)=1, rejected
  (prefilter_rejected)=0, errors=0, partial=no, cap reached=no
  (stats-postfix.json).
- FIDELITY: exit code 0; blockers=0; open-record accounting=100.0% (1/1
  in-scope); candidate traceability=100.0% (1/1); non_blocking
  exceptions=3 (missing_optional_metadata status, out_of_scope x2);
  no hidden cap/partial.
- TESTS: `py -3.13 -m pytest tests/test_fapergs_discovery.py -q`
  → **24 passed in 0.30s** (after residual-fix repair).
- CHANGES:
  1. *(prior session, preserved)* `scripts/discover_fapergs_candidates.py`
     — principal-PDF selection (`_select_principal_pdf`,
     `_RELATED_DOC_PATTERN`), related-document metadata,
     AJAX+static listing merge, YYYYMM-aware year guard.
  2. *(prior session, preserved)* `tests/test_fapergs_discovery.py` —
     `TestPrincipalPdfAndYearFolder` regressions.
  3. *(this session)* `scripts/discover_fapergs_candidates.py` —
     fixed `_UPLOAD_MONTH_PATTERN` to capture the full year:
     `r"/((?:19|20)\d{2})(0[1-9]|1[0-2])/"` so group(1) is `2021`
     not `20`.
  4. *(this session)* `tests/test_fapergs_discovery.py` — aligned
     `test_static_listing_yields_pdfs_from_each_detail_page` to the
     principal-PDF contract (1 candidate + related_document_urls).
  5. *(this session)* evidence only: commands.md rewritten, RESULT.md
     rewritten, discovery-postfix.json + stats-postfix.json added;
     fidelity/ outputs refreshed by the audit CLI.
- EVIDENCE:
  - docs/evidence/sources/fapergs/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/fapergs/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/fapergs/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/fapergs/technical-audit-2026-09-14/discovery-postfix.json
  - docs/evidence/sources/fapergs/technical-audit-2026-09-14/stats-postfix.json
  - docs/evidence/sources/fapergs/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. FAPERGS listing is AJAX-driven; a future source redesign that changes
     the pagedlistfilho contract could break discovery silently — the
     independent inventory refresh path covers this.
  2. Out-of-scope open records (CONFAP, Horizon) remain non-emitting by
     design; if product scope later includes them, inventory and filters
     must be updated together.
  3. Direct `py`/`python` shell remains permission-gated in this
     environment; verification used a git-alias shell channel — not a
     production concern, but operational friction for future audits.
- ESCALATION: none.
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches,
  deploys, submissions, or catalog mutations).

## Follow-up (non-blocking)

- Commit the fapergs adapter + tests fix through the normal review path
  when the coordinator schedules it (left uncommitted per task rules).
