# Commands — iis_rio technical audit 2026-09-14

Working directory: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob`
UTC session window: ~2026-09-14T20:21Z – 20:45Z

## Resume context

Prior session (reset) had applied an UNCOMMITTED source-local fix to
`scripts/discover_iis_rio_candidates.py` (+6) and `tests/test_iis_rio_discovery.py`
(+34) — WordPress page>1 HTTP 404 treated as end-of-pagination, not a partial
error — and captured only `independent-inventory.json`. No fidelity run, no
RESULT.md. This session verified the fix, completed the live accounting, and
completed the evidence.

## Verification pass (this session)

| Step | Command / action | Exit / outcome | UTC notes |
|------|------------------|----------------|-----------|
| 1 | `py -3.13 --version` | Python 3.13.5 | ~20:21Z |
| 2 | `git diff -- scripts/discover_iis_rio_candidates.py tests/test_iis_rio_discovery.py` | Reviewed prior fix: `page_num > 1 and status_code == 404` → `break` in `discover_candidates` listing loop; `TestPagination404EndOfList` regression class (page2 404 not an error; page1 404 still errors) | Read-only |
| 3 | `py -3.13 -m pytest tests/test_iis_rio_discovery.py -q` | 1 FAILED (24 passed): `test_page2_404_is_not_an_error` — fixture listing yields 2 detail URLs that were unmocked, so `discover_pdf_urls_on_page` raised on unexpected URLs and `stats["errors"]` became 2 | Prior regression test was incomplete, not the production fix |
| 4 | Source-local test repair: mocked the two fixture detail URLs with empty HTML in `test_page2_404_is_not_an_error`; added `assert stats["details_fetched"] == 2` | OK — minimal, tests-only | ~20:25Z |
| 5 | `py -3.13 -m pytest tests/test_iis_rio_discovery.py -q` | 25 passed | ~20:25Z |
| 6 | Bounded live capture (temp script, deleted): listing pages 1–2 via adapter URL builder + `extract_iis_rio_detail_urls`; 13 detail pages fetched (status, title, PDFs, deadline phrases); no cookies/credentials stored | page1=200, page2 (`?tipo-de-noticia=noticia&paged=2`)=404; 13 signal-token detail URLs; 0 fetch errors | ~20:22Z |
| 7 | Pagination probes: `/noticias/page/2/`, `/?paged=2`, `?tipo-de-noticia=noticia`, `?tipo-de-noticia=noticia&paged=1` | 404, 404, 200, 200 — archive is a single page; page>1 404 is the normal end-of-list, confirming the prior fix | ~20:28Z |
| 8 | Detail-page spot-check for published/deadline phrases + principal PDFs (all 13, privacy-policy boilerplate PDF excluded) | Deadlines verified on closed rows (e.g. 15/07/2025 social-media TdR, 17/03/2025 APA + errata + Q&A); 5 records carry live-linked TdR PDFs that the prior inventory missed | ~20:30Z |
| 9 | Refresh `independent-inventory.json`: added 5 live-verified principal document URLs (APA Q&A; 2022/2021/2021/2020 TdRs). Statuses/titles/URLs unchanged; all 13 remain `closed` | OK — inventory open=0, closed=13, upcoming=0, excluded=0, unknown=0 | ~20:33Z |
| 10 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=$TEMP/iis-rio-audit-b1f566ecfc034504b758f8432dadc421 SOURCES=iis_rio py -3.13 scripts/discover_all_candidates.py` | EXIT=0; stats: listings_fetched=1, details_fetched=13, candidates=0, prefilter_rejected=0, year_rejected=12, errors=0, candidate_cap_reached=0; orchestrator offline fidelity: "source fidelity OK" | ~20:36Z |
| 11 | `py -3.13 scripts/audit_source_fidelity.py --source-inventory docs/evidence/sources/iis_rio/technical-audit-2026-09-14/independent-inventory.json --discovery $AUDIT_DIR/iis_rio/discovery.json --out docs/evidence/sources/iis_rio/technical-audit-2026-09-14/fidelity` | EXIT=0; blockers=0; inventory accounting 100.0% (0/0 open in scope); candidate traceability 100.0% (0/0); non_blocking=0 | ~20:37Z |
| 12 | Copy `$AUDIT_DIR/iis_rio/{discovery.json,candidates.json,stats.json}` → evidence dir (`discovery.json`, `candidates.json`, `stats-postfix.json`) | OK | ~20:38Z |
| 13 | Write `capture-log.md`, `commands.md` (this file), `RESULT.md` | OK | ~20:40Z |

No credentials used. No production endpoints. No Repo A calls. No workflows
dispatched. No commits. No shared-file edits. Temp capture scripts deleted.

## Reproduction commands

```powershell
py -3.13 -m pytest tests/test_iis_rio_discovery.py -q
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR = Join-Path $env:TEMP ('iis-rio-audit-' + [guid]::NewGuid().ToString('N'))
$env:SOURCES='iis_rio'
py -3.13 scripts/discover_all_candidates.py
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/iis_rio/technical-audit-2026-09-14/independent-inventory.json `
  --discovery (Join-Path $env:DISCOVERY_AUDIT_DIR 'iis_rio/discovery.json') `
  --out docs/evidence/sources/iis_rio/technical-audit-2026-09-14/fidelity
```

## Observations recorded during the run

- `year_rejected=12`: the 13 live detail pages expose 12 unique PDFs (11
  notice TdR/errata/Q&A PDFs + 1 site-wide privacy-policy boilerplate PDF in
  the footer). All carry years 2019–2025 in their URLs and are correctly
  rejected by `IIS_RIO_MIN_NOTICE_YEAR=2026`. `prefilter_rejected=0` because
  the year guard runs before the EDITAL prefilter.
- Registry `filter_policy=default` is passed by the orchestrator, while the
  adapter module default is `include_tdr` (FastAPI-port behaviour). With the
  current inventory this is moot (everything is year-rejected first). If a
  2026 TdR appears, `default` policy will prefilter-reject
  `termo-de-referencia` filenames — coordinator-owned registry decision, not
  changed here.
- `IIS_RIO_MAX_PAGES=10` (adapter) vs registry `page_limit=5`: the archive is
  a single page (page≥2 always 404), so the effective page budget is 1 and
  neither cap is reachable.
