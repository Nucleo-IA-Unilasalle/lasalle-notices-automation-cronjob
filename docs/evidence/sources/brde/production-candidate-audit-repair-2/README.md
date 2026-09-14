# BRDE Post-Repair Production Candidate Audit 2

**Decision: PASS for the technical source-fidelity gate.**

- Signer: `/root/independent_review`
- Selected source: `brde`
- Selected contract: `candidate`
- Repo A head: `a5275dae46f223da74dc54d0734051acc66a8a9f`
- Repo B head: `2e0dd74ee64b999318dea4cc1767df4985b384ee`
- Official inventory was independently captured before the committed adapter run.
- No production API, database, workflow, scheduler, OCR, or submission operation was used.

The Repo A SHA above is the supplied candidate SHA. The Repo B SHA is the
post-repair commit under audit. No artifacts from another audit slot were used.

## Method

The audit fetched the public BRDE Production and Palacete pages with
credential-free `GET` requests, followed every current 2026 FSA detail link,
fetched each principal `Edital` PDF, and recorded response hashes, dates,
status markers, and host checks. It then ran
`discover_brde_candidates.discover_candidates(as_of_date=date(2026, 9, 13))`
from the committed Repo B head. The adapter run did not execute `main()` and
therefore did not download/OCR or submit candidates.

The official inventory was built at `2026-09-13T07:16:44.489401+00:00`; the
adapter started at `2026-09-13T07:16:44.489607+00:00`. The complete relevant
extracts and hashes are in `official-surfaces.json` and
`lifecycle-inventory.json`. The exact adapter output is in `adapter-run.json`.

## Lifecycle and Inventory

The official Production listing exposed eight distinct 2026 FSA records. The
detail-page periods classify exactly two as open at the audit date:

- `TV e VOD: Desempenho Comercial de Produtoras 2026`, 2026-07-27 through 2026-09-25.
- `Coproducao Brasil-Portugal 2026`, 2026-06-15 through 2026-09-25.

The other six FSA details were excluded: four carry explicit closed listing
markers (`Inscricoes encerradas`, including the two cinema records), and two
have expired deadlines (2026-09-04 and 2026-08-03). The Palacete page contains
the explicit heading `EDITAL 2026 | Encerrado`; its 2026 edital and related
documents are outside the open candidate inventory.

The full authoritative inventory is nine records: two open and seven closed.
`source_inventory.json` intentionally contains only the two open records for
the deterministic fidelity CLI, while `lifecycle-inventory.json` retains all
nine records and the official closed evidence.

## Adapter Result

The committed adapter produced exactly two candidates:

- The TV/VOD producers principal edital PDF.
- The Brazil-Portugal co-production principal edital PDF.

Its live stats were `listings_fetched=2`, `details_fetched=8`,
`open_details=2`, `closed_details=6`, `palacete_closed_sections=1`,
`candidates=2`, `errors=0`, `partial_inventory=0`,
`missing_lifecycle=0`, `detail_cap_reached=0`, and
`candidate_cap_reached=0`. No Palacete PDF, closed FSA PDF, annex, FAQ, or
result PDF was emitted.

The official Portugal listing href contains a malformed leading space:
`http://www.brde.com.br/ chamada-publica-brde-fsa-coproducao-brasil-portugal-2026/`.
The adapter strips that bounded defect and canonicalizes the detail URL to an
HTTPS root-level BRDE path. Both emitted detail URLs and principal PDF URLs
normalize to the official host `brde.com.br`; the host guard rejects external
hosts.

## Fidelity Result

The offline comparison in `fidelity/` passed with exit code `0`:

- `missing_open=0`
- `extra_submission=0`
- `duplicate_identity=0`
- `identity_mismatch=0`
- `authoritative_status_mismatch=0`
- `authoritative_deadline_mismatch=0`
- `renderability_mismatch=0`
- `parser_failure=0`
- Inventory accounting: `100.0%` (`2/2`)
- Candidate traceability: `100.0%` (`2/2`)

The focused committed Repo B regression suite also passed: `36 passed in
12.46s`.

## Decision and Boundaries

This slot-2 result is **PASS** for the post-repair BRDE technical source audit.
It is not, by itself, a production deployment authorization: the release
record still needs the required independent audit pair, current CI, exact
release SHAs, capacity/worker evidence, and operator-approved P4/P5 actions.
