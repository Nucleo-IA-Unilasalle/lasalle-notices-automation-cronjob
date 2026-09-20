# RESULT — fundacao_grupo_boticario technical audit 2026-09-14

RESULT: **pass**

## Contract

- Expected contract: `candidate` (registry + catalog: `submission_contract=candidate`, `rollout_mode=ingest`, `browser_required=TRUE`, group b, owner `pipeline-discovery-group-b.yml`, interval 60min, detail_limit=20, page_limit=5, attachment_limit=25). Catalog: `active`.
- Observed contract: adapter emits PDF candidates only (`kind=pdf`) from listing → detail → PDF anchors; no structured opportunity contract. Matches `candidate`.
- Entry point: `scripts/discover_fundacao_grupo_boticario_candidates.py::discover_candidates` via `scripts/discover_all_candidates.py`.
- Official listing URL: `https://fundacaogrupoboticario.org.br/`.
- LIFECYCLE HOLD: none (catalog active; no snapshot/release files touched; no audit/paused holds removed).

## Official inventory (independent capture, 2026-09-14 UTC)

| bucket | count |
|---|---|
| open | 0 |
| closed | 2 |
| upcoming | 0 |
| excluded | 0 |
| unknown | 0 |

Both detail pages are the El Niño sprint pair; application deadline 2026-08-03 passed before capture; results article dated 2026-08-31. Edital/form live on off-source microsites; zero foundation/fapeg PDF anchors.

## Discovery (audit-only)

- emitted: 0
- rejected: 0
- errors: 0
- partial: false
- cap reached: false
- stats: listings_fetched=1, details_fetched=2, candidates=0, playwright_fallback_used=0

## Fidelity

- exit code: 0
- blockers: 0 blocking exceptions
- open-record accounting: 100% (0/0 open in-scope)
- candidate traceability: 100% (0/0)
- hidden caps / partial inventory: none observed

## Tests

```text
py -3.13 -m pytest tests/test_fundacao_grupo_boticario_discovery.py -q
15 passed
```

## Verdict

No source-local defect found. Adapter correctly discovers the two closed sprint pages, finds no PDFs, and emits zero candidates — matching the independent open inventory of zero. No production actions. No code changes.
