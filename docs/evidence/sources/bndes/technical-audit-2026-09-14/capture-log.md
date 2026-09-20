# BNDES independent capture log (technical-audit-2026-09-14)

- Operator: MiMoCode subagent (Repo B worker audit). No credentials, cookies, or tokens stored.
- Method: direct webfetch of official BNDES public pages only (NOT via scripts/discover_bndes_candidates.py).
- Capture window (UTC, approximate from session): 2026-09-14 ~20:50Z–21:15Z (first pass); ~21:20Z–21:45Z (re-verification pass).
- Page-local render timestamps observed: "Renderizado em 9/14/26 4:56 PM" (first pass Corais / inovação); "Renderizado em 9/14/26 5:07 PM" (second pass Corais / inovação).

## Pages fetched

| # | Requested URL | Final/resolved page title | HTTP (tool success) | Content type | Notes |
|---|---------------|---------------------------|---------------------|--------------|-------|
| 1 | https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental | BNDES Fundo Socioambiental | success (HTML 200-class) | text/html | Primary adapter listing #1. Lifecycle text still names 5º Ciclo Periferias Mulheres + Corais as open (stale vs detail pages). Re-verified second pass. |
| 2 | https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao | Chamadas públicas para contratação de inovação | success | text/html | Primary adapter listing #2. Canonical path under licitacoes-contratos/licitacoes/chamadas-publicas-inovacao2. Re-verified second pass. |
| 3 | https://www.bndes.gov.br/wps/portal/site/home/onde-atuamos/social/bndes-periferias | BNDES Periferias | success | text/html | Open 6º ciclo deadline 04.12.2026 17h; 5º ciclo closed 12.03.2026. Re-verified second pass. |
| 4 | https://www.bndes.gov.br/wps/portal/site/home/onde-atuamos/meio-ambiente/bndes-azul/bndes-corais | BNDES Corais | success | text/html | Chamada encerrada 05/07/2024. Re-verified second pass (render 5:07 PM). |
| 5 | https://www.bndes.gov.br/wps/portal/site/home/onde-atuamos/social/bndes-bioinsumos | BNDES Bioinsumos | success | text/html | Segundo ciclo encerrado. Re-verified second pass. |
| 6 | https://www.bndes.gov.br/wps/portal/site/home/onde-atuamos/social/sertao-mais-produtivo | Sertão + Produtivo | success | text/html | Resultado final divulgado 02/06/2025. Re-verified second pass. |
| 7 | https://www.bndes.gov.br/wps/portal/site/home/onde-atuamos/social/bndes-periferias-fortes | BNDES Periferias Fortes | success | text/html | Fase classificatória final divulgada; BNDES-hosted editais closed; OSP registration via external partner sites only. Re-verified second pass. |

No pagination caps were hit (single-page listings). No retries beyond tool defaults. No Repo A endpoints called.

## Independent inventory summary (re-verified second pass)

- open: 4 (Periferias 6º ciclo; CPSI 001/2026; CPSI 003/2025; CPSI 002/2025)
- closed: 6 (Periferias 5º ciclo; Corais; Bioinsumos 2º; Sertão + Produtivo; Periferias Fortes; CPSI 01/2024)
- upcoming: 0
- excluded (explicit disposition reason_code): 0
- unknown: 0

Second-pass live re-fetch confirmed no lifecycle changes since the first capture earlier today. Counts and statuses identical.

## Principal documents observed (href extraction from HTML)

- Periferias 6º: Roteiro+BNDES+Periferias+em+Rede_6º+ciclo.pdf
- Corais: Modelo+Roteiro+MA_Corais_Web.pdf
- Bioinsumos: Roteiro_Projetos_Bioinsumos_2ºCiclo+05-05+vf.pdf
- CPSI entries: external worldlabs.org opportunity URLs only (no bndes.gov.br PDF anchors on the listing page)
- Sertão / Periferias Fortes: no BNDES-hosted open-call principal PDFs

## Adapter contract notes (from source code read, not live run)

- Module: scripts/discover_bndes_candidates.py
- Official entry points: BNDES_LISTING_URLS (fundo socioambiental + vanity chamadadeinovacao)
- Host filter: bndes.gov.br only; year guard BNDES_MIN_NOTICE_YEAR default 2026; is_likely_edital default filter_policy
- Caps: BNDES_MAX_CANDIDATES_PER_RUN=50, BNDES_MAX_DETAILS_PER_RUN=20
- Registry: contract=candidate, group=a, rollout_mode=ingest, interval 60min, detail_limit=20, page_limit=5, attachment_limit=25; catalog_status=active

## Limitations (failures, not passes)

1. Shell/bash STILL hard-denied in the re-verification session (permission rule: `{permission:bash, action:ask, pattern:*}` → auto-denied for subagent after multiple retries including interactive:true). Could NOT run pytest, discover_all_candidates.py, or audit_source_fidelity.py. Audit remains incomplete for adapter-execution evidence.
2. Adapter inventory/discovery comparison not performed this session (requires shell).
3. Document hashes not computed (no local HTTP client without shell).
4. Fundo listing lifecycle text conflicts with detail pages for Corais/5º ciclo; independent inventory prefers detail-page quotes (unchanged finding).
5. scripts/run_independent_source_audit.py was not used and is not independent evidence (per AGENTS.md).
