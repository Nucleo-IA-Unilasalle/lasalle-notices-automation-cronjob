# Canoas Independent Capture Log (2026-09-14)

Capture window (UTC): **2026-09-14T20:20:55Z – 2026-09-14T20:21:21Z**
Local America/Sao_Paulo: 2026-09-14 ~17:20–17:21 (−03:00).
Captured via direct HTTP (`Invoke-WebRequest` / urllib), **not** via the repo adapter.
Bounded discovery window: 3 days ending 2026-09-14 (adapter default `CANOAS_INCREMENTAL_WINDOW_DAYS=3`).

## Official endpoints

| URL | HTTP | Content-Type | Bytes | Outcome |
|-----|------|--------------|-------|---------|
| `https://sistemas.canoas.rs.gov.br/domc/api/public/diary-by-day?day=12%2F09%2F2026` | 200 | application/json | 2 | `{}` — empty day (Saturday; DOMC represents no edition as empty object) |
| `https://sistemas.canoas.rs.gov.br/domc/api/public/diary-by-day?day=13%2F09%2F2026` | 200 | application/json | 2 | `{}` — empty day (Sunday) |
| `https://sistemas.canoas.rs.gov.br/domc/api/public/diary-by-day?day=14%2F09%2F2026` | 200 | application/json | 6874 | Day edition 3930: 4 editions, 48 index rows (unique publication ids) |
| `https://sistemas.canoas.rs.gov.br/domc/api/publication-file/140919` | 200 | application/pdf | 74674 | Principal DOMC PDF for the only opportunity-signal row |
| `https://www.canoas.rs.gov.br/wp-json/wp/v2/licitacoes?search=319%202026&per_page=20` | 200 | application/json | 2 | `[]` — no 2026 WP page for edital 319 |
| `https://www.canoas.rs.gov.br/wp-json/wp/v2/licitacoes?search=edital%20319&per_page=20` | 200 | application/json | (large) | Only historical 2021/2022 pregão pages (class_list modalidade-pregao-eletronico); not 2026 |
| `https://sistemas.canoas.rs.gov.br/domc/pesquisar` | 200 | text/html | (SPA shell) | Official search UI; Vue app defaults publication_date to 14/09/2026; not used as inventory source |

No pagination caps on diary-by-day (full day index returned). No HTTP errors. No cookies/headers/tokens stored.

## Full day-14 publication accounting (48 rows)

Policy classification independently reproduced against adapter title filters (post_act / pncp_procurement / no_opportunity_signal):

| Class | Count | Examples |
|-------|------:|----------|
| no_opportunity_signal | 35 | ORÇAMENTO Nº 257/2026; PORTARIA Nº 2.0xx; SÚMULA CONTRATOS/TERMOS; CONSULTA PÚBLICA Nº 258/2026 (market survey; no edital/chamamento/credenciamento signal) |
| post_act | 10 | APOSTILAs 738–746; TERMO DE HOMOLOGAÇÃO; SÚMULA APOSTILA; DOCUMENTO OFICIAL LICITATÓRIO ATA |
| pncp_procurement | 2 | EDITAL Nº 227/2026 PREGÃO ELETRÔNICO (alterações); AVISO DE DISPENSA ELETRÔNICA Nº 002/2026 |
| opportunity-signal (emit candidate) | 1 | **140919 EDITAL N°319/2026** |

## Lifecycle classification (official inventory)

| Lifecycle | Count | Notes |
|-----------|------:|-------|
| open | 0 | No publication in the 3-day window is an open application opportunity |
| closed | 0 | — |
| upcoming | 0 | — |
| excluded | 47 | Policy-filtered noise (no_opportunity_signal / post_act / pncp_procurement) |
| unknown | 1 | 140919 EDITAL Nº319/2026 — administrative designation of named nursing staff to CEE electoral/ethics commission; PDF has no public application window or deadline; WordPress unresolved (empty search) |

### Principal document for 140919

- PDF (200, application/pdf, 74674 bytes): `https://sistemas.canoas.rs.gov.br/domc/api/publication-file/140919`
- PDF text: “EDITAL DE DESIGNAÇÃO N°319/2026 PARA COMPOSIÇÃO DA COMISSÃO ELEITORAL … COMISSÃO DE ÉTICA DE ENFERMAGEM … designam os profissionais abaixo descritos”
- Not a procurement (no pregão/dispensa); not a call for proposals; no inscription period.
- Adapter emits status=`unknown` with DOMC PDF as principal document when WP is unresolved — consistent with independent assessment.

## Caps / partial / errors

- Caps reached: none (records 48 < publication cap 300; opportunities 1 < 25; WP lookups 1 < 20).
- Partial inventory: no.
- Errors: none.
