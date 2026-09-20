# KfW independent capture log — 2026-09-14

All times UTC. No cookies, credentials, personal data, or tokens captured or stored.

## Entry point (from adapter)

- Adapter `scripts/discover_kfw_candidates.py` uses `KFW_LISTING_URL = https://www.kfw-entwicklungsbank.de/Service/Procurement-Regulations/` (English KfW Entwicklungsbank page; German mirror at `/Service/Vergaberegularien/`, not used by the adapter).
- Registry: contract=candidate, module=discover_kfw_candidates, group=c, rollout_mode=ingest, schedule_owner=pipeline-discovery-group-c.yml, interval 60 min, detail_limit=20, page_limit=5, attachment_limit=25, browser_required=TRUE. Catalog: active.

## Fetches (independent of the repo adapter)

| # | UTC time | URL | Method | HTTP | Content-Type | Notes |
|---|----------|-----|--------|------|--------------|-------|
| 1 | 2026-09-14T20:47:21Z | https://www.kfw-entwicklungsbank.de/Service/Procurement-Regulations/ | GET | 200 | text/html; charset=utf-8 | 96,417 bytes; 103 anchors, 15 PDF anchors; no pagination (single page, no rel next / page params) |
| 2 | 2026-09-14T20:49Z | same listing via Playwright chromium 1.52.0 (headless) | goto | 200 | text/html | 114 anchors rendered; PDF anchor set identical to static HTML (0 only-in-PW, 0 only-in-static). JS bundles load but add no extra PDF anchors; BS4 primary path is sufficient today, Playwright fallback consistent. |
| 3 | 2026-09-14T20:50:39–20:50:53Z | 15 listing PDF URLs (HEAD; ranged GET fallback) | HEAD | 200 | application/pdf | All 15 PDFs live. 5 non-ASCII-path PDFs needed percent-encoding in the probe client (urllib ascii limitation, not a server error). |

## Page structure (headings → PDFs)

- h1 Procurement regulations
  - h2 Guidelines
    - h3 FC Procurement Guidelines → FC-Guidelines-for-Procurement-2023.pdf (EN), CF …2023-FR/ES/PT, FC-Guidelines-for-the-Procurement-2021.pdf (EN), CF …2021 FR/ES/PT (7 PDFs + 1 DOCX Standard Request for Proposal template, non-PDF → out of adapter scope)
    - h3 Sustainability Guideline → Nachhaltigkeitsrichtlinie EN/FR/ES (3 PDFs)
  - h2 Standard Bidding Documents / Standard Evaluation Reports / Standard Contracts / Standard Service Descriptions → no PDF anchors (section content is non-PDF links or none)

## Lifecycle accounting

- The page hosts **standing regulation/guideline documents only**. Text scan: "call for proposals"=0, "request for proposals"=0, "expression of interest"=0, "deadline"=0, "closing"=0. There are **no time-bound procurement calls** (open/closed/upcoming) on the official listing at capture time.
- open=0 (no deadline-bearing calls), closed=0, upcoming=0, unknown=2 (the two English FC Procurement Guidelines PDFs that carry the adapter signal token `Procurement` in the path — standing documents, lifecycle not stated on the page), excluded=13 (other-language guideline editions, Vergaberichtlinien, Sustainability guidelines: no signal token in href/path/text/title/aria-label → outside adapter contract; recorded with reason_code=out_of_scope).
- Non-PDF signal-token anchor observed: `Standard-Request-for-Proposal-Consulting-Services_FR.docx` — correctly dropped by `looks_like_pdf_url` (not a PDF).

## Pagination / caps

- Single listing page; no pagination links or page parameters observed; page_limit=5 not reached. Adapter cap KFW_MAX_CANDIDATES_PER_RUN=50 not reached (2 candidates). No hidden cap or partial inventory.

## Errors

- Zero HTTP errors during independent capture (all listing/PDF requests 200).
- Discovery audit-only run: errors=0, candidate_cap_reached=0, playwright_fallback_used=0.

## Artifacts (scratch, removed after evidence copy)

- Temp working dir: `%TEMP%\kfw-audit-2026-09-14\` (listing.html, pw-anchors.json, pdf-checks.json, discovery/, fidelity/) — cleaned up after copy into this directory.
