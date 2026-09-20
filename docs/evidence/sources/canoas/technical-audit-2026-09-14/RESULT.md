# RESULT — Canoas Source-Adapter Verification (2026-09-14)

RESULT: pass

## Summary

Independent official capture (DOMC diary-by-day API + publication PDF + WordPress
licitações API, not via the repo adapter) found **one** opportunity-signal
publication in the default 3-day window (12–14 Sep 2026): `140919 EDITAL
Nº319/2026`, an administrative designation of named nursing staff to an ethics
commission electoral body with **no application window**. Audit-only discovery
(`DISCOVERY_AUDIT_ONLY=true`, opportunity contract, paused rollout untouched)
emitted exactly that record with status `unknown` and the DOMC PDF as principal
document. Official fidelity CLI vs the independent inventory: **exit 0,
0 blocking exceptions, 100% open-record accounting (0/0 in-scope open),
100% candidate traceability (1/1)**. Focused tests **11/11 pass**. No adapter
defect found; no code changes.

## Structured fields

- RESULT: pass
- SOURCE: canoas
- EXPECTED CONTRACT: opportunity (structured) — discover_canoas_opportunities,
  group a, rollout **paused**, owner pipeline-discovery-group-a.yml, interval
  60 min, detail_limit=20, page_limit=5, attachment_limit=25,
  browser_required=false; catalog active.
- OBSERVED CONTRACT: opportunity (audit-only path ran via
  `scripts/discover_all_candidates.py` with `SUBMISSION_CONTRACT=opportunity`
  and `OPPORTUNITY_SOURCES=canoas`; adapter module and registry entry match;
  no contract drift).
- LIFECYCLE HOLD: **rollout_mode=paused preserved** (registry unchanged;
  catalog stays active as a separate lifecycle). No paused/audit holds removed;
  no activation authorized.
- OFFICIAL INVENTORY: open=0, closed=0, upcoming=0, excluded=47, unknown=1
  (window 12–14/09/2026; diary-by-day HTTP 200×3 at 2026-09-14T20:20:55Z–
  20:20:56Z; day 14 edition 3930 fully enumerated 48 rows; excluded classes:
  no_opportunity_signal=35, post_act=10, pncp_procurement=2; unknown =
  140919 designation edital, no application deadline).
- DISCOVERY: emitted=1, rejected (policy)=47, errors=0, partial=no,
  cap reached=no (stats: days_requested=3, days_fetched=3, records=48,
  wordpress_lookups=1, wordpress_matches=0, wordpress_failures=0,
  opportunities=1, inventory_parse_failed absent/0).
- FIDELITY: exit code 0; blockers=0; open-record accounting=100.0% (0/0
  in-scope open; no open application opportunities in window); candidate
  traceability=100.0% (1/1); non_blocking exceptions=0; no hidden cap/partial.
  Match key stable_id ('canoas','140919'); status/deadline/renderable all
  match (unknown/unknown).
- TESTS: `py -3.13 -m pytest tests/test_canoas_discovery.py -q`
  → **11 passed in 0.25s**.
- CHANGES: none (adapter/tests/fixtures untouched; evidence only).
- EVIDENCE:
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/capture-log.md
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/opportunities.json
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/stats.json
  - docs/evidence/sources/canoas/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. DOMC title-only policy cannot pre-filter administrative “edital de
     designação” acts; when WordPress is unresolved the adapter emits them as
     status=unknown with DOMC PDF. Unknown-status noise is non-blocking for
     fidelity (not open-in-scope) but will appear as structured opportunities
     if ingest is ever enabled — product may later want a designação filter.
  2. WordPress licitações search for 2026 editals can be empty; DOMC PDF
     remains the principal document fallback (by design).
  3. DOMC empty-object weekend days are healthy; a future API shape change
     from `{}` to a different empty representation would fail-closed in
     `extract_publications` (tested).
  4. Direct `py`/`python` worked this session (Python 3.13.5); no shell
     permission friction observed.
- ESCALATION: none.
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches, deploys,
  submissions, or catalog mutations). Audit-only dry run submitted nothing.

## Follow-up (non-blocking)

- When the coordinator schedules rollout re-evaluation, keep the paused hold
  until the normal two-audit + soak path; this verification does not sign off
  RR-05 or authorize ingest.
