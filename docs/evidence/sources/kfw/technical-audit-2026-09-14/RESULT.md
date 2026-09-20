# KfW technical audit 2026-09-14

## Result

RESULT: pass
SOURCE: kfw
EXPECTED CONTRACT: candidate; module=discover_kfw_candidates; group=c; rollout ingest; schedule_owner=pipeline-discovery-group-c.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=true; catalog active; entry point https://www.kfw-entwicklungsbank.de/Service/Procurement-Regulations/; signal tokens call/request for proposals|expression of interest|eoi|procurement; kfw-entwicklungsbank.de path gate (/service/procurement-regulations/, /document-center/, /pdf/download-center/pdf-dokumente-richtlinien/); identity = PDF URL as source_record_id
OBSERVED CONTRACT: candidate — audit-only discovery fetches the single official listing page via BS4 (listings_fetched=1, details_fetched=1), emits exactly the 2 signal-token English FC Procurement Guidelines PDFs; Playwright fallback unused (static HTML and chromium render carry an identical 15-PDF anchor set; the page is fully server-rendered today); errors=0, no cap, no partial
LIFECYCLE HOLD: none in registry (ingest/active). No snapshot/RR-05/release-decision change claimed.
OFFICIAL INVENTORY: open=0, closed=0, upcoming=0, excluded=13, unknown=2
DISCOVERY: emitted=2; rejected: non-signal PDFs=13 (out_of_scope by signal-token contract), non-PDF signal anchor=1 (Standard-Request-for-Proposal-Consulting-Services_FR.docx, dropped by looks_like_pdf_url); errors=0; partial=false; cap_reached=false
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (0/0 open in-scope), traceability%=100.0 (2/2); non_blocking=13 (out_of_scope dispositions)
TESTS: `py -3.13 -m pytest tests/test_kfw_discovery.py -q` → 16 passed
CHANGES: none (no adapter/test/fixture change; adapter behaved correctly against the live page)
EVIDENCE: docs/evidence/sources/kfw/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,discovery.json,candidates.json,stats.json,fidelity/}
RISKS: the official listing currently hosts only standing regulation/guideline documents — zero time-bound procurement calls; the 2 emitted candidates are the standing English FC Procurement Guidelines (2023 + 2021 editions) whose paths carry the `procurement` signal token, so each hourly run re-emits the same 2 PDF candidates (downstream dedup/content-hash is expected to absorb re-emissions; if Repo A lacks idempotency for identical PDF re-submissions, ingestion could accumulate duplicates — coordinator-owned concern, not a kfw-adapter defect); non-ASCII PDF paths on the page (CF Directives/Directrices/Diretrizes) work in browsers and with `requests` but naive urllib clients need percent-encoding — the adapter uses `requests` via scraper_transport and the pipeline downloader, which handle unicode URLs; if KfW later adds real call-for-proposals PDFs under the gated subpaths, the adapter will pick them up automatically via the same signal tokens; browser_required=true in the registry is currently unnecessary for this page (BS4 sufficient) but remains a valid fallback if the page becomes JS-rendered
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via direct HTTP GET of the official KfW Entwicklungsbank listing (2026-09-14T20:47:21Z, HTTP 200, text/html, 96,417 bytes) plus an independent Playwright chromium render (2026-09-14T20:49Z, HTTP 200, 114 anchors) — identical 15-PDF anchor sets, 0 divergence.
- All 15 listing PDFs verified live via HEAD (200, application/pdf) at 20:50–20:52Z.
- Page sections: Guidelines (FC Procurement Guidelines: EN 2023, EN 2021 + FR/ES/PT editions of each; FZ Vergaberichtlinien 2021 EN/FR/ES/PT; Sustainability Guideline EN/FR/ES), Standard Bidding Documents, Standard Evaluation Reports, Standard Contracts, Standard Service Descriptions (no PDF anchors in the latter four sections).
- Text scan: "call for proposals"=0, "request for proposals"=0, "expression of interest"=0, "deadline"=0 — the page carries no time-bound procurement calls; lifecycle is unknown (standing documents) or excluded (non-signal editions), never open/closed/upcoming.
- Adapter signal-token contract keeps exactly 2 PDFs: FC-Guidelines-for-Procurement-2023.pdf and FC-Guidelines-for-the-Procurement-2021.pdf (English "Procurement" in path; under the gated /PDF/Download-Center/PDF-Dokumente-Richtlinien/ subpath). The DOCX Standard Request for Proposal template matches a signal token but is correctly dropped as non-PDF.
- Pagination: none (single page; page_limit=5 unreachable). Caps: candidate cap 50 (adapter default) not reached at 2.
