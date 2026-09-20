# msgov independent capture log (2026-09-14)

All timestamps UTC. Capture performed with direct HTTP (`requests`) and an
independent Playwright script — **not** via `scripts/discover_msgov_candidates.py`
or `scripts/run_independent_source_audit.py`. No cookies, tokens, or auth
headers are stored in evidence; the Prosas anonymous OAuth token was held
in memory only.

## Entry point

- Official listing: `https://editaisms.prosas.com.br` (HTTP 200,
  `text/html; charset=utf-8`, 20929 bytes, 2026-09-14T20:49:53Z).
- Page is a static shell loading `cdn.prosas.com.br/front-sdk` web
  components. Two tabs: "Editais com inscrições abertas" (open) and
  "Editais com inscrições encerradas" (closed). Public client id on the
  page drives an anonymous OAuth token against `prosas.com.br/auth/oauth2/token`.

## Listing API enumeration (full pagination)

- Open: `GET https://prosas.com.br/selecao/api/v2/third_party/oportunidades/inscricoes_abertas`
  with incentivador-id filter `1418,1567,1569,1573,1591,1634`, `page[size]=100`
  → HTTP 200 `application/vnd.api+json`, **23 items** on one page
  (2026-09-14T20:51:10Z).
- Closed: `GET https://prosas.com.br/selecao/api/v2/third_party/oportunidades`
  with `data_limite_inscricao_sem_rascunho < <now>` filter, `page[size]=100`
  → HTTP 200, page1=100 + page2=25 = **125 items** (same window).
- UI open tab (Playwright, default page size 20) rendered only **20** edital
  anchors; shadow DOM header says "23 editais encontrados" and pagination
  buttons (first/prev/next/last) exist at the end of the list. Missing from
  page 1: ids **16859, 16862, 17087**. Confirmed the adapter's pre-fix
  listing walk never clicked next.

## Detail documents

- Detail API:
  `GET https://prosas.com.br/selecao/api/v2/third_party/oportunidades/<id>?include=…,arquivos,…`
  → HTTP 200 for all 23 open ids; **113 arquivos total** (29 `.pdf`, rest
  office annexes on the same Prosas S3/objectstorage hosts).
- DOM detail pages (`/edital.html?id=<id>`) lazy-load annexes behind the
  `prosas-box-container-dropdown` ("Complementares") button; after expand,
  `.pdf` anchors appear on `objectstorage.sa-saopaulo-1.oraclecloud.com`
  (preauthenticated `/p/<token>/` paths — token changes every request;
  stable object path is under `/n/…/b/prosas-prod/o/arquivos/…`).
- All 23 open detail pages yielded ≥1 PDF after expand+wait; PDF list saved
  in the temp capture (`details/detail_pdfs.json`).

## Lifecycle accounting (capture window 2026-09-14T20:49Z–21:12Z)

| Class    | Count | Basis |
|----------|------:|-------|
| open     |    29 | 23 editais × their PDFs (status open per `inscricoes_abertas`; 3 have null deadline / continuous flow) |
| closed   |   125 | portal closed tab filter (deadline < now) |
| upcoming |     0 | none with future start outside open set |
| excluded |     0 | no policy exclusions applied to this source |
| unknown  |     0 | every listed edital classified |

## Errors

- Two early independent Playwright listing probes returned 0 edital anchors
  (intermittent component render timing); retries with longer waits
  succeeded. No HTTP non-2xx on official endpoints during the final capture.
- Independent first detail-URL DOM pass without a post-expand wait found 0
  PDFs (timing); re-run with expand+2.5s wait found PDFs on all 23.
