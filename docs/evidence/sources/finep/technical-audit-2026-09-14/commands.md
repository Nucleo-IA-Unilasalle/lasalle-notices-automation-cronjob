# Finep Technical Audit — Command Log (2026-09-14)

Session: bounded source-adapter verification for `finep` (Repo B worker).
Rollout mode **paused** preserved; no production actions.

UTC window: ~2026-09-14T18:59Z – 2026-09-14T19:10Z (local shell clock; capture
payload timestamps are UTC as recorded in capture-log.json).

## Commands executed

| # | Command | Purpose | Exit | Result |
|---|---------|---------|------|--------|
| 1 | `py -3.13 --version` | Confirm interpreter | 0 | Python 3.13.5 |
| 2 | `py -3.13 -m pytest tests/test_finep_discovery.py -q` | Offline tests (pre-fix baseline) | 0 | **4 passed** |
| 3 | Standalone capture script (urllib; not repo adapter): GET `https://www.finep.gov.br/o/c/chamadapublicas?sort=dataDePublicacao:desc&pageSize=20&page=N` for N=1..lastPage | Independent full inventory | 2* | 24 pages HTTP 200; 474 rows / 470 unique; open=34, closed=436; one open-record PDF check HTTP 404 (documented) |
| 4 | `DISCOVERY_AUDIT_ONLY=true DISCOVERY_AUDIT_DIR=<temp> SOURCES=finep SUBMISSION_CONTRACT=opportunity OPPORTUNITY_SOURCES=finep FINEP_MAX_PAGES_PER_RUN=100 FINEP_MAX_OPPORTUNITIES_PER_RUN=100 FINEP_PAGE_SIZE=20 py -3.13 scripts/discover_all_candidates.py` | Audit-only dry run (no submit); elevated FINEP_* caps so the adapter can cover all 24 pages / all in-scope opens for fidelity | 0 | opportunities=19, records=470, policy_rejected=451, duplicate_records_skipped=4, page_cap_reached=0, candidate_cap_reached=0, per_source_submitted=0; built-in fidelity OK |
| 5 | `py -3.13 scripts/audit_source_fidelity.py --source-inventory <independent-inventory.json> --discovery <DIR>/finep/discovery.json --out <fidelity-dir>` | Official fidelity CLI vs independent inventory | 0 | `source fidelity OK: no blocking exceptions`; accounting 100% (19/19); traceability 100% (19/19); non_blocking=15 (out_of_scope policy dispositions) |
| 6 | Same fidelity CLI vs **simulated pre-fix** discovery (status reverts to `Aberta`, duplicate open id re-inserted) | Prove the defects were blocking | 1 | 22 blocking: authoritative_status_mismatch=19, duplicate_identity=2, extra_submission=1; traceability 95% |
| 7 | `py -3.13 -m pytest tests/test_finep_discovery.py tests/test_reliability_review_regressions.py -q` | Offline tests after fix + new regressions | 0 | **32 passed** |

\*Capture script exit 2 is the intentional fail-loud path when the single PDF
document check returned HTTP 404; all 24 listing pages completed successfully
before that check, so the listing inventory is complete (not partial).

## Audit-only path and the paused hold

- Registry: `config/source_schedule.json` → finep `submission_contract=opportunity`,
  `rollout_mode=paused`, group c, owner `pipeline-discovery-group-c.yml`, interval 60,
  detail_limit=20, page_limit=5, attachment_limit=25, browser_required=false.
- Catalog: `config/source_catalog_contract.json` → finep `catalog_status=active`
  (catalog lifecycle separate from execution rollout hold).
- **Paused hold preserved.** No workflow dispatch, no repository variable change,
  no catalog mutation, no snapshot/sign-off edit.
- `DISCOVERY_AUDIT_ONLY=true` + `DISCOVERY_AUDIT_DIR` runs discovery and offline
  fidelity and skips submission (`per_source_submitted=0`). The orchestrator does
  **not** consult `rollout_mode=paused` inside audit-only mode; the production hold
  is enforced at the workflow/schedule layer (`pipeline-discovery-group-c.yml` /
  `pipeline-finep-discovery.yml`), which was not exercised.
- Audit elevation of `FINEP_MAX_PAGES_PER_RUN` / `FINEP_MAX_OPPORTUNITIES_PER_RUN`
  is **audit-only**. Production defaults remain page cap 5 / opportunity cap 10
  (docs/OPERATIONS.md and workflow env). Production caps set
  `page_cap_reached` / `candidate_cap_reached`, which make the run partial and
  prevent `finep-pages-v1` cursor advance (scripts/durable_source_work.py).
- AGENTS.md finep cursor rule respected: `finep-pages-v1` page metadata is only
  claimable after full page/record coverage; the audit run completed all 24 pages
  with no caps.

## Defects found and fixed (source-local)

1. **Lifecycle status not normalized to the worker contract.** Adapter emitted
   `authoritative_status`/`status` as the raw Portuguese name (`Aberta`/`Encerrada`),
   while source-fidelity `is_open_in_scope` requires `status == "open"` and peer
   adapters emit `open`/`closed`. Pre-fix fidelity vs independent inventory: 19
   `authoritative_status_mismatch` blockers.
2. **Pagination duplicates not deduped.** Live listing repeats ids across page
   boundaries (observed 4 duplicates, including open id 754839 on pages 1–2).
   Adapter extended records without identity dedup → pre-fix would emit duplicate
   opportunities (`duplicate_identity` + `extra_submission`).

Both fixed in `scripts/discover_finep_opportunities.py` with regression tests in
`tests/test_finep_discovery.py`.

## Safety constraints observed

- No PIPELINE_SECRET / RENDER_API_KEY / DATABASE_URL / Supabase / cookies / tokens read or used.
- No Repo A pipeline/submission/claim/work/scheduler/admin endpoints called.
- No GitHub Actions workflows dispatched; no repo variables mutated; no deploys.
- Catalog lifecycle / audit holds / snapshot sign-off / release-decision files untouched.
- Shared coordinator-owned files read-only; only finep adapter, finep tests, and finep evidence written.
- `scripts/run_independent_source_audit.py` was not used as evidence.
- Scratch lived under `%TEMP%\finep-audit-*` outside the repo.
