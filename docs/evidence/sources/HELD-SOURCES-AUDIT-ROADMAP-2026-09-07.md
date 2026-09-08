# Held Sources Ground-Truth Audit Roadmap

> Review qualification: Counts below are historical adapter probe results, not
> independently verified complete open-call inventories. Zero returned records
> does not prove zero open calls, capped results do not prove completeness, and
> document counts need not equal opportunity counts. Reported availability is
> not a current live check. All holds and RR-05 remain OPEN.

**Date**: 2026-09-07  
**Authorship**: Historical repository-runner draft; no independent reviewer sign-off
**Gate**: RR-05 (Official Ground-Truth Audit & Baseline Verification)  
**Repository**: `lasalle-notices-automation-cronjob`

---

## Executive Summary

This document records historical adapter-probe observations and an audit roadmap for the 10 held sources across the pipeline. It is not a comprehensive ground-truth assessment:
- **5 Paused Sources**: `canoas`, `dopa`, `fbds`, `finep`, `ibama`
- **5 Audit-Only Sources**: `funbio`, `tnc`, `govbr_mma_fnma`, `govbr_mma_public_calls`, `unep`

All 10 source adapters were used in live probes against their configured official endpoints on 2026-09-07. This roadmap records the resulting point-in-time reachability and adapter counts, contract requirements (`candidate` vs `opportunity`), proposed independent capture methodologies, and the preconditions necessary to achieve two clean independent audits prior to any catalog activation.

---

## 1. Paused Sources (5 Sources)

### 1.1 Canoas (`canoas`)
- **Lifecycle Mode**: `paused` (hold)
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group A (`pipeline-discovery-group-a.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Web Portal: `https://sistemas.canoas.rs.gov.br/domc`
  - REST API: `https://sistemas.canoas.rs.gov.br/domc/api/public`
  - Edition Search: `https://sistemas.canoas.rs.gov.br/domc/api/public/edicoes/busca`
  - Edition Download: `https://sistemas.canoas.rs.gov.br/domc/api/public/edicoes/download/<id>`
  - Municipal Bidding Portal: `https://www.canoas.rs.gov.br/licitacoes/`
- **Current Live Availability (2026-09-07)**:
  - Gazette API query across 3-day window (`days_requested: 3`) returned 1 publication entry (`records: 1`).
  - Pre-filter rejected 1 non-edital municipal decree (`policy_rejected: 1`).
  - Active open opportunities: `0` (`opportunities: 0`).
- **Hold Rationale**: Daily municipal official gazette (DOMC) contains municipal executive decrees and administrative acts requiring OCR text extraction; environmental calls are infrequent. Held in paused status pending structured opportunity contract stabilization.
- **Independent Ground-Truth Capture Methodology**:
  1. Make independent HTTP POST/GET requests to `https://sistemas.canoas.rs.gov.br/domc/api/public/edicoes/busca` covering the last 7 calendar days.
  2. Compute SHA-256 digest of each returned JSON page and downloaded gazette PDF.
  3. Search the gazette edition text for open public notices matching LaSalle keyword taxonomy (`meio ambiente`, `fundo municipal`, `chamamento publico`).
  4. If no open tenders exist, record an authoritative inventory of 0 open records, verifying zero-candidate/zero-blocker parity (`summary["total_blocking_exceptions"] == 0`).
  5. Repeat across two distinct temporal capture windows for Audit Slots 1 and 2.

---

### 1.2 Diário Oficial de Porto Alegre (`dopa`)
- **Lifecycle Mode**: `paused` (hold)
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group B (`pipeline-discovery-group-b.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Procempa API Gateway: `https://apigateway.procempa.com.br/apiman-gateway/administracao-planejamento/dopa/1.1`
  - Advanced Search: `https://apigateway.procempa.com.br/apiman-gateway/administracao-planejamento/dopa/1.1/api/diarios/busca-avancada`
  - Web Portal: `https://dopaonlineupload.procempa.com.br/`
- **Current Live Availability (2026-09-07)**:
  - Procempa gateway query returned 0 search hits for default search parameters (`records: 0`, `opportunities: 0`).
  - Active open opportunities: `0`.
- **Hold Rationale**: Procempa gateway pagination and authentication rate limits require specialized backoff and structured opportunity parsing.
- **Independent Ground-Truth Capture Methodology**:
  1. Direct HTTP POST to Procempa gateway endpoint `/api/diarios/busca-avancada` with query payload `{ "termo": "edital", "dataInicial": "<7_days_ago>", "dataFinal": "<today>" }`.
  2. Record response payload hash, edition numbers, and publication item IDs independently.
  3. Filter items by municipal environmental agencies (`SMAMUS`, `Fundo Municipal do Meio Ambiente`).
  4. Construct authoritative inventory JSON and compare against adapter discovery output via `audit_source_fidelity.py`.
  5. Validate two independent sessions (Slots 1 and 2).

---

### 1.3 Fundação Brasileira para o Desenvolvimento Sustentável (`fbds`)
- **Lifecycle Mode**: `paused` (hold)
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group C (`pipeline-discovery-group-c.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Configured Editais URL: `https://restaura-amazonia.fbds.org.br/Editais`
  - Institutional Homepage: `https://www.fbds.org.br/`
- **Current Live Availability (2026-09-07)**:
  - **CRITICAL FAILURE**: `https://restaura-amazonia.fbds.org.br/Editais` returned `DNS resolution failed: [Errno 11001] getaddrinfo failed`.
  - This records a local resolver failure only; authoritative NXDOMAIN,
    upstream outage and permanent decommissioning were not established.
  - Institutional portal `https://www.fbds.org.br` is responsive (HTTP 200, SPIP CMS), but does not currently expose an active public tenders/editais directory.
- **Hold Rationale**: Endpoint reachability is unresolved. Recheck the configured
  endpoint and independent DNS evidence before proposing an official replacement;
  this observation alone does not justify retirement or require a new endpoint.
- **Independent Ground-Truth Capture Methodology**:
  1. Monitor FBDS institutional announcements and identify if the Restaura Amazônia program has migrated to a new portal domain (or to BNDES/Fundo Amazônia).
  2. Once an active official URL is identified, capture the HTML listing independently, recording URL, HTTP headers, and SHA-256 digest.
  3. If no active portal exists, document the definitive unavailability in the audit report; `fbds` must remain paused and must NEVER be activated in this state.

---

### 1.4 FINEP - Financiadora de Estudos e Projetos (`finep`)
- **Lifecycle Mode**: `paused` (hold)
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group C (`pipeline-discovery-group-c.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Listing Portal: `https://www.finep.gov.br/chamadas-publicas/chamadaspublicas` (and `/o/c/chamadapublicas`)
  - Detail Pages: `https://www.finep.gov.br/chamada-publica/<id>`
- **Current Live Availability (2026-09-07)**:
  - Probed live: fetched 5 listing pages (`finep_pages_completed: [1, 2, 3, 4, 5]`), examined 100 records (`records: 100`).
  - Discovered **10 active open opportunities** (`opportunities: 10`, status: "Aberta"), hitting the per-run candidate cap (`candidate_cap_reached: 1`).
  - Open notices include:
    - *5ª Chamada Pública Conjunta - Finep e Conselho Norueguês de Pesquisa*
    - *BRICs - Chamada pública Cooperação Multilateral em Inovação*
    - *FIP Conexões Startups – 2026*
- **Hold Rationale**: Source produces rich structured opportunities across a large 24-page pagination catalog (`finep_last_page: 24`). Held in paused mode to prevent Action budget exhaustion until structured opportunity ingestion pipeline and pagination checkpoints are stabilized.
- **Independent Ground-Truth Capture Methodology**:
  1. Fetch `https://www.finep.gov.br/chamadas-publicas/chamadaspublicas` using an independent session.
  2. Parse the HTML table / article elements for calls with status badge "Aberta".
  3. For each active call, independently fetch its detail page to identify the edital PDF and application deadline.
  4. Construct authoritative inventory JSON (`source_key='finep'`, `source_record_id`, `canonical_url`, `title`, `status='open'`, `deadline`, `document_urls`).
  5. Run `discover_finep_opportunities.py` and verify zero blocking exceptions via `audit_source_fidelity.py`.
  6. Execute two separate runs for Slots 1 and 2.

---

### 1.5 IBAMA (`ibama`)
- **Lifecycle Mode**: `paused` (hold)
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group C (`pipeline-discovery-group-c.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Official Listing: `https://www.gov.br/ibama/pt-br/acesso-a-informacao/editais-e-convites/chamamentos-publicos/chamamentos-publicos`
  - Official RSS Feed: `https://www.gov.br/ibama/pt-br/acesso-a-informacao/editais-e-convites/chamamentos-publicos/RSS`
- **Current Live Availability (2026-09-07)**:
  - Probed live: fetched 3 listings and 2 RSS feeds (`records: 47`, `details_fetched: 9`).
  - Discovered **6 structured opportunities** (`opportunities: 6`), 41 policy-rejected (`policy_rejected: 41`).
  - Notices include:
    - *Orientações sobre o Edital de Chamamento Público nº 22/2026* (status: `open`)
    - *AGU prorroga edital de negociação para pequenos devedores do IBAMA* (status: `suspended`)
    - *Consulta pública sobre alterações nos formulários de Efluentes* (status: `closed`)
- **Hold Rationale**: IBAMA publishes public consultations, debt negotiations, and administrative notices alongside grant calls. Held in paused status pending validation of multi-document retifications merging and PNCP procurement disambiguation.
- **Independent Ground-Truth Capture Methodology**:
  1. Independently fetch official IBAMA RSS feed and Plone listing page.
  2. Extract items, parse publication dates, titles, and link references.
  3. Filter out administrative procurement (which belongs to PNCP) and closed notices.
  4. Build authoritative inventory JSON containing active chamamentos públicos.
  5. Run `audit_source_fidelity.py` against IBAMA discovery output.
  6. Execute across two independent sessions for Slots 1 and 2.

---

## 2. Audit-Only Sources (5 Sources)

### 2.1 FUNBIO - Fundo Brasileiro para a Biodiversidade (`funbio`)
- **Lifecycle Mode**: `audit`
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group B (`pipeline-discovery-group-b.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Listing Portal: `https://chamadas.funbio.org.br/`
  - News Leads: `https://chamadas.funbio.org.br/noticias`
- **Current Live Availability (2026-09-07)**:
  - Probed live: examined 5 records, discovered **5 open opportunities** (`opportunities: 5`, `errors: 0`).
  - Active notices:
    1. *Chamada de Projetos 07/2026 Apoio à Consolidação de RPPNs no Cerrado*
    2. *Chamada de Projetos 08/2026 - Uso público e negócios voltados à conservação*
    3. *Participe da 1ª Chamada do Projeto RAÍS - "Fortalecimento de Redes"*
    4. *Fortalecimento de Conselhos Gestores das UCs apoiadas pelo Programa Áreas Protegidas*
    5. *Seleção de Unidades de Conservação Costeiras e Marinhas Estaduais*
- **Hold Rationale**: Configured in `audit` mode to monitor notice stability and verify news-leads resolution without publishing unreviewed records.
- **Independent Ground-Truth Capture Methodology**:
  1. Make independent HTTP GET request to `https://chamadas.funbio.org.br/`.
  2. Parse the WordPress card grid for calls marked "Abertas".
  3. Extract detail URLs, submission deadlines, title, and PDF terms of reference.
  4. Construct `ground_truth_inventory.json` with 5 records (`status: "open"`).
  5. Run `discover_funbio_candidates.py` / `discover_opportunities()`.
  6. Verify 100% candidate traceability, 100% inventory accounting, and 0 blockers via `audit_source_fidelity.py`.
  7. Execute across two independent sessions for Slots 1 and 2.

---

### 2.2 The Nature Conservancy Brasil (`tnc`)
- **Lifecycle Mode**: `audit`
- **Submission Contract**: `opportunity`
- **Schedule Group**: Group B (`pipeline-discovery-group-b.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Communications / Notices: `https://www.tnc.org.br/conecte-se/comunicacao/noticias/`
  - Careers & Terms of Reference: `https://www.tnc.org.br/conecte-se/trabalhe-conosco/`
- **Current Live Availability (2026-09-07)**:
  - Probed live: fetched 48 blocks (`blocks: 48`), extracted **48 opportunities** (`opportunities: 48`, `malformed_blocks: 0`).
  - Notices comprise Terms of Reference (TDR), consultancy calls, and grant invitations.
- **Hold Rationale**: TDR and consultancy feeds have high churn and contain both employment and project tenders. Held in `audit` mode to verify classification fidelity between consulting contracts and institutional grants.
- **Independent Ground-Truth Capture Methodology**:
  1. Independently scrape `https://www.tnc.org.br/conecte-se/trabalhe-conosco/` and `/noticias/`.
  2. Parse each opportunity block: title, publication date, download URL for Termo de Referência (TDR) PDF.
  3. Construct authoritative inventory JSON.
  4. Compare with discovery output using `audit_source_fidelity.py`.
  5. Confirm zero blockers across two separate capture sessions.

---

### 2.3 MMA FNMA - Fundo Nacional do Meio Ambiente (`govbr_mma_fnma`)
- **Lifecycle Mode**: `audit`
- **Submission Contract**: `candidate`
- **Schedule Group**: Group A (`pipeline-discovery-group-a.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Official Portal: `https://www.gov.br/mma/pt-br/composicao/secex/dfre/fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1`
- **Current Live Availability (2026-09-07)**:
  - Probed live: fetched listing (`listings_fetched: 1`), discovered **1 active candidate** (`candidates: 1`, `errors: 0`).
  - Discovered notice: `https://www.gov.br/mma/pt-br/composicao/secex/dfre/fundo-nacional-do-meio-ambiente/editais-e-termos-de-referencia-1/edital-fnma-1-de-2026-iniciativa-arborizacidades.pdf` ("Edital FNMA nº 01/2026 - Iniciativa ArborizaCidades").
- **Hold Rationale**: Kept in `audit` mode to prevent duplicate submission with general `govbr_mma` adapter during catalog boundary evaluation.
- **Independent Ground-Truth Capture Methodology**:
  1. Independently fetch official FNMA editais listing page.
  2. Extract the active 2026 PDF URL and publication anchor text.
  3. Construct authoritative inventory JSON with 1 record (`edital-fnma-1-de-2026-iniciativa-arborizacidades.pdf`, `status: "open"`).
  4. Run `discover_govbr_mma_fnma_candidates.py`.
  5. Run `audit_source_fidelity.py` to achieve 100% accounting and 0 blockers.
  6. Record Slots 1 and 2.

---

### 2.4 MMA Chamamentos Públicos (`govbr_mma_public_calls`)
- **Lifecycle Mode**: `audit`
- **Submission Contract**: `candidate`
- **Schedule Group**: Group B (`pipeline-discovery-group-b.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Official Portal: `https://www.gov.br/mma/pt-br/acesso-a-informacao/participacao-social/3-5-editais-de-chamamento-publico/3-5-editais-de-chamamento-publico`
- **Current Live Availability (2026-09-07)**:
  - Probed live: fetched listing and details (`listings_fetched: 1`, `details_fetched: 1`).
  - Found 14 historical notices, all prior to 2026 (`year_rejected: 14`).
  - Active open candidates: **0** (`candidates: 0`).
- **Hold Rationale**: No open 2026 chamamentos públicos currently published on this specific Plone folder.
- **Independent Ground-Truth Capture Methodology**:
  1. Independently fetch the official gov.br chamamento publico page.
  2. Inspect all listed sub-anchors and verify that all referenced editais are historical (e.g. 2023–2024).
  3. Construct an authoritative inventory of 0 in-scope open notices.
  4. Compare with adapter discovery (which produces 0 candidates).
  5. Run `audit_source_fidelity.py` confirming a clean zero-candidate pass with 0 blockers.
  6. Execute across two independent sessions for Slots 1 and 2.

---

### 2.5 UNEP - United Nations Environment Programme (`unep`)
- **Lifecycle Mode**: `audit`
- **Submission Contract**: `candidate`
- **Schedule Group**: Group C (`pipeline-discovery-group-c.yml`, interval: 60m)
- **Official Portals / Endpoints**:
  - Official Call Portal: `https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding`
  - Document Repository: `https://wedocs.unep.org/`
- **Current Live Availability (2026-09-07)**:
  - Probed live: fetched call page (`listings_fetched: 1`), discovered **4 candidates** (`candidates: 4`, `errors: 0`).
  - Official guidelines and call documents:
    1. `GFC-Fund-Guidance-on-the-scope.pdf` (English)
    2. `GFC-Fund-Guidance-on-the-scope_FR.pdf` (French)
    3. `GFC-Fund-Guidance-on-the-scope_SP.pdf` (Spanish)
    4. `02_GFC_Fund_Concept_Note.pdf` (Concept Note template)
- **Hold Rationale**: Multi-language UN documentation without embedded calendar years in URL paths; held in `audit` mode to verify deduplication between translation variants and concept note templates.
- **Independent Ground-Truth Capture Methodology**:
  1. Fetch `https://www.unep.org/global-framework-chemicals/gfc-fund/applying-funding` independently.
  2. Parse all anchor links pointing to `wedocs.unep.org/bitstream/handle/`.
  3. Construct authoritative inventory JSON mapping the primary guidance document and language attachments.
  4. Run `discover_unep_candidates.py`.
  5. Compare via `audit_source_fidelity.py` ensuring zero blockers.
  6. Record Slots 1 and 2.

---

## 3. Summary Matrix & Audit Readiness

| Source Key | Mode | Contract | Live Active Items | Endpoint Reachability | Audit Feasibility | Primary Prerequisite |
|------------|------|----------|-------------------|-----------------------|-------------------|----------------------|
| **canoas** | paused | opportunity | 0 | OK (200) | **Ready** (zero-open) | Gazette parser validation |
| **dopa** | paused | opportunity | 0 | OK (200) | **Ready** (zero-open) | Procempa query filter verification |
| **fbds** | paused | opportunity | Unknown | Local resolution failure; authoritative DNS status unknown | **Blocked** | Verify reachability and official endpoint |
| **finep** | paused | opportunity | 10 | OK (200) | **Ready** | Manage pagination cap in runner |
| **ibama** | paused | opportunity | 6 | OK (200) | **Ready** | Disambiguate PNCP procurement |
| **funbio** | audit | opportunity | 5 | OK (200) | **Ready** | Baseline inventory creation |
| **tnc** | audit | opportunity | 48 | OK (200) | **Ready** | TDR vs Grant classification |
| **govbr_mma_fnma** | audit | candidate | 1 | OK (200) | **Ready** | Boundary review with govbr_mma |
| **govbr_mma_public_calls** | audit | candidate | 0 | OK (200) | **Ready** (zero-open) | Zero-open confirmation |
| **unep** | audit | candidate | 4 | OK (200) | **Ready** | Multilingual variant mapping |

---

## 4. Next Steps for Source Activation

Per project governance, two passing independent audits are **necessary but never sufficient** on their own for catalog activation. To promote any held source:
1. **Complete Two Clean Audits**: Independently enumerate the complete declared
   source scope, retaining exclusions and capture evidence, then compare against
   discovery across two reviewed capture cycles. The historical
   `run_independent_source_audit.py` selected known documents; running it twice
   with zero blockers is not sufficient evidence of an independent audit.
2. **Commit Evidence Artifacts**: Record `audits.md`, `snapshot.json`, and `checklist.md` under `docs/evidence/sources/<source_key>/`.
3. **Execute 48-Hour Staging Soak**: Verify at least 48 hours of scheduled continuous execution on hosted staging without unhandled exceptions.
4. **Authorized Lifecycle Transition**: Obtain operator signoff to transition `rollout_mode` from `paused`/`audit` to `ingest` in `config/source_schedule.json`.
