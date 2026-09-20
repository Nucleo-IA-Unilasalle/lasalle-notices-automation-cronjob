# Capture log — iis_rio independent inventory (2026-09-14)

Mode: bounded, read-only capture of official public IIS-Rio pages.
Captured via direct HTTP GET (requests, descriptive UA
`lasalle-notices-fidelity-audit/1.0`), no cookies, no credentials, no
session persistence. Timestamps UTC.

## Surfaces fetched

| URL | Status | Notes |
|-----|--------|-------|
| https://www.iis-rio.org/noticias/ | 200 | Listing page 1; 13 signal-token detail URLs extracted with the production `extract_iis_rio_detail_urls` |
| https://www.iis-rio.org/noticias/?tipo-de-noticia=noticia&paged=2 | 404 | End-of-archive (WordPress). Adapter now treats page>1 404 as clean end-of-pagination |
| https://www.iis-rio.org/noticias/?tipo-de-noticia=noticia | 200 | Filtered archive (probe only) |
| https://www.iis-rio.org/noticias/?tipo-de-noticia=noticia&paged=1 | 200 | Same content as unfiltered page 1 (probe only) |
| https://www.iis-rio.org/noticias/?paged=2 | 404 | Confirms single-page archive |
| https://www.iis-rio.org/noticias/page/2/ | 404 | Confirms single-page archive |
| 13 detail pages under /noticias/<slug>/ | 200 each | Titles, visible dates, deadline phrases, and PDF anchors recorded |

Fetch count: 16 (2 listing + 4 probes + 13 details − 1 duplicate page-1 refetch); errors: 0.

## Lifecycle accounting (as of 2026-09-14T20:22Z–20:33Z)

- **open: 0** — no notice carries a future deadline or an open-application
  phrase. Latest consultation closed 2025-07-15.
- **closed: 13** — every signal-token notice on the official listing is a
  past-dated consultoria/chamada/mestrado call; deadlines (where present)
  are 2019–2025.
- **upcoming: 0** — no future-dated call visible.
- **excluded: 0** — no out-of-scope dispositions needed (all rows are
  genuine IIS-Rio notices; none are news-only leads without a call).
- **unknown: 0** — every listed notice has enough on-page evidence
  (deadline phrase or past publication context) to classify as closed.

Recent 2026 news items on the site (Conaveg resolution, biochar, World
Biodiversity Forum, etc.) do **not** match the adapter's signal tokens
(`edital|chamada|consultoria|tdr`) and are correctly absent from the
inventory — they are news, not procurements.

## Principal documents

11 notice-scoped PDFs are live-linked from the detail pages (TdRs, errata,
Q&A). One additional site-wide PDF
(`Politica-de-Privacidade-Instituto-Internacional-para-Sustentabilidade-IIS.pdf`)
appears in the global footer of every page; it is boilerplate, not a notice
document, and is excluded from the inventory's `document_urls` by design.
Five records that the prior session captured with empty `document_urls`
were refreshed this session with their live-linked TdR PDFs (see
commands.md step 8–9).

## Caps and errors

- Effective listing pages required: 1 (archive is single-page).
- Detail fetches: 13 (registry `detail_limit=20` — not reached).
- Attachments observed per detail: ≤3 (registry `attachment_limit=25` —
  not reached).
- Errors during independent capture: 0.
- No rate limiting, no bot challenge, no authentication required.
