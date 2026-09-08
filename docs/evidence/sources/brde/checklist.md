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
- [ ] Audit Slot 1: obtain independently prepared official-source inventory and reviewer sign-off.
- [ ] Audit Slot 2: repeat independently from slot 1 and record provenance.
- [ ] Retain credential-redacted raw captures and reproducible inventory derivation.
- [ ] Record qualifying reports and reviewer sign-off. Existing `audit-1/` and
      `audit-2/` are diagnostic history only.

## Phase 3: Staging Execution Verification
- [x] Staging Ingestion Rehearsal (`da824048-181e-4653-9570-096ef1177073`): downloaded 278,314 PDF bytes, text extracted, 1 notice inserted. This is not image-only OCR proof.
- [x] Staging Idempotent Replay (`204538a5-9ac5-469d-a062-3618967c29e5`): zero duplicate insertions or redundant processing.
- [ ] 48-Hour Observation Soak (minimum 48 hours continuous scheduled execution).
- [ ] 7-Day Operating Review for production cutover signoff.
