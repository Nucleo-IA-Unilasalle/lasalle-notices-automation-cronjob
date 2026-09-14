# Evidence: brde (P5 CANARY/REPLAY PASSED, SCHEDULED RUNS PENDING)

Mode: **ingest**.
- Snapshot: `snapshot.json` (updated 2026-09-14)
- Audits: 2/2 technical runs **PASS** with zero blocking exceptions; the final
  P4 reviewer accepted the pair. The failed pre-repair runs are retained at
  [audit 1](production-candidate-audit-1/README.md) and
  [audit 2](production-candidate-audit-2/README.md). Passing post-repair evidence
  is at [repair audit 1](production-candidate-audit-repair-1/README.md) and
  [repair audit 2](production-candidate-audit-repair-2/README.md). Historical
  audit directories remain repository-owned diagnostic comparisons.
- Production P5: Canary `34883807324` and unchanged replay `34884405336`
  passed at Repo B `2b91ee5...`; two actual scheduled executions remain before
  P5 closes. See the [P5 record](../../production-only-2026-09-12/p5-production-canary-2026-09-14T1904Z.md).
- Staging Rehearsal: Historical ingestion and replay were validated on hosted
  staging; production P5 is the current release evidence.
- 48 h observation: Pending soak completion (see [checklist.md](checklist.md)).
