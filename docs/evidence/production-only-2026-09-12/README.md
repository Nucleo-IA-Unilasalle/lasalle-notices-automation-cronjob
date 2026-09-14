# Production-Only Candidate Evidence - 2026-09-12

Status: **P1-P4 COMPLETE; P5 CANARY/REPLAY PASSED, TWO SCHEDULED EXECUTIONS
PENDING**. This directory records the frozen predeployment gates and bounded
production cutover. P6 has not begun, and no other source or contract is
authorized.

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
- [P3 production refresh](p3-refresh-2026-09-14T1811Z.md)
- [P2 accepted migration-specific recoverability bundle](p2-recoverability-20260913T070433Z/README.md)
- [P4 independent release decision](p4-release-decision-2026-09-13T0748Z.md)
- [P4 refreshed release decision](p4-release-decision-2026-09-14T1815Z.md)
- [P4 Repo A ACL amendment](p4-release-amendment-2026-09-14T1823Z.md)
- [P4 Repo B default-deny amendment](p4-release-amendment-2026-09-14T1852Z.md)
- [P5 production cutover, canary, and replay](p5-production-canary-2026-09-14T1904Z.md)
- Repo A baseline: `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`
- Repo B baseline: `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`
- Repo A production and executable SHA:
  `419673a90cfd6feb192d505c6cd9a43d4d9ae251`.
- Repo B production and executable SHA:
  `2b91ee58e09a77cb5cd5b9b3760048832ef5aa12`.
- Supabase schema v3, RLS, internal-table ACL revokes, live admission, the
  25-workflow legacy fence, BRDE canary, and unchanged replay passed their P5
  checks. Two actual scheduled executions are still required to close P5.
- Production evidence is sanitized. No credential value, connection string,
  claim token, raw production payload, or destructive failure injection is
  recorded.
- Full-program RR-01 through RR-05 remain open beyond this one-source beta.

The writer ledger is the immutable pre-P4 inventory. The P5 record supersedes
its predeployment production-state observations: the additive migration is
now installed on Supabase, Repo A and Repo B are live at the SHAs above, only
BRDE is admitted, and group A owns its schedule. P5 still requires two actual
scheduled executions. P6 then requires a 48-hour soak and seven-day review.
Manual dispatches do not close those time-bound gates.
