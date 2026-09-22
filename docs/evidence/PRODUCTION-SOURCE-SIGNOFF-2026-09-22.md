# Production source sign-off - 2026-09-22

## Decision

The production source gate is accepted with PNCP and WWF recorded as external
degradations. DOPA is healthy. PNCP remains enabled and fail-closed. WWF
remains paused in `config/source_schedule.json`.

## DOPA

- Diagnostic logging shipped in commit `d64e6e7` and records the work item,
  source record, terminal error code, attachment outcomes, and sanitized
  submission result for every failed structured item.
- The rejected payload used `opportunity_type=public_call`, which is outside
  Repo A's `funding|procurement|consultancy|other` contract. Commit `d6cb4ba`
  maps DOPA's mixed public-call and hiring notices to `other`.
- Production run
  [35681264183](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/actions/runs/35681264183)
  succeeded after discovering 175 records and three opportunities, downloading
  five PDFs, and completing five OCR operations.
- Read-only monitor run
  [35681652901](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/actions/runs/35681652901)
  observed DOPA as `healthy` with `inventory_seen=175`, `inserted=3`,
  `updated=0`, `duplicates=0`, and `errors=0`.

## PNCP accepted external degradation

- Retry run
  [35680485745](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/actions/runs/35680485745)
  failed closed with 35 first-page search failures and zero records.
- The official `proposta`, `publicacao`, and `atualizacao` endpoints all timed
  out on the GitHub-hosted runner after the configured two attempts with an
  eight-second read timeout. No successful empty run was recorded and no code,
  timeout, source enablement, or checkpoint policy was changed.
- Production monitoring consequently reports PNCP as `failing`, with
  `inventory_seen=0`, `inserted=0`, and `errors=1`. This is accepted as an
  external PNCP API degradation pending recovery of an official endpoint.

## WWF accepted external degradation

- The local origin returned HTTP 200 during this check, but the required
  GitHub-hosted proof failed: audit run
  [35681801233](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/actions/runs/35681801233)
  received HTTP 403 from the official listing and recorded one fetch error.
- WWF remains `rollout_mode: paused`. No ingestion run was attempted, and the
  audit cannot qualify for a zero-blocker fidelity result while the official
  origin blocks the production runner.

## Verification

- `py -3.13 -m pytest tests/test_managed_source.py -q`: 43 passed.
- `py -3.13 -m pytest tests/test_dopa_discovery.py tests/test_managed_source.py -q`: 60 passed.
- `py -3.13 -m pytest tests/test_reliability_review_regressions.py -q`: 26 passed.
- Final full suite: 1174 passed.
