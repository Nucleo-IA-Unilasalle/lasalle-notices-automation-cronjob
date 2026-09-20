# govbr_mma_public_calls technical audit 2026-09-14

## Result

RESULT: pass
SOURCE: govbr_mma_public_calls
EXPECTED CONTRACT: candidate; module=discover_govbr_mma_public_calls_candidates; group=b; rollout audit; schedule_owner=pipeline-discovery-group-b.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official listing `https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico`; min year 2026; related docs (resultado/retificacao/errata/anexo) never standalone; status never inferred as open from year alone
OBSERVED CONTRACT: candidate — audit-only discovery fetches the official cover-richtext listing, year-rejects all 14 pre-2026 editorial links, excludes the 2026 resultado link as a related document, follows the single 2026 CONASQ news detail page which is access-restricted for anonymous clients (require_login / Conteúdo Restrito), finds no principal PDFs, emits 0 candidates and 1 inventory provenance record (`status=unknown`, `reason_code=unresolved_news_lead`). No unexpected records; no hidden cap; no parser failure.
LIFECYCLE HOLD: none in registry (rollout_mode=audit / catalog active). Audit-mode only (discovery without ingestion). No snapshot/RR-05/release-decision change claimed. No activation authorized.
OFFICIAL INVENTORY: open=0, closed=0, upcoming=0, excluded=15, unknown=1
DISCOVERY: emitted=0, rejected=14 (prefilter=0, year=14), errors=0, partial=false, cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (open-in-scope denominator=0; no open rows required), traceability%=100.0 (0/0 candidates)
TESTS: `py -3.13 -m pytest tests/test_govbr_mma_public_calls_discovery.py -q` → 25 passed in 6.31s
CHANGES: none (adapter already matches the live official page state; no defect found)
EVIDENCE: docs/evidence/sources/govbr_mma_public_calls/technical-audit-2026-09-14/{RESULT.md,commands.md,independent-inventory.json,capture.log,accounting.json,discovery.json,discovery-source-inventory.json,adapter-source-inventory.json,stats.json,candidates.json,fidelity/}
RISKS: the sole 2026 opportunity (CONASQ news page) is currently access-restricted for anonymous HTTP clients; the adapter correctly fails closed (no candidate, inventory provenance only). If gov.br later publishes a public principal PDF or lifts the restriction, discovery will need a re-audit. The listing is a Plone collective-cover page using `.callout` year markers rather than `<h2>` headings; the adapter already handles both. Residual risk is Portuguese wording drift and future multi-tile listing expansion. `write_candidate_audit` in discover_all_candidates derives discovery/source_inventory only from emitted candidates, so the orchestrator audit artifacts omit `unresolved_news_lead` inventory provenance (retained in adapter `source_inventory.json` via `--audit-dir`); fidelity open-gate is unaffected while there are zero open records.
ESCALATION: none
PRODUCTION ACTIONS: none

## Ground truth (live official page, 2026-09-14)

- Official listing: `https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico` (HTTP 200, single page; page_limit not approached; no pagination).
- Editorial body is a `.cover-richtext-tile` with `<p class="callout"><strong>2026</strong></p>` and `<strong>2025</strong>` year markers (not bare `<h2>` headings).
- 2026 section: (1) CONASQ edital news detail link; (2) “Resultado do EDITAL GM/MMA Nº 1/2026” related link (excluded as related_document).
- 2025 section: 14 news/detail links all year-guard rejected (min year 2026).
- CONASQ detail GET: 302 → require_login; page states “Conteúdo Restrito”; no principal edital PDFs extractable. Adapter records `unresolved_news_lead` with empty document_urls and status=unknown.
- No open or closed application windows with parseable deadlines are currently listed for 2026; open-in-scope denominator is 0.
- Document URLs: none (no principal PDFs reachable anonymously). Listing and detail HTML GET-verified without storing cookies/headers/tokens.
