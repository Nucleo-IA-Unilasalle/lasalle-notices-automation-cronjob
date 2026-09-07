# Staging Evidence Index

Status: **IN PROGRESS**. [Hosted staging report](STAGING-2026-09-07.md) records
deployment, catalog parity, BRDE ingestion/replay, BNDES audit failure and
aggregate admission. Per-source independent-audit and soak slots below remain
unfulfilled; adapter self-audits are not independent ground truth. RR-01 through RR-05 remain
**OPEN**. Paused (`canoas`, `dopa`, `fbds`, `finep`, `ibama`) and audit-only
(`tnc`, `funbio`, `govbr_mma_fnma`, `govbr_mma_public_calls`, `unep`) holds are preserved; evidence scaffolding never activates a
source.

## Conventions

- One folder per source: `docs/evidence/sources/<source_key>/` with a
  placeholder `README.md` and a `snapshot.json` + `checklist.md` pair on first use.
- Snapshots are structural only; validate offline with
  `py -3.13 scripts/validate_staging_snapshot.py --snapshot-dir <dir>`.
  See [snapshot validation](SNAPSHOT-VALIDATION.md).
- Audits require **two consecutive independently grounded clean runs** per
  source against independent official-source ground truth (not two copies of
  adapter output). Record report paths in `snapshot.json`. Use the
  [two-audit template](AUDIT-TEMPLATE.md) when starting them.
- Soak requires a **48 h minimum observation** per
  [observation template](OBSERVATION-48H-TEMPLATE.md), then a 7-day operating review.
- Redact credentials before storing anything (validator rejects
  `Authorization` / bearer / `PIPELINE_SECRET` / private-key material).
- Live parity observations from executed live runs go under
  `snapshots/<YYYY-MM-DD>/` (see [snapshots](snapshots/README.md)); the first
  hosted observation is currently retained in the private workspace location
  identified by the staging report.
- Ordered flow: [staging runbook](../STAGING-RUNBOOK.md) → snapshot → audits → 48 h observation.

## Per-source slots

| Source | Mode | Snapshot | Audit 1 | Audit 2 | 48 h observation |
|--------|------|----------|---------|---------|------------------|
| bndes | ingest | TODO | TODO | TODO | TODO |
| brde | ingest | TODO | TODO | TODO | TODO |
| fao | ingest | TODO | TODO | TODO | TODO |
| fapergs | ingest | TODO | TODO | TODO | TODO |
| fundacao_grupo_boticario | ingest | TODO | TODO | TODO | TODO |
| govbr_mma | ingest | TODO | TODO | TODO | TODO |
| iis_rio | ingest | TODO | TODO | TODO | TODO |
| kfw | ingest | TODO | TODO | TODO | TODO |
| msgov | ingest | TODO | TODO | TODO | TODO |
| pncp | ingest | TODO | TODO | TODO | TODO |
| sema_rs | ingest | TODO | TODO | TODO | TODO |
| worldbank | ingest | TODO | TODO | TODO | TODO |
| wwf | ingest | TODO | TODO | TODO | TODO |
| funbio | audit | TODO | TODO | TODO | TODO |
| govbr_mma_fnma | audit | TODO | TODO | TODO | TODO |
| govbr_mma_public_calls | audit | TODO | TODO | TODO | TODO |
| tnc | audit | TODO | TODO | TODO | TODO |
| unep | audit | TODO | TODO | TODO | TODO |
| canoas | paused | TODO (hold) | TODO (hold) | TODO (hold) | TODO (hold) |
| dopa | paused | TODO (hold) | TODO (hold) | TODO (hold) | TODO (hold) |
| fbds | paused | TODO (hold) | TODO (hold) | TODO (hold) | TODO (hold) |
| finep | paused | TODO (hold) | TODO (hold) | TODO (hold) | TODO (hold) |
| ibama | paused | TODO (hold) | TODO (hold) | TODO (hold) | TODO (hold) |
