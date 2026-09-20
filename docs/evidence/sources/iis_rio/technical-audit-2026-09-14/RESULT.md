# iis_rio technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: iis_rio
EXPECTED CONTRACT: candidate; module=discover_iis_rio_candidates; group=a; rollout ingest; schedule_owner=pipeline-discovery-group-a.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; listing https://www.iis-rio.org/noticias/; signal tokens edital|chamada|consultoria|tdr; IIS_RIO_MIN_NOTICE_YEAR=2026
OBSERVED CONTRACT: candidate — post-fix audit-only discovery fetches the single listing page (page>1 WordPress 404 ends pagination cleanly), visits all 13 signal-token detail pages, and emits 0 candidates because every live PDF carries a 2019–2025 year and the 2026 year guard rejects them; errors=0, no cap, no partial
LIFECYCLE HOLD: none in registry (ingest/active). No snapshot/RR-05 change claimed.
OFFICIAL INVENTORY: open=0, closed=13, upcoming=0, excluded=0, unknown=0
DISCOVERY: emitted=0; rejected: year_rejected=12 (11 notice PDFs + 1 site-wide privacy boilerplate PDF, all pre-2026), prefilter_rejected=0; errors=0; partial=false; cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (0/0 open in scope), traceability%=100.0 (0/0 candidates); non_blocking=0
TESTS: `py -3.13 -m pytest tests/test_iis_rio_discovery.py -q` → 25 passed (23 prior + TestPagination404EndOfList: page2 404 not an error, page1 404 still errors)
CHANGES:
- scripts/discover_iis_rio_candidates.py — PRIOR SESSION (verified, not reverted): in the listing loop's except branch, `page_num > 1 and status_code == 404` breaks pagination without incrementing `errors`, because WordPress returns 404 for out-of-range pages once the archive is exhausted (+6 lines)
- tests/test_iis_rio_discovery.py — PRIOR SESSION: added TestPagination404EndOfList regression class (+34 lines). THIS SESSION: completed the page2-404 test by mocking the two fixture detail URLs (they were unmocked, so detail fetches raised and inflated stats["errors"]; tests-only repair, +10/-1)
- docs/evidence/sources/iis_rio/technical-audit-2026-09-14/independent-inventory.json — refreshed: 5 live-verified principal TdR/Q&A document URLs added to records that previously had empty document_urls; statuses/titles/identities unchanged
EVIDENCE: docs/evidence/sources/iis_rio/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,discovery.json,candidates.json,stats-postfix.json,fidelity/}
RISKS: registry filter_policy=default overrides the adapter module default include_tdr (FastAPI-port behaviour) — moot while all PDFs are pre-2026, but a future 2026 TdR filename would be prefilter-rejected under the registry policy (coordinator-owned decision, unchanged here); the WordPress archive is currently single-page so the page>1 404 path is the only pagination terminator — if IIS-Rio restores multi-page archives the adapter will resume normal pagination automatically; `IIS_RIO_MAX_PAGES=10` (adapter) exceeds registry page_limit=5 but is unreachable while the archive stays single-page
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via direct HTTP of official IIS-Rio pages (listing page 1, pagination probes, 13 detail pages), 2026-09-14 ~20:22–20:33Z; production `extract_iis_rio_detail_urls` used for signal-token accounting; 0 fetch errors.
- Open: none. Latest consultation (Social Media TdR) closed 2025-07-15; no future-dated call on the official listing.
- Closed: 13 signal-token notices (consultorias 2025/2023/2022/2021, mestrado chamadas 2023/2022, Land Innovation Fund news 2022, bolsistas chamadas 2020/2019 ×3).
- 2026 news items on the site are not procurements and carry no signal tokens — correctly outside the inventory.
- Pagination probes (`/noticias/page/2/`, `?paged=2`, `?tipo-de-noticia=noticia&paged=2`) all 404: the archive is a single page, which is exactly the condition the prior fix handles.

## Pre-fix baseline (prior session, retained for provenance)

- Without the fix, the page-2 404 raised inside the listing loop, logged a failure, and incremented `stats["errors"]` → audit-only orchestrator marked `partial_inventory=true` and the run failed closed despite a complete single-page inventory.
