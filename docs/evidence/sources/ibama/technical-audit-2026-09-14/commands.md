# IBAMA technical audit 2026-09-14 — commands

Working directory: repository root (`lasalle-notices-automation-cronjob`).

## Environment check

```powershell
py -3.13 --version
# Python 3.13.5
```

## Unit tests

```powershell
py -3.13 -m pytest tests/test_ibama_discovery.py -q
# pre-fix: 13 passed
# post-fix: 17 passed (4 new regression tests)
```

## Independent capture (not via adapter)

Scratch script under `%TEMP%\ibama-audit-20260914\capture_independent.py`
(direct requests of the five official endpoints + 47 detail pages). Not treated
as `run_independent_source_audit.py`. Output: independent-inventory.json,
capture-log.json, independent-capture-summary.json.

```powershell
py -3.13 "$env:TEMP\ibama-audit-20260914\capture_independent.py" "$env:TEMP\ibama-audit-20260914"
```

## Audit-only discovery (DISCOVERY_AUDIT_ONLY bypasses rollout holds by design)

The paused rollout hold remains enforced at the workflow/schedule layer
(`pipeline-discovery-group-c.yml` / registry `rollout_mode=paused`). This path
is discovery-only with no ingestion or submission.

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\ibama-audit-20260914\audit-run"
$env:SOURCES='ibama'
$env:SUBMISSION_CONTRACT='opportunity'
$env:OPPORTUNITY_SOURCES='ibama'
py -3.13 scripts/discover_all_candidates.py
# EXIT=0; opportunities=8; errors=0; partial=0; cap_reached=0
```

## Source fidelity (external, independent inventory)

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory "$env:TEMP\ibama-audit-20260914\independent-inventory.json" `
  --discovery "$env:TEMP\ibama-audit-20260914\audit-run\ibama\discovery.json" `
  --out "$env:TEMP\ibama-audit-20260914\fidelity-run3"
# EXIT=0; blockers=0; accounting=100% (2/2); traceability=100% (8/8)
```

Pre-fix baseline (fidelity-run1, retained as pre-fix-*): EXIT=1; 6 blocking
(missing_open FSO, status/deadline mismatches AGU/Candonga/RAPP, inventory
duplicate_identity on edital-22 before inventory hygiene).

## Production actions

None. No commit, push, workflow dispatch, secrets, or Repo A endpoints used.
