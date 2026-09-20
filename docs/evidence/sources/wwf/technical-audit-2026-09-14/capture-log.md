# WWF independent capture log — 2026-09-14

Capture method: direct HTTPS GET via Python `requests` (not
`scripts/discover_wwf_candidates.py`, not `scripts/run_independent_source_audit.py`).

User-Agent: Chrome/128 Windows desktop string. No cookies, auth headers, or
credentials sent or stored.

## Listing

| Field | Value |
| --- | --- |
| URL | `https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/` |
| HTTP status | 200 |
| Content-Type | `text/html; charset=utf-8` |
| Fetched (UTC end) | see `capture-log.json` (`fetched_at_utc_end`) |
| Final URL | same (no cross-host redirect) |
| EDITAIS ABERTOS heading | present |
| EDITAIS ENCERRADOS heading | present |
| Rows parsed | 10 (4 open + 6 closed sections) |

## Detail pages (all HTTP 200, Content-Type text/html)

| Detail id | Query | Section | Notes |
| --- | --- | --- | --- |
| 95223 | Consultoria-para-intervencoes…Pantanal | open | content area `div.template433` present; **zero PDF links** (DOCX TDRs only) |
| 95221 | Consultoria-para-revisao…DCF | open | carta_convite + divulgacao PDFs |
| 95184 | Consultoria-para-engajamento-da-Rede-PainelMar | open | carta-convite + divulgacao PDFs |
| 95182 | Contratacao-de-assistente-de-apoio-operacional | open | carta-convite + divulgacao PDFs |
| 95100 | …Parque-Nacional-da-Amazonia | closed | carta-convite + divulgacao |
| 95081 | …COP17 | closed | carta-convite + divulgacao |
| 95080 | …Unidades-Demonstrativas… | closed | carta-convite (prorrogação) + divulgacao |
| 95044 | …textos-cientificos | closed | carta-convite + divulgacao |
| 95041 | …captacao-de-recursos… | closed | carta-convite + resultado (rejected) + divulgacao |
| 94961 | …Bem-Viver-e-Bioeconomia | closed | carta-convite + resultado/divulgacao (rejected set) |

Detail fetch cap: 20 (registry `detail_limit`); 10 fetched → **cap not reached**.
Pagination: single listing page (registry `page_limit` N/A — no multi-page feed).

## Lifecycle accounting (independent inventory)

| Status | Count | Notes |
| --- | --- | --- |
| open | 7 | 6 with adapter-eligible PDFs; 1 (95223) DOCX-only → `reason_code=out_of_scope` |
| closed | 13 | provenance only (closed expected for WWF) |
| upcoming | 0 | |
| excluded | 0 | |
| unknown | 0 | no detail fetch errors |

## Principal documents

Open rows publish a **carta convite / carta-convite** PDF as the principal
edital document, plus a **divulgacao_** announcement PDF. Closed rows keep the
same shape; **resultado_** PDFs are excluded by the default edital prefilter.
