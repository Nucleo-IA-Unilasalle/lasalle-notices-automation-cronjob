# DOPA independent capture log (2026-09-14)

All fetches used direct `urllib` GET against the official public DOPA API only
(no repo adapter, no cookies, no credentials, no personal data).

## Window

- Timezone: America/Sao_Paulo
- Local dates: 2026-09-12 .. 2026-09-14 (3-day incremental window, same as adapter)
- Capture start UTC: 2026-09-14T20:42:19Z
- Capture end UTC: 2026-09-14T20:43:28Z

## Principal search

| UTC | URL | HTTP | Content-Type | Bytes |
| --- | --- | --- | --- | --- |
| 2026-09-14T20:42:19Z | `https://apigateway.procempa.com.br/apiman-gateway/administracao-planejamento/dopa/1.1/api/diarios/busca-avancada?dataInicial=2026-09-12&dataFinal=2026-09-14&escopo=executivo` | 200 | application/json | 52958 |

- Rows returned: **145** (full list; no pagination parameter required by the API; search_result cap not hit)
- Duplicate `idConteudo` rows: 0
- Detail failures: 0 (145/145 details fetched successfully during classification pass)

## Detail endpoints

- Pattern: `https://apigateway.procempa.com.br/apiman-gateway/administracao-planejamento/dopa/1.1/api/diarios/conteudo/{id}/detalhes`
- All 145 detail GETs returned HTTP 200, `application/json` (see `capture-log.json` for per-request UTC/status/bytes).
- Principal document export pattern (not re-downloaded for inventory): `.../conteudo/{id}/exportar-pdf`

## Lifecycle accounting (independent classification of all 145 unique rows)

| Bucket | Count | Notes |
| --- | --- | --- |
| open | 5 | 627460, 627564, 627176, 627585, 627563 |
| closed | 2 | lifecycle-closed rows retained for provenance |
| upcoming | 0 | none identified |
| excluded | 138 | post-acts, PNCP procurement, non-opportunity gazette rows (includes 627636/627635/627632 post-acts that the pre-fix adapter wrongly emitted) |
| unknown | 0 | after full detail review every row was classifiable |

## Ground-truth open set (post-review)

1. **627460** — AVISO DE PRORROGAÇÃO EDITAL DE CHAMAMENTO PÚBLICO DPC-SMP 004/2026; propostas até 14/10/2026 18h AO → deadline `2026-10-15T02:59:59+00:00`
2. **627564** — CHAMAMENTO PÚBLICO 012/2026 credenciamento de oficineiros; permanece aberto 12 meses; no fixed calendar deadline
3. **627176** — EDITAL DE SORTEIO 001/2026; inscrições 25/09/2026–09/10/2026; end-of-day AO deadline `2026-10-10T02:59:59+00:00`
4. **627585** — EDITAL 002/2026 Residência Médica (Medicina Fetal/Endoscopia); edital das vagas 2027; deadline in attached PDF
5. **627563** — EDITAL 001/2026 PRIMURGE; edital de abertura 2027; deadline in attached PDF

## Pre-fix post-act leaks (must not emit)

- **627636** — Gabarito Definitivo (Residência Jurídica)
- **627635** — Respostas aos Recursos + Gabarito Definitivo + Notas Preliminares (Concurso 869–873)
- **627632** — Resultado Preliminar de Inscritos / Notas Preliminares; appeal window 16/09/2026 (misread as application deadline)

No cookies, Authorization headers, tokens, or personal data were stored.
