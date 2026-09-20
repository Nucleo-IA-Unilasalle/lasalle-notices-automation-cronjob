# WWF technical audit 2026-09-14 — commands

Working directory: `lasalle-notices-automation-cronjob` (Repo B).

Scratch (outside repo): `%TEMP%\wwf-audit-66332045` (removed after evidence copy).

## 1. Interpreter

```powershell
py -3.13 --version
# Python 3.13.5
```

## 2. Unit tests (pre-fix baseline)

```powershell
py -3.13 -m pytest tests/test_wwf_discovery.py -q
# 36 passed
```

## 3. Independent official capture (NOT via repo adapter)

Direct `requests.get` of `https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/`
plus each parsed detail URL (detail cap 20), script:
`%TEMP%\wwf-audit-66332045\capture_wwf_independent.py`.

```powershell
py -3.13 $env:TEMP\wwf-audit-66332045\capture_wwf_independent.py $env:TEMP\wwf-audit-66332045
# rows_parsed=10, inventory_records=20, open=7 (1 out_of_scope DOCX-only), closed=13,
# details_fetched=10, detail_cap_reached=false, headings both present
```

HTTP status/content-type/timestamps recorded in `capture-log.json` and
`independent-inventory.json` evidence blocks. No cookies/tokens stored.

## 4. Safe audit-only discovery (pre-fix)

```powershell
$env:DISCOVERY_AUDIT_ONLY="true"
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\wwf-audit-66332045\audit-run-1"
$env:SOURCES="wwf"
py -3.13 scripts/discover_all_candidates.py
# exit 1 — fidelity failures: 18 blocking duplicate_identity
# stats: candidates=19, details_fetched=10, errors=0, section_parse_failed=0
```

## 5. Fix + unit tests (post-fix)

```powershell
py -3.13 -m pytest tests/test_wwf_discovery.py -q
# 37 passed
```

## 6. Safe audit-only discovery (post-fix)

```powershell
$env:DISCOVERY_AUDIT_DIR="$env:TEMP\wwf-audit-66332045\audit-run-2"
py -3.13 scripts/discover_all_candidates.py
# exit 0 — source fidelity OK: no blocking exceptions
# stats: candidates=19, details_fetched=10, errors=0, section_parse_failed=0,
# prefilter_rejected=2, year_rejected=0, candidate_cap_reached=0
```

## 7. Module self-audit path

```powershell
py -3.13 scripts/discover_wwf_candidates.py --audit-dir $env:TEMP\wwf-audit-66332045\module-audit
# exit 0 — inventory 10 rows, discovery 9 grouped rows (DOCX-only row has no candidates),
# candidates 19 with unique per-document source_record_ids
```

## 8. External fidelity CLI

```powershell
py -3.13 scripts/audit_source_fidelity.py `
  --source-inventory $env:TEMP\wwf-audit-66332045\independent-inventory.json `
  --discovery $env:TEMP\wwf-audit-66332045\audit-run-2\wwf\discovery.json `
  --out $env:TEMP\wwf-audit-66332045\fidelity-ext
# exit 0 — blocking=0, accounting%=100.0 (6/6), traceability%=100.0 (19/19),
# non_blocking=1 (out_of_scope DOCX-only open edital 95223)
```
