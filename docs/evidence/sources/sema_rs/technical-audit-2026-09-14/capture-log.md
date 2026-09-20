# SEMA-RS independent capture log (sanitized)

Captured via direct HTTP (requests + BeautifulSoup), NOT via scripts/discover_sema_rs_candidates.py.
No cookies, headers, credentials, or personal data recorded; only URL, UTC time, HTTP status, content type.

## HTTP requests (chronological)

| # | UTC time | HTTP | Content-Type | URL |
|---|----------|------|--------------|-----|
| 1 | 2026-09-14T20:34:22Z | 200 | application/json | https://www.sema.rs.gov.br/busca/lista-data-table?currentPage=1&pageSize=20&form%5Bpalavraschave%5D=edital&form%5Bordem%5D=RECENTES |
| 2 | 2026-09-14T20:34:22Z | 200 | application/json | https://www.sema.rs.gov.br/busca/lista-data-table?currentPage=2&pageSize=20&form%5Bpalavraschave%5D=edital&form%5Bordem%5D=RECENTES |
| 3 | 2026-09-14T20:34:23Z | 200 | application/json | https://www.sema.rs.gov.br/busca/lista-data-table?currentPage=1&pageSize=20&form%5Bpalavraschave%5D=chamada&form%5Bordem%5D=RECENTES |
| 4 | 2026-09-14T20:34:24Z | 200 | text/html; charset=UTF-8 | https://www.sema.rs.gov.br/residuos-solidos |
| 5 | 2026-09-14T20:34:27Z | 200 | text/html; charset=UTF-8 | https://www.sema.rs.gov.br/edital-01-de-2024-delta-do-jacui |
| 6 | 2026-09-14T20:34:30Z | 200 | text/html; charset=UTF-8 | https://www.sema.rs.gov.br/inscricoes-abertas-edital-002-de-2022-voluntariado-pe-tainhas |

## Enumeration accounting

- AJAX keyword 'edital': pages_fetched=2, recordcount=29, pagecount=2, unique signal-matched detail URLs=2 (page 1: 20 articles / 0 signal matches; page 2: 9 articles / 2 signal matches). Pagination complete (page 3 body has no articles).
- AJAX keyword 'chamada': pages_fetched=1, recordcount=5, pagecount=1, unique signal-matched detail URLs=0 (5 articles, 0 signal matches). Pagination complete.
- Static page https://www.sema.rs.gov.br/residuos-solidos: HTTP 200, 15 PDF anchors (10 unique same-host non-call docs + 4 off-host statute PDFs on ww3.al.rs.gov.br/www.al.rs.gov.br + 1 duplicate). 1 signal-bearing PDF (Edital de Chamada Publica -> materia1309752.pdf) sits in a panel-body that also contains "Resultado Final" (call concluded).
- Detail page /edital-01-de-2024-delta-do-jacui: HTTP 200, 0 PDF anchors (2024 call, closed).
- Detail page /inscricoes-abertas-edital-002-de-2022-voluntariado-pe-tainhas: HTTP 200, 25 PDF anchors, all under /upload/arquivos/2020..2023 folders (pre-min-year archive; page titled "Editais Encerrados").
- Probe pages (bounded): /editais, /edital, /chamadas-publicas, /noticias -> HTTP 404 (no dedicated listing routes).
- Probe pages (bounded): /fundo-estadual-de-protecao-e-bem-estar-animal (HTTP 200) hosts two May-2026 edital PDFs but the page anchor/title carries no signal token, so the contracted selector never reaches it; both calls concluded by June-2026 portarias (out_of_scope). /programa-biogas-rs (HTTP 200) hosts 2022-2024 edital PDFs (pre-min-year). /programa-energia-forte-no-campo-5-fase, /outorga-aguas-subterraneas (HTTP 200): no open 2026 calls.
- Pagination caps: none reached (recordcounts fully enumerated within pagecount; year_rejected=25 is lifecycle filtering, not a cap).
- Errors: 0 during adapter-path capture; 4 expected 404s on nonexistent probe routes.


## Follow-up verification requests

- 2026-09-14T20:38Z: GET /editais /edital /chamadas-publicas /noticias -> HTTP 404 (text/html).
- 2026-09-14T20:39-20:41Z: GET /fundo-estadual-de-protecao-e-bem-estar-animal, /programa-biogas-rs, /programa-energia-forte-no-campo-5-fase, /outorga-aguas-subterraneas, /forum-gaucho-de-mudancas-climaticas-debate-monitoramento-de-eventos-extremos -> HTTP 200 (text/html); lifecycle evidence recorded in independent-inventory.json titles.
- 2026-09-14T20:42-20:45Z: GET listing pages edital p1-p3 / chamada p1-p3 re-verified article-presence and pagecount fields (200, application/json); HEAD materia1309752.pdf -> 200 application/pdf, Last-Modified Fri 22 May 2026.
- Deadlines observed: none parseable as future ISO deadlines on any open-surface page; all identified calls carry concluded-lifecycle evidence (Resultado Final, portarias, Editais Encerrados) or pre-2026 document folders.
