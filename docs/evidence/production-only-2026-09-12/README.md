# Production-Only Candidate Evidence - 2026-09-12

Status: **P1-P4 ACCEPTED FOR THE SCOPED P5 WINDOW**. This directory records
predeployment evidence. It is not a production canary or P5/P6 result.

- [P3 admission candidate](p3-admission-candidate-2026-09-12T061138Z.md)
- [P1 isolated harness runbook](P1-HARNESS.md)
- [P1 isolated harness pass](p1-isolated-2026-09-12T235832Z.md)
- [P1 isolated harness rerun](p1-isolated-2026-09-13T000802Z.md)
- [Latest P1 isolated harness pass with changed-content and poison/backoff coverage](p1-isolated-2026-09-13T002232Z.md)
- [P1 genuine image-only OCR fixture](p1-image-only-ocr-2026-09-13T0030Z.md)
- [P1 frozen-code harness pass](p1-frozen-2026-09-13T005113Z.md)
- [P1 BRDE frozen-code harness pass](p1-brde-frozen-2026-09-13T021659Z.md)
- [P1 BRDE harness run that exposed the live-claim cleanup bug](p1-brde-frozen-2026-09-13T021456Z.md)
- [P1 BRDE post-repair frozen-code harness pass](p1-brde-postrepair-2026-09-13T071527Z.md)
- [P1 BRDE post-repair invocation with wrong local password](p1-brde-postrepair-2026-09-13T071429Z.md)
- [P3 writer drain/fence readiness ledger](p3-writer-drain-fence-ledger-2026-09-12T2342Z.md)
- [P3 final frozen readiness record](p3-final-readiness-2026-09-13T0735Z.md)
- [P2 accepted migration-specific recoverability bundle](p2-recoverability-20260913T070433Z/README.md)
- [P4 independent release decision](p4-release-decision-2026-09-13T0748Z.md)
- Repo A baseline: `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`
- Repo B baseline: `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`
- Repo A frozen code candidate: `a5275dae46f223da74dc54d0734051acc66a8a9f`
- Repo B frozen code candidate: `2e0dd74ee64b999318dea4cc1767df4985b384ee`
- Both candidates are committed, pushed, and green in current branch CI. The
  exact post-repair P1 harness and two BRDE source audits use these SHAs.
- No production deployment, workflow/source activation, database mutation, or
  failure injection occurred. No credential value was read or recorded.
- Full-program RR-01 through RR-05 remain open beyond this one-source beta.

The writer ledger inventories the current remote `main` workflows and the
candidate schedule/CLI/API surfaces. It is sanitized readiness material only:
no production mutation was executed before P4. Named ownership, exact
candidate SHAs, current read-only observations, P1, migration-specific P2, P3,
and both post-repair BRDE audits were independently accepted for only the
enumerated P5 sequence in the staffed window. The live production schema check
reported
`application_schema_versions`, `source_work_items`, and
`source_schedule_state` absent; an approved additive migration is required,
and this evidence does not claim that durable-work or claim rows were read.
