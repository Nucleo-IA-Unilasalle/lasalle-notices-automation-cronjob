# UNEP technical audit — capture log (2026-09-14)

All times UTC. Fetches used plain `requests` with a generic User-Agent
(`Mozilla/5.0 (compatible; source-audit/1.0)` for the listing; a Chrome-style
UA only for PDF bitstream probes); no cookies, tokens, or credential headers
were sent or stored. Browser automation was not required for the independent
capture (entry page is server-rendered). Capture performed with an
independent script (not the repo adapter and not
`scripts/run_independent_source_audit.py`).

## Observation 1 — official entry point (authoritative for this source)

- Requested URL: `https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding`
- Final URL: same (no redirect)
- UTC: `2026-09-14T21:12:41.016057+00:00` → `2026-09-14T21:12:41.538146+00:00`
- HTTP status: `200`
- Content-Type: `text/html; charset=utf-8`
- Title: `Applying for funding | UNEP`
- Body length: 161213 bytes
- Render mode: **server-rendered** (full HTML body present without JS);
  Playwright not needed (`browser_required=false` matches).

### Lifecycle statements in page main text

The page is the GFC Fund "Applying for funding" landing page. Verbatim
lifecycle facts extracted from the server-rendered body text (14179 chars):

- "The Global Framework on Chemicals Fund issues periodic calls for
  applications. The second round of applications was launched on 30
  September 2025 and **closed on 15 December 2025**."
- Application process stage 1: "applicants are requested to submit a concept
  note. This stage was **open from 30 September to 15 December 2025**."
- Stage 2: shortlisted applicants "will be invited to submit a full project
  proposal (stage 2) by the **middle of June 2026**." — also past as of this
  audit (2026-09-14).
- "Concept notes should be sent electronically … to: unep-gfc.fund@un.org by
  the deadline set out above."

Keyword scan of body text: `call for proposals` 0 hits, `request for
proposals` 0 hits, `concept note` 7 hits, `deadline` 1 hit, `open call` 0,
`funding opportunity` 0. No new (third) round is advertised.

### Unique `.pdf` anchors on the entry page (complete list: 4)

All four are hosted on `wedocs.unep.org` (UNEP's document repository; a
subdomain of `unep.org`, accepted by the adapter host filter).

| # | Resolved URL | Anchor text | Lifecycle classification |
|---|---|---|---|
| 1 | `https://wedocs.unep.org/bitstream/handle/20.500.11822/48729/GFC-Fund-Guidance-on-the-scope.pdf?sequence=1&isAllowed=y` | English | **excluded** — GFC Fund scope guidance document (EN); standing reference material, not an open call |
| 2 | `https://wedocs.unep.org/bitstream/handle/20.500.11822/48729/GFC-Fund-Guidance-on-the-scope_FR.pdf?sequence=2&isAllowed=y` | French | **excluded** — same guidance PDF, FR translation |
| 3 | `https://wedocs.unep.org/bitstream/handle/20.500.11822/48729/GFC-Fund-Guidance-on-the-scope_SP.pdf?sequence=3&isAllowed=y` | Spanish | **excluded** — same guidance PDF, ES translation |
| 4 | `https://wedocs.unep.org/bitstream/handle/20.500.11822/48724/02_GFC_Fund_Concept_Note.pdf?sequence=3&isAllowed=y` | Concept note | **excluded** — standing Stage-1 application template for the closed second round (closed 15 Dec 2025); not an open opportunity |

### PDF probe (HTTP GET prefix, bounded; Chrome-style UA)

| # | Requested URL | Status | Content-Type | Bytes read | Final URL | UTC |
|---|---|---|---|---|---|---|
| 1 | `…/48729/GFC-Fund-Guidance-on-the-scope.pdf?sequence=1&isAllowed=y` | 200 | `text/html; charset=utf-8` | 544590 | `https://wedocs.unep.org/items/f9dcf13b-08c1-43a3-8c3e-417cec207517` | 21:13:40→21:13:44 |
| 2 | `…/48729/GFC-Fund-Guidance-on-the-scope_FR.pdf?sequence=2&isAllowed=y` | 200 | `text/html; charset=utf-8` | 544005 | `https://wedocs.unep.org/items/f9dcf13b-08c1-43a3-8c3e-417cec207517` | 21:13:44→21:13:47 |
| 3 | `…/48729/GFC-Fund-Guidance-on-the-scope_SP.pdf?sequence=3&isAllowed=y` | 200 | `text/html; charset=utf-8` | 544005 | `https://wedocs.unep.org/items/f9dcf13b-08c1-43a3-8c3e-417cec207517` | 21:13:47→21:13:50 |
| 4 | `…/48724/02_GFC_Fund_Concept_Note.pdf?sequence=3&isAllowed=y` | 200 | `text/html; charset=utf-8` | 519224 | `https://wedocs.unep.org/items/d6de5ca5-5cfa-49b0-94ef-c22979214584` | 21:13:50→21:13:52 |

Note: the wedocs bitstream URLs currently redirect to DSpace 7 Angular SPA
item pages (`text/html`) rather than streaming `application/pdf` directly to
plain HTTP clients. Discovery only needs the listing-page anchors (present in
server-rendered HTML); PDF download/OCR is a later pipeline stage and is out
of scope for this discovery audit.

### Entry-page inventory accounting

- **open: 0** — the second application round closed 15 December 2025; Stage-2
  full proposals were due mid-June 2026; no third round is advertised.
- **closed: 1** — GFC Fund second round of applications (launched 30 Sep 2025,
  concept-note stage closed 15 Dec 2025; Stage-2 proposals due mid-June 2026).
- **upcoming: 0**
- **excluded: 4** unique PDFs (3× scope guidance EN/FR/SP + 1 standing
  concept-note template) — application materials/governance, not open calls.
- **unknown: 0**
- Pagination: single page, no page parameter, no `next` link; no page cap hit.
- Errors: none on the listing (HTTP 200).

`independent-inventory.json` is therefore an empty JSON array (`[]`): the
authoritative set of **open** opportunities on the official entry point is
empty. Excluded standing PDFs are documented here rather than as inventory
records, because inventory records with matching document URLs would suppress
`extra_submission` detection and hide discovery false positives (same rationale
as the FAO audit).

## Defect confirmed (adapter, pre-fix)

The adapter's signal regex included the generic tokens `concept[\s_-]*note`
and `gfc[\s_-]*fund`. Safe audit path (`DISCOVERY_AUDIT_ONLY=true`,
`SOURCES=unep`) before the fix emitted **4 false-positive candidates** — all
four standing wedocs PDFs above — solely because their paths/text carried
`GFC Fund` / `Concept note`. Independent fidelity vs the empty open inventory
returned **exit 1** with 4× `extra_submission` and candidate traceability 0%
(`discovery-before-fix.json`, `fidelity-before-fix/`).

## Post-fix observation

After narrowing the signal regex to open-call tokens only
(`call for proposals|applying for funding|request for proposals`):

- Safe audit path: **0 candidates**, `errors=0`, `candidate_cap_reached=0`.
- Independent fidelity vs `independent-inventory.json` (`[]`): **exit 0**,
  0 blocking exceptions, inventory accounting **100%**, candidate
  traceability **100%** (healthy empty 0/0), no hidden cap/partial
  (`discovery.json`, `stats.json`, `fidelity/`).
