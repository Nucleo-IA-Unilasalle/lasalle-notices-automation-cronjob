# BRDE production candidate audit 1

## Decision

**FAIL / BLOCKED.** This is a qualifying independent-source audit attempt, not a
passing RR-05 audit. The official BRDE source exposed two in-scope open 2026
calls, while the candidate adapter emitted neither one. The offline fidelity
comparison therefore has two `missing_open` blockers and exits 1.

- Snapshot UTC: `2026-09-13T02:20:10Z`
- Source: `brde`
- Slot: `1`
- Auditor/operator: `/root/p3_ledger`
- Repo A candidate head: `a5275dae46f223da74dc54d0734051acc66a8a9f`
- Repo B candidate head: `5c935d7e30949f69158c8344c42379ff3bd09ef6`
- Independent reviewer: **TODO**
- Production API, database, workflow, and submission paths: **not accessed**
- Future audit slot 2: **not inspected or used**

## Method and provenance

This audit independently fetched public, credential-free official BRDE pages
and the official sitemap, then prepared the source inventory before comparing
it with the adapter. It did not call the repository diagnostic selector or
reuse the historical `audit-1/` or `audit-2/` inventories. The retained
capture is sanitized: relevant page extracts, listing rows, detail metadata,
document URLs, response metadata, SHA-256 hashes, and provenance are retained;
raw HTML and PDF bytes were not committed. PDF captures record MIME, PDF magic,
length, final URL, and SHA-256 only.

The inspected official surfaces were the sitemap index and page sitemap, the
Palacete editais page, FSA landing/index/category/result pages, the FSA
production listing, and adjacent BRDE incentives, contests, licitacoes, and
compras-e-servicos pages. The latter surfaces were retained to make scope
decisions explicit rather than silently dropping 2026 links.

See:

- `official_surface_captures.json`: sanitized page extracts and response/document provenance.
- `source_inventory.json`: independently prepared ground truth, including explicit out-of-scope records.
- `adapter_output.json`: function-level candidate output and comparison boundary.
- `discovery.json`: normalized discovery input supplied to the offline fidelity tool.
- `lifecycle_assessment.json`: closed-candidate admission analysis against the
  recorded Repo A/Repo B heads.
- `fidelity/report.md`: generated offline comparison report.

## Inventory

The source inventory has 14 deterministic records:

- 9 in-scope FSA Production and Palacete records: 2 open and 7 closed.
- 5 explicit out-of-scope records: one fiscal-incentive notice, three
  procurement items, and the employment-contest 2026 aggregate.

The two open in-scope records at the snapshot were:

- `fsa:chamada-publica-brde-fsa-tv-e-vod-desempenho-comercial-de-produtoras-2026`,
  deadline `2026-09-25`.
- `fsa:chamada-publica-brde-fsa-coproducao-brasil-portugal-2026`,
  deadline `2026-09-25`.

Seven records were closed from explicit listing labels or elapsed application
deadlines. Deadline-derived closure is marked in each record's
`status_basis`; it is not presented as a stronger official closed label.

## Adapter comparison and blockers

The adapter was run only at function level:
`discover_candidates(min_year=2026)`. The CLI `main()`, OCR, submission,
API, and production paths were not invoked.

The adapter observation was made at `2026-09-13T06:52:26.0632028Z` from the
Repo B head recorded above; the source capture snapshot is retained at
`2026-09-13T02:20:10Z`. No source mutation was made between these read-only
observations. The comparison is pinned to commit `5c935d7e...`; any later
working-tree edits to the adapter are deliberately outside this audit result.

- Listings fetched: 2
- Detail pages fetched: 0
- Candidates emitted: 1
- Year-rejected links: 13
- Errors: 0
- Partial inventory: 0
- Candidate cap reached: 0

The sole emitted candidate was the closed Palacete 2026 PDF. The adapter
missed all eight current FSA detail pages. The current extractor accepts
`/fsa/chamada-publica-brde-fsa-` paths, but the official production listing
currently publishes the 2026 FSA detail links at the root
`/chamada-publica-brde-fsa-` path. In addition, the Portugal listing row has
a leading space in its raw `href`, so its hyperlink is malformed; the valid
canonical detail page was independently recovered from the page sitemap/direct
official URL and retained as such.

The fidelity report records exactly two `missing_open` exceptions and no
extra-submission, duplicate-identity, identity-mismatch, authoritative-status,
deadline, renderability, or parser-failure exceptions. This result is a
fail-closed repair signal, not permission to activate the source.

## Lifecycle admission risk

The official capture labels the emitted Palacete 2026 edital **closed**
(`Encerrado`). The candidate metadata emitted by
`scripts/discover_brde_candidates.py` contains only source/listing/origin/year
fields; it does not carry `source_status`, `application_deadline`, or an
equivalent closed-state assertion. Repo A's generic worker-result contract
contains OCR/hash/validation fields only, and its generic candidate path maps
lifecycle timing metadata only when the worker metadata supplies it; the
generic provenance mapping does not include `source_status`. Therefore, if
this closed PDF reaches the generic candidate submission path, the persisted
row can have a null deadline/status.

Repo A's current `open` lifecycle predicate accepts non-PNCP rows with
`pncp_status_id IS NULL` and a null or future `application_deadline`.
Consequently, the closed Palacete candidate would be eligible for the default
open listing unless lifecycle metadata is propagated or the writer rejects
closed source records before processing. The same risk applies to any closed
FSA PDF admitted after repairing only the URL selector. This is a separate
blocking P3/P5 readiness issue from the two missing-open fidelity exceptions.
Evidence anchors are Repo B `discover_brde_candidates.py:154-184`, Repo A
`app/models/generic_worker_result.py:7-36`,
`app/services/scrape_candidate_service.py:521-590`, and
`app/repository/edital.py:362-370` at the recorded heads.

## Scope dispositions

The 2026 fiscal-incentive PDF is explicitly outside the current FSA plus
Palacete adapter contract. The three 2026 compras-e-servicos items are
procurement records handled by procurement/PNCP semantics. The 19 2026 links
on the concursos page are employment-contest notices. None were counted in the
open FSA/Palacete denominator, and each is retained with an
`out_of_scope` reason.

## Required next steps

1. Repair the FSA detail-link selector to accept the current official root-path
   links and handle the malformed Portugal anchor without broadening into
   unrelated notices.
2. Re-run an independent capture after repair and have a reviewer verify scope,
   status derivation, document hashes, and the Portugal-link exception.
3. Do not claim RR-05 or Gate C completion from this slot. A second independent
   audit is still required, and it must be performed separately from this
   capture.

Signed by `/root/p3_ledger` as the audit operator at the snapshot above.
