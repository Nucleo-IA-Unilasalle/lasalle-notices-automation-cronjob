# BNDES technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: bndes
EXPECTED CONTRACT: candidate; module=discover_bndes_candidates; group=a; rollout ingest; schedule_owner=pipeline-discovery-group-a.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official surfaces fundo-socioambiental + vanity chamadadeinovacao; host filter bndes.gov.br; BNDES_MIN_NOTICE_YEAR=2026
OBSERVED CONTRACT: candidate — post-fix audit-only discovery emits exactly the one open BNDES-hosted call (Periferias 6º ciclo principal PDF); three fully closed fundo urile routes are lifecycle-rejected; CPSI worldlabs-only calls are out_of_scope by host-filter contract
LIFECYCLE HOLD: none in registry (ingest/active). No snapshot/RR-05/P5/P6 change claimed.
OFFICIAL INVENTORY: open=1 (in-scope), open out_of_scope=3 (CPSI worldlabs-only), closed=6, upcoming=0, unknown=0
DISCOVERY: emitted=1, rejected: lifecycle_rejected=3 (closed pages), prefilter_rejected=5, year_rejected=0; errors=0; partial=false; cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0, traceability%=100.0 (non_blocking=5: optional metadata + out_of_scope dispositions)
TESTS: `py -3.13 -m pytest tests/test_bndes_discovery.py -q` → 40 passed (37 prior + 3 new regression tests)
CHANGES:
- scripts/discover_bndes_candidates.py — page-level lifecycle gate (`_CLOSED_PAGE_PHRASES`/`_OPEN_CALL_PHRASES`, `_page_is_fully_closed`, `lifecycle_rejected` stat) skips fully closed fundo urile routes (Corais/Sertão/Bioinsumos verified live); `_strip_tracking_params` drops per-fetch `CVID` query param from candidate identity
- tests/test_bndes_discovery.py — CVID expectations updated; TestLifecycleGate regression class (closed page skipped, mixed page emits, CVID stripped)
- docs/evidence/sources/bndes/technical-audit-2026-09-14/independent-inventory.json — aligned identities (principal PDF URL sans CVID for the open call; unique canonical_urls per record; CPSI open records marked out_of_scope with rationale)
EVIDENCE: docs/evidence/sources/bndes/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,discovery.json,stats-postfix.json,fidelity/}
RISKS: lifecycle phrases are Portuguese-text heuristics verified against 2026-09-14 live pages — a wording change on BNDES pages could re-open the closed-call leak; mixed pages rely on the existing prefilter to keep only open-call PDFs (Periferias page verified); CPSI out_of_scope depends on the host-filter contract remaining intentional
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via direct webfetch of official BNDES pages (fundo listing +4 urile routes + chamadadeinovacao vanity), 2026-09-14 UTC; second-pass re-verify identical.
- Open in-scope: Periferias 6º ciclo only (deadline 2026-12-04T17:00-03:00; principal PDF Roteiro 6º ciclo).
- Open out_of_scope: CPSI 001/2026, 003/2025, 002/2025 — worldlabs.org links only; adapter host filter (bndes.gov.br) intentionally drops external-only calls.
- Closed: Periferias 5º Mulheres (2026-03-12), Corais (2024-07-05), Bioinsumos 2º ciclo, Sertão+Produtivo (resultado 2025-06-02), Periferias Fortes, CPSI 01/2024.
- Fundo listing copy remains stale (advertises closed calls as open); detail/urile pages are authoritative and the adapter now lifecycle-gates them.

## Pre-fix baseline (this session, retained for provenance)

- First audit-only run emitted 5 candidates (4 closed-call PDFs + 1 open); independent fidelity FAIL: 11 blockers (extra_submission=5, missing_open=4, duplicate_identity=2), 0%/0%.
