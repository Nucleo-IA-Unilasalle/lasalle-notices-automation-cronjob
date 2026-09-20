# FAO technical audit — capture log (2026-09-14)

All times UTC. Fetches used plain `requests` with a generic User-Agent
(`Mozilla/5.0 (compatible; source-audit/1.0)`); no cookies, tokens, or
credential headers were sent or stored. Browser automation was not required
for the independent capture (entry page is server-rendered).

## Observation 1 — official entry point (authoritative for this source)

- Requested URL: `https://www.fao.org/plant-treaty/areas-of-work/funding/`
- Final URL: `https://www.fao.org/plant-treaty/areas-of-work/funding/` (no redirect)
- UTC: `2026-09-14T20:14:34.325710+00:00` → `2026-09-14T20:14:34.478828+00:00`
- HTTP status: `200`
- Content-Type: `text/html; charset=utf-8`
- Last-Modified header: `Mon, 14 Sep 2026 19:37:51 GMT`
- Meta last-modified: `2026-06-17T16:17:28Z`
- Title: `The Funding Strategy | International Treaty on Plant Genetic Resources for Food and Agriculture | FAO`
- Body length: 74441 bytes
- Render mode: **server-rendered** (full HTML body present without JS); Playwright
  not needed for inventory capture. The adapter's `browser_required=TRUE` fallback
  still ran in the safe audit path after the fix (BS4 found zero open-call PDFs).

Full-page keyword scan of main content (body_text length 5281): zero occurrences of
`call for`, `request for`, `expression of interest`, `procurement`, `deadline`,
`proposal`, `grant`, `submit`, `open call`. One mention of `Benefit-sharing Fund`
(in narrative prose, not a listing).

### On-host `.pdf` anchors on the entry page (complete list, 135 anchors total)

| Resolved URL | Anchor text | Lifecycle classification |
|---|---|---|
| `https://www.fao.org/3/nb780en/nb780en.pdf` | Funding Strategy | **excluded** — Funding Strategy policy document (adopted Nov 2019 for 2020–2025), not an open call |
| `https://www.fao.org/3/nb780en/nb780en.pdf#page=7` | Results Framework for the Funding Strategy | **excluded** — same policy PDF, fragment view |
| `https://www.fao.org/3/nb780en/nb780en.pdf` | Resolution 3/2019 | **excluded** — same policy PDF, resolution citation |
| `https://www.fao.org/3/no028en/no028en.pdf` | Resolution 4/2023 | **excluded** — governance resolution PDF |
| `https://www.fao.org/3/cc3636en/cc3636en.pdf` | The Funding Strategy of the ITPGRFA 2020-2025 | **excluded** — strategy policy PDF |
| `https://www.fao.org/3/cc3626en/cc3626en.pdf` | Food Processing Industry Engagement Strategy | **excluded** — unrelated engagement strategy; never matched open-call signals |

### Principal-document verification (HTTP GET, bounded stream, SHA-256)

| Requested URL | Status | Final URL (redirect) | Content-Type | Bytes read | SHA-256 | UTC |
|---|---|---|---|---|---|---|
| `https://www.fao.org/3/nb780en/nb780en.pdf` | 200 | `https://openknowledge.fao.org/server/api/core/bitstreams/9a152504-f576-4a45-8fb5-384be8f87822/content` | `application/pdf;charset=UTF-8` | 1279966 | `85cbbbe733dce5f692395d6d0d1e97e7da33b20a83a5ec93d23c3707f1d68b7a` | 20:17:09→20:17:11 |
| `https://www.fao.org/3/no028en/no028en.pdf` | 200 | `https://openknowledge.fao.org/server/api/core/bitstreams/00c11d81-c1ea-4833-803c-f7b8cec52950/content` | `application/pdf;charset=UTF-8` | 191467 | `d1c8f2490bdda8fc55edca490b27a09442dd08edb41ec237fb01c020e23c6641` | 20:17:11→20:17:13 |
| `https://www.fao.org/3/cc3636en/cc3636en.pdf` | 200 | `https://openknowledge.fao.org/server/api/core/bitstreams/eae32a78-7825-4b30-882b-7490b41201ec/content` | `application/pdf;charset=UTF-8` | 527661 | `5a943de98f4b03893590e774697d67a0de9087235247405ac2c6d05c1517aa5a` | 20:17:13→20:17:15 |

Note: `www.fao.org/3/...` PDFs redirect to `openknowledge.fao.org` bitstream
`/content` paths (host still under `*.fao.org`). Adapter host filter accepts them.

### Entry-page inventory accounting

- **open: 0** — no open call / RFP / EOI / procurement opportunity is listed on the official entry page.
- **closed: 0** — no closed opportunity listing with deadline is present on the entry page.
- **upcoming: 0**
- **excluded: 4 unique on-host PDFs** (nb780en, no028en, cc3636en, cc3626en) — strategy/resolution/engagement governance materials; not opportunities.
- **unknown: 0**
- Pagination: single page, no page parameter, no `next` link for opportunity listings; no page cap hit.
- Errors: none (HTTP 200).

`independent-inventory.json` is therefore an empty JSON array (`[]`): the
authoritative set of **open** opportunities on the official entry point is empty.
Excluded governance PDFs are documented here and in RESULT.md rather than as
inventory records, because inventory records with matching document URLs would
suppress `extra_submission` detection and hide discovery false positives.

## Observation 2 — related pages (provenance only; not the source entry point)

Fetched to confirm no open call is hidden on sibling funding pages that the
adapter does not visit. These pages are **out of the source's configured scope**;
they are not included in `independent-inventory.json`.

### Benefit-sharing Fund landing

- URL: `https://www.fao.org/plant-treaty/areas-of-work/benefit-sharing-fund/en/`
- Status 200; UTC `2026-09-14T20:15:31.816701+00:00` → `20:15:31.958147+00:00`
- No call/RFP/EOI/procurement keywords in main text; PDFs are evaluations, MEL
  framework, operations manual, standing committee — all governance materials.

### BSF overview

- URL: `https://www.fao.org/plant-treaty/areas-of-work/benefit-sharing-fund/bsf-overview/en/`
- Status 200; UTC `2026-09-14T20:15:31.959088+00:00` → `20:15:34.276625+00:00`
- PDFs: Funding Strategy / Operations Manual only.

### Fifth Cycle of the BSF

- URL: `https://www.fao.org/plant-treaty/areas-of-work/benefit-sharing-fund/fifth-cycle/en/`
- Status 200; UTC `2026-09-14T20:15:47.450686+00:00` → `20:15:49.705242+00:00`
- Contains "Text of the Fifth Call for Proposals"
  (`https://www.fao.org/3/cc0235en/cc0235en.pdf`) but the call is **closed**:
  page states pre-proposals were due **29 July 2022, 23.59 CEST**, and the
  Committee approved funded projects in May 2023. No sixth call is advertised.
- Not on the adapter's listing URL; not part of this source's independent inventory.

## Defect confirmed (adapter, pre-fix)

Safe audit path (`DISCOVERY_AUDIT_ONLY=true`) before the fix emitted **3**
false-positive candidates solely because the signal tokens `funding strategy`
and `resolution` matched governance PDF text/paths:

1. `https://www.fao.org/3/nb780en/nb780en.pdf` (Funding Strategy / Resolution 3/2019)
2. `https://www.fao.org/3/no028en/no028en.pdf` (Resolution 4/2023)
3. `https://www.fao.org/3/cc3636en/cc3636en.pdf` (Funding Strategy 2020-2025)

Independent fidelity vs empty inventory: **exit 1**, 3× `extra_submission`,
candidate traceability 0%, inventory accounting 100% (0 open in scope).
See `discovery-before-fix.json`, `fidelity-before-fix/`.

## Post-fix observation

After narrowing the signal regex to open-call tokens only
(`call for proposals|request for proposals|expression of interest|eoi|procurement`):

- Safe audit path: **0 candidates**, `errors=0`, `candidate_cap_reached=0`,
  `playwright_fallback_used=1` (BS4 empty → Playwright ran and also found 0).
- Independent fidelity: **exit 0**, 0 blocking exceptions, inventory accounting
  100%, candidate traceability 100% (0/0 healthy empty).
- See `discovery.json`, `stats.json`, `fidelity/`.
