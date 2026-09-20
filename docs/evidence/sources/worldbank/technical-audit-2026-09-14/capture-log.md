# WorldBank technical audit 2026-09-14 — capture log

Independent inventory captured WITHOUT the repo adapter (direct HTTP only). No cookies, headers with credentials, or personal data retained.

## Listing page

- URL: `https://www.worldbank.org/en/programs/sief-trust-fund/brief/sief-call-for-proposals-8-edtech-for-foundational-learning`
- Method: direct HTTP GET (PowerShell `HttpWebRequest`, User-Agent `Mozilla/5.0 (compatible; source-audit/1.0)`)
- UTC timestamp: `2026-09-14T21:47:10Z`
- HTTP status: `200`
- Content-Type: `text/html;charset=utf-8`
- Body size: `40,793` bytes
- Parsed independently with BeautifulSoup (`total_anchors=22`)

## Page text (main content)

- Title: SIEF Call for Proposals 8: EdTech for Foundational Learning
- Brief date / published: **April 8, 2026**
- Deadlines stated on the page:
  - Quick assessment form (World Bank External researchers): **Due April 22, 2026**
  - Main application form (via World Bank Task Team Leader): **Due May 19, 2026**
- As of capture `2026-09-14T21:47Z` both deadlines are in the past → authoritative lifecycle for the call is **closed** (page remains publicly listed).
- Token scan (body lowercased): `call for proposals`=25, `request for proposals`=0, `expression of interest`=0, `deadline`=0 (the word "Due" is used, not "deadline"), `procurement`=0.

## PDF anchors (full accounting)

| # | URL | Anchor text | Signal token | HTTP check | Inventory status |
|---|-----|-------------|--------------|------------|------------------|
| 1 | `https://thedocs.worldbank.org/en/doc/15fc51eee03c29f8e5ed847b76ed9d55-0090052026/original/SIEF-Call-8-EdTech-040926.pdf` | Call for proposals (appears twice; deduped to one canonical URL) | yes (`call for proposals` in text) | HEAD `200 application/pdf` 430,260 bytes @ `2026-09-14T21:47:56Z` | **closed** (deadlines past); principal document |
| 2 | `https://thedocs.worldbank.org/en/doc/8edffdcd096b9275c8786996b33c21ce-0090052026/original/Call-8-announcement.pdf` | Presenting the evaluations of the EdTech for Foundational Learning Window (RELATED > Funding decisions) | no | HEAD `200 application/pdf` 228,904 bytes @ `2026-09-14T21:47:56Z` | **excluded** (`out_of_scope`: no signal token) |

Totals: open=0, closed=1, upcoming=0, excluded=1, unknown=0.

## Non-PDF application channels (outside adapter PDF contract)

- Quick assessment form: Google Forms link (`docs.google.com/forms/d/e/1faipql...`) — not a PDF; not discoverable by `extract_worldbank_pdf_urls`.
- Main application form: World Bank Internal Google Forms link — not a PDF; not discoverable.
- These are recorded here for completeness only; the adapter contract discovers `.pdf` anchors on `worldbank.org` hosts only.

## Pagination and caps

- Single static HTML page; no pagination controls or next-page links.
- Candidate cap 50 (adapter default) unreachable at 2 PDFs / 1 signal PDF.
- Playwright fallback not required: the page is fully server-rendered (static HTML contains all main content and PDF anchors); registry `browser_required=false` matches observed reality.

## Errors

- None. All fetches returned HTTP 200.
