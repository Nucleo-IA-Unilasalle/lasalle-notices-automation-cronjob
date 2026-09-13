# B5 Local Fix Validation

Status: **REVIEW**. UTC test start/end: `2026-09-08T18:10:37Z` /
`2026-09-08T18:12:59Z`; final observation: `2026-09-08T18:13:17Z`. This run
validates two local fixes after the independent B5 review. It does not prove
staging aggregate claim capacity/ownership, old-ref/default-branch writer
fencing, API-side writer fencing, or a release-safe drain plan.

## Fixes

1. `tests/test_beta_admission.py` now exercises the candidate-contract rejection
   with a synthetic validated `ingest`/`opportunity` entry. The real held-source
   test remains unchanged, so the production admission check was not weakened
   or reordered merely to satisfy a message assertion.
2. `scripts/run_managed_source.py` now binds `pncp` exclusively to
   `scripts/discover_pncp_candidates.py` and every other key exclusively to
   `scripts/discover_all_candidates.py`, returning `2` before constructing
   `SourceControl`. Parameterized tests cover both mismatch directions.

## Verification

| Command | Exit | Result |
|---|---:|---|
| `py -3.13 -m pytest tests/test_beta_admission.py tests/test_managed_source.py tests/test_source_schedule_registry.py tests/test_workflow_static.py -q` | 0 | `74 passed in 1.22s`. |
| `py -3.13 -m pytest -q` | 0 | `1059 passed in 140.40s`; retained stdout, stderr, and exit-code artifacts are in this directory. |
| `py -3.13 -c "import pathlib, yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]"` | 0 | All 39 workflow YAML files parsed. |
| `git diff --check` | 0 | No whitespace errors. |

`actionlint` remains unavailable, as recorded by the independent review; YAML
parsing is not a replacement for that unavailable tool.

## Separate Review

`/root/b5_independent_review`, a separate session, accepted these two local
fixes only after an independent focused Python 3.13 rerun (`74 passed`). The
reviewer explicitly withheld B5 release acceptance: direct/old-ref/API-side
writer fencing, staging aggregate-cap/ownership evidence, and a named
operational drain/fence plan remain unresolved.

## Disposition

Keep `B5` at **REVIEW**. No staging mutation or source activation was
authorized or performed. Do not mark B5 `PASS` until the unresolved operational
and staging evidence has been linked and separately accepted.
