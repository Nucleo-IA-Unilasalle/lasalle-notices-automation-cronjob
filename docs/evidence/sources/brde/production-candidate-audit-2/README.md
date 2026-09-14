# BRDE Production Candidate Audit 2

**Decision: FAIL / REJECT for the production candidate contract.**

- Signer: `/root/independent_review`
- Selected source: `brde`
- Selected contract: `candidate`
- Audit snapshot: 2026-09-13, credential-free official HTTP captures and local adapter execution
- Repo A head: `a5275dae46f223da74dc54d0734051acc66a8a9f`
- Repo B head: `5c935d7e30949f69158c8344c42379ff3bd09ef6`
- Production API, database, workflow, and scheduler state were not changed.

## Scope and Method

This is an independent slot-2 audit. It starts from the two supplied committed
heads, captures the official BRDE listing surfaces, builds a lifecycle-aware
inventory, runs the BRDE adapter separately, and compares the adapter output to
the open inventory with the repository's deterministic fidelity CLI. No
credentials, cookies, production endpoints, or writes were used. The current
Repo B checkout contains unrelated uncommitted changes; committed `HEAD`
contents, rather than those changes, are the audited revision.

Official captures and per-response SHA-256 values are in
`official-surfaces.json` and `lifecycle-inventory.json`. The raw adapter result
is in `adapter-run.json`; its normalized comparison input is `discovery.json`.
The open-only inventory used by the fidelity tool is `source_inventory.json`.

## Official Lifecycle Result

The current official BRDE production listing exposes eight 2026 FSA calls. The
Palacete listing exposes one 2026 cultural edital. At the snapshot, two FSA
calls have deadlines after the snapshot and no closed marker, while seven
2026 records are closed by an explicit marker or an elapsed deadline:

- Open: TV/VOD commercial performance for producers, deadline 2026-09-25.
- Open: Brazil-Portugal co-production, deadline 2026-09-25.
- Closed: Creative Nuclei, deadline 2026-09-04.
- Closed: Artistic performance for producers, deadline 2026-08-03.
- Closed: Brazil-Argentina co-production, explicit `Inscrições encerradas`, deadline 2026-07-17.
- Closed: Cinema commercial performance for producers, explicit closure for indirect beneficiaries, deadline 2026-07-01.
- Closed: Cinema commercial performance for distributors, explicit closure for indirect beneficiaries, deadline 2026-06-17.
- Closed: Brazil-Uruguay co-production, explicit `Inscrições encerradas`, deadline 2026-05-25.
- Closed: Palacete dos Leões Cultural Sponsorship 2026, explicit `EDITAL 2026 | Encerrado`.

The full nine-record lifecycle inventory is retained for provenance. Only the
two open records are supplied to the fidelity CLI because its documented
missing-open gate treats `status == "open"` as the in-scope denominator;
closed rows remain evidence, not current submission targets.

## Adapter Findings

The committed Repo B adapter is not faithful to the current official source:

1. `scripts/discover_brde_candidates.py:55-56` uses the Palacete page and the
   obsolete `/fsa/chamadas-de-investimento/` page. The current official FSA
   listing is `/producao/`; the obsolete page returned HTTP 200 but no current
   2026 detail links. The current `/producao/` page returned eight 2026 detail
   links, including both open records.
2. `scripts/discover_brde_candidates.py:105-142` only accepts detail paths
   beginning `/fsa/chamada-publica-brde-fsa-`, while current detail links are
   root-level `/chamada-publica-brde-fsa-...` paths. Updating only the listing
   URL would therefore still fail closed by omission.
3. `scripts/discover_brde_candidates.py:154-186` applies only a URL year guard
   and an edital filename prefilter. It does not parse or enforce official
   lifecycle/status/deadline evidence. The Palacete listing's 2026 PDF is
   therefore emitted as a candidate even though the official listing says
   `EDITAL 2026 | Encerrado`.
4. `scripts/discover_brde_candidates.py:344-410` processes every emitted
   candidate and calls `pipeline_core.submit_candidates` when OCR succeeds;
   there is no open-lifecycle gate before processing or submission.

The adapter-only run at 2026-09-13T06:53:34Z returned one candidate, the
closed Palacete PDF, with `errors: 0`, `partial_inventory: 0`, and
`details_fetched: 0`. This is a false healthy/empty result for the FSA surface,
not a clean empty inventory.

## Fidelity Result

The offline fidelity comparison must fail for the current candidate revision:

- `missing_open`: 2, for the two current open FSA calls absent from adapter output.
- `extra_submission`: 1, for the closed Palacete 2026 PDF emitted by the adapter.
- The closed candidate would be downloaded/OCRed and posted to Repo A if the
  production environment variables were present; the local audit did not run
  `main()` and did not submit anything.

Repo A's candidate endpoint admits the source/contract boundary but does not
reject a generic candidate based on official lifecycle: `app/api/pipeline_routes.py:523-556`
passes the payload to `ScrapeCandidateService`, and
`app/services/scrape_candidate_service.py:521-565` persists generic worker
results while copying optional deadline metadata. There is no BRDE-specific
open-status check. Under the source-reliability candidate contract, submitting
the explicitly closed Palacete material is a release-blocking
`extra_submission`, not an acceptable historical record.

## Release Decision

**Reject P4 / do not activate BRDE candidate production.** The adapter must be
corrected to enumerate the official `/producao/` surface (including its current
root-level detail URLs), retain complete inventory evidence, and fail closed on
unknown or closed lifecycle. A second independent clean audit must then show
both open calls matched and zero extra submissions, followed by the required
candidate canary/replay and operational checks. No production deployment or
rollback action is authorized by this evidence bundle.

This decision applies the acceptance requirements in
`plans/source-reliability/07-verification-and-acceptance.md:63-65` and
`plans/source-reliability/05-source-repair-matrix.md:76-83`, and the production
P4 gate in `plans/source-reliability/PRODUCTION-ONLY-CUTOVER-PLAN-2026-09-12.md:60-64`.
