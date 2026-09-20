# FBDS technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: fbds
EXPECTED CONTRACT: opportunity; module=discover_fbds_opportunities; group=c; rollout paused (execution hold); schedule_owner=pipeline-discovery-group-c.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official surface https://restaura-amazonia.fbds.org.br/Editais (Fundação Brasileira para o Desenvolvimento Sustentável / Restaura Amazônia MR2)
OBSERVED CONTRACT: opportunity — post-fix audit-only discovery emits all 4 official edital detail pages as closed opportunities with correct deadlines and principal ZIP documents; no open calls currently exist on the official listing
LIFECYCLE HOLD: rollout_mode=paused preserved in config/source_schedule.json; catalog_status=active unchanged; DISCOVERY_AUDIT_ONLY bypasses the hold only for discovery-only/no-ingestion audit; paused hold remains enforced at the workflow/schedule layer. No snapshot/RR-05/release-decision change claimed.
OFFICIAL INVENTORY: open=0, closed=4, upcoming=0, excluded=0, unknown=0
DISCOVERY: emitted=4, rejected=0, errors=0, partial=false, cap_reached=false (records=4 ≤ detail_limit=20)
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (0 open-in-scope; 0/0 healthy empty), traceability%=100.0 (4/4), non_blocking=0
TESTS: `py -3.13 --version` → Python 3.13.5; `py -3.13 -m pytest tests/test_fbds_discovery.py -q` pre-fix → 4 passed; post-fix → 7 passed
CHANGES:
- scripts/discover_fbds_opportunities.py — lifecycle badge parsing (Concluído→closed, Aberto→open) preferred over body text with English open/closed normalization; deadline extraction via Brasília clock + widened keyword window (`-03:00`); principal ZIP (`#Download`) marked is_principal
- tests/test_fbds_discovery.py — three regression tests: Concluído badge closed, FAQ "aberto" does not override badge, status fallback normalization
EVIDENCE: docs/evidence/sources/fbds/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,discovery.json,stats.json,fidelity/}
RISKS: badge markup is SPIP-theme specific — a future theme change could reintroduce unknown status; body-text fallback still heuristics; closed-only inventory means the open-record accounting gate is trivially healthy until a new open edital appears (next open call should be re-audited); deadline clock regex assumes "Brasília" wording
ESCALATION: none
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture 2026-09-14 UTC via direct webfetch of the official FBDS Restaura Amazônia listing and all four detail pages.
- Zero open editais; all four rows sit under "Editais Concluídos" and each detail badge reads Concluído.
- Deadlines (official copy, 18:00 horário de Brasília): 004/2025 → 2025-11-10; 003/2025 → 2025-08-18; 002/2025 → 2025-07-07; 001/2024 → 2025-02-28.
- Principal documents are the per-edital ZIP packages under `/IMG/zip/` linked from `#Download` buttons.

## Pre-fix baseline (this session, retained for provenance)

- First audit-only run emitted 4 opportunities: 3 status=unknown, 1 status=aberto (false open from 002 FAQ body text), all deadlines null. Independent fidelity against a closed-status inventory would fail on authoritative_status_mismatch; defects fixed in the fbds-local adapter before the passing re-audit recorded above.
