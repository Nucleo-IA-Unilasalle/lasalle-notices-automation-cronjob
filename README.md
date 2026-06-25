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
| `pipeline-funbio-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FUNBIO, Phase 3) |
| `pipeline-iis-rio-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (IIS-Rio, Phase 3) |
| `pipeline-sema-rs-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (SEMA-RS, Phase 3) |
| `pipeline-tnc-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (TNC, Phase 3) |
| `pipeline-wwf-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (WWF, Phase 3) |
| `pipeline-unep-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (UNEP, Phase 3; Cloudflare bypass via browser User-Agent) |
| `pipeline-govbr-mma-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (GOVBR-MMA, Phase 3) |
| `pipeline-worldbank-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (WorldBank, Phase 3; BS4 primary + Playwright fallback) |
| `pipeline-fao-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FAO, Phase 4; Playwright-based listing) |
| `pipeline-kfw-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (KfW, Phase 4; Playwright-based listing) |
| `pipeline-fundacao-grupo-boticario-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (Fundação Grupo Boticário, Phase 4; Playwright-based listing) |
| `pipeline-msgov-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (MSGOV, Phase 4; pure-Playwright with shadow-DOM probing; magic-byte check rejects `.doc` annex leakage at download time) |
| `pipeline-all-discovery.yml` | Hourly cron + manual | Unified orchestrator over the non-PNCP sources (Phase 5); reads `SOURCES` from the workflow_dispatch input (default: BNDE, BRDE, FAPERGS, FUNBIO, IIS-Rio, SEMA-RS, TNC, WWF — all BS4) |
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
- `WORLDBANK_MAX_CANDIDATES_PER_RUN=50` — same cap on the WorldBank discoverer
- `PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN=20` — bound download/OCR attempts per Actions run
- `PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN=5` — stop once enough valid candidates are ready to submit incrementally
- `PNCP_FETCH_MAX_ATTEMPTS=3` — retry transient PNCP connection timeouts before marking a search/document lookup failed
- `SCRAPE_MAX_PDF_BYTES=15000000` — reject candidate PDFs larger than this many bytes during download
- `SCRAPE_MAX_PDFS_PER_RUN=5` — generic per-run cap on successful PDF downloads/OCR completions (used by `pipeline_core.pdf_download_limit_reached`)
- `RENDER_SUBMIT_BATCH_SIZE=30` — candidates per Render `/api/pipeline/candidates` POST batch
- `RENDER_SUBMIT_TIMEOUT=90` — per-batch HTTP timeout in seconds
- `RENDER_SUBMIT_MAX_ATTEMPTS=4` — retry budget for transient Render submit failures (5xx, 408, 425, 429)
- `RENDER_SUBMIT_BACKOFF_BASE=5` — exponential backoff base seconds between Render submit retries
- `RENDER_SUBMIT_MAX_MARKDOWN_CHARS=1000000` — truncate OCR markdown longer than this before submitting to Render
- `FLAGS_use_mkldnn=0` — disables Paddle oneDNN on CPU runners; required to avoid the current PaddleOCR runtime failure seen in GitHub Actions
- `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0` — disables PaddleX's default oneDNN path used by PaddleOCR
- `SOURCES` (Phase 5 unified orchestrator only) — comma-separated list of source names to run (e.g. `SOURCES=bndes,brde,wwf`); whitespace is tolerated and empty entries are dropped. Valid sources: `bndes`, `brde`, `fapergs`, `funbio`, `govbr_mma`, `iis_rio`, `sema_rs`, `tnc`, `unep`, `worldbank`, `wwf`, `fao`, `fundacao_grupo_boticario`, `kfw`, `msgov`. PNCP is intentionally not in this list (see plan §5 / "PNCP keeps its own workflow" below).
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

## Local development

```bash
# Install OCR worker dependencies
pip install -r requirements-ocr-worker.txt

# Run tests
python -m pytest -v

# Run discovery locally (requires env vars)
RENDER_APP_URL=https://your-render.onrender.com PIPELINE_SECRET=token python scripts/discover_pncp_candidates.py
```

## Documentation

- [Operations guide](docs/OPERATIONS.md) — runbooks, monitoring, rollback procedures
