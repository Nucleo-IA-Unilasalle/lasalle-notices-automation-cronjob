# BRDE technical audit 2026-09-14

## Result

RESULT: pass
SOURCE: brde
EXPECTED CONTRACT: candidate; rollout ingest; schedule_owner pipeline-discovery-group-a.yml (group a); detail_limit=20, page_limit=5, attachment_limit=25; discovery via scripts/discover_all_candidates.py SOURCES=brde; official surfaces https://www.brde.com.br/palacete/editais/ and https://www.brde.com.br/producao/?tab=ci
OBSERVED CONTRACT: adapter sources Palacete (heading lifecycle, year guard >=2026, closed-section skip) and FSA (detail extract with whitespace-href repair, application-period parse, open-only principal Edital). Registry and catalog entries match (active, interval 60).
LIFECYCLE HOLD: none in registry (ingest/active). No snapshot/RR-05/P5/P6 change claimed.
OFFICIAL INVENTORY: open=2, closed=9, upcoming=0, excluded=0, unknown=0
DISCOVERY: emitted=2, rejected=0, errors=0, partial=0, cap_reached=false (listings_fetched=2, details_fetched=8, open_details=2, closed_details=6, palacete_closed_sections=1)
FIDELITY: exit code=0, blockers=0, accounting%=100.0, traceability%=100.0
TESTS: `py -3.13 -m pytest tests/test_brde_discovery.py tests/test_source_fidelity.py tests/test_discover_all_candidates.py -q` -> 169 passed
CHANGES: none (adapter matched independent ground truth)
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via webfetch of official BRDE public pages (FSA tab + Palacete), 2026-09-14 UTC session.
- Open FSA 2026: TV/VOD Desempenho Comercial Produtoras (deadline 2026-09-25); Coproducao Brasil-Portugal (deadline 2026-09-25; listing href has known leading-space defect which the adapter repairs).
- Closed FSA 2026: nucleos-criativos, desempenho-artistico, coproducao-brasil-argentina, cinema-desempenho-comercial-produtoras, cinema-desempenho-comercial-distribuidoras, coproducao-brasil-uruguai.
- Closed Palacete: Encerrado sections 2026, 2024-2025, 2019-2020 (collapsed to one provenance row to satisfy unique identity).

## Limitations

- document_hashes empty (no PDF byte hashing in this pass).
- No repo adapter changes were required; the audit-only path already emitted exactly the two open principal PDFs.
