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

Exit codes: `0` = no blocking exceptions, `1` = fidelity failures (any blocking reason code count > 0), `2` = invalid input or configuration. Blocking reason codes are `missing_open`, `extra_submission`, `duplicate_identity`, `identity_mismatch`, `authoritative_status_mismatch`, `authoritative_deadline_mismatch`, `renderability_mismatch`, and `parser_failure`. A source may be enabled only when two consecutive live runs meet the program's quantitative gates (see `plans/opportunity-sources/README.md`).

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
outcome and no introductory/generic documents appear as candidates (see
`plans/opportunity-sources/02-wwf-discovery-precision.md`).

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
both in the same first production run (see
`plans/opportunity-sources/03-mma-source-expansion.md`).

## Structured opportunity rollout

`finep`, `fbds`, `tnc`, and `funbio` use
`POST /api/pipeline/opportunities`. The shared worker validates principal PDFs,
keeps ZIP/DOCX attachments non-renderable, OCRs safe PDF members from ZIPs in
memory, and submits source Markdown even when attachment validation fails.

Run one source at a time with a manual audit in
`pipeline-all-discovery.yml`. Upload the workflow artifact, run
`audit_source_fidelity.py` against the source's inventory/discovery files, and
require two consecutive passing live runs before changing its production
route.

Manual runs of `pipeline-all-discovery.yml` default to
`DISCOVERY_AUDIT_ONLY=true`, which skips OCR and all Render submissions. After
two reviewed passing runs, add the source key to the `OPPORTUNITY_SOURCES`
repository variable to opt it into the structured submission contract.

FINEP uses API item `id`; FBDS uses the portal record identity; TNC uses the
explicit TDR URL or a canonical heading/deadline hash; FUNBIO uses the canonical
call slug. `FUNBIO_NEWS_ENABLED` defaults off. When enabled, news is resolved
only by exact canonical URL/slug/source ID and unresolved likely calls are not
submitted.

### FUNBIO/TNC production-route cutover

Three workflows can discover FUNBIO or TNC:

| Workflow | FUNBIO | TNC | Submission path |
|----------|--------|-----|-----------------|
| `pipeline-funbio-discovery.yml` | yes | no | Legacy `/api/pipeline/candidates` |
| `pipeline-tnc-discovery.yml` | no | yes | Legacy `/api/pipeline/candidates` |
| `pipeline-all-discovery.yml` | yes | yes | Structured `/api/pipeline/opportunities` when approved; audit-only otherwise |

Before route gating, the unified schedule selected FUNBIO and TNC while both
dedicated schedules were also active. The unified legacy mode loads the same
`discover_funbio_candidates` / `discover_tnc_candidates` modules as the
dedicated workflows and submits the same document URLs with the same source
keys. The schedules could therefore submit the same source identity more than
once, even though backend idempotency usually prevented a duplicate row.

`OPPORTUNITY_SOURCES` is now the single route switch for these two sources:

- Key absent: the dedicated legacy workflow submits; the scheduled unified
  workflow excludes the source.
- Key present: the dedicated workflow stops before dependency installation or
  submission; the scheduled unified workflow includes the source and uses the
  structured endpoint.
- Manual audit: the unified audit step has no `RENDER_APP_URL` or
  `PIPELINE_SECRET`, sets `DISCOVERY_AUDIT_ONLY=true`, and never submits.
- Manual submission: the route resolver rejects FUNBIO/TNC unless the source
  is already approved in `OPPORTUNITY_SOURCES`.

Use lowercase comma-separated keys, for example `finep,fbds,funbio`; whitespace
and case are normalized by the route resolver. Change only one key at a time.
Do not add `tnc` while its shared-TDR identity conflict remains open.

Cut over one approved source:

```bash
gh variable set OPPORTUNITY_SOURCES \
  --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob \
  --body "finep,fbds,funbio"
```

Verify the next unified run reports `funbio_route=structured`, then verify the
dedicated FUNBIO run contains only checkout/route-resolution steps. Do not
perform this change until the source's rollout gates pass.

Roll back immediately by removing only the failing key from the variable, then
manually dispatch its dedicated workflow. Route resolution will exclude it
from the next unified schedule and restore the legacy submission step:

```bash
gh variable set OPPORTUNITY_SOURCES \
  --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob \
  --body "finep,fbds"
gh workflow run pipeline-funbio-discovery.yml \
  --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob
```

Never use `workflow_dispatch` inputs as a production enablement bypass. The
repository variable remains authoritative.

## PNCP opportunity normalization

The manual PNCP workflow exposes v2 in shadow mode. Keep
`PNCP_OPPORTUNITY_V2_SHADOW=true` until its parent/document inventory matches
the legacy production inventory for two runs. Before apply, restore a current
production backup in isolation and run the backend reconciliation rehearsal.
Review exported analyses and every association action, add `reviewed: true` to
the exact rehearsal report, then pass it as `--reviewed-report` in apply mode.
Any distinct uploaded Drive file conflict aborts the transaction.
