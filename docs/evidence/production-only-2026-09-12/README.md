# Production-Only Candidate Evidence - 2026-09-12

Status: **REVIEW / INCOMPLETE**. This directory records candidate implementation
and local verification only. It is not production evidence, release approval,
or a passed P1/P3 gate.

- [P3 admission candidate](p3-admission-candidate-2026-09-12T061138Z.md)
- [P1 isolated harness runbook](P1-HARNESS.md)
- [P1 isolated harness pass](p1-isolated-2026-09-12T235832Z.md)
- [P1 isolated harness rerun](p1-isolated-2026-09-13T000802Z.md)
- [Latest P1 isolated harness pass with changed-content and poison/backoff coverage](p1-isolated-2026-09-13T002232Z.md)
- [P1 genuine image-only OCR fixture](p1-image-only-ocr-2026-09-13T0030Z.md)
- [P3 writer drain/fence readiness ledger](p3-writer-drain-fence-ledger-2026-09-12T2342Z.md)
- Repo A baseline: `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`
- Repo B baseline: `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`
- Both repositories contained uncommitted candidate changes when this record
  was written; the baseline SHAs do not identify the resulting candidate.
- No production deployment, workflow/source activation, database mutation, or
  failure injection occurred. No credential value was read or recorded.
- RR-01 through RR-05 remain OPEN.

The writer ledger inventories the current remote `main` workflows and the
candidate schedule/CLI/API surfaces. It is sanitized readiness material only:
no production mutation was executed, and P3 remains incomplete pending named
owners, approvals, frozen candidate SHAs, immediate production observations,
and independent acceptance of the P1 evidence. The isolated P1 harness now
covers process termination, submit/finish lost-ACK replay, changed-content
replay, poison backoff/quarantine, and measured local capacity. A separate
bounded image-only PDF fixture passed through the real pinned PaddleOCR path.
The live production schema check also reported
`application_schema_versions`, `source_work_items`, and
`source_schedule_state` absent; an approved additive migration is required,
and this evidence does not claim that durable-work or claim rows were read.
