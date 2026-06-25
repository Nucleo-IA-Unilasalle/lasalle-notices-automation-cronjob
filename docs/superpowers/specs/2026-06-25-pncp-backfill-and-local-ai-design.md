# PNCP Backfill And Local AI Drain Design

Date: 2026-06-25

## Context

The production backlog is not primarily an AI backlog. There are 6,111 PNCP rows in `public.scrape_candidates` with `status = 'pending'` and no matching `public.editais` row by `source_url`. These candidates were discovered between 2026-06-06 and 2026-06-13. A subset is still confirmed active by PNCP metadata because `candidate_metadata->>'dataEncerramentoProposta'` is in the future.

The current PNCP architecture puts download, validation, OCR, and submission in GitHub Actions. Render persists trusted worker results, runs AI analysis, serves the API/frontend, and optionally syncs to Drive. The backfill should preserve that boundary.

## Goals

- Drain the confirmed-active PNCP pending candidate backlog through GitHub Actions, not Render-side OCR.
- Prioritize candidates that still matter: active deadlines first, `Edital` documents first.
- Reuse the existing Actions worker pipeline for download, validation, OCR, and `/api/pipeline/candidates` submission.
- Keep the first version idempotent and low-risk; duplicate work is acceptable, duplicate `editais` rows are not.
- After backfill promotion, drain the resulting AI queue from a local operator command with small batches and visible logs.

## Non-Goals

- Do not OCR PNCP PDFs inside Render for this backfill.
- Do not rewrite the normal PNCP discovery algorithm.
- Do not add a dashboard UI for backlog triage in this iteration.
- Do not permanently skip expired backlog rows until the active backlog has been handled and measured.

## Backfill Architecture

Add a backend claim endpoint that exposes a bounded list of pending PNCP candidates:

```text
POST /api/pipeline/candidates/backfill/claim?source=pncp&limit=20
```

The endpoint is protected by the existing pipeline bearer token. It returns candidate rows containing at least:

- `id`
- `url`
- `kind`
- `candidate_metadata`
- `pncp_control_number`
- `pncp_document_sequence`
- `discovered_at`

The first version does not need a database lease field. It claims by query only, relying on idempotent PNCP identity upserts when Actions submits worker results back to Render.

Ordering:

1. Candidates with `dataEncerramentoProposta > now()` first.
2. `tipoDocumentoNome = 'Edital'` before other document types.
3. Earliest future deadline first.
4. Oldest `discovered_at` first.
5. Lowest `id` as final tie-breaker.

The endpoint should default to active-only for PNCP. Any future override must be explicit, such as `active_only=false`, and must not be used by the default workflow.

## GitHub Actions Backfill Worker

Add a new cronjob script, for example `scripts/backfill_pncp_pending_candidates.py`, that:

1. Requires `RENDER_APP_URL` and `PIPELINE_SECRET`.
2. Calls the backend claim endpoint with a small limit.
3. Converts each claimed row into the existing candidate shape: `{"url", "kind", "metadata"}`.
4. Processes candidates with `pipeline_core.process_candidate`.
5. Submits successful worker results through the existing `pipeline_core.submit_candidates(..., source="pncp")`.
6. Prints stats for claimed, processed, OCR successes, OCR failures, submitted, and failed batches.
7. Exits non-zero when it claimed candidates but submitted none, matching the current PNCP discovery failure policy.

Add a manual GitHub Actions workflow first:

```text
.github/workflows/pipeline-pncp-backfill.yml
```

The workflow should start as `workflow_dispatch` only. After a successful manual run and validation, it can be scheduled at a conservative cadence. Runtime knobs should mirror PNCP discovery where possible:

- `PNCP_BACKFILL_CLAIM_LIMIT`
- `PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN`
- `PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN`
- `SCRAPE_MAX_PDF_BYTES`
- OCR env vars used by current PNCP discovery

## Local AI Drain

Once backfilled candidates are submitted, they become `editais` rows with OCR markdown and `ai_processing_completed = false`. That backlog should be drained locally, not in GitHub Actions.

Add or document a local runner that:

1. Connects to production with `DATABASE_URL`.
2. Uses the existing `AIProcessingService` and model policy.
3. Processes only rows with `ai_processing_completed IS NOT TRUE`.
4. Requires markdown/text content to exist before processing.
5. Accepts a small operator-controlled limit.
6. Logs each batch summary and leaves failures retryable.

Example operator shape:

```powershell
$env:DATABASE_URL="..."
$env:GOOGLE_API_KEY="..."
python scripts/run_ai_backlog.py --limit 25 --only-with-markdown
```

The local runner may be implemented in the backend repository because that is where `AIProcessingService` lives.

## Validation

Backfill validation queries:

```sql
SELECT
  COUNT(*) AS pending_candidates,
  COUNT(e.id) AS matching_editais
FROM public.scrape_candidates sc
LEFT JOIN public.editais e ON e.source_url = sc.url
WHERE sc.source = 'pncp'
  AND sc.status = 'pending';
```

Expected backfill effect:

- `pending_candidates` decreases for active PNCP candidates.
- `editais` count increases or existing PNCP rows are updated.
- The AI backlog may increase because newly promoted editais need model analysis.

AI validation query:

```sql
SELECT
  COUNT(*) FILTER (WHERE ai_processing_completed IS FALSE) AS ai_not_completed,
  COUNT(*) FILTER (WHERE ai_processing_completed IS TRUE) AS ai_completed
FROM public.editais;
```

Expected local AI effect:

- `ai_not_completed` decreases.
- `ai_completed` increases.
- Failed rows remain visible for retry rather than being silently hidden.

## Risks And Mitigations

- Duplicate work: without leases, two Actions runs can claim the same rows. Mitigation: workflow concurrency plus existing PNCP identity upsert makes persistence idempotent.
- Long OCR runtime: keep manual workflow first and cap processed/submitted candidates per run.
- Render endpoint accidentally exposes too much work: require bearer auth, source filter, active-only default, and strict limits.
- AI quota burn: run AI locally with small explicit limits and visible logs.
- Expired backlog remains: intentionally deferred until active rows are drained and measured.
