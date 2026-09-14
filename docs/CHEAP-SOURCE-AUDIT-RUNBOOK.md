# Focused Source Audits With A Lower-Cost Model

Use one isolated task per source. The task may inspect official public pages,
run local tests, repair that source's adapter, and produce sanitized evidence.
It must not access production credentials, call Repo A submission endpoints,
change catalog lifecycle, enable workflows, or make a release decision.

This split is intentional: a lower-cost model performs bounded collection and
adapter verification; a separate reviewer validates evidence and authorizes
any later production change.

## Source Queue

Candidate-contract sources:
`bndes`, `brde`, `fao`, `fapergs`, `govbr_mma_fnma`, `iis_rio`,
`fundacao_grupo_boticario`, `govbr_mma`, `govbr_mma_public_calls`, `sema_rs`,
`kfw`, `msgov`, `unep`, `worldbank`, `wwf`, and `pncp`.

Opportunity-contract sources:
`canoas`, `funbio`, `tnc`, `dopa`, `fbds`, `finep`, and `ibama`.

Run paused and audit-mode sources exactly like the others, but never remove
their hold. Run at most three source tasks concurrently to keep public-site
traffic and local resource use bounded. Use two separately created tasks for
audit slots 1 and 2; do not ask one task to manufacture both "independent"
captures.

## Ready-To-Paste Source Prompt

Replace every `<SOURCE_KEY>`, `<SLOT>`, and `<UTC_DATE>` before dispatch. Use a
fresh task for each slot.

```text
Work only on source `<SOURCE_KEY>`, independent audit slot `<SLOT>`, in the
lasalle-notices-automation-cronjob repository. This is a bounded source-adapter
verification task, not a production release task.

Safety constraints:
- Never read, print, request, or use PIPELINE_SECRET, RENDER_API_KEY,
  DATABASE_URL, Supabase credentials, GitHub secrets, or any production token.
- Never call Repo A pipeline/submission/claim endpoints, dispatch or enable a
  workflow, change a repository variable, modify a catalog lifecycle state,
  deploy, commit, push, or mutate production.
- You may fetch only the source's official public pages, APIs, feeds, and
  documents. Keep requests bounded and identify caps or partial inventory as a
  failure, not a pass.
- Do not use scripts/run_independent_source_audit.py as independent evidence;
  it is a repository-owned diagnostic and currently supports only BRDE/BNDES.
- Store no cookies, headers, personal data, credentials, or raw tokens. Evidence
  must be sanitized and reproducible.

Required work:
1. Read AGENTS.md, config/source_schedule.json,
   config/source_catalog_contract.json, the source adapter, its focused tests,
   docs/evidence/AUDIT-TEMPLATE.md, docs/OPERATIONS.md, and any existing source
   evidence. Confirm the expected contract, group owner, lifecycle hold, limits,
   official URLs, and source-specific discovery entry point before running it.
2. Run the focused deterministic tests for `<SOURCE_KEY>`. Discover test files
   with `rg --files tests | rg '<SOURCE_KEY>|source_fidelity|discover_all'` and
   run only the relevant files first. Record exact commands and results.
3. Independently capture the current official-source inventory. Do not derive
   ground truth from adapter output. Record UTC capture time, requested/final
   URLs, status/lifecycle evidence, deadlines, document URLs, HTTP/content type,
   byte lengths, and SHA-256 hashes. Explicitly account for open, closed,
   upcoming, excluded, malformed, and unclassified records.
4. Run only the source's documented local audit/dry-run path with submission
   disabled and no pipeline credentials. If no safe local audit path exists,
   stop and report `blocked_no_safe_audit_entrypoint`; do not improvise with a
   production endpoint.
5. Compare the independently captured inventory to adapter discovery with
   `py -3.13 scripts/audit_source_fidelity.py --source-inventory <inventory> --discovery <discovery> --out <fidelity-dir>`.
   Require complete inventory, 100% traceability for open in-scope records,
   correct lifecycle filtering, correct principal documents, no unexpected
   records, zero blocking exceptions, zero parser/download/submission errors,
   and no partial/capped inventory.
6. If the adapter is wrong, make the smallest source-local repair with
   apply_patch, add a regression test, rerun the focused suite and fidelity
   comparison, and run `git diff --check`. Do not change admission, schedules,
   shared contracts, or unrelated sources. If a shared change is necessary,
   stop and report `escalate_shared_contract_change`.
7. Write sanitized evidence under
   `docs/evidence/sources/<SOURCE_KEY>/audit-<SLOT>-<UTC_DATE>/`. Preserve the
   independent inventory, discovery artifact, fidelity outputs, commands,
   exit codes, changed files, limitations, and result. Do not alter
   snapshot.json sign-off or claim that RR-05, P5, P6, activation, or release is
   complete.

Return exactly:
- `RESULT: pass | fail | blocked`
- `SOURCE: <SOURCE_KEY>`
- `SLOT: <SLOT>`
- `CONTRACT:` expected and observed
- `LIFECYCLE:` current hold and whether preserved
- `OFFICIAL INVENTORY:` open/closed/upcoming/excluded/unknown counts
- `DISCOVERY:` emitted/rejected/error/partial/cap counts
- `FIDELITY:` exit code, blockers, accounting %, traceability %
- `TESTS:` exact commands and pass/fail counts
- `CHANGES:` files changed, or none
- `EVIDENCE:` repository-relative paths
- `ESCALATIONS:` every uncertainty, shared change, unavailable page, or missing
  safe audit entry point
- `PRODUCTION ACTIONS: none`
```

## Reviewer Prompt

Run this only after both source tasks finish. Prefer a stronger model for this
small decision task.

```text
Review independent source audit slots 1 and 2 for `<SOURCE_KEY>`. Do not browse
or repair code unless necessary to verify a cited claim. Confirm the captures
were independently obtained from official sources, all inventory classes are
accounted for, hashes and lifecycle evidence are reproducible, focused tests
pass, fidelity has zero blockers, no cap/partial/error is hidden, and no
credential or production action is present. Inspect the exact diff for scope
creep and shared-contract impact.

Return `ACCEPT_AUDITS` only if both slots independently pass. Otherwise return
`REJECT_AUDITS` with file/line findings and the smallest next task. Acceptance
qualifies evidence only: it must not activate the source, edit snapshot
sign-off, enable a workflow, or authorize production.
```

## Coordinator Prompt

Use this to turn the queue into focused tasks without letting one model perform
an unbounded all-source run.

```text
Read docs/CHEAP-SOURCE-AUDIT-RUNBOOK.md and config/source_schedule.json. Produce
a queue with two independent tasks per source, using the exact source prompt.
Limit concurrency to three. Start with active candidate-contract sources, then
audit-mode sources, paused sources, and PNCP last. Do not run production or
change lifecycle states. After each pair, create a separate reviewer task. Stop
that source on any blocker; do not let failure on one source prevent unrelated
source tasks. Report a table of source, slots, evidence paths, test result,
fidelity result, reviewer decision, and next focused task.
```

## Acceptance Boundary

A cheap-model result may close a focused adapter defect or populate an audit
candidate. It cannot by itself close RR-05, P5, P6, the 48-hour soak, or the
seven-day review. It also cannot authorize a schema, shared-contract, admission,
workflow, catalog, deployment, or production change. Those require a separate
review against the current frozen SHAs and release plan.
