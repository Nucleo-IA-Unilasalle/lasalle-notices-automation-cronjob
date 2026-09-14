# Evidence: brde (P4 ACCEPTED, P5/P6 PENDING)

Mode: **ingest**.
- Snapshot: `snapshot.json` (recorded 2026-09-07)
- Audits: 2/2 technical runs **PASS** with zero blocking exceptions; the final
  P4 reviewer accepted the pair. The failed pre-repair runs are retained at
  [audit 1](production-candidate-audit-1/README.md) and
  [audit 2](production-candidate-audit-2/README.md). Passing post-repair evidence
  is at [repair audit 1](production-candidate-audit-repair-1/README.md) and
  [repair audit 2](production-candidate-audit-repair-2/README.md). Historical
  audit directories remain repository-owned diagnostic comparisons.
- Staging Rehearsal: Ingestion and replay validated on hosted staging.
- 48 h observation: Pending soak completion (see [checklist.md](checklist.md)).
