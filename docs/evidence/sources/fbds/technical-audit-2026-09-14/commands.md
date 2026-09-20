# Commands — fbds technical audit 2026-09-14

Working directory: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob`
UTC session: 2026-09-14 (~21:45Z–22:00Z). Shell available. Python 3.13.5 verified via `py -3.13 --version`.

## Step 1 — Read adapter/tests/registry (read-only)

- `scripts/discover_fbds_opportunities.py`
- `tests/test_fbds_discovery.py`
- `config/source_schedule.json` (fbds: opportunity, group c, paused, owner pipeline-discovery-group-c.yml, interval 60, detail_limit 20, page_limit 5, attachment_limit 25)
- `config/source_catalog_contract.json` (fbds: catalog_status active)
- `scripts/source_fidelity.py` `validate_records` / `run_audit`
- `docs/evidence/sources/fbds/README.md` (paused, NOT STARTED)

## Step 2 — Unit tests (pre-fix baseline)

```powershell
py -3.13 -m pytest tests/test_fbds_discovery.py -q
```

Result: `4 passed in 0.16s`

## Step 3 — Independent official capture (webfetch, not adapter)

- `https://restaura-amazonia.fbds.org.br/Editais` → 200 HTML; 4 concluded editais
- 4 detail pages (004/2025, 003/2025, 002/2025, 001/2024) → each 200 HTML; badge Concluído; ZIP #Download principal doc

## Step 4 — Baseline audit-only discovery (pre-fix adapter)

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR = Join-Path $env:TEMP ('fbds-audit-baseline-' + [guid]::NewGuid().ToString('N'))
$env:SOURCES='fbds'
$env:SUBMISSION_CONTRACT='opportunity'
$env:OPPORTUNITY_SOURCES='fbds'
py -3.13 scripts/discover_all_candidates.py
```

Result: exit 0; 4 opportunities; statuses `unknown`/`aberto`; all deadlines `null`.
Root cause: status regex misses "Concluído"; deadline window `.{0,40}` too narrow for
"Prazo Submissão das propostas até as 18:00 (horário de Brasília) do dia DD/MM/YYYY";
002 falsely `aberto` from FAQ body text.

## Step 5 — Adapter fix (fbds-local)

Edited `scripts/discover_fbds_opportunities.py`:

- SPIP badge lifecycle (`.button` Concluído/Aberto) preferred over body text; tokens normalized to `open`/`closed`/`unknown`
- Deadline: Brasília clock form `até as HH:MM ... Brasília ... DD/MM/YYYY` → `HH:MM-03:00`; keyword+date fallback window expanded to 120 chars → `23:59-03:00`
- Principal document: `#Download` link marked `is_principal=True`

Added regression tests in `tests/test_fbds_discovery.py`:
`test_concluido_badge_is_closed_not_unknown`,
`test_body_open_mention_does_not_override_concluido_badge`,
`test_status_text_fallback_normalizes_to_open_closed`.

## Step 6 — Unit tests (post-fix)

```powershell
py -3.13 -m pytest tests/test_fbds_discovery.py -q
```

Result: `7 passed in 0.18s`

## Step 7 — Post-fix audit-only discovery

```powershell
$env:DISCOVERY_AUDIT_ONLY='true'
$env:DISCOVERY_AUDIT_DIR = Join-Path $env:TEMP ('fbds-audit-postfix-' + [guid]::NewGuid().ToString('N'))
$env:SOURCES='fbds'
$env:SUBMISSION_CONTRACT='opportunity'
$env:OPPORTUNITY_SOURCES='fbds'
py -3.13 scripts/discover_all_candidates.py
```

Result: exit 0; stats `records=4, details_fetched=4, opportunities=4, errors=0`;
statuses all `closed`; deadlines all `HH:MM-03:00` matching independent inventory.
`DISCOVERY_AUDIT_ONLY` bypasses the rollout hold by design (discovery-only, no
ingestion). The registry `rollout_mode=paused` hold remains enforced at the
workflow/schedule layer (`pipeline-discovery-group-c.yml` matrix entry).

## Step 8 — Independent fidelity CLI

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory docs/evidence/sources/fbds/technical-audit-2026-09-14/independent-inventory.json `
  --discovery <AUDIT_DIR>/fbds/discovery.json `
  --out docs/evidence/sources/fbds/technical-audit-2026-09-14/fidelity
```

Result: exit 0; blockers=0; inventory_accounting_pct=100.0; candidate_traceability_pct=100.0;
open_in_scope=0 (all official rows closed); non_blocking=0.

## Safety

No credentials. No Repo A endpoints. No workflow dispatch. No commits/pushes.
No shared config/workflow/registry edits. Scratch dirs under `%TEMP%`.
