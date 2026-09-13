# B1 Evidence Maintenance Validation

Status: **REVIEW**. Executor: `/root/b1_checksum_maintenance`. Separate
reviewer: required. UTC start: `2026-09-08T17:02:33Z`; UTC end:
`2026-09-08T17:02:33Z`. Scope is documentation and evidence only. No hosted
system, database, schedule, source, deployment, claim, or other runtime state
was accessed or mutated.

## Purpose And Boundary

B0 review found that the original B1 manifest hashed the mutable shared
[`index.md`](../index.md), which became stale after legitimate later index
updates. The original B1 directory, its historical acceptance, and its
`SHA256SUMS` are retained unchanged. This maintenance run records that
acceptance in a run-local [snapshot](acceptance-snapshot.md), provides a
run-local immutable checksum manifest, and updates only the central evidence
index with this maintenance entry.

This does not re-run B1, pass B2, establish genuine takeover fencing, close a
release gate, or make a release decision.

## Commands And Results

| Command | Result |
|---|---|
| PowerShell direct-local Markdown target check across the historical B1 records, their linked evidence documents, the central index, and both maintenance records | Exit 0; 39 targets checked, 0 missing. External links and anchors were excluded. |
| PowerShell sensitive-pattern scan across the same seven B1-related Markdown files | Exit 0; 0 matches for raw bearer credentials, configured secrets, private keys, credentialed connection strings, raw claim-token assignments, or local user paths. This is a bounded redaction scan, not a whole-repository leak guarantee. |
| Original B1 `SHA256SUMS` validation | Exit 0; 4 immutable artifact entries matched. The sole mismatch was the preserved shared `../index.md` entry: expected `11EBA230BB4E4A7C457A686F833159D44947F8C357890EB7F63A781C9DF23E72`, observed before this run's index update `0751951B5AE04B69A83C9BD9FE49FA70ED17AE0931A6BA3B1B92EC1A0ED398B3`. |
| `git ls-tree HEAD -- docs/evidence/failure_injection_results.json`; `git hash-object docs/evidence/failure_injection_results.json` | Exit 0; both identify blob `21b4451a210d61afb382f3ff79ff880111063399`. Historical runner JSON remains unchanged from `HEAD`. |
| `git diff --check -- docs/evidence/README.md docs/evidence/STAGING-CONTINUATION-2026-09-08.md docs/evidence/closed-beta-2026-09-08/index.md docs/evidence/failure_injection_results.json` | Exit 0; no whitespace errors in tracked B1-related evidence changes. |

## Run-Local Integrity

[`SHA256SUMS`](SHA256SUMS) hashes only this run's
[`acceptance-snapshot.md`](acceptance-snapshot.md) and this report. It excludes
the checksum file itself and all shared mutable documents, especially the
central index. Validate it from this directory with:

```powershell
Get-Content SHA256SUMS | ForEach-Object {
  if ($_ -match '^([A-F0-9]{64})  (.+)$') {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $matches[2]).Hash -ne $matches[1]) { throw "checksum mismatch: $($matches[2])" }
  }
}
```

## Reviewer Handoff And Risk

A separate reviewer should verify the original B1 evidence and acceptance link
targets, rerun the bounded redaction and manifest checks, confirm that the
original B1 directory remains untouched, and validate this run-local manifest
after the central-index update. Keep this maintenance run at `REVIEW` unless
that reviewer accepts it.

Remaining risk is unchanged: B2 still needs authentic alpha-expiry, beta
reclaim, and post-takeover stale-alpha zero-side-effect evidence. B0 remains
blocked; RR-01 through RR-05, source audits, crash/replay, recoverability,
default-deny admission, and release readiness remain open.

### Files Changed By This Run

- `docs/evidence/closed-beta-2026-09-08/index.md`
- `docs/evidence/closed-beta-2026-09-08/b1-evidence-maintenance-2026-09-08T170233Z/acceptance-snapshot.md`
- `docs/evidence/closed-beta-2026-09-08/b1-evidence-maintenance-2026-09-08T170233Z/maintenance.md`
- `docs/evidence/closed-beta-2026-09-08/b1-evidence-maintenance-2026-09-08T170233Z/SHA256SUMS`
