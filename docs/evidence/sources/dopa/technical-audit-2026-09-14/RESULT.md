# DOPA technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: dopa
EXPECTED CONTRACT: opportunity; module=discover_dopa_opportunities; group=b; rollout_mode=paused; schedule_owner=pipeline-discovery-group-b.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official surface apigateway.procempa.com.br DOPA 1.1 (Diário Oficial de Porto Alegre API); window 3d America/Sao_Paulo; scope executivo
OBSERVED CONTRACT: opportunity — post-fix audit-only discovery emits exactly the five independent open calls (627460 prorrogação chamamento, 627564 chamamento oficineiros, 627176 sorteio táxi, 627585 residência médica, 627563 PRIMURGE); post-acts (gabarito/resultado preliminar/notas preliminares) correctly rejected; no caps, no errors
LIFECYCLE HOLD: registry rollout_mode=paused PRESERVED (catalog remains active separately). DISCOVERY_AUDIT_ONLY bypasses rollout holds by design for discovery-only runs with no ingestion; scheduled execution remains held at pipeline-discovery-group-b.yml. No snapshot/RR-05/release-decision change.
OFFICIAL INVENTORY: open=5, closed=2, upcoming=0, excluded=138, unknown=0 (145 unique rows, 0 detail failures, full window accounting)
DISCOVERY: emitted=5, rejected=policy_rejected=140 (title+detail stage), errors=0, partial=false, cap reached=false (search_result_cap=0, detail_cap=0, candidate_cap=0; details_fetched=10 of 145 title-pass-filtered rows; attachment_rejected=1)
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (5/5), traceability%=100.0 (5/5); pre-fix baseline exit=1 with accounting%=40.0, missing_open=3, authoritative_status_mismatch=1
TESTS: `py -3.13 --version` → Python 3.13.5; `py -3.13 -m pytest tests/test_dopa_discovery.py -q` → 17 passed (12 prior + 5 new regression tests)
CHANGES:
- scripts/discover_dopa_opportunities.py — expand detail post-act rejects (`gabarito definitivo`, `resultado preliminar`, `notas preliminares`, `respostas aos recursos`); accept reverse-order open signal (`abertas as inscrições`), `edital de abertura` / `edital das vagas`, `permanecerá/estiver aberto`; deadline cues `do dia`/`ao dia` with 220-char window so dates after long URLs are captured
- tests/test_dopa_discovery.py — regression tests for post-act rejects, sorteio open status+deadline, permanecer aberto, edital de abertura/das vagas, ao-dia range after long URL
- docs/evidence/sources/dopa/technical-audit-2026-09-14/* — independent inventory, capture log, discovery copy, fidelity reports, commands, this RESULT
EVIDENCE: docs/evidence/sources/dopa/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,capture-log.json,accounting.json,discovery.json,stats-postfix.json,fidelity/}
RISKS: deadline still null for 627585/627563/627564 (period lives in attached PDF or multi-month open window — documented unknown deadline, not a blocker); Portuguese lifecycle heuristics verified against 2026-09-14 live bodies — future wording drift could re-open false positives/negatives; attachment_rejected=1 is the non-PDF/blank-filename anexo on 627564 (intentional); 3-day window means a closed-but-still-listed call can reappear only within the rolling window
ESCALATION: none
PRODUCTION ACTIONS: none

## Pre-fix baseline (this session, retained for provenance)

- First audit-only run emitted 5 candidates including three post-acts (627636 gabarito definitivo, 627635 recursos/gabarito/notas, 627632 resultado preliminar treated as open with appeal deadline) and missed three true opens (627176 sorteio, 627585 residência médica, 627563 PRIMURGE).
- Independent fidelity FAIL: exit 1, accounting 40%, blockers missing_open=3 + authoritative_status_mismatch=1.
