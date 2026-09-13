# B1 Historical Acceptance Snapshot

Status: **HISTORICAL ACCEPTANCE RECORDED**. This is a maintenance snapshot,
not a new B1 pass, a B2 fencing result, release approval, or authorization for
a hosted mutation. Executor: `/root/b1_checksum_maintenance`. UTC snapshot:
`2026-09-08T17:02:33Z`.

## Accepted Historical Result

The original B1 run
[`b1-evidence-correction-2026-09-08T163541Z`](../b1-evidence-correction-2026-09-08T163541Z/)
was independently accepted by
[`/root/b1_review`](../b1-evidence-correction-2026-09-08T163541Z/review-acceptance.md)
for evidence correction only. Its acceptance explicitly withholds genuine
post-takeover stale-owner fencing, RR closure, release approval, hosted
mutation authorization, and source-admission changes.

The retained historical runner JSON
[`failure_injection_results.json`](../../failure_injection_results.json)
still has the `HEAD` blob and current worktree hash
`21b4451a210d61afb382f3ff79ff880111063399`. The acceptance evidence therefore
continues to support only the qualified admission, fabricated-token, expiry,
and observed best-effort restoration findings described in the original B1
report.

## Original Manifest Disposition

The original B1 `SHA256SUMS` is preserved unchanged. It recorded four B1
evidence artifacts that still matched at maintenance validation, plus the
shared mutable `../index.md`. Its index entry expected
`11EBA230BB4E4A7C457A686F833159D44947F8C357890EB7F63A781C9DF23E72`; before
this maintenance run updated the central index, the observed hash was
`0751951B5AE04B69A83C9BD9FE49FA70ED17AE0931A6BA3B1B92EC1A0ED398B3` after
legitimate later index updates. This is a maintenance defect in the original
manifest design, not evidence tampering or a change to the historical B1
acceptance result.

This run's [`SHA256SUMS`](SHA256SUMS) covers only immutable files in this run
directory. It deliberately excludes the shared central index and does not
modify the original B1 evidence or manifest.
