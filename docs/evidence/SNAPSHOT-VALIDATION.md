# Snapshot Validation (offline scaffold)

Validates structure only. It never calls live endpoints, never proves health,
and never fabricates audit/soak results. Placeholder `TODO` values pass
structure with an outstanding-placeholders report.

## Required layout

```text
docs/evidence/sources/<source_key>/
  README.md        # per-source placeholder (status NOT STARTED)
  snapshot.json    # required on first use (see schema below)
  checklist.md     # required on first use (runbook steps for this source)
```

## snapshot.json schema (all fields required)

```json
{
  "source_key": "bndes",
  "observed_at": "TODO: ISO-8601 once observed",
  "registry_ref": "TODO: config/source_schedule.json commit",
  "pin_ref": "TODO: config/source_catalog_contract.json exported_at",
  "runs": [],
  "audits": [{ "result": "TODO", "report_path": "" }],
  "notes": "TODO"
}
```

- `source_key` must be one of the 23 registry keys.
- `observed_at` and each run `started_at` must be ISO-8601 once filled.
- `runs[]` entries: `{run_id, started_at, status}` with status in
  `pending|success|failed|warning|skipped|TODO`.
- `audits[]`: at most 2 entries, `result` in `TODO|pass|fail`; a concluded
  `pass`/`fail` must set `report_path` to its independent ground-truth report.
- Credential substrings (`Authorization`, bearer material, `PIPELINE_SECRET`,
  private keys) are rejected; redact before storing.

## Command

```powershell
py -3.13 scripts/validate_staging_snapshot.py --snapshot-dir docs/evidence/sources/<source_key>
```

Exit codes: `0` = structure OK (placeholders reported, not hidden);
`1` = structural failure; `2` = invalid input. Covered offline by
`tests/test_validate_staging_snapshot.py`.
