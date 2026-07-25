# Lasalle Notices Automation Cronjob

GitHub Actions workflows that discover, download, OCR, and submit PNCP public procurement notices to a Render backend for AI processing and serving.

## Architecture

The pipeline is split between GitHub Actions (discovery, download, OCR, submission) and Render (AI processing, persistence, serving, Drive sync).

### GitHub Actions responsibilities

- **Discover** active PNCP procurement records (modalities 6/8/4) via `/publicacao`, `/proposta`, and `/atualizacao` endpoints
- **Filter** notices explicitly to `anoCompra >= 2026` before download/OCR/submission
- **Download** each candidate PDF once with bounded HTTP (SSRF protection, size limits, retry)
- **Validate** PDFs via magic-byte and structure checks
- **OCR** extracted PDFs to markdown using PaddleOCR
- **Submit** candidates with metadata, markdown, and content hash to Render `/api/pipeline/candidates`
- **Submit** stable API/web opportunities, including zero-document and non-renderable-attachment records, to Render `/api/pipeline/opportunities`

### Render responsibilities

- Trust and persist authenticated submissions
- Run AI processing (model-only inference on submitted markdown)
- Serve direct URLs for processed notices
- Sync Drive for opted-in users

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pipeline-pncp-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (PNCP) |
| `pipeline-pncp-backfill.yml` | Manual only | Claims active pending PNCP candidates from Render, downloads/OCRs them in Actions, and submits worker results back to Render |
| `pipeline-bndes-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (BNDES pilot, Phase 2) |
| `pipeline-brde-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (BRDE, Phase 3) |
| `pipeline-fapergs-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FAPERGS, Phase 3) |
| `pipeline-funbio-discovery.yml` | Hourly cron + manual | Legacy FUNBIO candidate route; submission steps run only while `funbio` is absent from `OPPORTUNITY_SOURCES` |
| `pipeline-iis-rio-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (IIS-Rio, Phase 3) |
| `pipeline-sema-rs-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (SEMA-RS, Phase 3) |
| `pipeline-tnc-discovery.yml` | Hourly cron + manual | Legacy TNC candidate route; submission steps run only while `tnc` is absent from `OPPORTUNITY_SOURCES` |
| `pipeline-wwf-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (WWF, Phase 3) |
| `pipeline-unep-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (UNEP, Phase 3; Cloudflare bypass via browser User-Agent) |
| `pipeline-govbr-mma-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (GOVBR-MMA, Phase 3) |
| `pipeline-worldbank-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (WorldBank, Phase 3; BS4 primary + Playwright fallback) |
| `pipeline-fao-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FAO, Phase 4; Playwright-based listing) |
| `pipeline-kfw-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (KfW, Phase 4; Playwright-based listing) |
| `pipeline-fundacao-grupo-boticario-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (Fundação Grupo Boticário, Phase 4; Playwright-based listing) |
| `pipeline-msgov-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (MSGOV, Phase 4; pure-Playwright with shadow-DOM probing; magic-byte check rejects `.doc` annex leakage at download time) |
| `pipeline-all-discovery.yml` | Hourly cron + manual | Unified non-PNCP orchestrator. Scheduled FUNBIO/TNC routes are included only when their keys are in `OPPORTUNITY_SOURCES`; manual audits may select them without enabling submission. |
| `pipeline-ai.yml` | After PNCP discovery + hourly cron | Trigger Render AI processing (daytime Pacific gate) |
| `pipeline-ingest.yml` | Manual only | Legacy Render ingest (rollback) |
| `pipeline-ocr.yml` | Manual only | Legacy Render OCR worker (backfill) |
| `pipeline-scrape.yml` | Manual only | Legacy Render scrape (rollback) |
| `pipeline-run.yml` | Manual only | Legacy full pipeline run (rollback) |

## Secrets

- `RENDER_APP_URL` — Render service base URL
- `PIPELINE_SECRET` — Bearer token for Render API authentication

## Important runtime settings

- `PNCP_MIN_NOTICE_YEAR=2026` — do not process notices before 2026 (PNCP discoverer)
- `BNDES_MIN_NOTICE_YEAR=2026` — per-source year guard for the BNDE discoverer (the unified orchestrator-level `MIN_NOTICE_YEAR` lands in Phase 5; until then each non-PNCP discoverer carries its own `*_MIN_NOTICE_YEAR` knob)
- `BRDE_MIN_NOTICE_YEAR=2026` — per-source year guard for the BRDE discoverer
- `FAPERGS_MIN_NOTICE_YEAR=2026` — per-source year guard for the FAPERGS discoverer
- `FUNBIO_MIN_NOTICE_YEAR=2026` — per-source year guard for the FUNBIO discoverer
- `IIS_RIO_MIN_NOTICE_YEAR=2026` — per-source year guard for the IIS-Rio discoverer
- `SEMA_RS_MIN_NOTICE_YEAR=2026` — per-source year guard for the SEMA-RS discoverer
- `TNC_MIN_NOTICE_YEAR=2026` — per-source year guard for the TNC discoverer
- `WWF_MIN_NOTICE_YEAR=2026` — per-source year guard for the WWF discoverer
- `UNEP_MIN_NOTICE_YEAR=2026` — per-source year guard for the UNEP discoverer
- `GOVBR_MMA_MIN_NOTICE_YEAR=2026` — per-source year guard for the GOVBR-MMA discoverer
- `WORLDBANK_MIN_NOTICE_YEAR=2026` — per-source year guard for the WorldBank discoverer
- `FAO_MAX_CANDIDATES_PER_RUN=50` — same cap on the FAO discoverer
- `KFW_MAX_CANDIDATES_PER_RUN=50` — same cap on the KfW discoverer
- `FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN=50` — same cap on the Fundação Grupo Boticário discoverer
- `FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per Fundação Grupo Boticário run
- `MSGOV_MAX_CANDIDATES_PER_RUN=50` — same cap on the MSGOV discoverer
- `MSGOV_MAX_DETAILS_PER_RUN=40` — bound the number of detail-page navigations per MSGOV run (Playwright is the primary path, so detail fetching is more expensive)
- `PNCP_MAX_CANDIDATES_PER_RUN=50` — keep a larger discovery pool so a few invalid PDFs do not starve valid notices
- `BNDES_MAX_CANDIDATES_PER_RUN=50` — same cap on the BNDE discoverer
- `BRDE_MAX_CANDIDATES_PER_RUN=50` — same cap on the BRDE discoverer
- `BRDE_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per BRDE run
- `FAPERGS_MAX_CANDIDATES_PER_RUN=50` — same cap on the FAPERGS discoverer
- `FAPERGS_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per FAPERGS run
- `FUNBIO_MAX_CANDIDATES_PER_RUN=50` — same cap on the FUNBIO discoverer
- `FUNBIO_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per FUNBIO run
- `IIS_RIO_MAX_CANDIDATES_PER_RUN=50` — same cap on the IIS-Rio discoverer
- `IIS_RIO_MAX_DETAILS_PER_RUN=30` — bound the number of detail-page fetches per IIS-Rio run
- `SEMA_RS_MAX_CANDIDATES_PER_RUN=50` — same cap on the SEMA-RS discoverer
- `SEMA_RS_MAX_DETAILS_PER_RUN=40` — bound the number of detail-page fetches per SEMA-RS run
- `TNC_MAX_CANDIDATES_PER_RUN=50` — same cap on the TNC discoverer
- `TNC_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per TNC run
- `WWF_MAX_CANDIDATES_PER_RUN=50` — same cap on the WWF discoverer
- `WWF_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per WWF run
- `UNEP_MAX_CANDIDATES_PER_RUN=50` — same cap on the UNEP discoverer
- `GOVBR_MMA_MAX_CANDIDATES_PER_RUN=50` — same cap on the GOVBR-MMA discoverer
- `GOVBR_MMA_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per GOVBR-MMA run
- `GOVBR_MMA_PUBLIC_CALLS_MIN_NOTICE_YEAR=2026` — per-source year guard for the GOVBR-MMA public-calls (participation-social) discoverer (Plan 03)
- `GOVBR_MMA_PUBLIC_CALLS_MAX_CANDIDATES_PER_RUN=50` — same cap on the GOVBR-MMA public-calls discoverer
- `GOVBR_MMA_PUBLIC_CALLS_MAX_DETAILS_PER_RUN=20` — bound the number of detail-page fetches per GOVBR-MMA public-calls run
- `GOVBR_MMA_FNMA_MIN_NOTICE_YEAR=2026` — per-source year guard for the GOVBR-MMA FNMA discoverer (Plan 03)
- `GOVBR_MMA_FNMA_MAX_CANDIDATES_PER_RUN=50` — same cap on the GOVBR-MMA FNMA discoverer
- `GOVBR_MMA_FNMA_INCLUDE_TDR=0` — source-specific opt-in (set `1`) to surface FNMA terms-of-reference (`termo de referencia`) as principal candidates. Default `0` keeps TDR as RELATED metadata and does NOT change the global `FILTER_POLICY` default.
- `WORLDBANK_MAX_CANDIDATES_PER_RUN=50` — same cap on the WorldBank discoverer
- `PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN=20` — bound download/OCR attempts per Actions run
- `PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN=5` — stop once enough valid candidates are ready to submit incrementally
- `PNCP_FETCH_MAX_ATTEMPTS=3` — retry transient PNCP connection timeouts before marking a search/document lookup failed
- `PNCP_OPPORTUNITY_V2_ENABLED=false` — opt into one PNCP parent per control number; the manual workflow exposes this separately from the legacy path
- `PNCP_OPPORTUNITY_V2_SHADOW=true` — write the normalized PNCP inventory artifact without production submission
- `FINEP_MAX_OPPORTUNITIES_PER_RUN=10` — bound structured FINEP API submissions
- `FBDS_MAX_DETAILS_PER_RUN=20` — bound Restaura Amazônia detail parsing and ZIP inspection
- `FUNBIO_NEWS_ENABLED=false` — enable bounded news resolution; unresolved articles remain artifacts and are never submitted
- `FUNBIO_NEWS_LOOKBACK_DAYS=45` / `FUNBIO_NEWS_MAX_DETAILS=20` — bound news inventory work
- `OPPORTUNITY_ATTACHMENT_MAX_BYTES=15000000` — compressed-size limit for non-PDF attachments
- `SCRAPE_MAX_PDF_BYTES=15000000` — reject candidate PDFs larger than this many bytes during download
- `SCRAPE_MAX_PDFS_PER_RUN=5` — generic per-run cap on successful PDF downloads/OCR completions (used by `pipeline_core.pdf_download_limit_reached`)
- `RENDER_SUBMIT_BATCH_SIZE=30` — candidates per Render `/api/pipeline/candidates` POST batch
- `RENDER_SUBMIT_TIMEOUT=90` — per-batch HTTP timeout in seconds
- `RENDER_SUBMIT_MAX_ATTEMPTS=4` — retry budget for transient Render submit failures (5xx, 408, 425, 429)
- `RENDER_SUBMIT_BACKOFF_BASE=5` — exponential backoff base seconds between Render submit retries
- `RENDER_SUBMIT_MAX_MARKDOWN_CHARS=1000000` — truncate OCR markdown longer than this before submitting to Render
- `FLAGS_use_mkldnn=0` — disables Paddle oneDNN on CPU runners; required to avoid the current PaddleOCR runtime failure seen in GitHub Actions
- `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0` — disables PaddleX's default oneDNN path used by PaddleOCR
- `SOURCES` (unified orchestrator only) — comma-separated source names; whitespace is tolerated and duplicates are removed. Valid structured sources include `finep`, `fbds`, `funbio`, and `tnc`, in addition to the legacy PDF source keys. PNCP remains in its dedicated workflow.
- `DISCOVERY_AUDIT_ONLY=true` — performs discovery and writes fidelity artifacts without OCR or Render submission; manual all-sources runs default to this safe mode.
- `OPPORTUNITY_SOURCES` — normalized lowercase comma-separated sources allowed to use the structured opportunity endpoint. Scheduled runs default to the legacy candidate path until a source passes its rollout gates. For FUNBIO/TNC this is also the single production-route switch: adding a key moves it from its dedicated legacy workflow to the unified structured workflow; removing it restores the legacy route.
- `DISCOVERY_AUDIT_DIR` — when set, every structured source writes an authoritative `source_inventory.json` independently from accepted `discovery.json` records, plus `opportunities.json`, `policy_rejections.json`, `parser_failures.json`, `audit_manifest.json`, and `stats.json`. Structured audit verification fails closed on parser failures or an incomplete contract.
- `MIN_NOTICE_YEAR` (Phase 5 unified orchestrator only, default `2026`) — generic year guard forwarded to BS4 discoverers as their `min_year` argument. Plan §9 recommends a generic name (not `PNCP_MIN_NOTICE_YEAR`) so the unified orchestrator does not couple non-PNCP sources to PNCP-specific env vars. Playwright sources (`fao`, `fundacao_grupo_boticario`, `kfw`, `msgov`) do not accept `min_year` and run with their own internal filtering.
- `FILTER_POLICY` (Phase 5 unified orchestrator only, default `default`) — EDITAL inclusion/exclusion policy forwarded to BS4 discoverers (`default` | `include_tdr` | `no_prefilter`). Ignored by Playwright sources.

### PNCP pending candidate backfill

`pipeline-pncp-backfill.yml` is a manual integration workflow for draining the active PNCP backlog in `scrape_candidates`. It calls the Render claim endpoint for active pending PNCP candidates, reuses the same download/OCR worker path as PNCP discovery, and submits successful worker results to `/api/pipeline/candidates`.

Use conservative inputs until the post-deploy testing gate passes:

- `claim_limit=1`
- `process_limit=1`

After Render is confirmed healthy and the first manual run moves an active candidate into `editais`, the limits can be increased gradually. Do not schedule this workflow until the active backlog behavior is verified in production.

The PNCP workflow fails if PNCP search fails and produces no candidates, if discovered candidates all fail download/OCR, or if no discovered candidate is submitted to Render, so the PNCP checkpoint is not advanced over unprocessed notices. The BNDE workflow mirrors the same shape but has no checkpoint to advance.

### PNCP keeps its own workflow (Phase 5 decision)

The Phase 5 plan recommends **keeping** `pipeline-pncp-discovery.yml` separate from the new `pipeline-all-discovery.yml` orchestrator rather than folding PNCP into it. Reasoning (plan §5):

- PNCP has hard-won guardrails (`PNCP_MIN_NOTICE_YEAR`, `PNCP_MAX_CANDIDATES_PER_RUN`, modality filtering, document-type priorities, the `/atualizacao` checkpoint) that are not directly applicable to other sources.
- The unified orchestrator uses the generic `MIN_NOTICE_YEAR` / `FILTER_POLICY` / `SOURCES` env vars; binding PNCP to those would couple its knobs to the new generic ones prematurely.
- The PNCP discoverer also has a different return shape (``(stats, candidates, checkpoint)`` vs ``(stats, candidates)``), which would require either forcing it into the new shape or special-casing it.

Operators who want to discover non-PNCP sources in a single Actions run should use `pipeline-all-discovery.yml`. PNCP continues to run via `pipeline-pncp-discovery.yml` unchanged. Folding PNCP in is tracked as a follow-up PR after the unified orchestrator stabilises.

### WWF discovery precision (Plan 02)

`discover_wwf_candidates.py` discovers WWF editais by structurally parsing the `EDITAIS ABERTOS` (status `open`) and `EDITAIS ENCERRADOS` (status `closed`) sections of the acquisitions page, following only those rows' detail URLs, and extracting record-owned PDF or DOCX attachments from the record content area. DOCX-only rows are emitted through `discover_opportunities()` as non-renderable structured opportunities; the legacy candidate path remains PDF-only. Generic supplier documents (`documentos-necessarios`, `requisitos-basicos`, proposal-model, and supplier-portal) are rejected; record-bound divulgação, retification, and annex PDFs are retained. A missing section, zero parsed rows, or missing detail content selector is reported as a failure rather than a healthy zero-result run.

If the acquisitions listing returns HTTP 403, the discoverer falls back only to the two official WWF section feeds linked by that page, then rebuilds public WWF detail URLs from their content IDs. It does not use a proxy or an unofficial mirror.

Run a live no-submit audit and write Plan-01-compatible inputs with:

```bash
python scripts/discover_wwf_candidates.py --audit-dir artifacts/wwf
```

This writes `source_inventory.json`, normalized `discovery.json`, structured `opportunities.json`, raw `candidates.json`, and `stats.json`. The manual WWF workflow runs in audit-only mode by default on GitHub's macOS runner pool, enforces the fidelity comparator, and uploads this directory as an artifact. The scheduled production job remains on Ubuntu.

### MMA public-calls and FNMA discovery (Plan 03)

`discover_govbr_mma_public_calls_candidates.py` and `discover_govbr_mma_fnma_candidates.py` add two SEPARATE MMA feeds without touching the existing `govbr_mma` procurement discoverer:

- `govbr_mma_public_calls` — the participation-social public-call (chamamento) index.
- `govbr_mma_fnma` — the FNMA editais / terms-of-reference page.

Both parse only the gov.br editorial body (`#content-core #parent-fieldname-text`, legacy `#content-core`, or the current `#content` cover body), associate heading/callout year markers with following edital links, and emit a Plan-01-compatible inventory for deterministic fidelity checks. `resultado` / `retificacao` / `errata` / historical / annex PDFs are treated as RELATED metadata of the parent opportunity using accent-normalized anchor text and filenames. The principal edital PDF is the candidate. Explicit publication/status/deadline text is preserved; otherwise status remains `unknown`.

The FNMA feed accepts an opt-in `GOVBR_MMA_FNMA_INCLUDE_TDR=1` to surface terms-of-reference as principal candidates; this is a SOURCE-SPECIFIC switch that does NOT mutate the global `FILTER_POLICY` default.

Enable `govbr_mma_public_calls` first, then `govbr_mma_fnma` (do not enable both in the same first production run). Every candidate carries `metadata.source_record_id` + `metadata.detail_url` (where applicable) and traces to an inventory record.

Run each source without OCR/submission and produce fidelity inputs with:

```bash
python scripts/discover_govbr_mma_public_calls_candidates.py --audit-dir artifacts/mma-public
python scripts/discover_govbr_mma_fnma_candidates.py --audit-dir artifacts/mma-fnma
```

Each command writes `source_inventory.json`, normalized `discovery.json`, raw `candidates.json`, and `stats.json`. A detail/news lead that currently exposes no principal PDF is retained as `unresolved_news_lead`, not silently discarded or submitted.

## Local development

```bash
# Install OCR worker dependencies
pip install -r requirements-ocr-worker.txt

# Run tests
python -m pytest -v

# Run discovery locally (requires env vars)
RENDER_APP_URL=https://your-render.onrender.com PIPELINE_SECRET=token python scripts/discover_pncp_candidates.py
```

## Source-fidelity audits

`scripts/audit_source_fidelity.py` produces a deterministic, offline (no LLM/network) report comparing the authoritative source inventory, discovery candidates, and an optional dashboard export. It classifies each disagreement as a blocking or non-blocking exception and writes `summary.json`, `matches.json`, `exceptions.json`, and `report.md`. Inventory accounting is scoped to open, in-scope records, so a source can retain closed rows for provenance without falsely reporting them as missing current submissions.

```bash
python scripts/audit_source_fidelity.py \
  --source-inventory tests/fixtures/audit/source_inventory.json \
  --discovery tests/fixtures/audit/discovery.json \
  --dashboard tests/fixtures/audit/dashboard.json \
  --out ./report
```

Exit codes: `0` = no blocking exceptions, `1` = fidelity failures, `2` = invalid input/config. The matching ladder is, in descending authority: `(source_key, source_record_id)`, canonical URL (fragment removed, query params preserved), exact document SHA-256, then exact normalized document URL. Title similarity never establishes identity. See `plans/opportunity-sources/01-deterministic-source-fidelity.md` for the full contract and the quantitative success gates.

Input files must contain arrays of record objects. `document_urls` and `document_hashes` are arrays of strings; hashes are 64-character SHA-256 hex digests. A record explicitly rejected by policy may set `reason_code` to `out_of_scope`; an unsubmitted unresolved announcement may use `unresolved_news_lead`. Include an `evidence` object for either disposition. A record with `renderable: true` must also include `content_type_validated: true` and `hash_validated: true`.

## Structured opportunity sources

The unified orchestrator detects `discover_opportunities()` modules and uses
the stable opportunity endpoint instead of the legacy PDF-only endpoint:

- `finep` consumes the paginated official `/o/c/chamadapublicas` JSON API, keys records by API `id`, excludes site-wide manuals/tutorials, and accepts complete records without a PDF.
- `fbds` parses only the Restaura Amazônia edital portal. ZIPs remain official, non-renderable attachments; archive members are inspected and OCRed in memory with path, encryption, nesting, member-count, size, ratio, symlink, and PDF-magic guards.
- `tnc` parses only the consultancy/service section of `trabalhe-conosco`, uses `NOVO PRAZO` over `PRAZO`, classifies every record as `consultancy`, and reports malformed blocks instead of traversing general news.
- `funbio` keeps the calls portal as canonical. News resolution uses exact call URLs/slugs only; canonical fields win, institutional news is ignored, and unresolved likely calls are artifact-only.

Structured sources remain outside the scheduled default until two consecutive
live fidelity reports pass. Run a manual audit in
`pipeline-all-discovery.yml`, then compare each source's inventory and
discovery files with `audit_source_fidelity.py`. The audit step receives no
Render secrets and the orchestrator skips OCR and every submission call.

For FUNBIO and TNC, `OPPORTUNITY_SOURCES` is the cutover switch. With a key
absent, only its dedicated legacy workflow can submit it and the scheduled
unified route excludes it. Adding a key disables the dedicated submission
steps and schedules that source through the structured opportunity route.
Removing the key reverses both decisions. Manual submission through the
unified workflow is rejected for either source unless its structured route is
already approved in the repository variable.

## PNCP v2 reconciliation

Set `PNCP_OPPORTUNITY_V2_ENABLED=true` and keep
`PNCP_OPPORTUNITY_V2_SHADOW=true` for artifact-only parent/document discovery.
Only after two passing shadow comparisons should a reviewed backend
reconciliation be applied. The backend command is:

```bash
python scripts/reconcile_pncp_opportunities.py --mode rehearsal --report pncp-plan.json
python scripts/reconcile_pncp_opportunities.py --mode apply --reviewed-report pncp-plan.reviewed.json --report pncp-applied.json
```

Apply mode requires the exact current `plan_hash` with `reviewed: true` and
aborts when one user has distinct uploaded Drive files on rows that would be
merged.

## Documentation

- [Operations guide](docs/OPERATIONS.md) — runbooks, monitoring, rollback procedures
