# 48-Hour Observation Template (scaffold — no observation performed)

Copy this file to `docs/evidence/sources/<source_key>/observation-48h.md` when a
staging soak begins. Until then every field stays `TODO`. A 48 h soak never
replaces the two independently grounded clean audits.

- Source: `TODO`
- Window start (UTC): `TODO`
- Window end (UTC, >= start + 48 h): `TODO`
- Registry ref: `TODO: config/source_schedule.json commit`
- Pin ref: `TODO: config/source_catalog_contract.json exported_at`
- Live parity run id: `TODO`
- Hourly attempts observed: `TODO / TODO`
- Completion age <= 120 min: `TODO% of monitored source-minutes (raw, all 23 reported separately)`
- Backlog at start (pending/retrying/quarantined): `TODO / TODO / TODO`
- Backlog at end (pending/retrying/quarantined): `TODO / TODO / TODO`
- Cap-deferred (`cap_reached`) occurrences: `TODO`
- Fidelity blockers: `TODO`
- Incidents / missed ticks (with run ids): `TODO`
- Rollback exercised: `TODO`
- Operator sign-off: `TODO (name, date)`
- Reviewer sign-off: `TODO (name, date)`

Missing monitor samples are unknown, never compliant by default. Never silently
exclude failing sources to meet an SLO; report raw freshness across all 23 plus
a separately labeled upstream-available view.
