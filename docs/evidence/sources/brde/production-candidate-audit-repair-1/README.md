# BRDE production candidate audit repair 1

## Decision

**PASS.** This is the post-repair qualifying independent-source audit for BRDE
audit slot 1. The source inventory and official captures were prepared
independently before the committed adapter function was run. The offline
fidelity comparison has zero blocking exceptions.

- Source: `brde`
- Snapshot UTC: `2026-09-13T07:18:48Z`
- Snapshot local date: `2026-09-13`
- Auditor/operator: `/root/p3_ledger`
- Independent reviewer: **TODO**
- Repo A head: `a5275dae46f223da74dc54d0734051acc66a8a9f`
- Repo B head: `2e0dd74ee64b999318dea4cc1767df4985b384ee`
- Production API, database, workflows, OCR, and submission paths: **not accessed**
- Other post-repair audit slot: **not accessed or used**

This is one clean audit only. RR-05/Gate C still requires the separate second
independent audit and reviewer sign-off.

## Method and provenance

The audit used public credential-free GET requests with no authorization or
pipeline credentials. It independently fetched the BRDE sitemap index and page
sitemap, Palacete editais, FSA landing/index/category/result pages, the current
FSA Production listing, and adjacent incentives, contests, licitacoes, and
compras-e-servicos surfaces. It then fetched all eight 2026 FSA detail pages
and their principal edital PDFs.

The retained evidence is sanitized: complete relevant listing/detail extracts,
2026 rows, lifecycle text, document links, response status/content type/length,
and SHA-256 hashes are retained. Raw HTML and PDF bytes are not retained.
Public URLs are the only network identifiers stored.

Evidence files:

- `official_surface_captures.json`: 17 official surfaces, detail extracts,
  listing rows, principal-document provenance, and hashes.
- `source_inventory.json`: source ground truth prepared before adapter output.
- `adapter_output.json`: committed function output at the recorded Repo B SHA.
- `discovery.json`: normalized adapter records supplied to the offline tool.
- `fidelity/summary.json`, `fidelity/report.md`: reproducible offline result.

## Official inventory

The inventory contains 14 deterministic records:

- 9 in-scope records: 8 FSA Production 2026 calls and the Palacete 2026 edital.
- 2 open FSA calls at the snapshot, each with an application deadline of
  `2026-09-25`.
- 6 closed FSA calls, with elapsed deadlines or explicit listing closure.
- 1 closed Palacete edital, explicitly under the `EDITAL 2026 | Encerrado`
  section.
- 5 explicit `out_of_scope` records: the fiscal-incentive 2026 edital, three
  2026 procurement items, and the 2026 employment-contest aggregate.

The two open records are:

- `fsa:chamada-publica-brde-fsa-tv-e-vod-desempenho-comercial-de-produtoras-2026`
- `fsa:chamada-publica-brde-fsa-coproducao-brasil-portugal-2026`

The Portugal listing retains the malformed raw href with a leading space after
the host and records the repaired canonical detail URL. This is evidence of
the source defect and of bounded handling, not an omission.

## Committed adapter result

Only `discover_candidates(min_year=2026, as_of_date=2026-09-13)` was called.
The CLI `main()`, OCR, worker processing, API, and submission functions were
not called.

- Listings fetched: 2
- Detail pages fetched: 8
- Open details: 2
- Closed details excluded: 6
- Upcoming details: 0
- Candidates emitted: 2
- Prefilter/year rejections: 0
- Errors: 0
- Partial inventory: 0
- Detail/candidate caps reached: 0
- Closed Palacete sections observed and excluded: 1

The two emitted candidates are the two open FSA principal editals only. Each
has official BRDE listing/detail URLs, `source=brde`,
`application_start`, `application_deadline`, and `status=open` metadata.
No closed FSA PDF and no Palacete PDF was emitted.

The bounded selector accepts both root-level and legacy `/fsa/` detail paths,
repairs only leading whitespace in the official Portugal path, enforces the
official BRDE host, extracts the official application period, and admits a
principal PDF only while the application period is active. The corresponding
implementation is at Repo B `scripts/discover_brde_candidates.py:120-529`.

## Fidelity result

The offline verifier returned exit 0:

- Blocking exceptions: 0
- `missing_open`: 0
- `extra_submission`: 0
- `duplicate_identity`: 0
- `identity_mismatch`: 0
- Authoritative status/deadline mismatches: 0
- Parser failures: 0
- Inventory accounting: 100% (2/2 open records)
- Candidate traceability: 100% (2/2 candidates)

The five non-blocking exceptions are the intentionally retained
`out_of_scope` dispositions. They are not counted in the open FSA/Palacete
denominator.

## Lifecycle assessment

The failed pre-repair audit emitted a closed Palacete PDF without lifecycle
metadata. At this recorded post-repair SHA, the Palacete extractor reads the
explicit `Encerrado` heading and emits no PDF from that section. The FSA
extractor reads each detail-page application period, counts six expired calls
as closed, and emits only the two calls whose periods contain the snapshot
date. Consequently, closed 2026 material is excluded before candidate
construction and cannot reach the generic writer through this adapter run.

This audit verifies the adapter-side admission boundary; it does not claim
that unrelated legacy/direct writers or already persisted production rows have
been drained or fenced. Those remain P3 production cutover prerequisites.

## Follow-up

1. Obtain independent reviewer sign-off for this slot.
2. Perform a separate second independent official-source audit; do not reuse
   this inventory or adapter output.
3. Complete the production drain/fence ledger and all P3/P5 operational gates
   before activation.

Signed by `/root/p3_ledger` as the audit operator at the snapshot above.
