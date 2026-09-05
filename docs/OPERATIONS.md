# Operations Guide

## Pipeline overview

The PNCP pipeline runs hourly via `pipeline-pncp-discovery.yml`; the eight
non-PNCP sources `bndes`, `brde`, `fapergs`, `funbio`, `iis_rio`, `sema_rs`,
`tnc`, and `wwf` run hourly through the canonical
`pipeline-all-discovery.yml` orchestrator:

1. **Discover** — queries PNCP API for active procurement records across modalities 6 (Pregão Eletrônico), 8 (Dispensa de Licitação), and 4 (Concorrência Eletrônica)
2. **Filter** - keeps only notices with `anoCompra >= 2026`
3. **Download** - fetches each candidate PDF with bounded HTTP, SSRF protection, and retry
4. **Validate** - confirms PDF magic bytes and structure
5. **OCR** - extracts text to markdown using PaddleOCR (latin language, tiny model tier)
6. **Submit** - sends candidates with metadata, markdown, and content hash to Render `/api/pipeline/candidates`

The workflow fails instead of advancing the PNCP checkpoint when PNCP search fails and produces no candidates, when eligible candidates are discovered but all fail download/OCR, or when none are submitted to Render.

After successful discovery, Render AI processing is triggered via
`pipeline-ai.yml` with a daytime Pacific gate.

## Schedule

| Workflow | Schedule | Notes |
|----------|----------|-------|
| `pipeline-pncp-discovery.yml` | `05 * * * *` UTC + manual | Dedicated PNCP discover/download/OCR/submit pipeline |
| `pipeline-all-discovery.yml` | `08 * * * *` UTC + manual | Canonical hourly scheduler for BNDES, BRDE, FAPERGS, FUNBIO, IIS-Rio, SEMA-RS, TNC, and WWF |
| `pipeline-ai.yml` | `16 * * * *` UTC + after PNCP discovery + manual | Pacific daytime gate (08:00–19:00 year-round) |
| `pipeline-fao-discovery.yml` | `12 * * * *` UTC + manual | FAO source workflow |
| `pipeline-fundacao-grupo-boticario-discovery.yml` | `17 * * * *` UTC + manual | Fundação Grupo Boticário source workflow |
| `pipeline-kfw-discovery.yml` | `28 * * * *` UTC + manual | KfW source workflow |
| `pipeline-msgov-discovery.yml` | `38 * * * *` UTC + manual | MSGOV source workflow |
| `pipeline-govbr-mma-discovery.yml` | `50 * * * *` UTC + manual | GOVBR-MMA source workflow |
| `pipeline-unep-discovery.yml` | `45 * * * *` UTC + manual | UNEP source workflow |
| `pipeline-worldbank-discovery.yml` | `55 * * * *` UTC + manual | WorldBank source workflow |
| `pipeline-backfill.yml` | `23 11 * * 6` UTC + manual | Legacy Render backfill rollback path |
| `pipeline-sync.yml` | `37 * * * *` UTC + manual | Render sync trigger |
| `pipeline-bndes-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-brde-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-fapergs-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-funbio-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-iis-rio-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-sema-rs-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-tnc-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-wwf-discovery.yml` | Manual only | Per-source fallback; no duplicate cron |
| `pipeline-pncp-backfill.yml` | Manual only | Active PNCP pending-candidate backfill |
| `pipeline-ingest.yml` | Manual only | Legacy Render ingest rollback path |
| `pipeline-ocr.yml` | Manual only | Legacy Render OCR worker |
| `pipeline-scrape.yml` | Manual only | Legacy Render scrape rollback path |
| `pipeline-run.yml` | Manual only | Legacy full-pipeline rollback path |

All cron expressions are UTC. The AI cron uses 16:00 UTC, which is 08:00 in
Pacific Standard Time and 09:00 in Pacific Daylight Time, so both sides of the
year-round window are inside the gate.

`pipeline-sync.yml` uses the dedicated `pipeline-sync` concurrency group. It
polls `/api/pipeline/runs` using the `run_id` returned by the initial `202` and
does not report success until the backend records a terminal successful or
skipped result. A failed Drive batch therefore remains visible as a failed
Actions run instead of a successful trigger-only run.

All workflows in the shared `pipeline-trigger` concurrency group use
`queue: max` with `cancel-in-progress: false`. Runs remain serialized, but an
overlapping cron or manual dispatch waits in the bounded GitHub Actions queue
instead of replacing the existing pending run. Apply this setting to every new
workflow that joins the group; a member that uses the default single pending
slot can reintroduce scheduler cancellations.

The eight per-source workflows above intentionally retain `workflow_dispatch`
but no `schedule`. Do not add a source-specific cron without first removing it
from the canonical orchestrator and updating this table.

`pipeline-pncp-backfill.yml`, `pipeline-ocr.yml`, and the legacy
`pipeline-ingest.yml`, `pipeline-scrape.yml`, and `pipeline-run.yml` are
manual-only operational paths. They are not part of the hourly discovery
schedule and should be used only for controlled rollback, audit, or backlog
drain work.

Post-fix inventory: this checkout contains 26 workflow files, all with an
explicit job timeout; 12 are scheduled, 13 are manual-only, and Worker CI runs
on pushes and pull requests after duplicate schedule removal.

## Monitoring

### GitHub Actions

- Check workflow run status in the Actions tab
- Key metrics logged: discovery stats, candidates found, OCR successes/failures, submission results
- Cache file `.cache/pncp-last-successful-update.json` tracks the update checkpoint
- Normalize `RENDER_APP_URL` with a trailing-slash-safe base URL before manually debugging a trigger endpoint.

### Render

- Monitor `/api/pipeline/candidates` endpoint health
- Check AI processing logs for model inference outcomes
- Verify direct URL serving for processed notices

## Cache and checkpoint

The PNCP update checkpoint (`.cache/pncp-last-successful-update.json`) is cached between runs using the stable key `pncp-update-checkpoint-${{ runner.os }}` and the same prefix as its restore key. The key deliberately does not include `github.run_id`, so a successful checkpoint can be restored by a later run. This ensures the `/atualizacao` endpoint queries only new or updated records since the last successful run.

## Rollback procedures

### Rollback to legacy Render pipeline

If the combined GitHub Actions pipeline fails:

1. **Ingest**: Trigger `pipeline-ingest.yml` manually (workflow_dispatch) to run Render-side download
2. **OCR**: Trigger `pipeline-ocr.yml` manually to run Render-side OCR worker
3. **Scrape**: Trigger `pipeline-scrape.yml` manually for legacy scrape path
4. **Full run**: Trigger `pipeline-run.yml` manually for complete Render pipeline

### Disable combined pipeline

To pause the hourly combined pipeline:

1. Disable the `pipeline-pncp-discovery.yml` and `pipeline-all-discovery.yml` schedules in GitHub Actions
2. Manually trigger a per-source or legacy workflow only when needed

Do not disable or re-enable one of the eight per-source schedules: those
workflows are manual fallbacks, while `pipeline-all-discovery.yml` owns their
hourly schedule.

### Source-run telemetry rollout

Deploy Repo A's source-run endpoints and database migrations first. Seed and
verify stable source keys for the PNCP source and every source selected in the
unified orchestrator; a source need not be activated merely to receive telemetry.
Confirm the existing `RENDER_APP_URL` and `PIPELINE_SECRET` secrets target that
deployment. The worker production branch is `main`.

The `pipeline-all-discovery.yml` and `pipeline-pncp-discovery.yml` workflows
pass the repository variable `SOURCE_RUN_REPORTING_ENABLED` into their
instrumented Python entrypoints, defaulting to `false`. Standalone per-source
discoverers are not instrumented and are not made observable by this toggle.
After deploying compatible code in both repositories, enable reporting with:

```powershell
gh variable set SOURCE_RUN_REPORTING_ENABLED --body true --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob
gh workflow run pipeline-all-discovery.yml --ref main -f sources=bndes -f audit_only=true --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob
```

Verify that the no-submit canary creates and completes one source run, and
inspect its fidelity artifact and public metrics before relying on production
health indicators. Enabling the repository flag also affects subsequent
scheduled PNCP/unified runs. It does not approve or activate a source and does
not replace the two reviewed clean audit runs required for activation.

To roll back telemetry without stopping ingestion:

```powershell
gh variable set SOURCE_RUN_REPORTING_ENABLED --body false --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob
```

## Environment variables

### GitHub Actions (PNCP discovery)

| Variable | Default | Description |
|----------|---------|-------------|
| `RENDER_APP_URL` | (required) | Render service base URL |
| `PIPELINE_SECRET` | (required) | Bearer token for Render API |
| `SOURCE_RUN_REPORTING_ENABLED` | `false` | GitHub repository variable enabling source-run callbacks in PNCP and unified discovery workflows |
| `PNCP_UPDATE_CHECKPOINT_PATH` | `.cache/pncp-last-successful-update.json` | Checkpoint file path |
| `PNCP_MIN_NOTICE_YEAR` | `2026` | Earliest `anoCompra` eligible for processing |
| `PNCP_MAX_CANDIDATES_PER_RUN` | `50` | Maximum candidates discovered in one Actions run |
| `PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN` | `20` | Maximum download/OCR attempts in one Actions run |
| `PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN` | `5` | Maximum valid candidates prepared for submission in one Actions run |
| `PNCP_FETCH_MAX_ATTEMPTS` | `2` | Maximum PNCP API attempts for transient connection failures in the scheduled workflow |
| `PNCP_FETCH_BACKOFF_SECONDS` | `2` | Base sleep seconds between PNCP API retry attempts |
| `PNCP_FETCH_TIMEOUT_SECONDS` | `8` | PNCP request timeout in seconds |
| `PNCP_LOOKBACK_DAYS` | `30` | Update-feed lookback when the checkpoint is absent or reset |
| `PNCP_PAGE_SIZE` | `50` | Records requested per PNCP page |
| `PNCP_MAX_PAGES_PER_QUERY` | `20` | Maximum pages per PNCP query |
| `PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN` | `100` | Maximum attachment-list lookups per run |
| `PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES` | `10` | Consecutive document failures before enumeration stops |
| `PNCP_PROPOSTA_FORWARD_DAYS` | `60` | Forward window for open proposal records |
| `SCRAPE_MAX_PDF_BYTES` | `15000000` | Max PDF download size |
| `SCRAPE_MAX_PDFS_PER_RUN` | `5` | Maximum successful PDF downloads/OCR completions per run |
| `OCR_MAX_PDF_PAGES` | `50` | Maximum pages passed to OCR per PDF |
| `KREUZBERG_PADDLE_LANGUAGE` | `latin` | OCR language |
| `KREUZBERG_PADDLE_MODEL_TIER` | `tiny` | OCR model tier |
| `KREUZBERG_EXTRACTION_TIMEOUT_SECONDS` | `300` | Shared OCR extraction timeout |
| `FLAGS_use_mkldnn` | `0` | Disable Paddle oneDNN on CPU runners |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | `0` | Disable PaddleX oneDNN defaults used by PaddleOCR |
| `PADDLE_PDX_CACHE_HOME` | `/home/runner/.paddlex` | PaddleX model-cache root used by `pipeline-ocr.yml` |

### Opportunity tuning and safety caps

These values are read by structured sources or the shared submission layer.
They are intentionally documented as defaults rather than workflow inputs so
manual tuning remains an explicit repository change:

| Variable | Default | Description |
|----------|---------|-------------|
| `FINEP_FETCH_TIMEOUT_SECONDS` | `30` | FINEP API request timeout |
| `FINEP_MAX_PAGES_PER_RUN` | `5` | FINEP API page cap |
| `FINEP_PAGE_SIZE` | `20` | FINEP records per API page |
| `FINEP_MAX_OPPORTUNITIES_PER_RUN` | `10` | FINEP opportunity cap |
| `FBDS_FETCH_TIMEOUT_SECONDS` | `30` | FBDS listing/detail request timeout |
| `FBDS_MAX_DETAILS_PER_RUN` | `20` | FBDS detail-page cap |
| `DOPA_INCREMENTAL_WINDOW_DAYS` | `3` | Rolling DOPA search window, bounded because daily publication volume is high |
| `DOPA_MAX_SEARCH_RESULTS` | `1000` | Maximum DOPA search rows retained per run; reaching the cap marks the run incomplete |
| `DOPA_MAX_DETAILS_PER_RUN` | `50` | Maximum DOPA detail lookups per run |
| `DOPA_MAX_OPPORTUNITIES_PER_RUN` | `25` | Maximum DOPA opportunities emitted per run |
| `DOPA_MAX_ATTACHMENTS_PER_OPPORTUNITY` | `25` | Maximum DOPA PDF annexes retained per opportunity |
| `DOPA_MAX_RESPONSE_BYTES` | `5000000` | Maximum DOPA JSON response size |
| `DOPA_MAX_CONTENT_CHARS` | `2000000` | Maximum normalized DOPA content size |
| `DOPA_FETCH_MAX_ATTEMPTS` | `3` | DOPA API retry attempts |
| `DOPA_FETCH_BACKOFF_SECONDS` | `2` | Linear DOPA retry backoff base in seconds |
| `DOPA_FETCH_TIMEOUT_SECONDS` | `30` | DOPA API request timeout |
| `CANOAS_INCREMENTAL_WINDOW_DAYS` | `3` | Rolling Canoas DOMC window in the local `America/Sao_Paulo` calendar |
| `CANOAS_MAX_DAYS_PER_RUN` | `3` | Hard Canoas day-window cap; an over-limit request fails the audit |
| `CANOAS_MAX_PUBLICATIONS_PER_RUN` | `300` | Maximum DOMC publication rows retained per run |
| `CANOAS_MAX_OPPORTUNITIES_PER_RUN` | `25` | Maximum Canoas opportunities emitted per run |
| `CANOAS_MAX_WORDPRESS_LOOKUPS_PER_RUN` | `20` | Maximum exact WordPress `licitacoes` searches per run |
| `CANOAS_MAX_ATTACHMENTS_PER_OPPORTUNITY` | `15` | Maximum official WordPress attachments retained per opportunity |
| `CANOAS_MAX_RESPONSE_BYTES` | `5000000` | Maximum DOMC or WordPress response size |
| `CANOAS_MAX_CONTENT_CHARS` | `2000000` | Maximum normalized WordPress content size |
| `CANOAS_FETCH_MAX_ATTEMPTS` | `3` | Canoas API/WordPress retry attempts |
| `CANOAS_FETCH_BACKOFF_SECONDS` | `2` | Linear Canoas retry backoff base in seconds |
| `CANOAS_FETCH_TIMEOUT_SECONDS` | `30` | Canoas API/WordPress request timeout |
| `FUNBIO_NEWS_LOOKBACK_DAYS` | `45` | FUNBIO news lookback |
| `FUNBIO_NEWS_MAX_DETAILS` | `20` | FUNBIO news detail cap |
| `OPPORTUNITY_ATTACHMENT_MAX_BYTES` | `15000000` | Non-PDF attachment compressed-size cap |
| `OPPORTUNITY_MARKDOWN_MAX_CHARS` | `2000000` | Structured source Markdown cap |
| `RENDER_SUBMIT_MAX_PAYLOAD_CHARS` | `9500000` | Worker aggregate submission cap below Repo A's 10M request cap |
| `PNCP_OPPORTUNITY_V2_ENABLED` | `false` | Manual opt-in for PNCP parent/document normalization |
| `PNCP_OPPORTUNITY_V2_SHADOW` | `true` | Keep PNCP v2 artifact-only until reconciliation passes |
| `OPPORTUNITY_SOURCES` | empty | Structured sources explicitly enabled after audit gates |

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

## OCR entrypoint and bootstrap

The OCR workflow bootstraps the worker with the repository dependency file and
uses this entrypoint:

```bash
pip install -r requirements-ocr-worker.txt
python scripts/ocr_worker/run_ocr_worker.py --limit 5
```

PaddleOCR 3.x delegates model storage to PaddleX. Set
`PADDLE_PDX_CACHE_HOME` before starting the worker when a different model root
is required. The workflow caches `/home/runner/.paddlex`; its older PaddleOCR
2.x cache paths are retained only for compatibility with existing cache data.

## Documentless capability probe

`pipeline-all-discovery.yml` checks whether each imported source module exposes
a callable `discover_opportunities()` before selecting the legacy PDF path.
Structured sources can return a stable opportunity with `documents: []` or
source Markdown, so a documentless opportunity is valid and is not represented
by a fabricated PDF. `finep` and `fbds` always use the structured path when
selected; other sources require an explicitly enabled `OPPORTUNITY_SOURCES`
key or an audit-only run. Otherwise the scheduled legacy candidate path
remains the default.

On the canonical `pipeline-all-discovery.yml` schedule, `DISCOVERY_AUDIT_ONLY`
is false and the eight default sources run through the live legacy candidate
path. A manual dispatch defaults to audit-only and does not download, OCR, or
submit. Keep other structured opportunity keys out of `OPPORTUNITY_SOURCES`
until their fidelity gates and the Repo A documentless capability are
coordinated.

## Timeout defaults

These job limits include headroom for the full retry loops:

| Workflow group | Job timeout | Budget represented |
|----------------|-------------|--------------------|
| AI, sync, and legacy ingest | 50 minutes | Four 10-minute requests plus three 2-minute waits |
| Legacy Render backfill | 70 minutes | Four 15-minute requests plus three 2-minute waits |
| Legacy run and scrape | 170 minutes | Four 40-minute requests plus three 2-minute waits |
| PNCP pending backfill | 80 minutes | Five capped download/OCR items plus claim and submission retries |

PNCP pending backfill defaults to `claim_limit=1` and `process_limit=1` for
manual rollout safety. The 80-minute job limit covers the configured
five-PDF safety cap when those inputs are increased by an operator.

Dispatch limits are validated as integers from `1` through `100`, with
`claim_limit <= process_limit` to match Repo A's claim endpoint. The OCR and
PNCP backfill workflows use the same `pipeline-trigger` concurrency group as
scheduled discovery and therefore cannot run concurrently with it.

All discovery, PNCP backfill, and manual OCR workflows use
`KREUZBERG_EXTRACTION_TIMEOUT_SECONDS=300`. This is an await timeout only:
`asyncio.wait_for` cannot stop the underlying PaddleOCR thread created by
`asyncio.to_thread`, so a timed-out extraction may continue using CPU until its
thread returns. The job-level timeout remains the final hard stop.

## Source-fidelity audits

Before enabling or modifying a source, run the offline fidelity audit to detect missing open opportunities, unrelated/extra records, duplicates, and field mismatches. The tool makes no LLM or network calls.

```bash
python scripts/audit_source_fidelity.py \
  --source-inventory path/to/source_inventory.json \
  --discovery path/to/discovery.json \
  --dashboard path/to/dashboard_export.json \
  --out ./report
```

Outputs (all written to `--out`):

- `summary.json` — quantitative gates (inventory accounting %, candidate traceability %) and per-reason-code counts with pass/fail status. Inventory accounting uses only open, in-scope source records; retain closed rows in the inventory for provenance without expecting a current submission.
- `matches.json` — deterministic matches and field-comparison evidence.
- `exceptions.json` — every missing/extra/duplicate/mismatch/unverifiable record, each with `severity`, `reason_code`, and `evidence`. Authorization headers and credentials are redacted.
- `report.md` — concise human-readable report.

Exit codes: `0` = no blocking exceptions, `1` = fidelity failures (any blocking reason code count > 0), `2` = invalid input or configuration. Blocking reason codes are `missing_open`, `extra_submission`, `duplicate_identity`, `identity_mismatch`, `authoritative_status_mismatch`, `authoritative_deadline_mismatch`, `renderability_mismatch`, and `parser_failure`. A source may be enabled only when two consecutive live runs meet the program's quantitative gates described in the source-fidelity section above.

Input extensions used by the audit:

- Set `reason_code` to `out_of_scope` for an explicit policy rejection or `unresolved_news_lead` for an unsubmitted lead that has not resolved to a canonical opportunity. Add a structured `evidence` object explaining the disposition.
- A record declaring `renderable: true` must also provide `content_type_validated: true` and `hash_validated: true`. A file extension alone is not validation evidence.
- Records and nested evidence are recursively redacted before reports are written, including authorization headers, cookies, password/token fields, URL user information, and authentication query parameters.

## WWF discovery (Plan 02: structural precision)

`discover_wwf_candidates.py` sources from the single WWF acquisitions page
(`/sobrenos/aquisicoesecontratacoes/`). Plan 02 changed discovery from
scanning every listing anchor to **structural section parsing**:

- The listing HTML is split into `EDITAIS ABERTOS` (status `open`) and
  `EDITAIS ENCERRADOS` (status `closed`) sections by their heading text.
- Each edital row inside a section is parsed independently. The stable
  process number (e.g. `005705`) becomes `source_record_id`; when no
  process number is present the numeric WWF content ID from either the
  current `?<id>/<slug>` URL or legacy `uNewsID` URL is used as fallback.
- Only the detail URLs belonging to parsed edital rows are followed
  (`WWF_MAX_DETAILS_PER_RUN` cap). PDFs are extracted only from the
  record content area (`div.template433`, with legacy `div.page-content`
  support); a missing selector is a parser failure rather than a whole-page
  fallback.
- Generic supplier assets are rejected in addition to the existing edital
  prefilter (`is_likely_edital`): filenames/URLs matching
  `documentos-necessarios`, `requisitos-basicos`, proposal-model
  (`modelo*proposta` / `proposta*modelo`), and supplier-portal
  (`portal*fornecedor` / `fornecedor*portal`). Record-bound divulgação,
  retification (`retificacao` / `errata`), and annex (`anexo`) PDFs reached
  via an edital row's detail page are retained.
- `discover_candidates` still returns `(stats, candidates)` for the
  unchanged download/OCR/submit path. `stats["section_parse_failed"]`
  (and `errors`) is set when either heading is absent or no rows can be
  parsed; `detail_parse_failed` covers missing record content selectors.
  Either condition produces a non-zero command and workflow result.
- `build_inventory(...)` emits a Plan-01-compatible normalized record per
  parsed edital row (fields `source_key`, `source_record_id`,
  `canonical_url`, `title`, `status`, `published_at`, `deadline`,
  `document_urls`, `document_hashes`) for audit mode. Every candidate
  carries `metadata.source_record_id` and `metadata.detail_url` so it
  traces to a specific WWF row.

Run `python scripts/discover_wwf_candidates.py --audit-dir artifacts/wwf`
to fetch the live source without OCR or submission. It writes
`source_inventory.json`, normalized `discovery.json`, raw `candidates.json`,
and `stats.json`. A manual run of `pipeline-wwf-discovery.yml` defaults to this
mode and uploads those files as the `wwf-fidelity-<run-id>` artifact.

Enable WWF submission only after the audit shows all open records have an
outcome and no introductory/generic documents appear as candidates (see the
WWF discovery section above).

## MMA public-calls and FNMA discovery (Plan 03)

`discover_govbr_mma_public_calls_candidates.py` and
`discover_govbr_mma_fnma_candidates.py` add two SEPARATE MMA feeds
(`govbr_mma_public_calls`, `govbr_mma_fnma`) that do NOT modify the existing
`govbr_mma` procurement discoverer. Both:

- Parse only the gov.br editorial body (`#content-core #parent-fieldname-text`,
  legacy `#content-core`, or the current `#content` cover body), so
  cross-section navigation / footer links are excluded.
- Associate year headings (`<h2>2026</h2>`) with the edital links that
  follow, carrying the source year into `source_record_id` / inventory
  records.
- Treat `resultado` / `retificacao` / `errata` / historical / annex PDFs as
  RELATED metadata of the parent opportunity — attached to the parent
  inventory record's `document_urls`, never a separate candidate or inventory
  entry. The principal edital PDF is the candidate.
- Emit a Plan-01-compatible inventory (`build_inventory`) for deterministic
  fidelity checks; every candidate carries `metadata.source_record_id` (and
  `metadata.detail_url` where applicable) tracing to a record.
- Do NOT infer `open` from the current year; when no deadline/status is
  stated, `status` is `unknown`.

The FNMA feed accepts a source-specific opt-in `GOVBR_MMA_FNMA_INCLUDE_TDR=1`
to surface terms-of-reference as principal candidates. This is a SOURCE-
SPECIFIC switch and must NOT change the global `FILTER_POLICY` default.

When the editorial body is present but zero inventory records can be parsed,
`discover_candidates` sets `stats["inventory_parse_failed"] = 1` and
increments `errors` — it does NOT silently emit zero candidates as success.

Run the staged live gates without OCR or submission:

```bash
python scripts/discover_govbr_mma_public_calls_candidates.py --audit-dir artifacts/mma-public
python scripts/discover_govbr_mma_fnma_candidates.py --audit-dir artifacts/mma-fnma
```

Both directories contain `source_inventory.json`, `discovery.json`,
`candidates.json`, and `stats.json`. Keep both MMA keys out of the scheduled
default until the public-calls audit passes first, then enable FNMA in a later
production run.

Enable `govbr_mma_public_calls` first, then `govbr_mma_fnma`; do not enable
both in the same first production run (see the MMA discovery section above).

## Structured opportunity rollout

`finep`, `fbds`, `dopa`, `canoas`, `ibama`, `tnc`, and `funbio` use
`POST /api/pipeline/opportunities`. The shared worker validates principal PDFs,
keeps ZIP/DOCX/ODS attachments non-renderable, OCRs safe PDF members from ZIPs
in memory, and submits source Markdown even when attachment validation fails.

Run one source at a time with `DISCOVERY_AUDIT_DIR=artifacts/source-audits`.
Upload the workflow artifact, run `audit_source_fidelity.py` against the
source's inventory/discovery files, and require two consecutive passing live
runs before adding the source to the scheduled default. Roll back by removing
only that key from `SOURCES`.

Manual runs of `pipeline-all-discovery.yml` default to
`DISCOVERY_AUDIT_ONLY=true`, which skips OCR and all Render submissions. After
two reviewed passing runs, add the source key to the `OPPORTUNITY_SOURCES`
repository variable to opt it into the structured submission contract.

Audit-only orchestration verifies the emitted inventory/discovery artifacts
in-process before reporting terminal source-run telemetry. Fidelity blockers
produce a failed run with the actual blocker count; invalid inputs or verifier
errors also fail closed and cannot reuse an earlier passing report. Reports
are written under each source's `fidelity/` directory. Submission exceptions
and partial structured submissions return a nonzero workflow exit code;
partial acceptance is reported as `warning`, not `success`.

FINEP uses API item `id`; FBDS uses the portal record identity; DOPA uses
`idConteudo` (falling back to detail `protocolo`); TNC uses the
explicit TDR URL or a canonical heading/deadline hash; FUNBIO uses the canonical
call slug. `FUNBIO_NEWS_ENABLED` defaults off. When enabled, news is resolved
only by exact canonical URL/slug/source ID and unresolved likely calls are not
submitted.

DOPA is registered in the unified orchestrator but remains audit-only unless
an operator explicitly includes it in `OPPORTUNITY_SOURCES`; it is absent from
the scheduled source list. Keep that opt-in disabled until two consecutive
fidelity runs pass. Its deterministic policy rejects
post-publication acts (`resultado`, `ata`, `homologacao`, `errata`, and similar)
and ordinary procurement terms covered by PNCP (`pregao`, `licitacao`,
`registro de precos`, and similar). The API's whole-edition PDF is never used;
only the per-content exported PDF and source-listed PDF annexes are retained.

Canoas is also registered in the unified orchestrator but remains audit-only
until an operator explicitly includes `canoas` in `OPPORTUNITY_SOURCES`; it is
absent from the scheduled source list. Its DOMC publication id is the stable
identity. The discoverer first inventories `diary-by-day`, then searches the
official WordPress `licitacoes` REST API. A match requires equal number/year,
a publication date within seven days, compatible semantic signals, and a
non-procurement WordPress modality; number/year alone is not unique across
municipal departments. When the page resolves, its canonical URL and
source-owned PDF/DOCX/ZIP links are preserved, while ODT and legacy office
files use the backend's non-renderable `other` kind. The individual DOMC
`/api/publication-file/{publication_id}` PDF is always retained as evidence
and is the structured fallback when WordPress cannot be resolved. Do not use
the DOMC edition PDF as a candidate because it mixes unrelated acts. The
deterministic policy rejects results, minutes, homologations, post-publication instruments, errata,
notifications, and common PNCP procurement modalities while retaining open
editais, chamamentos, chamadas públicas, credenciamentos, and selection calls.

IBAMA uses `source_record_id` from the edital or process number, falling back to
the canonical detail-page slug. The three official editorial inventories and
their RSS feeds are read with bounded GET requests; `/view` and
`/@@download/file` file variants are normalized while retaining the original
source URL. Retifications, results, decisions, minutes and annexes are merged
into the principal opportunity and never emitted as independent opportunities.
Results, notifications, embargos, brigadistas, patrimonial donations and
ordinary PNCP procurement are rejected deterministically. A detail/feed error,
inventory parse error, or cap reached sets `inventory_parse_failed` and must
fail the audit run rather than advancing an incomplete inventory. IBAMA remains
out of the scheduled `SOURCES` default and requires `OPPORTUNITY_SOURCES=ibama`
for non-audit submission.

## PNCP opportunity normalization

The manual PNCP workflow exposes v2 in shadow mode. Keep
`PNCP_OPPORTUNITY_V2_SHADOW=true` until its parent/document inventory matches
the legacy production inventory for two runs. Before apply, restore a current
production backup in isolation and run the backend reconciliation rehearsal.
Review exported analyses and every association action, add `reviewed: true` to
the exact rehearsal report, then pass it as `--reviewed-report` in apply mode.
Any distinct uploaded Drive file conflict aborts the transaction.
# Source Budget Fairness

The all-source workflow passes its run number as `SOURCE_ROTATION_OFFSET`.
The orchestrator rotates the configured priority list without increasing the
shared PDF budget. Manual invocations default to offset zero and can override
it explicitly. Discovery continues after the processing cap; deferred sources
emit warning telemetry with `stats.cap_reached=true` rather than disappearing
from source-run history. This does not guarantee every source is processed in
every run; verify freshness over a full rotation and inspect repeated failures.

Repo A's accepted pipeline jobs require its separately supervised durable
executor. A 202 is not completion; keep polling the run's existing terminal
status contract. Coordinate its schema/API/frontend rollout using Repo A's
`docs/ARCHITECTURE.md` release procedure before resuming production triggers.
