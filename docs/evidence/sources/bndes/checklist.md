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
- [ ] Audit Slot 1: obtain independently prepared official-source inventory and reviewer sign-off.
- [ ] Audit Slot 2: repeat independently from slot 1 and record provenance.
- [ ] Retain credential-redacted raw captures and reproducible inventory derivation.
- [ ] Record qualifying reports and reviewer sign-off. Existing `audit-1/` and
      `audit-2/` are diagnostic history only.

## Phase 3: Staging Execution Verification
- [x] Bugfix applied in commit `fff65a6`: canonical URL mapping for child attachments, URL percent-encoding unquote, and added `bndes-bioinsumos` route.
- [x] Staging Ingestion Rehearsal: downloaded 5 PDFs (Corais, Periferias, Sertão Produtivo, Sertão Anexo IV, Bioinsumos), extracted text, and submitted 5 notices accepted by staging. This is not image-only OCR proof.
- [x] Staging Idempotent Replay: zero re-downloads, zero new submissions, idempotency verified.
- [ ] 48-Hour Observation Soak (minimum 48 hours continuous scheduled execution).
- [ ] 7-Day Operating Review for production cutover signoff.
