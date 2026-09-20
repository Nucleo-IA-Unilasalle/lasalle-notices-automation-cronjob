# RESULT — finep Source-Adapter Verification (2026-09-14)

RESULT: fixed

## Structured fields

- RESULT: fixed
- SOURCE: finep
- EXPECTED CONTRACT: opportunity (structured) — discover_finep_opportunities,
  group c, rollout **paused**, owner pipeline-discovery-group-c.yml, interval
  60 min, detail_limit=20, page_limit=5, attachment_limit=25,
  browser_required=false; catalog active; official surface
  `https://www.finep.gov.br/o/c/chamadapublicas` (Liferay public JSON).
- OBSERVED CONTRACT: opportunity — audit-only path ran via
  `scripts/discover_all_candidates.py` with `SUBMISSION_CONTRACT=opportunity`
  and `OPPORTUNITY_SOURCES=finep`; adapter module and registry entry match;
  no contract drift. Cursor scope remains `finep-pages-v1` (full coverage only).
- LIFECYCLE HOLD: **rollout_mode=paused preserved** (registry unchanged; catalog
  stays active as a separate lifecycle). No paused/audit holds removed; no
  activation authorized. `DISCOVERY_AUDIT_ONLY` bypasses rollout holds by design
  for discovery-only runs with no ingestion; scheduled execution remains held at
  pipeline-discovery-group-c.yml / pipeline-finep-discovery.yml.
- OFFICIAL INVENTORY: open=34, closed=436, upcoming=0, excluded=0, unknown=0
  (470 unique after removing 4 page-boundary duplicates from 474 fetched rows;
  24/24 pages HTTP 200 at 2026-09-14T21:59:51Z–22:00:09Z; situacao keys only
  `aberta`/`encerrada`; 15 of the 34 opens dispositioned `reason_code=out_of_scope`
  under declared MIN_NOTICE_YEAR=2026, leaving 19 open-in-scope; 1 open-record
  principal PDF check returned HTTP 404 — source-side dead link retained).
- DISCOVERY: emitted=19, rejected (policy)=451 (closed 436 + pre-2026 open 15),
  errors=0, partial=false, cap reached=false (stats-postfix.json: records=470,
  opportunities=19, candidate_cap_reached=0, page_cap_reached=0,
  duplicate_records_skipped=4, finep_pages_completed=1..24, finep_last_page=24,
  inventory_parse_failed absent). Audit used elevated FINEP_MAX_PAGES_PER_RUN=100 /
  FINEP_MAX_OPPORTUNITIES_PER_RUN=100 for full coverage; production defaults stay
  5/10 (caps fail-loud and block finep-pages-v1 advance when hit).
- FIDELITY: exit code=0, blockers=0, accounting%=100.0 (19/19 in-scope open),
  traceability%=100.0 (19/19), non_blocking=15 (out_of_scope policy dispositions
  only), no hidden cap/partial. Pre-fix simulated baseline: exit=1, 22 blocking
  (authoritative_status_mismatch=19, duplicate_identity=2, extra_submission=1),
  traceability 95%.
- TESTS: `py -3.13 --version` → Python 3.13.5;
  `py -3.13 -m pytest tests/test_finep_discovery.py -q` → 4 passed (pre-fix);
  `py -3.13 -m pytest tests/test_finep_discovery.py tests/test_reliability_review_regressions.py -q`
  → **32 passed** (post-fix, including new lifecycle-normalization and
  pagination-dedup regressions).
- CHANGES:
  - scripts/discover_finep_opportunities.py — map Finep `situacao` to the
    worker-wide `open`/`closed`/`unknown` contract for `authoritative_status`,
    inventory `status`, and the open filter; dedupe page-boundary duplicate
    record ids during pagination and report `duplicate_records_skipped`.
  - tests/test_finep_discovery.py — regression tests for lifecycle normalization
    and cross-page duplicate dedup.
  - docs/evidence/sources/finep/technical-audit-2026-09-14/* — independent
    inventory, capture log, discovery copy, fidelity reports, commands, RESULT.
- EVIDENCE:
  - docs/evidence/sources/finep/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/finep/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/finep/technical-audit-2026-09-14/capture-log.md
  - docs/evidence/sources/finep/technical-audit-2026-09-14/capture-log.json
  - docs/evidence/sources/finep/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/finep/technical-audit-2026-09-14/accounting.json
  - docs/evidence/sources/finep/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/finep/technical-audit-2026-09-14/stats-postfix.json
  - docs/evidence/sources/finep/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. Finep keeps years-old chamadas in `aberta` (2015/2017/2024/2025); the
     MIN_NOTICE_YEAR=2026 filter hides them from discovery by design. If the
     product later lowers MIN_NOTICE_YEAR, those opens re-enter scope and must
     be re-audited.
  2. Source listing can repeat records across page boundaries; the adapter now
     dedupes by id, but a future id-less item shape would skip dedup for that
     row (id-less rows are rejected for missing identity).
  3. At least one open record links a dead principal PDF (HTTP 404); document
     URLs still match inventory↔discovery, but ingest would download-fail that
     attachment when rollout is enabled.
  4. Production page_limit=5 / opportunity cap 10 intentionally bound each run;
     full open-set coverage across a cycle depends on finep-pages-v1 only after
     uncapped complete enumeration — unchanged and still fail-loud on caps.
  5. 15 non-blocking `out_of_scope` dispositions are policy, not source truth;
     they are visible in the inventory evidence.
- ESCALATION: none (fixes are source-local: lifecycle interpretation + pagination
  dedup, ~40 production lines in one adapter file + two regression tests; no
  shared contracts, multi-source, schema, auth, workflow, or dependency changes).
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches, deploys,
  submissions, or catalog mutations). Audit-only dry run submitted nothing.

## Follow-up (non-blocking)

- When the coordinator schedules rollout re-evaluation, keep the paused hold
  until the normal two-audit + soak path; this verification does not sign off
  RR-05 or authorize ingest.
- Consider a product-side note (not this task) that Finep `aberta` is not a
  reliable recency signal; MIN_NOTICE_YEAR remains the worker fence.
