# Staging Runbook Checklist: brde

Source Key: `brde`  
Mode: `ingest`  
Orchestrator: `discover_brde_candidates.py` via `pipeline-discovery-group-a.yml`

## Phase 1: Pre-Flight & Contract Alignment
- [x] Verify entry in `config/source_schedule.json` (Group A, interval 60 min, contract `candidate`).
- [x] Verify pinned entry in `config/source_catalog_contract.json` (active status).
- [x] Verify official listing URLs:
  - Palacete: `https://www.brde.com.br/palacete/editais/`
  - FSA: `https://www.brde.com.br/fsa/chamadas-de-investimento/`

## Phase 2: Independent Official Ground-Truth Audits (Gate RR-05)
- [x] Audit Slot 1: Direct capture from official portal (`2026-09-07T23:02:01.184360+00:00`), 0 blockers, 100% accounting, 100% traceability.
- [x] Audit Slot 2: Independent second capture session (`2026-09-07T23:02:09.655045+00:00`), 0 blockers, 100% accounting, 100% traceability.
- [x] Retain credential-redacted captures in `docs/evidence/sources/brde/audit-1` and `audit-2`.
- [x] Update `docs/evidence/sources/brde/audits.md` and sign off completion gate.

## Phase 3: Staging Execution Verification
- [x] Staging Ingestion Rehearsal (`da824048-181e-4653-9570-096ef1177073`): downloaded 278,314 PDF bytes, OCR extracted, 1 notice inserted.
- [x] Staging Idempotent Replay (`204538a5-9ac5-469d-a062-3618967c29e5`): zero duplicate insertions or redundant processing.
- [ ] 48-Hour Observation Soak (minimum 48 hours continuous scheduled execution).
- [ ] 7-Day Operating Review for production cutover signoff.
