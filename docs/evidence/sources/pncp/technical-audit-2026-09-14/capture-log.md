# PNCP independent capture log (2026-09-14)

All timestamps UTC. Capture performed with direct HTTP (`requests`) against the
official public PNCP API — **not** via `scripts/discover_pncp_candidates.py`
and **not** via `scripts/run_independent_source_audit.py`. No cookies, tokens,
or auth headers are stored in evidence; PNCP is anonymous public API only.

## Entry point (official)

- Publicação listing: `https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao`
- Documentos: `https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos`
- Canonical web UI (not fetched for inventory): `https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}`

## Query bound (documented precisely — high-volume source)

Because full RS production windows are high-volume, this audit uses a
**bounded representative capture**. Any page or doc cap inside the bound is a
failure signal, not a pass.

| Knob | Value |
|------|-------|
| endpoint | publicação |
| uf | RS |
| codigoModalidadeContratacao | **4 only** (Concorrência Eletrônica) |
| dataInicial | 20260913 (capture-day − 1, Brasília) |
| dataFinal | 20260914 (capture day, Brasília) |
| tamanhoPagina | 50 |
| max pages/query | 20 |
| anoCompra filter | ≥ 2026 (classification) |
| capture window | 2026-09-14T22:25:46Z – 22:26:49Z |

**Out of this independent bound** (documented, not silently omitted):
modalities 6 (Pregão Eletrônico) and 8 (Dispensa); federal CNPJ sweeps
(`33654831000136`, `00889834000108`, `00394494000136`, `37115375000107`);
`/proposta` and `/atualizacao` listing endpoints. A full multi-modality
one-day probe (`full-day-mod-all-summary.json`) showed mod6=184, mod8=425,
mod4=30 for 20260914 alone (639 unique controls; open=150) and a 30-day
mod6 window of 3076 records / 62 pages — beyond a single bounded audit pass
under rate limits. That high-volume probe hit its own open-set/doc hard caps
and is retained only as a failure-signal contrast, not as ground truth.

## Listing enumeration (within bound)

- `GET …/publicacao?uf=RS&codigoModalidadeContratacao=4&dataInicial=20260913&dataFinal=20260914&pagina=1&tamanhoPagina=50`
  → HTTP 200 `application/json`, **totalRegistros=30**, totalPaginas=1.
- Single page enumerated completely (pages_fetched=1; no page cap).
- Dedup by `numeroControlePNCP` (prefer higher `dataAtualizacaoGlobal`) → **30 unique controls**.

## Lifecycle accounting (capture 2026-09-14T22:25:46Z)

Classification mirrors adapter policy independently:
anoCompra≥2026; situacaoCompraId≠1 → closed; missing
dataEncerramentoProposta → unknown; deadline ≤ now → closed; abertura > now →
upcoming; else open.

| Class | Count | Basis |
|-------|------:|-------|
| open | 15 | situacaoCompraId=1, deadline in future, abertura not future |
| closed | 4 | deadline passed or situacao≠1 |
| upcoming | 11 | dataAberturaProposta in future |
| excluded | 0 | none below anoCompra 2026 |
| unknown | 0 | all records had encerramento dates |

## Principal documents (open records)

- Docs API HTTP 200 for all 15 open controls (doc_lookups=15, doc_failures=0).
- Preferred types: edital, aviso de contratação direta, termo de referência.
- **15/15 open controls have ≥1 preferred principal document.**
- SHA-256 of ≤1.5 MiB streamed prefix recorded per preferred URL (sanitized
  path-only URLs in evidence; no cookies/headers stored).

## Errors / rate limits

- Independent inventory pass: 0 HTTP errors, 0 rate-limit events.
- Earlier full-day multi-modality probe and some discovery dry-run retries
  hit HTTP 429 / read timeouts under public rate limits (documented in
  commands.md). The synchronized bound used for fidelity avoided caps.

## Caps

- Within the documented bound: **no page cap, no doc cap, no unknown leftovers.**
- Full-day multi-modality probe (contrast only): hard open/doc caps reached →
  treated as failure signal for unbounded production-window auditing, not a pass.
