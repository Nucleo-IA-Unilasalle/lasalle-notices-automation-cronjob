# Operations Guide

## Pipeline overview

The combined PNCP pipeline runs hourly via `pipeline-pncp-discovery.yml`:

1. **Discover** — queries PNCP API for active procurement records across modalities 6 (Pregão Eletrônico), 8 (Dispensa de Licitação), and 4 (Concorrência Eletrônica)
2. **Filter** - keeps only notices with `anoCompra >= 2026`
3. **Download** - fetches each candidate PDF with bounded HTTP, SSRF protection, and retry
4. **Validate** - confirms PDF magic bytes and structure
5. **OCR** - extracts text to markdown using PaddleOCR (latin language, tiny model tier)
6. **Submit** - sends candidates with metadata, markdown, and content hash to Render `/api/pipeline/candidates`

The workflow fails instead of advancing the PNCP checkpoint when PNCP search fails and produces no candidates, when eligible candidates are discovered but all fail download/OCR, or when none are submitted to Render.

After successful discovery, Render AI processing is triggered via `pipeline-ai.yml` (with daytime Pacific gate).

## Schedule

| Workflow | Schedule | Notes |
|----------|----------|-------|
| PNCP discovery | `05 * * * *` (hourly at :05) | Combined pipeline |
| AI processing | `15 * * * *` (hourly at :15) + after PNCP discovery | Pacific daytime gate (08:00–19:00) |

## Monitoring

### GitHub Actions

- Check workflow run status in the Actions tab
- Key metrics logged: discovery stats, candidates found, OCR successes/failures, submission results
- Cache file `.cache/pncp-last-successful-update.json` tracks the update checkpoint

### Render

- Monitor `/api/pipeline/candidates` endpoint health
- Check AI processing logs for model inference outcomes
- Verify direct URL serving for processed notices

## Cache and checkpoint

The PNCP update checkpoint (`.cache/pncp-last-successful-update.json`) is cached between runs using GitHub Actions cache with key pattern `pncp-update-checkpoint-${{ runner.os }}-*`. This ensures the `/atualizacao` endpoint queries only new or updated records since the last successful run.

## Rollback procedures

### Rollback to legacy Render pipeline

If the combined GitHub Actions pipeline fails:

1. **Ingest**: Trigger `pipeline-ingest.yml` manually (workflow_dispatch) to run Render-side download
2. **OCR**: Trigger `pipeline-ocr.yml` manually to run Render-side OCR worker
3. **Scrape**: Trigger `pipeline-scrape.yml` manually for legacy scrape path
4. **Full run**: Trigger `pipeline-run.yml` manually for complete Render pipeline

### Disable combined pipeline

To pause the hourly combined pipeline:

1. Disable the `pipeline-pncp-discovery.yml` schedule in GitHub Actions
2. Manually trigger legacy workflows as needed

## Environment variables

### GitHub Actions (PNCP discovery)

| Variable | Default | Description |
|----------|---------|-------------|
| `RENDER_APP_URL` | (required) | Render service base URL |
| `PIPELINE_SECRET` | (required) | Bearer token for Render API |
| `PNCP_UPDATE_CHECKPOINT_PATH` | `.cache/pncp-last-successful-update.json` | Checkpoint file path |
| `PNCP_MIN_NOTICE_YEAR` | `2026` | Earliest `anoCompra` eligible for processing |
| `PNCP_MAX_CANDIDATES_PER_RUN` | `50` | Maximum candidates discovered in one Actions run |
| `PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN` | `20` | Maximum download/OCR attempts in one Actions run |
| `PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN` | `5` | Maximum valid candidates prepared for submission in one Actions run |
| `PNCP_FETCH_MAX_ATTEMPTS` | `3` | Maximum PNCP API attempts for transient connection failures |
| `PNCP_FETCH_BACKOFF_SECONDS` | `2` | Base sleep seconds between PNCP API retry attempts |
| `SCRAPE_MAX_PDF_BYTES` | `15000000` | Max PDF download size |
| `KREUZBERG_PADDLE_LANGUAGE` | `latin` | OCR language |
| `KREUZBERG_PADDLE_MODEL_TIER` | `tiny` | OCR model tier |
| `KREUZBERG_EXTRACTION_TIMEOUT_SECONDS` | `120` | OCR timeout |
| `FLAGS_use_mkldnn` | `0` | Disable Paddle oneDNN on CPU runners |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | `0` | Disable PaddleX oneDNN defaults used by PaddleOCR |

### PNCP filter configuration

The PNCP discovery filter behavior (UF filter, federal CNPJ list, expired-record
drop) is configured in code, not via environment variables. See
`scripts/pncp_filters.py` as the single source of truth — `UF_FILTER`,
`FEDERAL_CNPJS`, and `DROP_EXPIRED`. Editing those values requires a code change.

The values are public configuration (UF sigla and public federal agency CNPJs)
and are not sensitive. Coordinate any changes with the Render backend so the
discovered editais stay in sync with the processing pipeline.

### GitHub Actions (AI processing)

| Variable | Default | Description |
|----------|---------|-------------|
| `PACIFIC_WINDOW_START` | `8` | Earliest Pacific hour for AI triggers |
| `PACIFIC_WINDOW_END` | `19` | Latest Pacific hour for AI triggers |
| `AI_EDITAIS_PER_DAY` | `20` | Backend daily AI capacity |
| `AI_EDITAIS_PER_MINUTE` | `3` | Backend per-minute AI capacity |
