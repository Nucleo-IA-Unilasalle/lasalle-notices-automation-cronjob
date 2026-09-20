# IBAMA independent capture log (2026-09-14)

Method: direct `requests` GET of official public gov.br/ibama pages and RDF/RSS
feeds only. No repo adapter import. No cookies, headers, tokens, or personal
data stored. User-Agent: `Mozilla/5.0 (compatible; ibama-independent-audit/1.0)`.

## Official endpoints (UTC capture window ~22:05)

| URL | status | content-type | notes |
| --- | --- | --- | --- |
| https://www.gov.br/ibama/pt-br/acesso-a-informacao/editais-e-convites/chamamentos-publicos/chamamentos-publicos | 200 | text/html | listing |
| https://www.gov.br/ibama/pt-br/acesso-a-informacao/editais-e-convites/editais-e-convites | 200 | text/html | listing |
| https://www.gov.br/ibama/pt-br/assuntos/notas/2026/ | 200 | text/html | listing |
| https://www.gov.br/ibama/pt-br/acesso-a-informacao/editais-e-convites/chamamentos-publicos/RSS | 200 | application/rss+xml | RDF feed |
| https://www.gov.br/ibama/pt-br/assuntos/notas/2026/RSS | 200 | application/rss+xml | RDF feed |

Detail pages: 47 unique gov.br/ibama seeds (min year 2026), all HTTP 200,
content-type text/html. No listing pagination beyond the single official page.
No detail cap reached (47/60 module cap; registry detail_limit=20 applies to
production ingest, not this discovery-only audit).

## Lifecycle accounting (independent inventory)

- open=2 (edital-4-2026 AGU adhesion deadline 2026-11-30; edital-20-2026 FSO
  hearing-request period 2026-10-15)
- closed=9
- upcoming=0
- excluded=35 (administrative/results/brigadistas/doações/leilão/historical 2020, etc.)
- unknown=2 (CIMAN fire-season informe; offshore drilling hearing news without deadline)
- cancelled=0

Principal documents: detail-page PDF/ZIP/DOCX/ODS attachments only; edital-22
merged retificação attachments retained on the principal record.

Sanitization: capture-log.json records only url/final_url/status/content_type/
content_length/timestamps/ok/error. No request headers or cookies persisted.
