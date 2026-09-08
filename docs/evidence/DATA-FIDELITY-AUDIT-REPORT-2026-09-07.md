# Data Fidelity Evidence Review - 2026-09-07

**Original evidence commit**: `abf2fba`
**Review status**: Corrected; RR-05 remains open for BRDE and BNDES
**Environment mutation**: None during this review

## Corrected verdict

The committed BRDE and BNDES artifacts reproduce blocker-free URL comparisons,
but they do not satisfy the independent-ground-truth requirements of RR-05.
The earlier `GATE RR-05 PASSED` verdict is withdrawn.

| Source | Historical comparison | Independent audit slots | RR-05 |
|---|---:|---:|---|
| BRDE | 2 runs, 1/1 URL identities matched, 0 blockers | 0/2 | OPEN |
| BNDES | 2 runs, 5/5 URL identities matched, 0 blockers | 0/2 | OPEN |

The percentages in the generated fidelity summaries are correct for the record
sets supplied to the verifier. They are not proof that those record sets were
complete, independently prepared, or authoritative as to lifecycle state.

## Evidence-integrity findings

### Critical: the capture was not independent

`scripts/run_independent_source_audit.py` both selected the purported inventory
and invoked the production adapter in one repository-owned process. The same
code and runner produced slot 1 and slot 2 only 8-9 seconds apart. Separate HTTP
requests demonstrate repeatability, not independent ground truth or independent
reviewer sign-off.

The runner also identified itself as `Independent Auditor (Antigravity)`. That
string was supplied by the program and does not identify a documented human or
organizationally independent reviewer. The historical `capture_metadata.json`
files are retained unchanged so the record of what happened is not rewritten.

### High: the comparison covered a preselected subset

BRDE selection was hard-coded to a PDF URL containing `Patrocinio` and `2026`.
BNDES selection hard-coded four known subpages and filename patterns expected to
produce five links. A clean match therefore proves that the adapter returned
those selected URLs; it does not prove that all in-scope official opportunities
were inventoried or that excluded documents were correctly classified.

No raw HTML response was committed. Response byte counts and SHA-256 digests
cannot reconstruct the pages or allow a reviewer to audit the selection boundary.

### High: lifecycle claims were asserted, not captured

The historical inventory records set every selected link to `status: open`, but
the runner did not parse or retain authoritative status or deadline evidence.
Consequently, the generated comparisons do not validate lifecycle fidelity.

### Critical: snapshot run data included unsupported values

The BNDES snapshot contained two invented identifiers,
`fff65a6a-bnde-47eb-96a2-cc9b827d86b4` and
`bnde5101-9358-47eb-96a2-cc9b827d86b5`; neither is a UUID or appears in the
staging run evidence. Both snapshots also assigned exact round-hour
`started_at` values that were not retained by the handoff and, for BRDE, predate
the documented hosted database creation window. The snapshot run arrays are now
empty rather than preserving fabricated precision. Known observed run IDs and
staging outcomes remain in `STAGING-2026-09-07.md` without invented timestamps.

## Remediation

- Historical `audit-1/` and `audit-2/` inventories, discovery files, and fidelity
  reports remain unchanged and are classified as diagnostic comparisons.
- Both snapshot audit slots and checklists are reset to `TODO`.
- The diagnostic runner now fails closed on unsuccessful official-page requests,
  adapter errors, cap exhaustion, empty output, and stats mismatches.
- The runner requires a new output directory and writes `diagnostic_only` plus
  `rr05_accepted: false` into standalone output. A blocker-free comparison exits
  with code 2 so it cannot be consumed as a release pass.
- The evidence index and source pages no longer claim two independent audits.

## Required evidence to close RR-05

Each source still needs two separately prepared official-source inventories with
retained raw provenance, explicit scope and lifecycle decisions, separate capture
sessions, and identifiable reviewer sign-off. Those inventories may then be
compared offline with `scripts/audit_source_fidelity.py`. Repository-owned
selected-page diagnostics may support investigation but cannot fill either slot.

Production activation, 48-hour soak, and the seven-day review remain separate
gates. This correction performed no live or production mutation.
