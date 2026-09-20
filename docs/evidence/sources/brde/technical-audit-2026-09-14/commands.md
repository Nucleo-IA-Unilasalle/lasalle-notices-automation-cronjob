# Commands executed (coordinator shell), UTC date 2026-09-14

```
py -3.13 -m pytest tests/test_brde_discovery.py tests/test_source_fidelity.py tests/test_discover_all_candidates.py -q
# -> 169 passed in 14.76s

$env:DISCOVERY_AUDIT_ONLY='true'; $env:DISCOVERY_AUDIT_DIR='artifacts/tech-audit/brde-2026-09-14'; $env:SOURCES='brde'; py -3.13 scripts/discover_all_candidates.py
# -> exit 0; brde: discovered 2 candidates; errors=0; partial_inventory=0; cap_reached=0

py -3.13 scripts/audit_source_fidelity.py --source-inventory docs/evidence/sources/brde/technical-audit-2026-09-14/independent-inventory.json --discovery artifacts/tech-audit/brde-2026-09-14/brde/discovery.json --out docs/evidence/sources/brde/technical-audit-2026-09-14/fidelity
# -> exit 0; source fidelity OK: no blocking exceptions; accounting 100%; traceability 100%
```

Independent inventory source: subagent read-only webfetch capture of official BRDE pages (FSA production tab + Palacete editais) on 2026-09-14, coordinator-persisted. Adapter-written source_inventory.json was not used as ground truth.
