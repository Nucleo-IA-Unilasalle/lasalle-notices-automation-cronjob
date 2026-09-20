# RESULT — SEMA-RS Source-Adapter Technical Audit (2026-09-14)

RESULT: fixed

## Summary

Independent direct-HTTP capture of the official SEMA-RS surfaces (AJAX
`lista-data-table` search for keywords `edital`/`chamada` + static
`residuos-solidos` service page + bounded lifecycle probes) exposed three
source-local defects in `scripts/discover_sema_rs_candidates.py`:

1. **Pagination premature stop** — the AJAX endpoint is a full-text search
   (`recordcount=29, pagecount=2` for `edital`) whose page 1 carries 20
   articles with zero signal-matched anchors; the only real edital detail
   URLs live on page 2. `_paginate_keyword` broke on the first
   empty-extraction page, so the keyword sweep never reached any detail
   page (`listings_fetched=0`) and would silently miss future open calls on
   later pages.
2. **Year-guard blind spots** — `/YYYYMM/` upload folders
   (`/upload/arquivos/202307/…`) extracted no year, and percent-encoded
   names (`Lei%20n%C2%BA%2009.921.pdf`) produced a false year 2009 from the
   `%2009` encoding boundary.
3. **Static-page over-emission** — the generic PDF sweep of
   `residuos-solidos` emitted 8 candidates that were guidance reports /
   investment-plan PDFs plus one off-host statute PDF
   (`ww3.al.rs.gov.br/.../Lei%20n%C2%BA%206.503.pdf`); the one real signal
   PDF (Edital de Chamada Pública) sits in a panel whose sibling link is
   "Resultado Final" — a concluded call.

All three were repaired source-locally (pagination honours the server
`pagecount` + article-free placeholder bodies; year extraction decodes
percent-encoding and recognises `/YYYYMM/` folders; the static sweep now
uses a same-host, signal-token, closure-marker-aware extractor). Pre-fix
discovery failed fidelity with **16 blocking exceptions** (8
extra_submission + 8 identity_mismatch) against the independent inventory;
post-fix **34/34 unit tests pass**, audit-only discovery emits **0
candidates** (correct: every official call found on 2026-09-14 is closed),
and the official fidelity CLI reports **pass, 0 blocking exceptions,
100% open-record accounting, 100% candidate traceability**.

## Structured fields

- RESULT: fixed
- SOURCE: sema_rs
- EXPECTED CONTRACT: candidate — discover_sema_rs_candidates, group b,
  rollout ingest, owner pipeline-discovery-group-b.yml, interval 60 min,
  detail_limit=20, page_limit=5, attachment_limit=25,
  browser_required=false; catalog active.
- OBSERVED CONTRACT: candidate (audit-only path ran via
  `scripts/discover_all_candidates.py`; adapter module and registry entry
  match; no contract drift).
- LIFECYCLE HOLD: none for sema_rs (catalog active). No paused/audit holds
  and no catalog lifecycle mutations performed.
- OFFICIAL INVENTORY: open=0, closed=6, upcoming=0, excluded=1 inventory
  record (10 non-call documents: guidance reports, investment plan,
  two-pager, 4 off-host statutes), unknown=0
  (independent-inventory.json; capture ~2026-09-14T20:33–20:45Z).
  Closed calls: Edital 001/2024 Delta do Jacuí (no PDFs on page);
  Editais Encerrados PE Tainhas (25 PDFs, all `/2020..2023/` folders);
  Comunidade de Prática chamada pública 2026 (Resultado Final published);
  Fundo animal conselho-gestor chamamento + habilitação de municípios
  (concluded by June-2026 portarias; page not reachable via contracted
  signal-token selector — out_of_scope); Biogás RS edital archive
  (2022–2024, pre-min-year, out_of_scope).
- DISCOVERY (post-fix, audit-only): emitted=0, rejected
  (year_rejected)=25, rejected (prefilter_rejected)=0, errors=0,
  partial=no, cap reached=no (stats.json). Pre-fix run for contrast:
  emitted=8 (all unexpected non-calls/off-host), listings_fetched=0.
- FIDELITY: exit code 0; blockers=0; open-record accounting=100.0% (0/0
  in-scope); candidate traceability=100.0% (0/0); non_blocking=4
  (out_of_scope ×4 documenting the out-of-selector concluded calls and
  non-call documents); no hidden cap/partial. Pre-fix comparison run:
  exit 1, 16 blockers.
- TESTS:
  - `py -3.13 --version` → Python 3.13.5
  - `py -3.13 -m pytest tests/test_sema_rs_discovery.py -q` (baseline)
    → **23 passed in 54.28s**
  - `py -3.13 -m pytest tests/test_sema_rs_discovery.py -q` (post-fix)
    → **34 passed in 27.39s**
  - `py -3.13 -m pytest tests/test_discover_all_candidates.py
    tests/test_source_fidelity.py -q` → **133 passed in 5.31s**
- CHANGES:
  1. `scripts/discover_sema_rs_candidates.py` — pagination honours
     server-reported `pagecount` and stops only on article-free
     placeholder bodies / stale pages / failures / page cap
     (`_fetch_keyword_listing_html` now returns `(body, pagecount)`;
     `_paginate_keyword` tracks per-keyword yield);
     `_extract_year_from_url` percent-decodes and recognises `/YYYYMM/`
     upload folders; new `extract_static_service_pdf_urls` /
     `_extract_static_service_pdf_urls_from_soup` same-host +
     signal-token + closure-marker (`Resultado Final`/`encerrad…`)
     extractor wired into the static sweep via
     `discover_pdf_urls_on_page(..., extractor=...)`.
  2. `tests/test_sema_rs_discovery.py` — listing mock accepts
     `pagecount`; regression classes `TestPaginationContinuation`,
     `TestYearFolderExtraction`, `TestStaticServiceExtractor`.
  3. Evidence only: commands.md, RESULT.md, capture-log.md,
     independent-inventory.json, discovery.json, stats.json,
     fidelity/ outputs.
- EVIDENCE:
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/capture-log.md
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/stats.json
  - docs/evidence/sources/sema_rs/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. Zero open calls on 2026-09-14 means open-record accounting and
     candidate traceability are 0/0 (reported 100% by design); the gates
     gain real discriminating power only when SEMA-RS publishes a new
     open call — the pre-fix/post-fix blocker contrast (16 → 0) and the
     unit regressions are the evidence of correctness today.
  2. The AJAX search is full-text; future open calls hosted on pages
     whose anchors never carry `edital|chamada|chamamento` (like the
     current Fundo animal page) remain outside the contracted signal-token
     selector — a coverage limitation of the ported FastAPI contract, not
     a regression; revisit only with an explicit contract change.
  3. Closure detection on static panels relies on `Resultado
     Final`/`encerrad…` text markers; a future concluded call using
     different wording could slip through as an open-looking static PDF
     (year guard and prefilter still apply).
  4. `py`/`python` shell remains permission-gated in parts of this
     environment; PowerShell quoting required script-file indirection for
     some inline commands — operational friction only.
- ESCALATION: none.
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches,
  deploys, submissions, secret access, or catalog mutations).

## Follow-up (non-blocking)

- Commit the sema_rs adapter + tests fix through the normal review path
  when the coordinator schedules it (left uncommitted per task rules).
- When SEMA-RS next publishes an open edital, re-run the audit-only +
  fidelity path to exercise the non-vacuous accounting gates.
