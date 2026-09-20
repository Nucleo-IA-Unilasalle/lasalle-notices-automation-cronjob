# funbio technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: funbio
EXPECTED CONTRACT: opportunity (structured); module=discover_funbio_candidates; group=b; rollout audit; schedule_owner=pipeline-discovery-group-b.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official listing `https://chamadas.funbio.org.br/`
OBSERVED CONTRACT: opportunity — post-fix audit-only discovery emits all 9 open FUNBIO calls from the home Seleções Abertas panel with authoritative status=open, Brasília-stamped deadlines (UTC-normalized), and a single principal regulamento document per call
LIFECYCLE HOLD: none in registry beyond rollout_mode=audit / catalog active. Audit-mode only (discovery without ingestion). No snapshot/RR-05/release-decision change claimed.
OFFICIAL INVENTORY: open=9, closed=0, upcoming=0, excluded=1, unknown=0
DISCOVERY: emitted=9, rejected=0, errors=0, partial=false, cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (9/9 open-in-scope), traceability%=100.0 (9/9)
TESTS: `py -3.13 -m pytest tests/test_funbio_discovery.py -q` → 27 passed (23 pre-existing + 4 `TestParseFunbioOpportunity` / Manifestação regression)
CHANGES:
- scripts/discover_funbio_candidates.py — listing signal tokens expanded to include `interesse|manifestação` (three open "Manifestação de Interesse" cards were invisible to discovery); deadline parsed as 23:59 America/Sao_Paulo then converted to UTC (page states "23h59 horário de Brasília"); first (regulamento) document marked is_principal/is_renderable
- tests/test_funbio_discovery.py — added TestParseFunbioOpportunity (Brasília deadline, principal document, past-deadline closed) and TestExtractFunbioDetailUrls.test_manifestacao_interesse_titles_are_discovered
EVIDENCE: docs/evidence/sources/funbio/technical-audit-2026-09-14/{RESULT.md,commands.md,independent-inventory.json,capture-log.json,discovery.json,opportunities.json,stats.json,fidelity/}
RISKS: FUNBIO regulamento downloads are HTML wrappers embedding base64 PDFs (not direct application/pdf); one call (`fortalecimentoconselhosgestoresg7`) repeatedly returned HTTP 524 / read timeout so its principal PDF could not be binary-validated (document URL still inventoried; fidelity matched by stable_id/URL). Deadline timezone depends on zoneinfo America/Sao_Paulo (tzdata present on this interpreter). Signal-token expansion is still a denylist-style filter; future new call titles without any token could re-appear as missing_open. Home listing is single-page today; closed archive is not SSR on /calendario-chamadas so closed inventory is 0 from public HTML alone.
ESCALATION: none
PRODUCTION ACTIONS: none

## Ground truth (live official portal, 2026-09-14 UTC)

- Official listing: `https://chamadas.funbio.org.br/` — Seleções Abertas panel lists 9 open calls; Próximas Seleções panel empty ("Teremos novas seleções previstas em breve").
- Open calls and Inscrições até (Brasília 23:59):
  - planodemanejo-rppn — 25/09/2026
  - usopublico-rppn — 09/10/2026
  - raisfortalecimento1 — 07/10/2026
  - tcsa-porto-sul — 09/11/2026
  - fortalecimentoconselhosgestoresg7 — 14/09/2026 (still open at capture ~20:24 UTC / 17:24 BRT)
  - selecao-de-ucs-estaduais-fundo-marinho — 16/09/2026
  - conselho-ucs-municipais-estaduais — 25/09/2026
  - planodemanejo-sinalizacao-estadual-municipal — 25/09/2026
  - usopublico-ucs — 25/09/2026
- Principal document per call: `/download/regulamento?id=<uuid>` anchor on each detail page (privacy PDF excluded).
- Pagination: single listing page; registry detail_limit=20 not approached (9 details).

## Pre-fix baseline (retained for provenance)

- Pre-fix discovery emitted only 6 opportunities: the three "Manifestação de Interesse" open cards lacked signal tokens (`chamada|projeto|edital|floresta|selecao`).
- Pre-fix fidelity vs independent inventory: missing_open ×3; after inventory renderable hygiene also showed renderability_mismatch ×9 (inventory claimed renderable without PDF validation).
- Post-fix: same inventory vs fresh discovery → status/deadline/identity match on all 9, zero blockers, pass=true.
