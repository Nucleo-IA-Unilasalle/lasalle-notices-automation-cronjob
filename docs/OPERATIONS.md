# Operations Guide

## Pipeline overview

The PNCP pipeline runs hourly via `pipeline-pncp-discovery.yml`; the 22
non-PNCP sources run hourly through the three canonical group workflows
(`pipeline-discovery-group-a/b/c.yml`) sharing the reusable single-source job
(`pipeline-discovery-source.yml`). `pipeline-all-discovery.yml` is manual-only
audit/recovery and never owns scheduled production traffic:

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

Scheduled discovery ownership is declarative: `config/source_schedule.json`
assigns every operational source to exactly one owner group. The three group
workflows build a strict per-source matrix from that registry with
`scripts/build_source_matrix.py` and run each source through the reusable
single-source job in `pipeline-discovery-source.yml`, which serializes on a
per-source concurrency lock (`discovery-<source>`) shared with the manual
fallback workflows. Sources with `rollout_mode: paused` stay visible in the
registry but are omitted from scheduled execution; `audit` sources run
discovery and fidelity verification without ingestion.

| Workflow | Schedule | Notes |
|----------|----------|-------|
| `pipeline-pncp-discovery.yml` | `05 * * * *` UTC + manual | Dedicated PNCP discover/download/OCR/submit pipeline; own `discovery-pncp` lock |
| `pipeline-discovery-group-a.yml` | `07 * * * *` UTC + manual | bndes, brde, fao, fapergs, govbr_mma_fnma, iis_rio (canoas paused) |
| `pipeline-discovery-group-b.yml` | `17 * * * *` UTC + manual | funbio, fundacao_grupo_boticario, govbr_mma, govbr_mma_public_calls, sema_rs, tnc (dopa paused) |
| `pipeline-discovery-group-c.yml` | `27 * * * *` UTC + manual | kfw, msgov, unep, worldbank, wwf (fbds, finep, ibama paused) |
| `pipeline-all-discovery.yml` | Manual only | Manual multi-source audit/recovery; no scheduled ownership |
| `pipeline-ai.yml` | `16 * * * *` UTC + after PNCP discovery + manual | Pacific daytime gate (08:00–19:00 year-round) |
| `pipeline-backfill.yml` | `23 11 * * 6` UTC + manual | Legacy Render backfill rollback path |
| `pipeline-sync.yml` | `37 * * * *` UTC + manual | Render sync trigger |
| `pipeline-*-discovery.yml` (22 per-source workflows) | Manual only | Instrumented per-source manual fallbacks on the same orchestrator path and per-source lock |
| `pipeline-discovery-source.yml` | Reusable only | Single-source job shared by the three group matrices (per-source `discovery-<source>` lock) |
| `pipeline-source-monitor.yml` | `*/15 * * * *` UTC + manual | Read-only freshness check; never triggers ingestion |
| `source-catalog-parity.yml` | Push to `main` + daily `43 8 * * *` UTC + manual | Pinned/live A-catalog parity; uploads `catalog-observation.json` (7-day retention) |
| `pipeline-pncp-backfill.yml` | Manual only | Active PNCP pending-candidate backfill |
| `pipeline-ingest.yml` | Manual only | Legacy Render ingest rollback path |
| `pipeline-ocr.yml` | Manual only | Legacy Render OCR worker |
| `pipeline-scrape.yml` | Manual only | Legacy Render scrape rollback path |
| `pipeline-run.yml` | Manual only | Legacy full-pipeline rollback path |

Recovery ticks (`37`, `47`, `57` minutes) are declared in the registry with
`recovery_enabled: false`; enabling them waits for durable due-state/lease
integration (Plan 03/R5) and a reviewed aggregate-concurrency proof. Group
`max-parallel: 3` is per group, not a global cap; the effective global admission
limit is Repo A's advisory lock **910012** with a hard cap of **3** concurrent
source claims (due/backoff checked under the lock, UTC-bucket cadence, forced
runs clamped). The per-run PDF cap (`SCRAPE_MAX_PDFS_PER_RUN=5`) bounds work
inside one job only and is not an aggregate concurrency guarantee.

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

The 22 per-source workflows above intentionally retain `workflow_dispatch`
but no `schedule`. Do not add a source-specific cron without first removing it
from the canonical orchestrator and updating this table.

`pipeline-pncp-backfill.yml`, `pipeline-ocr.yml`, and the legacy
`pipeline-ingest.yml`, `pipeline-scrape.yml`, and `pipeline-run.yml` are
manual-only operational paths. They are not part of the hourly discovery
schedule and should be used only for controlled rollback, audit, or backlog
drain work.

Post-fix inventory: this checkout contains 39 workflow files, all with an
explicit job timeout; 9 have schedules (3 groups + PNCP + AI + sync + backfill
+ 15-min monitor + catalog parity), 1 is Worker CI (push/PR plus the pinned
parity gate), 1 is the reusable single-source job, and the remainder are
manual-only (22 per-source fallbacks + all-discovery + PNCP backfill +
legacy/operational paths). Worker CI runs on pushes and pull requests.

## Source reliability coordination (Repo A schedule/work contract)

Repo A schema **v3** owns the coordination tables (`source_schedule_state`,
`source_work_items`, `source_collection_checkpoints` with RLS; the schedule
state adds `config_fingerprint`, `claim_config_fingerprint`, `claim_scope`,
`claim_purpose`) behind the
versioned release command `python -m scripts.migrate_schema`. Web startup runs
read-only `verify_db_schema()` and never applies DDL. The v1 baseline is never
rerun on an already-versioned database; v2 adds the three satellites and v3
adds the fingerprint/scope/purpose columns in ordered migrations.

- **Aggregate admission:** advisory key **910012**, hard cap **3** concurrent
  source claims. Due (`next_due_at`) and backoff (`retry_after_at`) are checked
  under the lock. Successful completion anchors `next_due_at` to the next UTC
  interval bucket of the admitted window (not completion + 60 min); forced
  early runs are clamped to the current bucket. `force` never bypasses capacity
  or source lifecycle. `not_due`/`claim_active` skips record no success;
  `capacity_full` waits in 15 s increments only while more than 450 s of budget
  remains.
- **Supervisor** (`scripts/run_managed_source.py`): takes one central claim
  (300 s lease, 60 s renewals), runs discovery in a subprocess, and kills the
  process tree on deadline or renewal uncertainty. The application budget is
  `min(1080 s, job_minutes*60 - setup_elapsed - 120 s cleanup reserve)`; the
  child receives source/contract/PDF cap/filter policy from the registry.
  Outcomes are `complete` (collection marker present), `failed`, or `noop`
  (audit). Registry `paused`/`audit` entries reject ingestion; audit runs must
  set `DISCOVERY_AUDIT_ONLY=true`.
- **Source-work API** (`POST /api/pipeline/source-work`, Bearer
  `PIPELINE_SECRET`, 512 KiB body limit; actions
  `register`/`take`/`finish`/`checkpoint`/`retry_quarantined`): mutations
  require an `active` source and the current lease token. Queue contract:
  256 KiB/item, 1000 items/source, 32 MiB aggregate JSON payload, 16 KiB cursor,
  at-most-3 attempts with 5-minute doubling backoff (max 60 min) then
  quarantine, fenced finish by claim generation + revision, accepted items
  pruned only after 30 days unseen, unchanged accepted snapshots rechecked
  after 24 h. Pending/quarantined work is never silently deleted.
- **Backlog DTO** (public source detail `backlog`, nullable): pending,
  retrying, quarantined counts, oldest pending time, last checkpoint, observed
  time, payload size. `null` means unknown, which is distinct from an empty
  backlog. Raw payloads and claim tokens are never exposed.
- **Ingestion fencing:** candidate/opportunity submissions accept an optional
  `X-Source-Claim` header. `SOURCE_CLAIM_ENFORCEMENT=compatible` (default):
  absent headers stay legacy-compatible; supplied invalid tokens fail with 409
  `claim_invalid`. `strict`: every write requires a live claim (missing header
  → 409 `claim_missing`). Strict mode is the rollout gate for universal
  enforcement; flip it only after all worker paths send the header. Renewals
  recheck the claim's pinned config fingerprint (interval/timeout/URL/status)
  and reject `config_changed`; releases never fail on config drift. Claims
  carry `scope` (checkpoint writes must match it) and `purpose`
  (`collection` respects next_due; `recovery` is drain-only, ignores next_due
  while respecting backoff, requires actionable pending work, cannot register
  new descriptors, and releases as noop without advancing cadence).
- **Watermark limits:** collection cursors are scope watermarks (for example
  PNCP `last_successful_update`), not pagination guarantees. A capped listing
  can repeat its prefix forever. Never advance a cursor beyond
  unregistered/failed records and never treat the watermark as proof of full
  enumeration. PNCP queue identity uses
  `numeroControlePNCP`/`sequencialDocumento` (legacy `pncp_control_number`/
  `pncp_document_sequence` accepted).
- **Drain-only recovery:** `SOURCE_DRAIN_ONLY=true` together with
  `SOURCE_WORK_ENABLED=true` skips discovery and drains the existing spool one
  item at a time with a 420 s preflight and lazy OCR init. It rejects the
  `DISCOVERY_AUDIT_ONLY=true` combination and requires work mode enabled.
  Recovery claims (`purpose=recovery`) bypass `next_due` but respect failure
  backoff and require actionable pending work; `GET /api/pipeline/source-schedule/recovery-candidates`
  lists them read-only. Supervisor recovery ticks remain disabled; do not
  enable them until the drain/collection separation is reviewed against real
  backlog telemetry.
- **Drain PDF cap, error codes, and lease aborts:** the drain enforces the
  shared per-run PDF cap (`SCRAPE_MAX_PDFS_PER_RUN`) for candidate items the
  same way the legacy loop does: `pdf_download_limit_reached` is checked
  before taking work and again after taking a candidate (before OCR init),
  `record_pdf_download` runs only on successful extractions, and a capped
  candidate is finished `deferred` (stays pending, no error code) with
  `cap_reached` telemetry while the drain stops — mirroring opportunity
  cap-deferred semantics. Failed finishes carry one of Repo A's spool error
  codes: candidate-path download/OCR failures use `download_failed`/
  `ocr_failed`, partial attachment snapshots use `attachment_validation_failed`
  (any `*_validation_failed` attachment outcome — download, OCR, size-cap, or
  archive-inspection failure — never conflated with candidate download
  failures), unexpected processing exceptions use `processing_failed`, and
  submission/ACK failures use `submission_failed`. The codes are additive over
  the legacy four: against an older server a finish carrying a new code 422s,
  aborting that drain run while the server keeps the item pending (the take
  already set its retry backoff) — deploy Repo A before the worker. A
  lease-fencing 409 mid-drain (`claim_expired`/`claim_missing`/
  `claim_invalid`; set `LEASE_EXPIRED_REASONS` in `scripts/source_control.py`)
  prints `drain aborted: source lease expired mid-drain (<reason>); server
  keeps work pending` to stderr, exits 1 without a traceback, and removes the
  collection-success marker so the supervisor outcome stays `failed`; every
  other conflict reason keeps propagating as before.

## Catalog parity: pinned/live CI

- **Pinned gate (offline, always):** `config/source_catalog_contract.json`
  (contract_version 1, `exported_at`, `source_commit`, `manifest_sha256`,
  23 items) is compared against `config/source_schedule.json` by
  `scripts/check_source_catalog_parity.py`. Worker CI (`.github/workflows/ci.yml`)
  runs this gate on every push/PR. Paused registry entries are explicit local
  execution holds, printed as `Locally paused (not covered)` and excluded from
  the healthy coverage gate; they never waive cadence for active sources.
- **Live gate (main push / daily / manual):**
  `.github/workflows/source-catalog-parity.yml` runs
  `python scripts/check_source_catalog_parity.py --live --output catalog-observation.json`
  with `RENDER_APP_URL` + `PIPELINE_SECRET`, and uploads the observation
  artifact (7-day retention). It checks the pin, the live
  `GET /api/pipeline/source-schedule/catalog` (identity/lifecycle/cadence/
  run-timeout plus `max_concurrent_source_runs == 3`), and exact pin-vs-live
  equality. Pins older than **14 days** are rejected.
- **Live validation steps (run manually, not from unit tests):**
  1. Confirm repository secrets exist and target the intended Repo A
     deployment: `gh secret list --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob`
     must show `RENDER_APP_URL` and `PIPELINE_SECRET` (never print values).
  2. Confirm the Repo A deployment commit and its `operational_manifest.json`
     hash match the reviewed pin's `source_commit`/`manifest_sha256`
     (`config/source_catalog_contract.json`).
  3. Run the offline pinned gate first:
     `py -3.13 scripts/check_source_catalog_parity.py` — it must pass before
     any live attempt.
  4. Dispatch the live workflow manually:
     `gh workflow run source-catalog-parity.yml --ref main --repo Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob`,
     then watch the run to a green conclusion
     (`gh run watch` or the Actions tab; 5-minute job timeout).
  5. Download the `catalog-parity-<run-id>` artifact (`catalog-observation.json`)
     and store it under `docs/evidence/snapshots/<date>/` as the parity
     observation for that release.
  6. Investigate any `Lifecycle mismatch`, `Cadence mismatch`, run-timeout,
     capacity (`!= 3`), auth (401/403), network, or pin-age failure before
     proceeding; the daily live workflow has not yet been validated end to end
     and no deployed contract has been verified.
- **Weekly pin refresh (14-day gate):** regenerate the pin from the Repo A
  checkout with `py -3.13 scripts/export_source_contract.py --output <pin>`,
  review the diff (identity, lifecycle, cadence, timeouts, commit hash,
  manifest SHA256). The pin records the exporting checkout's `source_commit`
  (git HEAD) plus the manifest SHA256: **HEAD does not include uncommitted
  dirty changes**, so export from a clean checkout or verify the working tree
  has no relevant dirty edits first. Copy the reviewed file to
  `config/source_catalog_contract.json`, rerun the pinned gate plus the full
  worker suite, and reset the 14-day age clock on the commit that lands it.
  The pin is a reviewed bootstrap-manifest export, not live evidence.

## Staging and evidence scaffolding (NOT STARTED)

Placeholders only; no staging run, audit, soak, or live traffic is claimed.
RR-01 through RR-05 remain OPEN and paused/audit holds are preserved. See
[staging runbook](STAGING-RUNBOOK.md) for the ordered checklist,
[evidence index](evidence/README.md) for per-source TODO slots,
[snapshot validation](evidence/SNAPSHOT-VALIDATION.md) plus
`scripts/validate_staging_snapshot.py` for the offline structural check,
[two-audit template](evidence/AUDIT-TEMPLATE.md) for the independent
ground-truth requirement, and
[48 h template](evidence/OBSERVATION-48H-TEMPLATE.md) for the soak log.

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

To pause the hourly discovery:

1. Disable the `pipeline-discovery-group-a/b/c.yml` and `pipeline-pncp-discovery.yml` schedules in GitHub Actions
2. Manually trigger a per-source fallback workflow only when needed

Do not add a source-specific cron without first removing it from the canonical
group matrix and updating the registry (`config/source_schedule.json`) plus
this table. `pipeline-all-discovery.yml` never owns scheduled traffic.

### Source-run telemetry rollout

Deploy Repo A's source-run endpoints and database migrations first. Seed and
verify stable source keys for the PNCP source and every source selected in the
unified orchestrator; a source need not be activated merely to receive telemetry.
Confirm the existing `RENDER_APP_URL` and `PIPELINE_SECRET` secrets target that
deployment. The worker production branch is `main`.

The `pipeline-all-discovery.yml`, `pipeline-pncp-discovery.yml`, group
workflows (via the reusable job), and all 22 per-source fallback workflows
pass the repository variable `SOURCE_RUN_REPORTING_ENABLED` into their
instrumented Python entrypoints, defaulting to `false`. Every fallback runs
the same `discover_all_candidates.py` path and shares the per-source
concurrency lock with its scheduled group writer, so manual/scheduled runs of
the same source serialize.
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

On the canonical group schedules, `DISCOVERY_AUDIT_ONLY`
is derived from the registry `rollout_mode` (`audit=true`, `ingest=false`).
A manual dispatch of a per-source fallback defaults to audit-only and does
not download, OCR, or submit unless explicitly set to ingest. Multi-source
manual ingest is rejected fail-closed (use one source per job); keep other
structured opportunity keys out of `OPPORTUNITY_SOURCES`
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

Managed collection checkpoints advance only on complete coverage. PNCP preserves
the last successful update watermark on page/lookup/candidate caps, upstream
failures, and registration failures; already registered descriptors remain
drainable. Historical versioned incomplete PNCP checkpoints are ignored, causing
the configured initial lookback to be scanned again. This does not reconstruct
updates older than that lookback: inspect prior partial runs before rollout and
use an explicitly reviewed backfill if needed. Finep checkpoints include its
complete page metadata; capped collections do not claim completion.

Durable processing reports actual download/OCR and acknowledged submission
outcomes independently of spool completion. Ambiguous submission acknowledgments
remain failures/retries, not accepted counts. The freshness report separates
recent but failing/warning/checking/unknown sources into `unhealthy`; recent run
timestamps alone do not pass monitoring. These fixes do not close RR-01 through
RR-05 or change any paused/audit rollout holds.

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
