# Capture log — fbds technical audit 2026-09-14

Independent capture via direct official public pages only (webfetch of
`restaura-amazonia.fbds.org.br`). Not via the repo adapter. No cookies,
headers, tokens, or personal data retained. UTC session window ~21:45Z–22:00Z
on 2026-09-14.

## Official surface

| URL | HTTP | Content-Type | Notes |
|-----|------|--------------|-------|
| https://restaura-amazonia.fbds.org.br/Editais | 200 (webfetch success) | text/html; charset=utf-8 | SPIP 4.4.23 listing; section header "Editais Concluídos"; 4 detail links under "Informações completas" |
| .../Apoio-a-Restauracao-Ecologica-e-ao-Fortalecimento-da-Cadeia-Produtiva-da-Restauracao-em-municipios-do-Mato-Grosso-e-24 | 200 | text/html; charset=utf-8 | Edital 004/2025 badge Concluído; deadline 10/11/2025 18:00 BRT; principal ZIP `/IMG/zip/restaura_amazonia_mr2_-_edital_004-2025_e_docs_de_apoio.zip` |
| .../Apoio-a-Restauracao-Ecologica-e-ao-Fortalecimento-da-Cadeia-Produtiva-da-Restauracao-em-municipios-do-Mato-Grosso-e | 200 | text/html; charset=utf-8 | Edital 003/2025 badge Concluído; deadline 18/08/2025 18:00 BRT; principal ZIP `...edital_003-2025_e_docs_de_apoio.zip` |
| .../Apoio-a-Restauracao-Ecologica-e-Fortalecimento-da-Cadeia-Produtiva-da-Restauracao-em-municipios-do-Mato-Grosso-e | 200 | text/html; charset=utf-8 | Edital 002/2025 badge Concluído; deadline 07/07/2025 18:00 BRT; principal ZIP `...edital_002-2025_e_docs_de_apoio.zip` |
| .../Apoio-a-Restauracao-Ecologica-e-Fortalecimento-da-Cadeia-Produtiva-da-Restauracao-em-municipios-do-Mato-Grosso | 200 | text/html; charset=utf-8 | Edital 001/2024 badge Concluído; deadline 28/02/2025 18:00 BRT; principal ZIP `...edital_001-2024.zip` |

## Full accounting (no caps)

| Category | Count | Records |
|----------|------:|---------|
| open | 0 | — |
| closed | 4 | Edital 004/2025, 003/2025, 002/2025, 001/2024 |
| upcoming | 0 | — |
| excluded | 0 | — |
| unknown | 0 | — |

Pagination: single listing page; no page-2 / next-link observed; adapter
`detail_limit=20` and `page_limit=5` not reached (4 ≤ 20). No request errors.
No cookies or auth material stored.

## Principal documents (independent)

- 004/2025: `https://restaura-amazonia.fbds.org.br/IMG/zip/restaura_amazonia_mr2_-_edital_004-2025_e_docs_de_apoio.zip`
- 003/2025: `https://restaura-amazonia.fbds.org.br/IMG/zip/restaura_amazonia_mr2_-_edital_003-2025_e_docs_de_apoio.zip`
- 002/2025: `https://restaura-amazonia.fbds.org.br/IMG/zip/restaura_amazonia_mr2_-_edital_002-2025_e_docs_de_apoio.zip`
- 001/2024: `https://restaura-amazonia.fbds.org.br/IMG/zip/restaura_amazonia_mr2_-_edital_001-2024.zip`

## Lifecycle evidence notes

- Listing places all four rows under the "Editais Concluídos" heading.
- Each detail page badge reads `<b>Concluído</b>`.
- Edital 002 body FAQ mentions "está aberto um edital com foco em Terras
  Indígenas (Edital 003)" — that reference does not make 002 open; the 002
  badge is Concluído.
