# Source Adapter Audit — Fix Review Summary (2026-09-14)

Reviewer-facing index of the 23-source technical audit. One document so the
reviewer does not need to reconstruct before/after state from 23 evidence
packages. Every claim below is backed by on-disk artifacts under
`docs/evidence/sources/<key>/technical-audit-2026-09-14/` and by the uncommitted
working-tree diff.

Scope reminders (unchanged by this audit):
- No production action, commit, push, deploy, workflow activation, secret
  access, or usage reset occurred.
- Catalog lifecycle, paused/audit holds, snapshot sign-off, and RR/P gates are
  untouched; this audit qualifies evidence only.
- Combined offline suite after all fixes: **752 passed**. Catalog parity
  (pinned offline): passed. Credential scan over 287 evidence files: clean.

## Summary

| # | Source | Result | Defect class | Pre-fix fidelity | Post-fix fidelity | Prod diff (adapter+tests) |
|---|--------|--------|--------------|------------------|-------------------|---------------------------|
| 1 | bndes | fixed | lifecycle + identity | 11 blockers, 0%/0% | 0 blockers, 100%/100% | +70 / +99 |
| 2 | brde | pass | — | 0 blockers, 100%/100% | same | none |
| 3 | fao | fixed | signal tokens | 3 extra_submission | 0 blockers, 100% | +26 / +45 |
| 4 | fapergs | fixed | principal-PDF + year capture | 10 blockers, 0%/0% | 0 blockers, 100%/100% | +86 / +40 |
| 5 | govbr_mma_fnma | fixed | deadline→closed | 1 status_mismatch | 0 blockers, 100%/100% | +11 / +48 |
| 6 | iis_rio | fixed | pagination fail-closed | partial-inventory fail (errors=1) | 0 blockers, 100% | +6 / +44 |
| 7 | canoas | pass | — | 0 blockers, 100%/100% | same | none |
| 8 | funbio | fixed | signal tokens + deadline TZ | 3 missing_open | 0 blockers, 100%/100% (9/9) | +27 / +97 |
| 9 | fundacao_grupo_boticario | pass | — | 0 blockers, 100% | same | none |
| 10 | govbr_mma | fixed | dead-link fail-closed | errors=1 → partial fail (EXIT=1) | 0 blockers, 100%/100% | +8 / +30 |
| 11 | govbr_mma_public_calls | pass | — | 0 blockers, 100% | same | none |
| 12 | sema_rs | fixed | pagination + year + extractor | 16 blockers | 0 blockers, 100%/100% | +185 / +213 |
| 13 | tnc | fixed | identity (shared TDR) | 2 identity_mismatch | 0 blockers, 100%/100% | +16 / +7 |
| 14 | dopa | fixed | lifecycle + signals | 40% accounting, 4 blockers | 0 blockers, 100%/100% | +16 / +144 |
| 15 | kfw | pass | — | 0 blockers, 100% | same | none |
| 16 | msgov | fixed | pagination + identity + filter | 50 emitted, cap reached, PDFs starved | 0 blockers, 100%/100% (29/29) | +156 / +177 |
| 17 | unep | fixed | signal tokens | 4 extra_submission | 0 blockers, 100% | +40 / +50 |
| 18 | worldbank | pass | — | 0 blockers, 100% | same | none |
| 19 | wwf | fixed | identity (multi-PDF rows) | 18 duplicate_identity | 0 blockers, 100%/100% (19/19) | +24 / +15 |
| 20 | fbds | fixed | lifecycle + deadline | unknown/false-open, null deadlines | 0 blockers, 100%/100% | +95 / +55 |
| 21 | finep | fixed | status normalize + dedup | 22 blockers (simulated) | 0 blockers, 100%/100% (19/19) | +56 / +48 |
| 22 | ibama | fixed | lifecycle ×4 | status/deadline/term/year defects | 0 blockers, 100%/100% | +107 / +75 |
| 23 | pncp | pass | — | 0 blockers, 100%/100% (bounded) | same | none |

Totals: 7 pass, 16 fixed, 0 fail, 0 blocked, 0 escalated.
Production-code diff: 16 adapters + 16 test files, +1945/−171 lines, all
source-local.

Raw pre-fix captures retained on disk where the agent saved them
(`*-before-fix*`, `stats-prefix.json`, `fidelity/pre-fix-*`): fao, unep, ibama,
wwf, govbr_mma, msgov. For the other fixed sources the pre-fix numbers above
are recorded verbatim in each `RESULT.md` ("Pre-fix baseline" section) and in
`AUDIT-COORDINATION-LOG-2026-09-14.md` at the workspace root.

---

## Fixed sources — before/after and decisions

### bndes (candidate, ingest)
- Before: audit-only run emitted 5 candidates — 4 PDFs from fully closed fundo
  urile routes (Corais, Sertão ×2, Bioinsumos) plus the 1 truly open Periferias
  6º ciclo PDF. Independent fidelity: 11 blockers (extra_submission=5,
  missing_open=4, duplicate_identity=2), 0%/0%. Root causes: (a) no lifecycle
  gate — fundo listing copy still advertises closed calls and the adapter
  followed stale anchors; (b) per-fetch `CVID` cache-buster baked into
  candidate identity; (c) independent inventory used listing-page canonical
  URLs shared across records.
- After: page-level lifecycle gate (`_CLOSED_PAGE_PHRASES` +
  `_OPEN_CALL_PHRASES`; fully-closed pages skipped, mixed pages proceed to the
  normal prefilter); `CVID` stripped from canonical URLs; inventory rewritten
  with per-record identities (open call keyed by principal PDF URL; CPSI
  worldlabs-only records dispositioned `out_of_scope` with rationale). Discovery
  emits exactly 1 candidate; fidelity 0 blockers, 100%/100%. 40 tests
  (3 new).
- Decision: CPSI calls linking only to worldlabs.org are outside the
  BNDES-hosted PDF contract → `out_of_scope`, not missing-open. Lifecycle
  phrases verified against live pages 2026-09-14; wording drift is a residual
  risk noted in RESULT.md.

### fao (candidate, ingest, browser)
- Before: signal regex included `funding strategy` and `resolution`, matching
  3 governance policy PDFs (nb780en, no028en, cc3636en) as open calls.
  Fidelity: 3 extra_submission, exit 1. Independent inventory: 0 open (BSF 5th
  cycle closed 2022/23; no 6th advertised).
- After: tokens narrowed to open-call language only. Discovery emits 0;
  fidelity exit 0. 17 tests (2 new). Raw before-fix captures retained
  (`discovery-before-fix.json`, `fidelity-before-fix/`).
- Decision: 0 candidates is the correct steady state; a future off-listing call
  (e.g. 6th BSF cycle page) needs a deliberate entry-point change, not a token
  loosening.

### fapergs (candidate, ingest)
- Before: adapter emitted one candidate per PDF on a detail page, so aditivo /
  consolidada / regulamento PDFs became separate candidates. Independent
  fidelity: 10 blockers (extra_submission=4, identity_mismatch=3,
  missing_open=3), 0%/0%. Additionally the prior session's
  `_UPLOAD_MONTH_PATTERN` captured only `(19|20)` (century), so YYYYMM folder
  years resolved to `20`.
- After: `_select_principal_pdf` + `_RELATED_DOC_PATTERN` (related docs as
  metadata, not candidates); AJAX+static merge; year pattern captures the full
  year. Discovery emits 1 principal; fidelity 0 blockers, 100%/100%. 24 tests.
- Decision: one-principal-per-detail is the contract; older multi-PDF tests
  updated to assert principal + related_document_urls.

### govbr_mma_fnma (candidate, audit)
- Before: FNMA page keeps "prorroga/abert" wording after the 2026-07-13
  deadline; discovery reported the call open. Fidelity: 1
  authoritative_status_mismatch (inventory=closed, discovery=open).
- After: `_extract_listing_metadata` forces status=closed when the extracted
  deadline is past UTC today, regardless of open wording. Discovery emits 1
  closed principal (retificação stays related metadata). Fidelity 0 blockers,
  100%/100%. 26 tests (regression fixture dates repaired to dd/mm/yyyy).
- Decision: deadline is authoritative over badge/wording when both are present.

### iis_rio (candidate, ingest)
- Before: `/noticias/` WordPress archive is single-page; a page>1 probe
  returned 404, which raised inside the listing loop, incremented
  `stats["errors"]`, and the audit orchestrator marked the complete inventory
  as partial → fail-closed EXIT=1.
- After: page>1 HTTP 404 breaks pagination without incrementing errors.
  Zero open calls on live source (latest closed 2025-07-15); all live PDFs
  pre-2026 and year-rejected. Fidelity 0 blockers, 100%. 25 tests.
- Decision: 404-on-page>1 is the designed end-of-pagination terminator for this
  archive, not an error. Registry `filter_policy=default` overriding the
  adapter's `include_tdr` default is flagged as a latent coordinator-owned
  question (moot while no 2026 TdR exists).

### govbr_mma (candidate, ingest)
- Before: live listing contains a dead Plone `resolveuid/<sha>` stub (Plano
  Anual 2020) that 404'd; the error count made the audit-only orchestrator
  fail closed ("inventory is partial", EXIT=1) despite otherwise complete
  enumeration.
- After: `/resolveuid/` paths skipped in the detail extractor. Post-fix run:
  0 errors, 5 emitted closed-era PDFs (no year token → intentional pass-through),
  fidelity 0 blockers, 100%/100%. 22 tests. Raw `stats-prefix.json` retained.
- Decision: skipping `/resolveuid/` is narrow and specific; the year-guard
  no-token pass-through is per plan §9 and is documented as a residual risk
  (closed-era PDFs re-emitted; downstream hash dedup absorbs).

### tnc (opportunity, audit)
- Before: two distinct expired consultancy blocks on the official page share
  one TDR PDF URL; the adapter kept that URL as a document on both fallback
  stable IDs → 2 identity_mismatch blockers in built-in fidelity.
- After: fallback identity clears structured documents and keeps the shared TDR
  as markdown provenance only. Open inventory: 1 (PEPSA/PA metodologia TDR,
  deadline 2026-09-25). Fidelity 0 blockers, 100%/100% (49/49 traced). 26 tests.
- Decision: a shared document URL may not participate in the identity of two
  different stable IDs; provenance stays in markdown. Audit-mode hold preserved
  (1 of 2 clean audits required before ingest).

### funbio (opportunity, audit)
- Before: signal tokens (`chamada|projeto|edital|floresta|selecao`) missed an
  entire open-card family "Manifestação de Interesse" → 3 open calls invisible;
  fidelity 3 missing_open. Deadlines parsed as UTC end-of-day instead of
  Brasília 23:59.
- After: tokens extended with `interesse|manifestação`; deadline converted
  America/Sao_Paulo 23:59 → UTC; first regulamento document marked
  principal/renderable. Discovery emits all 9 open calls; fidelity 0 blockers,
  100%/100%. 27 tests.
- Decision: token lists must cover title synonyms; Brasília is the deadline
  clock. HTML-wrapper regulamento URLs (base64 PDF in `__NEXT_DATA__`) are
  inventoried with renderable=null; one PDF hit HTTP 524 (noted, URL retained).

### dopa (opportunity, paused)
- Before: pre-fix fidelity 40% accounting — 3 missing_open (reverse-order
  phrases "estão abertas as inscrições", "edital de abertura/das vagas",
  "permanecerá aberto" not matched) + 1 status_mismatch; post-act notices
  (gabarito/resultado/notas preliminares) also emitted as open.
- After: open-signal phrases extended (incl. reverse order); post-act phrases
  rejected; deadline cues (`do dia`/`ao dia`) with wider window. Live open set:
  5, all traced; excluded=138. Fidelity 0 blockers, 100%/100%. 17 tests
  (5 new).
- Decision: DOPA = Diário Oficial de Porto Alegre API (procempa), not
  Defensoria. Paused rollout hold preserved; DISCOVERY_AUDIT_ONLY bypasses
  holds by design (discovery-only).

### sema_rs (candidate, ingest)
- Before: 16 blockers (8 extra_submission + 8 identity_mismatch). Three
  defects: (a) AJAX `lista-data-table` is full-text search — adapter stopped at
  the first page with zero signal-matched anchors, missing detail pages later
  in the result set; (b) year guard blind to `/upload/arquivos/YYYYMM/` folders
  and fabricated years from percent-encoded filenames (`%2009.921` → 2009);
  (c) static service pages swept all PDFs incl. guidance/off-host documents.
- After: pagination honours server `pagecount` + article-free placeholder stop;
  year extraction percent-decodes and recognizes YYYYMM folders; same-host +
  signal-token + closure-marker extractor for static pages. Zero open calls on
  contracted surfaces; fidelity 0 blockers, 100%/100%. 34 tests (11 new).
- Decision: AJAX sources must trust the API envelope, not the first empty page;
  percent-decode before year scanning (same class as fapergs); static pages
  need host+token+closure filters, not generic PDF sweeps.

### msgov (candidate, ingest, browser)
- Before: Prosas listing is JS with UI page size 20 and shadow-DOM next-page
  buttons the adapter never clicked → 3 open editais missed. Detail annexes
  behind Oracle preauthenticated URLs (`/p/<token>/…`, token changes every
  request) caused identity churn; an `amazonaws.com` catch-all emitted .doc
  annexes until the candidate cap of 50 starved real PDFs (50 emitted,
  cap_reached=1, 8 PDFs dropped).
- After: listing pagination up to registry page_limit (5×20); token-free
  stable identity (`_stable_pdf_identity`); non-PDF extension filter on
  object-storage hrefs. Discovery emits 29 PDFs across 23 open editais (closed:
  125); fidelity 0 blockers, 100%/100% (29/29). 14 tests (5 new). Raw
  `stats-prefix.json` retained.
- Decision: independent inventory for JS Prosas portals should replay the
  public OAuth client_credentials + third_party API, not scrape the UI;
  preauthenticated tokens must never enter identity.

### unep (candidate, audit)
- Before: signal tokens `gfc fund` / standing `concept note` matched 4
  standing guidance/template PDFs that persist between application rounds on a
  closed round (2nd round closed 2025-12-15). Fidelity: 4 extra_submission,
  exit 1.
- After: tokens narrowed to open-call language
  (`call for proposals|applying for funding|request for proposals`). Discovery
  emits 0; fidelity exit 0. 26 tests (2 new). Raw before-fix captures retained.
- Decision: same class as fao — open-call tokens only; a future round advertised
  only via template wording needs a deliberate signal extension.

### wwf (candidate, ingest)
- Before: multi-PDF edital rows reused one process-number
  `source_record_id` across every PDF in the row; the orchestrator flattens one
  record per candidate → 18 duplicate_identity blockers.
- After: per-document identity `source_record_id = <row_id>::<pdf_filename>`
  with `row_source_record_id` for row grouping; audit artifacts group by parent
  row. Live page: 10 rows (4 open / 6 closed); open 95223 DOCX-only is
  out_of_scope for the PDF contract. Fidelity 0 blockers, 100%/100% (19/19
  traced). 37 tests (1 new). Raw prefix fidelity retained.
- Decision: identity must be unique per flattened document. This changes the
  candidate metadata identity shape consumed by Repo A — flagged for stronger
  review; production ingest of the new shape was NOT exercised (restriction).

### fbds (opportunity, paused)
- Before: first audit run emitted 4 opportunities with status=unknown or
  false-aberto (FAQ body text "aberto" overriding lifecycle) and null
  deadlines on all four; SPIP detail badges ("Concluído") ignored.
- After: SPIP badge lifecycle preferred over body text (Concluído→closed,
  Aberto→open) with normalization; deadline via Brasília clock + widened
  keyword window; `#Download` ZIP marked is_principal. All 4 closed with
  correct deadlines; fidelity 0 blockers, 100%/100%. 42 combined tests
  (3 new). Paused hold preserved.
- Decision: badge/markup lifecycle beats body-text heuristics on SPIP pages;
  FAQ/ancillary "aberto" must not override the badge.

### finep (opportunity, paused)
- Before: adapter passed Portuguese `situacao` (`aberta`/`encerrada`) through
  without mapping to the worker's open/closed contract → simulated fidelity 22
  blockers (status_mismatch=19, duplicate_identity=2, extra_submission=1).
  Live API also repeats record ids across page boundaries (4/24 pages).
- After: `situacao` mapped to open/closed/unknown for status, open filter, and
  fidelity; page-boundary duplicates deduped by id
  (`duplicate_records_skipped`). Full 24/24-page audit capture: 470 unique
  rows (34 aberta → 19 in-scope after MIN_NOTICE_YEAR=2026, 15
  out_of_scope), 436 closed. Fidelity 0 blockers, 100%/100% (19/19). 32 tests.
- Decision: production caps (5 pages / 10 opportunities) intentionally bound
  runs and block finep-pages-v1 advance when hit; the audit elevated caps
  locally only. MIN_NOTICE_YEAR is the recency fence for years-old "aberta"
  rows; do not lower without re-audit. One open record has a dead principal
  PDF (404) — download-fail at ingest, noted.

### ibama (opportunity, paused)
- Before: four defects — (a) bare `\bsuspens` matched incidental legal phrases
  ("exigibilidade suspensa") → false `suspended`; (b) schedule extraction took
  the last date in a multi-date clause (DOU publication after deadline) and
  any "10h" as the deadline time; (c) positive-term filter missed
  "audiência pública" hearing editals (FSO Edital 20/2026 open) → missing_open;
  (d) `/copy_of_notas/` URLs lack a year path segment so 2020 pages passed the
  URL year filter.
- After: suspension requires call-noun proximity; deadline-cued date preferred
  with tail-only time attachment; `audi[eê]ncia p[uú]blica` added to
  `_POSITIVE_TERMS`; detail publication-year guard rejects pre-min_year pages.
  Open=2, emitted=8, excluded=35. Fidelity 0 blockers, 100%/100% (2/2 open,
  8/8 traced). 17 tests (4 new). Pre-fix fidelity retained
  (`fidelity/pre-fix-*`).
- Decision: status terms need proximity to the call noun; schedule parsing is
  deadline-first; publication year is a second fence beyond URL year. Paused
  hold preserved; compatibility candidate wrapper unused.

---

## Pass sources — what was verified (no code change)

- **brde**: 2 open FSA calls traced; closed sections skipped; known listing
  href leading-space defect repaired by adapter; fidelity 0 blockers.
- **canoas**: opportunity contract; paused hold preserved; DOMC/WP enumeration
  (excluded=47, unknown=1 designation edital); 11 tests.
- **fundacao_grupo_boticario**: 0 open (El Niño sprint pair closed); editais
  on off-source microsites are outside the PDF contract; Playwright path
  returns 0 correctly; 15 tests.
- **govbr_mma_public_calls**: 0 open; sole 2026 CONASQ entry access-restricted
  anonymously → `unresolved_news_lead` fail-closed; 25 tests.
- **kfw**: 0 time-bound calls; 2 standing FC Procurement Guidelines PDFs
  traced (re-emitted hourly by design; downstream hash dedup absorbs); 16
  tests.
- **worldbank**: single-page SIEF Call 8; 1 PDF traced (deadline-closed;
  re-emit-by-design, no page-text deadline parsing in contract); 24 tests.
- **pncp**: bounded RS+modality-4+publicação inventory (15 open) synchronized
  with library dry-run discovery (`discover_candidates()` with temp
  checkpoint; never `_main_impl`/submit/checkpoint-save); 108 tests. Full RS
  windows exceed caps by design (watermark stays put on capped scans); only
  this bound independently audited end-to-end.

## Reviewer checklist

- [ ] Each fixed source: diff is source-local (adapter+tests only; no shared
      files, workflows, config, catalog, or snapshot edits).
- [ ] Each fixed source: regression test exists and the focused suite passes
      (combined run: 752 passed).
- [ ] Each source: evidence tree complete (independent-inventory, discovery,
      fidelity/, commands.md, RESULT.md); credential scan clean.
- [ ] Paused/audit holds preserved: canoas, dopa, fbds, finep, ibama (paused);
      funbio, govbr_mma_fnma, govbr_mma_public_calls, tnc, unep (audit).
- [ ] Acceptance boundary respected: no RR-05/P5/P6/soak/activation/release
      claim anywhere; no production endpoint touched.
- [ ] Carry-forward items for stronger review: wwf identity-shape vs Repo A
      ingest; worldbank/kfw standing-PDF re-emission policy; pncp unaudited
      mods 6/8 + federal windows; iis_rio filter_policy TdR question; finep
      dead principal PDF (404); msgov 3 null deadlines.
