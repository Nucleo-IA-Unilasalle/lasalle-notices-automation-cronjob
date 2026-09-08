# Lasalle Notices Automation Cronjob

Trusted GitHub Actions worker for discovering, validating, extracting, and
submitting opportunities from PNCP and the registered public-source adapters.
It sends authenticated results to the FastAPI application for persistence and
AI processing.

For the product vision, cross-repository architecture, decisions, guided tours,
and interactive system atlas, start with the application repository's
[project handbook](https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation/blob/master/docs/README.md).

## Architecture

The preferred pipeline is split between GitHub Actions (source-specific
discovery, bounded download, text/OCR extraction, fidelity evidence, and
submission) and the FastAPI application (AI processing, persistence, user API,
and Drive integration). The repositories do not by themselves prove the live
deployment topology.

### GitHub Actions responsibilities

- **Discover** active PNCP procurement records (modalities 6/8/4) via `/publicacao`, `/proposta`, and `/atualizacao` endpoints
- **Filter** notices explicitly to `anoCompra >= 2026` before download/OCR/submission
- **Download** each candidate PDF once with bounded HTTP (SSRF protection, size limits, retry)
- **Validate** PDFs via magic-byte and structure checks
- **Extract** PDF markdown from embedded text, falling back to PaddleOCR when needed
- **Submit** candidates with metadata, markdown, and content hash to `/api/pipeline/candidates`
- **Submit** stable API/web opportunities, including zero-document and non-renderable-attachment records, to `/api/pipeline/opportunities`

### FastAPI application responsibilities

- Trust and persist authenticated submissions
- Run AI processing (model-only inference on submitted markdown)
- Serve the authenticated opportunity and document APIs
- Coordinate per-user Drive copies without blocking the global catalogue

## Workflows

`pipeline-all-discovery.yml` is the canonical hourly scheduler for
`bndes`, `brde`, `fapergs`, `funbio`, `iis_rio`, `sema_rs`, `tnc`, and `wwf`.
The per-source workflows for those keys retain manual dispatch only.
The scheduled unified run is a live discovery/OCR/submission run; only a
manual dispatch defaults to audit-only mode.

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pipeline-pncp-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (PNCP) |
| `pipeline-pncp-backfill.yml` | Manual only | Claims active pending PNCP candidates from Render, downloads/OCRs them in Actions, and submits worker results back to Render |
| `pipeline-bndes-discovery.yml` | Manual only | Combined discover → download → OCR → submit (BNDES pilot, Phase 2) |
| `pipeline-brde-discovery.yml` | Manual only | Combined discover → download → OCR → submit (BRDE, Phase 3) |
| `pipeline-fapergs-discovery.yml` | Manual only | Combined discover → download → OCR → submit (FAPERGS, Phase 3) |
| `pipeline-funbio-discovery.yml` | Manual only | Combined discover → download → OCR → submit (FUNBIO, Phase 3) |
| `pipeline-iis-rio-discovery.yml` | Manual only | Combined discover → download → OCR → submit (IIS-Rio, Phase 3) |
| `pipeline-sema-rs-discovery.yml` | Manual only | Combined discover → download → OCR → submit (SEMA-RS, Phase 3) |
| `pipeline-tnc-discovery.yml` | Manual only | Combined discover → download → OCR → submit (TNC, Phase 3) |
| `pipeline-wwf-discovery.yml` | Manual only | Combined discover → download → OCR → submit (WWF, Phase 3) |
| `pipeline-unep-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (UNEP, Phase 3; Cloudflare bypass via browser User-Agent) |
| `pipeline-govbr-mma-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (GOVBR-MMA, Phase 3) |
| `pipeline-worldbank-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (WorldBank, Phase 3; BS4 primary + Playwright fallback) |
| `pipeline-fao-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (FAO, Phase 4; Playwright-based listing) |
| `pipeline-kfw-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (KfW, Phase 4; Playwright-based listing) |
| `pipeline-fundacao-grupo-boticario-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (Fundação Grupo Boticário, Phase 4; Playwright-based listing) |
| `pipeline-msgov-discovery.yml` | Hourly cron + manual | Combined discover → download → OCR → submit (MSGOV, Phase 4; pure-Playwright with shadow-DOM probing; magic-byte check rejects `.doc` annex leakage at download time) |
| `pipeline-all-discovery.yml` | Hourly at `08 * * * *` UTC + manual | Canonical unified orchestrator; the scheduled default is the eight sources listed above. |
| `pipeline-ai.yml` | After PNCP discovery + hourly at `16 * * * *` UTC + manual | Trigger Render AI processing (daytime Pacific gate) |
| `pipeline-backfill.yml` | Weekly cron + manual | Legacy Render backfill (rollback) |
| `pipeline-ingest.yml` | Manual only | Legacy Render ingest (rollback) |
| `pipeline-ocr.yml` | Manual only | Legacy Render OCR worker (backfill) |
| `pipeline-scrape.yml` | Manual only | Legacy Render scrape (rollback) |
| `pipeline-run.yml` | Manual only | Legacy full pipeline run (rollback) |
| `pipeline-sync.yml` | Hourly cron + manual | Trigger Render Drive synchronization |

The Drive sync workflow uses its own non-canceling `pipeline-sync` concurrency
group, so unrelated discovery and OCR runs cannot replace a queued sync. After
Render accepts the request with `202`, the workflow polls the authenticated
pipeline history by `run_id` and succeeds only after the backend records a
terminal `success` or `skipped` status; a failed Drive batch fails the workflow.

Discovery, AI, backfill, and manual OCR workflows share the non-canceling
`pipeline-trigger` concurrency group with `queue: max`. This preserves their
serialized execution while allowing pending runs to wait instead of replacing
one another when the hourly schedules overlap.

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
- `PNCP_FETCH_MAX_ATTEMPTS=3` — code default for transient PNCP connection retries; the scheduled workflow sets `2`
- `PNCP_FETCH_BACKOFF_SECONDS=2` / `PNCP_FETCH_TIMEOUT_SECONDS=8` — PNCP retry delay and request timeout
- `PNCP_LOOKBACK_DAYS=30` — update-feed lookback window when the checkpoint is absent or reset
- `PNCP_PAGE_SIZE=50` — records requested per PNCP page
- `PNCP_MAX_PAGES_PER_QUERY=20` — maximum pages per PNCP query
- `PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN=100` — maximum attachment-list lookups per run
- `PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES=10` — stop document enumeration after this many consecutive failures
- `PNCP_PROPOSTA_FORWARD_DAYS=60` — forward window for open proposal records
- `PNCP_OPPORTUNITY_V2_ENABLED=false` — opt into one PNCP parent per control number; the manual workflow exposes this separately from the legacy path
- `PNCP_OPPORTUNITY_V2_SHADOW=true` — write the normalized PNCP inventory artifact without production submission
- `FINEP_MAX_OPPORTUNITIES_PER_RUN=10` — bound structured FINEP API submissions
- `FINEP_FETCH_TIMEOUT_SECONDS=30` / `FINEP_MAX_PAGES_PER_RUN=5` / `FINEP_PAGE_SIZE=20` — bound FINEP API work
- `FBDS_MAX_DETAILS_PER_RUN=20` — bound Restaura Amazônia detail parsing and ZIP inspection
- `FBDS_FETCH_TIMEOUT_SECONDS=30` — per-request timeout for FBDS listing/detail fetches
- `DOPA_INCREMENTAL_WINDOW_DAYS=3` — rolling Porto Alegre DOPA search window; keep it short because daily publication volume is high
- `DOPA_MAX_SEARCH_RESULTS=1000` / `DOPA_MAX_DETAILS_PER_RUN=50` — DOPA search and detail safety caps; reaching either fails the fidelity run instead of silently submitting a partial window
- `DOPA_MAX_OPPORTUNITIES_PER_RUN=25` / `DOPA_MAX_ATTACHMENTS_PER_OPPORTUNITY=25` — DOPA output and attachment caps; reaching an opportunity cap fails the fidelity run
- `DOPA_MAX_RESPONSE_BYTES=5000000` / `DOPA_MAX_CONTENT_CHARS=2000000` — bounded DOPA JSON and normalized-content sizes
- `DOPA_FETCH_MAX_ATTEMPTS=3` / `DOPA_FETCH_BACKOFF_SECONDS=2` / `DOPA_FETCH_TIMEOUT_SECONDS=30` — DOPA API retry budget
- `CANOAS_INCREMENTAL_WINDOW_DAYS=3` / `CANOAS_MAX_DAYS_PER_RUN=3` — rolling local `America/Sao_Paulo` DOMC day window and hard day cap
- `CANOAS_MAX_PUBLICATIONS_PER_RUN=300` / `CANOAS_MAX_OPPORTUNITIES_PER_RUN=25` — Canoas inventory and structured-output caps; a reached cap marks the audit incomplete
- `CANOAS_MAX_WORDPRESS_LOOKUPS_PER_RUN=20` / `CANOAS_MAX_ATTACHMENTS_PER_OPPORTUNITY=15` — bound WordPress resolution and source-owned attachments
- `CANOAS_MAX_RESPONSE_BYTES=5000000` / `CANOAS_MAX_CONTENT_CHARS=2000000` — bounded DOMC/WP response and normalized-content sizes
- `CANOAS_FETCH_MAX_ATTEMPTS=3` / `CANOAS_FETCH_BACKOFF_SECONDS=2` / `CANOAS_FETCH_TIMEOUT_SECONDS=30` — Canoas retry budget
- `FUNBIO_NEWS_ENABLED=false` — enable bounded news resolution; unresolved articles remain artifacts and are never submitted
- `FUNBIO_NEWS_LOOKBACK_DAYS=45` / `FUNBIO_NEWS_MAX_DETAILS=20` — bound news inventory work
- `OPPORTUNITY_ATTACHMENT_MAX_BYTES=15000000` — compressed-size limit for non-PDF attachments
- `OPPORTUNITY_MARKDOWN_MAX_CHARS=2000000` — maximum source or extracted Markdown retained per structured opportunity
- `SCRAPE_MAX_PDF_BYTES=15000000` — reject candidate PDFs larger than this many bytes during download
- `SCRAPE_MAX_PDFS_PER_RUN=5` — generic per-run cap on successful PDF downloads/OCR completions (used by `pipeline_core.pdf_download_limit_reached`)
- `OCR_MAX_PDF_PAGES=50` — page-count safety cap applied before OCR optimization
- `RENDER_SUBMIT_BATCH_SIZE=5` — candidates per Render `/api/pipeline/candidates` POST batch
- `RENDER_SUBMIT_MAX_PAYLOAD_CHARS=9500000` — worker aggregate payload ceiling, below Repo A's 10,000,000-character request cap
- `RENDER_SUBMIT_TIMEOUT=90` — per-batch HTTP timeout in seconds
- `RENDER_SUBMIT_MAX_ATTEMPTS=4` — retry budget for transient Render submit failures (5xx, 408, 425, 429)
- `RENDER_SUBMIT_BACKOFF_BASE=5` — exponential backoff base seconds between Render submit retries
- `RENDER_SUBMIT_MAX_MARKDOWN_CHARS=1000000` — truncate OCR markdown longer than this before submitting to Render
- `FLAGS_use_mkldnn=0` — disables Paddle oneDNN on CPU runners; required to avoid the current PaddleOCR runtime failure seen in GitHub Actions
- `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0` — disables PaddleX's default oneDNN path used by PaddleOCR
- `SOURCES` (unified orchestrator only) — comma-separated source names; whitespace is tolerated and duplicates are removed. Valid structured sources include `finep`, `fbds`, `dopa`, `canoas`, `ibama`, `funbio`, and `tnc`, in addition to the legacy PDF source keys. PNCP remains in its dedicated workflow.
- `DISCOVERY_AUDIT_ONLY=true` — performs discovery and writes fidelity artifacts without OCR or Render submission; manual all-sources runs default to this safe mode.
- `OPPORTUNITY_SOURCES` — comma-separated sources allowed to use the structured opportunity endpoint. Scheduled runs default to the legacy candidate path until a source passes its rollout gates; set the repository variable to enable sources reversibly.
- `DISCOVERY_AUDIT_DIR` — when set, every structured source writes stable `source_inventory.json`, `discovery.json`, `opportunities.json`, and `stats.json` artifacts.
- `MIN_NOTICE_YEAR` (Phase 5 unified orchestrator only, default `2026`) — generic year guard forwarded to BS4 discoverers as their `min_year` argument. Plan §9 recommends a generic name (not `PNCP_MIN_NOTICE_YEAR`) so the unified orchestrator does not couple non-PNCP sources to PNCP-specific env vars. Playwright sources (`fao`, `fundacao_grupo_boticario`, `kfw`, `msgov`) do not accept `min_year` and run with their own internal filtering.
- `FILTER_POLICY` (Phase 5 unified orchestrator only, default `default`) — EDITAL inclusion/exclusion policy forwarded to BS4 discoverers (`default` | `include_tdr` | `no_prefilter`). Ignored by Playwright sources.

The PNCP and opportunity values above are code defaults unless a workflow sets
them explicitly. They are intentionally conservative safety caps: a tuning
change should be made in the workflow environment and reviewed with the
corresponding source-fidelity artifacts. The MMA public-calls and FNMA feeds
are manual audit paths, not scheduled source keys; their year and candidate
limits are controlled through the unified `MIN_NOTICE_YEAR` path until they
receive dedicated workflows.

## OCR entrypoint and bootstrap

Install the worker dependencies from the repository root, then invoke the
manual Render-side OCR worker with:

```bash
pip install -r requirements-ocr-worker.txt
python scripts/ocr_worker/run_ocr_worker.py --limit 5
```

PaddleOCR 3.x uses PaddleX for model downloads. `PADDLE_PDX_CACHE_HOME` is
the documented cache variable; `pipeline-ocr.yml` sets it to
`/home/runner/.paddlex` and caches that directory. The older
`~/.cache/paddleocr`, `~/.paddleocr`, and `~/.paddlehub` paths remain only as
compatibility entries for pre-PaddleX caches.

## Documentless opportunity capability

The unified orchestrator probes each source module for a callable
`discover_opportunities()` entrypoint before choosing the legacy PDF-candidate
path. Structured sources can therefore emit a stable opportunity with
`documents: []` and/or source Markdown; a missing document is not converted
into a fake PDF. `finep` and `fbds` are always routed through this structured
path when selected in the all-source workflow; `OPPORTUNITY_SOURCES` remains
the opt-in allowlist for other structured sources. Manual audit-only runs may
exercise the capability without OCR or Render submission.

## Workflow timeout defaults

The job timeouts include headroom for the configured retry budgets:

| Workflow group | Timeout | Retry budget |
|----------------|---------|--------------|
| AI, sync, and legacy ingest | 50 minutes | Four 10-minute requests plus three 2-minute waits |
| Legacy Render backfill | 70 minutes | Four 15-minute requests plus three 2-minute waits |
| Legacy run and scrape | 170 minutes | Four 40-minute requests plus three 2-minute waits |
| PNCP pending backfill | 80 minutes | Up to five capped download/OCR items plus claim and submission retries |

PNCP pending backfill dispatch defaults are `claim_limit=1` and
`process_limit=1`. The 80-minute timeout still covers its five-PDF safety cap
when an operator increases those inputs manually.

`KREUZBERG_EXTRACTION_TIMEOUT_SECONDS=300` is the shared OCR extraction
timeout in every discovery, backfill, and OCR workflow. It bounds the awaitable
operation, not the underlying PaddleOCR work: `asyncio.wait_for` around
`asyncio.to_thread` cannot kill the worker thread after the timeout fires, so a
timed-out extraction can continue consuming CPU until the thread returns.

### PNCP pending candidate backfill

`pipeline-pncp-backfill.yml` is a manual integration workflow for draining the active PNCP backlog in `scrape_candidates`. It calls the Render claim endpoint for active pending PNCP candidates, reuses the same download/OCR worker path as PNCP discovery, and submits successful worker results to `/api/pipeline/candidates`.

Use conservative inputs until the post-deploy testing gate passes:

- `claim_limit=1`
- `process_limit=1`

Both dispatch inputs are validated in the worker to the Repo A range `1..100`,
and `claim_limit` must not exceed `process_limit`. The PNCP backfill and manual
OCR workflows share the `pipeline-trigger` concurrency group with discovery so
they cannot overlap a scheduled discovery run.

After Render is confirmed healthy and the first manual run moves an active candidate into `editais`, the limits can be increased gradually. Do not schedule this workflow until the active backlog behavior is verified in production.

The PNCP workflow fails if PNCP search fails and produces no candidates, if discovered candidates all fail download/OCR, or if no discovered candidate is submitted to Render, so the PNCP checkpoint is not advanced over unprocessed notices. The BNDE workflow mirrors the same shape but has no checkpoint to advance.

### PNCP keeps its own workflow (Phase 5 decision)

The Phase 5 plan recommends **keeping** `pipeline-pncp-discovery.yml` separate from the new `pipeline-all-discovery.yml` orchestrator rather than folding PNCP into it. Reasoning (plan §5):

- PNCP has hard-won guardrails (`PNCP_MIN_NOTICE_YEAR`, `PNCP_MAX_CANDIDATES_PER_RUN`, modality filtering, document-type priorities, the `/atualizacao` checkpoint) that are not directly applicable to other sources.
- The unified orchestrator uses the generic `MIN_NOTICE_YEAR` / `FILTER_POLICY` / `SOURCES` env vars; binding PNCP to those would couple its knobs to the new generic ones prematurely.
- The PNCP discoverer also has a different return shape (``(stats, candidates, checkpoint)`` vs ``(stats, candidates)``), which would require either forcing it into the new shape or special-casing it.

Operators who want to discover non-PNCP sources in a single Actions run should use `pipeline-all-discovery.yml`. PNCP continues to run via `pipeline-pncp-discovery.yml` unchanged. Folding PNCP in is tracked as a follow-up PR after the unified orchestrator stabilises.

### WWF discovery precision (Plan 02)

`discover_wwf_candidates.py` discovers WWF editais by structurally parsing the `EDITAIS ABERTOS` (status `open`) and `EDITAIS ENCERRADOS` (status `closed`) sections of the acquisitions page, following only those rows' detail URLs, and extracting PDFs only from the record content area. Generic supplier documents (`documentos-necessarios`, `requisitos-basicos`, proposal-model, and supplier-portal) are rejected; record-bound divulgação, retification, and annex PDFs are retained. A missing section, zero parsed rows, or missing detail content selector is reported as a failure rather than a healthy zero-result run.

Run a live no-submit audit and write Plan-01-compatible inputs with:

```bash
python scripts/discover_wwf_candidates.py --audit-dir artifacts/wwf
```

This writes `source_inventory.json`, normalized `discovery.json`, raw `candidates.json`, and `stats.json`. The manual WWF workflow runs in audit-only mode by default and uploads this directory as an artifact.

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

Exit codes: `0` = no blocking exceptions, `1` = fidelity failures, `2` = invalid input/config. The matching ladder is, in descending authority: `(source_key, source_record_id)`, canonical URL (fragment removed, query params preserved), exact document SHA-256, then exact normalized document URL. Title similarity never establishes identity. The executable contract is in `scripts/audit_source_fidelity.py`.

Input files must contain arrays of record objects. `document_urls` and `document_hashes` are arrays of strings; hashes are 64-character SHA-256 hex digests. A record explicitly rejected by policy may set `reason_code` to `out_of_scope`; an unsubmitted unresolved announcement may use `unresolved_news_lead`. Include an `evidence` object for either disposition. A record with `renderable: true` must also include `content_type_validated: true` and `hash_validated: true`.

## Structured opportunity sources

The unified orchestrator detects `discover_opportunities()` modules and uses
the stable opportunity endpoint instead of the legacy PDF-only endpoint:

- `finep` consumes the paginated official `/o/c/chamadapublicas` JSON API, keys records by API `id`, excludes site-wide manuals/tutorials, and accepts complete records without a PDF.
- `fbds` parses only the Restaura Amazônia edital portal. ZIPs remain official, non-renderable attachments; archive members are inspected and OCRed in memory with path, encryption, nesting, member-count, size, ratio, symlink, and PDF-magic guards.
- `dopa` consumes the official Porto Alegre DOPA `busca-avancada` and detail APIs, keys records by `idConteudo`/`protocolo`, keeps the exported content PDF plus owned PDF annexes, rejects post-publication acts and ordinary PNCP procurement vocabulary, and uses a three-day rolling audit window by default. It is registered for audit selection but is not in the scheduled source list or automatic structured-source set; a non-audit run requires explicit inclusion in `OPPORTUNITY_SOURCES`.
- `canoas` consumes the official DOMC `diary-by-day` inventory, keys records by `publication_id`, and resolves WordPress `licitacoes` pages only when number/year, local publication date, semantic signals, and non-procurement modality agree. Number/year alone is not unique across municipal departments. It preserves the canonical WordPress page, official PDF/DOCX/ZIP attachments and other source files such as ODT as non-renderable metadata, plus the individual `/api/publication-file/{publication_id}` DOMC PDF as evidence/fallback; it rejects later acts and ordinary PNCP procurement vocabulary. The source uses a bounded three-day `America/Sao_Paulo` window, is registered for audit selection only, and requires explicit `OPPORTUNITY_SOURCES=canoas` opt-in for non-audit submission.
- `ibama` reads the official chamamentos, editais and annual-notes pages plus their RSS feeds. Detail pages are canonical, edital/process identities are stable across feeds, and retifications/results/annexes remain documents of the principal opportunity. It includes environmental projects, recovery calls, OSCs and credenciamentos while excluding common procurement, firefighting, patrimonial donation and generic news. IBAMA is audit-only until explicitly listed in `OPPORTUNITY_SOURCES`; it is not in the scheduled source default.
- `tnc` parses only the consultancy/service section of `trabalhe-conosco`, uses `NOVO PRAZO` over `PRAZO`, classifies every record as `consultancy`, and reports malformed blocks instead of traversing general news.
- `funbio` keeps the calls portal as canonical. News resolution uses exact call URLs/slugs only; canonical fields win, institutional news is ignored, and unresolved likely calls are artifact-only.

Structured sources remain outside the scheduled default until two consecutive
live fidelity reports pass. Run a manual workflow with
`DISCOVERY_AUDIT_DIR=artifacts/source-audits`, then compare each source's
inventory and discovery files with `audit_source_fidelity.py`.

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
- [Staging runbook](docs/STAGING-RUNBOOK.md) — NOT STARTED ordered release checklist
- [Staging evidence index](docs/evidence/README.md) — per-source evidence slots (placeholders only)
- [Live A catalog parity](docs/OPERATIONS.md#catalog-parity-pinnedlive-ci) — pinned/live CI gate and pin-refresh procedure
