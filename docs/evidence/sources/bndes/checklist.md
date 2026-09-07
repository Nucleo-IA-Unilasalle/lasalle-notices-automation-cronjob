# Staging Runbook Checklist: bndes

Source Key: `bndes`  
Mode: `ingest`  
Orchestrator: `discover_bndes_candidates.py` via `pipeline-discovery-group-a.yml`

## Phase 1: Pre-Flight & Contract Alignment
- [x] Verify entry in `config/source_schedule.json` (Group A, interval 60 min, contract `candidate`).
- [x] Verify pinned entry in `config/source_catalog_contract.json` (active status).
- [x] Verify official listing URLs:
  - Fundo Socioambiental: `https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental`
  - Chamadas de Inovação: `https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao`

## Phase 2: Independent Official Ground-Truth Audits (Gate RR-05)
- [x] Audit Slot 1: Direct capture from official portal (`2026-09-07T23:02:25.336124+00:00`), 0 blockers, 100% accounting, 100% traceability.
- [x] Audit Slot 2: Independent second capture session (`2026-09-07T23:02:34.162458+00:00`), 0 blockers, 100% accounting, 100% traceability.
- [x] Retain credential-redacted captures in `docs/evidence/sources/bndes/audit-1` and `audit-2`.
- [x] Update `docs/evidence/sources/bndes/audits.md` and sign off completion gate.

## Phase 3: Staging Execution Verification
- [x] Bugfix applied in commit `fff65a6`: canonical URL mapping for child attachments, URL percent-encoding unquote, and added `bndes-bioinsumos` route.
- [x] Staging Ingestion Rehearsal: downloaded 5 PDFs (Corais, Periferias, Sertão Produtivo, Sertão Anexo IV, Bioinsumos), OCR extracted, 5 notices submitted and accepted.
- [x] Staging Idempotent Replay: zero re-downloads, zero new submissions, idempotency verified.
- [ ] 48-Hour Observation Soak (minimum 48 hours continuous scheduled execution).
- [ ] 7-Day Operating Review for production cutover signoff.
