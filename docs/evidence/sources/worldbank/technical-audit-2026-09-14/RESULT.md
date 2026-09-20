# WorldBank technical audit 2026-09-14

## Result

RESULT: pass
SOURCE: worldbank
EXPECTED CONTRACT: candidate; module=discover_worldbank_candidates; group=c; rollout ingest; schedule_owner=pipeline-discovery-group-c.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; entry point https://www.worldbank.org/en/programs/sief-trust-fund/brief/sief-call-for-proposals-8-edtech-for-foundational-learning; signal tokens call/request for proposals|expression of interest|eoi|procurement|funding strategy|resolution; worldbank.org host gate; identity = PDF URL as source_record_id; year guard min 2026 on URL-embedded years only
OBSERVED CONTRACT: candidate — audit-only discovery fetches the single official listing page via BS4 (listings_fetched=1), emits exactly the 1 signal-token SIEF Call 8 PDF; Playwright fallback unused (static HTML carries all content and both PDF anchors; page is fully server-rendered today); errors=0, no cap, no partial
LIFECYCLE HOLD: none in registry (ingest/active). No snapshot/RR-05/release-decision change claimed.
OFFICIAL INVENTORY: open=0, closed=1, upcoming=0, excluded=1, unknown=0
DISCOVERY: emitted=1; rejected: non-signal PDF=1 (Call-8-announcement.pdf, out_of_scope by signal-token contract), non-PDF application forms=2 (Google Forms, outside PDF contract); errors=0; partial=false; cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (0/0 open in-scope), traceability%=100.0 (1/1); non_blocking=3 (2 missing_optional_metadata for discovery null status/deadline; 1 out_of_scope disposition)
TESTS: `py -3.13 -m pytest tests/test_worldbank_discovery.py -q` → 24 passed in 6.24s
CHANGES: none (no adapter/test/fixture change; adapter behaved correctly against the live page)
EVIDENCE: docs/evidence/sources/worldbank/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,discovery.json,candidates.json,stats.json,fidelity/}
RISKS: the single official entry point is one SIEF call page (Call 8, EdTech for Foundational Learning) whose deadlines (April 22, 2026 assessment; May 19, 2026 main application) are both past as of the 2026-09-14 capture, so authoritative lifecycle is closed — yet the adapter has no page-text deadline parsing and will keep re-emitting the same closed-call PDF every hourly run (downstream content-hash/idempotency is expected to absorb re-emissions; if Repo A lacks idempotency for identical PDF re-submissions, closed calls could accumulate duplicates — coordinator-owned concern, not an isolated adapter parsing defect under this audit's pass criteria); the two application forms on the page are Google Forms (not PDFs) and are permanently outside the adapter's PDF discovery contract; year guard cannot fire on this page because no year token appears in the PDF URL (extracted_year=null → pass-through is intentional per adapter contract); if the World Bank replaces the listing with a multi-call procurement index or JS-only rendering, the adapter's single-page BS4 assumption and host gate would need re-evaluation (Playwright fallback exists and is correctly gated); browser_required=false is currently correct
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via direct HTTP GET of the official World Bank SIEF Call 8 listing (2026-09-14T21:47:10Z, HTTP 200, text/html;charset=utf-8, 40,793 bytes). No Playwright needed: content is fully server-rendered.
- All 2 listing PDFs verified live via HEAD (200, application/pdf) at 21:47:56Z: SIEF-Call-8-EdTech-040926.pdf (430,260 bytes) and Call-8-announcement.pdf (228,904 bytes).
- Page published April 8, 2026; deadlines Due April 22, 2026 (assessment form) and Due May 19, 2026 (main application). Both past at capture → call is closed.
- Adapter signal-token contract keeps exactly 1 PDF: SIEF-Call-8-EdTech-040926.pdf (anchor text "Call for proposals"; host thedocs.worldbank.org ends with .worldbank.org). The announcement PDF is correctly excluded (no signal token). Duplicate "Call for proposals" anchors are correctly deduped.
- Pagination: none (single page; page_limit=5 unreachable). Caps: candidate cap 50 (adapter default) not reached at 1.
