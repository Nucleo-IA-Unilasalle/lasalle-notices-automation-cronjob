# Finep Independent Capture Log

- Captured (UTC): 2026-09-14T21:59:51Z → 2026-09-14T22:00:09Z (API pages); document checks ~22:00:09Z
- API: https://www.finep.gov.br/o/c/chamadapublicas (Liferay public JSON; Accept: application/json)
- Method: direct HTTP via a standalone capture script (urllib) — **not** via the repo adapter, **not** via `scripts/run_independent_source_audit.py`
- Pagination: pageSize=20, pages fetched=24, advertised lastPage=24, totalCount consistent (474 rows across pages)
- Records: 474 fetched, 470 unique ids, 4 page-boundary duplicates (first occurrence kept)
- Lifecycle (post-dedup): open=34, closed=436, upcoming=0, excluded=0, unknown=0
- Situação distribution (raw API keys): aberta=35 (34 unique), encerrada=439 (436 unique)
- Open by first-seen page: p1=18 unique, p2=7, p3=4, p9=4, p10=1 (see accounting.json)
- Document checks (open records, bounded): 1 PDF returned HTTP 404
  (`http://www.finep.gov.br/images/chamadas-publicas/2026/27_02_2026_PA_Anexo_1_Rerratificado.pdf`)
  — source-side dead link retained as provenance; not a capture failure of the listing API
- API listing errors: 0 (all 24 pages HTTP 200, application/json)
- No cookies, auth headers, tokens, or personal data stored; User-Agent was a public research identifier only

## Pagination duplicates observed (live)

| id | first page | duplicate page | lifecycle |
|----|------------|----------------|-----------|
| 754839 | 1 | 2 | open |
| 745169 | 3 | 4 | closed |
| 733756 | 5 | 6 | closed |
| 712169 | 11 | 12 | closed |

## Policy disposition in the independent inventory

- Declared worker policy: `MIN_NOTICE_YEAR=2026` (default in `scripts/discover_all_candidates.py`).
- 15 open (`aberta`) records published before 2026 are retained with `status=open` and
  `reason_code=out_of_scope` (evidence: `policy_disposition`) so the fidelity open-gate
  denominator equals the 19 in-scope 2026 opens the declared policy admits.
- Closed records remain provenance only (`status=closed`, not open-in-scope).

## HTTP captures

| UTC start | UTC end | Status | Content-Type | Bytes | URL |
|-----------|---------|--------|--------------|-------|-----|
| (see capture-log.json — 24 listing pages + open-record PDF checks) | | | | | |

Full machine-readable request log: `capture-log.json`.
Per-page raw payloads retained outside the repo (scratch; not committed): raw page JSON
was used only to build this inventory and was not stored under `docs/`.
