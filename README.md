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
| `pipeline-bndes-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (BNDES pilot, Phase 2) |
| `pipeline-brde-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (BRDE, Phase 3) |
| `pipeline-fapergs-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FAPERGS, Phase 3) |
| `pipeline-funbio-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FUNBIO, Phase 3) |
| `pipeline-iis-rio-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (IIS-Rio, Phase 3) |
| `pipeline-sema-rs-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (SEMA-RS, Phase 3) |
| `pipeline-tnc-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (TNC, Phase 3) |
| `pipeline-wwf-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (WWF, Phase 3) |
| `pipeline-unep-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (UNEP, Phase 3; Cloudflare bypass via browser User-Agent) |
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

The PNCP workflow fails if PNCP search fails and produces no candidates, if discovered candidates all fail download/OCR, or if no discovered candidate is submitted to Render, so the PNCP checkpoint is not advanced over unprocessed notices. The BNDE workflow mirrors the same shape but has no checkpoint to advance.

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
