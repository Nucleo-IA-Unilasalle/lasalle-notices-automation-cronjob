# Closed-Beta Evidence Index

Status: BLOCKED. This index records available closed-beta evidence. It is not
release approval, deployment authorization, a hosted mutation, or source
activation. RR-01 through RR-05 remain OPEN.

## Runs

| Task/run | Status | Executor | Reviewer | Evidence |
|---|---|---|---|---|
| B0 / `b0-baseline-2026-09-08T162840Z` | BLOCKED | `/root/b0_baseline` (actual session; model assignment unavailable to this record) | `/root/b0_review` (separate actual session; model assignment unavailable to this record) | [baseline](b0-baseline-2026-09-08T162840Z/baseline.md), [scenario map](b0-baseline-2026-09-08T162840Z/scenario-map.md), [review](b0-baseline-2026-09-08T162840Z/review.md) |
| B0 / `b0-identity-collection-2026-09-08T174920Z` | BLOCKED | `/root` | Separate reviewer required | [authorized read-only identity collection](b0-identity-collection-2026-09-08T174920Z/identity-collection.md); active default-branch legacy schedules and candidate/deployment mismatches observed; production/staging DB schema/work aggregates, deployed B worker identity, and GitHub secret-value target attestation remain unavailable |
| B1 / `b1-evidence-correction-2026-09-08T163541Z` | PASS (evidence correction only) | `/root/b1_evidence` (actual session; model assignment unavailable to this record) | `/root/b1_review`, separate session; accepted | [evidence correction](b1-evidence-correction-2026-09-08T163541Z/evidence-correction.md), [independent review](b1-evidence-correction-2026-09-08T163541Z/review-acceptance.md) |
| B1 maintenance / `b1-evidence-maintenance-2026-09-08T170233Z` | REVIEW (checksum maintenance only) | `/root/b1_checksum_maintenance` | Separate reviewer required | [acceptance snapshot](b1-evidence-maintenance-2026-09-08T170233Z/acceptance-snapshot.md), [maintenance validation](b1-evidence-maintenance-2026-09-08T170233Z/maintenance.md), [run-local checksums](b1-evidence-maintenance-2026-09-08T170233Z/SHA256SUMS) |
| B2 | TODO | Sol xhigh | Separate Sol high pass | Not started |
| B3 | TODO | Sol xhigh | Separate Sol high pass | Not started; contract freeze after B2 |
| B4 / `b4-migration-recoverability-prep-2026-09-08T165123Z` | BLOCKED | `/root/b4_recovery_prep` (actual session; model assignment unavailable to this record) | Separate Sol high review required | [local migration/recoverability preparation](b4-migration-recoverability-prep-2026-09-08T165123Z/migration-recoverability.md), [current blocker revalidation](b4-blocker-revalidation-2026-09-08T174920Z/blocker-revalidation.md); production version, authorization, named private backup/restore, hosted prior-worker compatibility, and final post-B2/B3 rerun remain blocked |
| B5 / `b5-default-deny-2026-09-08T165842Z`; review `b5-independent-review-2026-09-08T174525Z` | REVIEW (changes required) | `/root/b5_default_deny` | `/root/b5_independent_review` (separate actual session; acceptance withheld) | [implementation evidence](b5-default-deny-2026-09-08T165842Z/b5-default-deny.md), [independent review](b5-independent-review-2026-09-08T174525Z/review.md), [local fixes and final validation](b5-final-validation-2026-09-08T180900Z/validation.md), [final run-local checksums](b5-final-validation-2026-09-08T180900Z/SHA256SUMS), [independent-review checksums](b5-independent-review-2026-09-08T174525Z/SHA256SUMS) |
| B6 | TODO | Terra high | Sol high | Not started |
| B7 | TODO | Sol xhigh | Separate Sol high pass | Not started |
| B8 | TODO | Sol high | Sol high and operator | Explicit production approval required |
| B9-B11 | TODO | See release plan | See release plan | Not started |

## Evidence Rules

- Add one new task/run directory; never overwrite failed evidence.
- Sanitize public evidence. Store no credentials, connection strings, raw claim
  tokens, personal data, or production dumps here.
- A task can be `PASS` only with linked verification and separate reviewer
  acceptance. B0 remains `BLOCKED`; B1 passed its separately reviewed evidence
  correction scope only and closed no release gate.
- Historical staging documents are observations, not proof of current target
  identity, production state, source audit completion, or release readiness.

## Proposed Beta Exceptions

These are unapproved proposals, not active exceptions. Delayed source cadence
and incomplete 23-source coverage may be tolerated only while visibility is
truthful and a named operator has recorded scope, expiry, rollback condition,
and approval. Source audits, record integrity, fencing, recoverability, and
default-deny admission remain release gates. A held source must not be replaced
by silently enabling another source.

## B0 Review Disposition

Reviewer: `/root/b0_review`, a separate session from `/root/b0_baseline`.

The review corrected the omitted current GitHub Actions/default-branch writer
state and clarified unknown identity assertions. No sensitive value was found.
B0 cannot pass until the operator supplies or authorizes the remaining
read-only production/staging service, database, deployed runtime-writer, and
API-side pending-work observations described in the linked review.
