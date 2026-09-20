# Capture log — fundacao_grupo_boticario (independent inventory)

Capture date (local audit day): 2026-09-14. All timestamps UTC.

Method: independent capture via direct HTTP (`requests`) and Playwright Chromium **without** importing `scripts/discover_fundacao_grupo_boticario_candidates.py`. No cookies, tokens, or credentials stored. Request budget ≤ 40.

## Listing

| URL | Method | HTTP | Content-Type | Bytes | UTC time | Notes |
|---|---|---|---|---|---|---|
| https://fundacaogrupoboticario.org.br/ | requests GET | 200 | text/html; charset=UTF-8 | 130868 | 2026-09-14T20:25:39Z | static HTML |
| https://fundacaogrupoboticario.org.br/ | playwright chromium goto | 200 | text/html | ~rendered | 2026-09-14T20:32Z | 85 anchors after render |

Signal tokens searched in href/path/text/title/aria-label: `chamada`, `edital`, `sprint`, `bolsa`. Allowed hosts: `fundacaogrupoboticario.org.br`, `goias.gov.br` (FAPEG path only). Blacklisted foundation paths: `/noticias`, `/quem-somos`, `/nossa-atuacao`, `/fale-conosco`.

Detail URLs found (both static BS4-equivalent parse and Playwright rendered): **2** (under detail cap 20).

## Detail pages

| URL | HTTP | Content-Type | Title | Status (as of capture) | Deadline |
|---|---|---|---|---|---|
| https://fundacaogrupoboticario.org.br/teia-sprint-chuvas-do-el-nino/ | 200 | text/html; charset=UTF-8 | Sprint Chuvas do El Niño: Inscrições abertas para ações urgentes | closed | 2026-08-03 |
| https://fundacaogrupoboticario.org.br/sprint-chuvas-el-nino/ | 200 | text/html; charset=UTF-8 | Ações para minimizar impactos do El Niño recebem R$ 4,2 milhões | closed | n/a (results article) |

Lifecycle quotes:

- teia page: "Inscrições estarão abertas até 3 de agosto de 2026"; "O resultado das propostas apoiadas está previsto para ser divulgado até 31 de agosto de 2026."
- sprint-chuvas-el-nino page: results article dated "31 de agosto de 2026" listing nine selected actions.

Deadline 2026-08-03 < capture date 2026-09-14 → both closed. Zero open records.

## Principal documents

Rendered pages expose **zero** `.pdf` anchors. Edital completo and formulário point off-source:

- https://sprint.teiadesolucoes.com.br
- https://sprintchuvas.paniclobster.com/

No `goias.gov.br/fapeg` links currently on the listing. No pagination observed (single listing page). No fetch errors. No caps hit.

## Full accounting

- open: 0
- closed: 2
- upcoming: 0
- excluded: 0
- unknown: 0

Machine-readable inventory: `independent-inventory.json`. Structured fetch list: `capture-log.json`.
