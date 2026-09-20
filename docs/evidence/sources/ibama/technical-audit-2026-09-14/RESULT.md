# IBAMA technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: ibama
EXPECTED CONTRACT: opportunity; module=discover_ibama_candidates; group=c; rollout paused (hold preserved); schedule_owner=pipeline-discovery-group-c.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official entries chamamentos-publicos + editais-e-convites listings + notas/2026 + two RDF/RSS feeds on www.gov.br/ibama
OBSERVED CONTRACT: opportunity — structured records with source_record_id/canonical_url/status/deadline/documents; discover_candidates wrapper emits no PDF candidates; SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=ibama
LIFECYCLE HOLD: registry rollout_mode=paused PRESERVED; catalog_status=active unchanged; no snapshot/RR-05/release-decision edits; DISCOVERY_AUDIT_ONLY bypasses holds by design (discovery-only, no ingestion); paused hold remains enforced at workflow/schedule layer
OFFICIAL INVENTORY: open=2, closed=9, upcoming=0, excluded=35, unknown=0 (2 unknown news rows classified out_of_scope/excluded in final inventory); detail cap not reached (47/60 module; 12 details after policy prefilter)
DISCOVERY: emitted=8, rejected=39 (policy), errors=0, partial=false, cap_reached=false; internal fidelity (orchestrator) blockers=0
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (2/2 open in-scope), traceability%=100.0 (8/8); non_blocking=35 (explicit out_of_scope dispositions)
TESTS: `py -3.13 --version` → Python 3.13.5; `py -3.13 -m pytest tests/test_ibama_discovery.py -q` → 17 passed (13 prior + 4 new regressions)
CHANGES:
- scripts/discover_ibama_candidates.py — `_status` no longer treats incidental "exigibilidade suspensa"/"suspensão de prazos" as call suspension (requires call-noun proximity or foi/está suspenso); `_extract_schedule` prefers deadline-cued dates (termina/até/encerramento) over later DOU publication dates, takes the first cued deadline, and only applies an explicit time attached to the deadline date (start-time "às 10h" no longer forces midnight); `_POSITIVE_TERMS` includes `audi[eê]ncia p[uú]blica` so participatory hearing-request edital periods are eligible at seed level; `parse_detail` rejects details whose publication year precedes min_year (guards /copy_of_notas/ historical pages)
- tests/test_ibama_discovery.py — new regressions: incidental suspension phrases, deadline-cued date preference, start-time vs end-of-day deadline, published-before-min-year rejection
EVIDENCE: docs/evidence/sources/ibama/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,capture-log.json,independent-inventory.json,independent-capture-summary.json,discovery.json,opportunities.json,stats.json,fidelity/}
RISKS: live Plone heading/body drift can still fail-close via inventory_parse_failed; future news pages whose titles lack call keywords and whose bodies omit positive terms remain policy-rejected (conservative); AGU debt-negotiation edital is tracked as an opportunity by the current positive-term policy — operators may wish to review whether debt-settlement editais belong in the product scope; paused rollout hold still requires an operator decision before any production ingest
ESCALATION: none
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via direct requests of the 3 official listings + 2 RDF feeds + 47 detail pages, 2026-09-14 ~22:05 UTC; all HTTP 200; no caps hit.
- Open in-scope: edital-4-2026 (AGU adhesion to 2026-11-30), edital-20-2026 (FSO hearing-request period prorrogated to 2026-10-15 under Edital 20/2026).
- Closed provenance includes edital-22-2026 Reverdear (deadline 2026-09-08), RAPP consultas (2026-09-02), Candonga (2026-04-04), CTF/APP FTE (2026-06-03), BR-242 hearing window (2026-08-13).
- Excluded: brigadistas, doações, leilão, resultados/notificações, webinar noise, historical 2020 audiência (publication year < 2026).
- Principal open documents: detail-page attachments on www.gov.br/ibama file endpoints; no separate CDN.

## Pre-fix baseline (this session, retained for provenance)

- First audit-only discovery emitted 6 opportunities; FSO open page missing (seed filter), AGU/Candonga status false-suspended, RAPP-termina deadline picked DOU 28 June instead of 2 Sept.
- External fidelity pre-fix: exit 1, 6 blocking (missing_open, authoritative_status_mismatch×2, authoritative_deadline_mismatch×2, inventory duplicate_identity before hygiene).
- Post-fix external fidelity: exit 0, 0 blockers, 100%/100%.
