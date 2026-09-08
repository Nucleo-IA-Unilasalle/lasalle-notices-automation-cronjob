# Staging Runbook

Status: **IN PROGRESS**. Hosted deployment, parity, BRDE ingestion/replay and
aggregate admission were exercised on 2026-09-07; see the
[staging report](evidence/STAGING-2026-09-07.md). Independent audits, full
failure-injection/load gates and the soak are incomplete. RR-01 through RR-05
remain **OPEN**. Paused sources
(`canoas`, `dopa`, `fbds`, `finep`, `ibama`) and audit-only sources (`tnc`,
`funbio`, `govbr_mma_fnma`, `govbr_mma_public_calls`, `unep`) keep their holds;
this runbook never authorizes activation.

## Prerequisites

- [x] Staging authorization recorded: user approved free-only replacement and
      preferred reuse of the existing setup on 2026-09-07. Not production activation.
- [x] Staging Repo A deployment commit: `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`.
- [x] Staging database provisioning recorded: free Render PostgreSQL 17, named
      `lasalle-notices-staging-db`; expires 2026-10-07. The operator reported
      loading catalog fixtures only and not restoring production users/data.
      Independent confirmation that its identity is distinct remains open below.
- [x] Worker target: `https://lasalle-notices-api-staging.onrender.com`;
      newly generated staging-only secret remains in Render, not this document.
- [x] Catalog pin: `config/source_catalog_contract.json`, export 2026-09-06;
      live hosted comparison passed on 2026-09-07.
- [ ] Database identity verified distinct from production, backup recorded,
      and restore verified in isolation before any production migration.
- [ ] Exact A/B release commits and offline verification results recorded.
- [ ] Staging secrets isolated from production. The existing parity workflow
      uses repository secrets; do not dispatch it expecting staging unless its
      target is explicitly verified. Never replace production repository secrets
      just to run a staging check.

## Ordered checklist (partial evidence does not check off compound gates)

1. [ ] Apply `python -m scripts.migrate_schema` (Repo A) on the staging database; confirm schema v3, including the v1-to-v2-to-v3 upgrade path. API startup only verifies schema; it does not migrate it.
2. [ ] Pinned parity: `py -3.13 scripts/check_source_catalog_parity.py` passes.
3. [ ] Run `python scripts/check_source_catalog_parity.py --live --output catalog-observation.json` with verified staging credentials, or dispatch `source-catalog-parity.yml` only against its verified intended target. Store the sanitized observation, target, and exact commits under `docs/evidence/snapshots/<date>/`.
4. [ ] Audit-only canary for one source (`DISCOVERY_AUDIT_ONLY=true`); upload fidelity artifact; run `audit_source_fidelity.py` offline.
5. [ ] Drain-only rehearsal (`SOURCE_DRAIN_ONLY=true` + `SOURCE_WORK_ENABLED=true`) where backlog exists; confirm 420 s preflight and warning stats.
6. [ ] Exercise a genuine worker through registration, download/OCR, submission, acknowledgement, telemetry and catalog reads. Verify old-worker compatibility, lost acknowledgements, restart/replay, stale-owner fencing, queue backpressure, and aggregate concurrency of three. Record API/DB load, latency and backlog results. Record per-source snapshots with `scripts/validate_staging_snapshot.py --snapshot-dir <dir>`; this validator checks structure only, and a pass with TODO placeholders is NOT release evidence.
7. [ ] Two consecutive independently grounded clean audits per source before any activation (independent official-source ground truth, not two copies of adapter output; see the [two-audit template](evidence/AUDIT-TEMPLATE.md)).
8. [ ] After approved production canaries and the final activation wave, start 48 h minimum observation using `docs/evidence/OBSERVATION-48H-TEMPLATE.md`; verify actual scheduled runs, monitoring delivery and daily human fallback, then follow with a 7-day operating review. Do not backdate the observation window or count unknown samples as passes.
9. [ ] Rehearse rollback: stop new claims and disable/drain the affected schedule owner before restoring a compatible worker; preserve pending work, accepted records and schema. Keep `SOURCE_RUN_REPORTING_ENABLED=true`. Disabling callbacks is emergency-only and must explicitly record loss of observability, not serve as the standard rollback.

## Production cutover interlock

- Do not merge Repo B's schedule changes to `main` before A is deployed,
  migrated and live-parity verified. The group workflows contain active crons
  and ingest-mode entries; merging is not a dormant code upload.
- Start A with `SOURCE_CLAIM_ENFORCEMENT=compatible` for the old-worker
  compatibility window. Enable strict enforcement only after all writer paths
  have been verified to supply valid claims.
- Disable the old owner and drain or safely fence its active jobs before
  enabling exactly one replacement per source. Pending old-version jobs need
  explicit cancellation review; YAML replacement alone does not stop them.
- Keep recovery ticks disabled until live admission/backlog evidence supports
  enabling them. Retain all paused and audit modes until source-specific gates
  pass; no catalog lifecycle change is implied by deploying infrastructure.

## Sign-off (all TODO)

| Role | Name | Date | Decision |
|------|------|------|----------|
| Operator | TODO | TODO | TODO |
| Reviewer | TODO | TODO | TODO |

Free-only constraint: GitHub Actions remains the scheduler/worker platform. Hourly
targets are attempts, not guarantees. A GitHub-only monitor cannot detect a
GitHub-wide outage while that platform is down.
