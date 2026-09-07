# Two-Independent-Audit Template (scaffold — no audit performed)

Copy this file to `docs/evidence/sources/<source_key>/audits.md` when the
first audit begins. Until then every field stays `TODO`. A completed audit is
**not** two copies of the adapter's own output.

## Ground truth rules

- Each audit's ground truth must come from the **official source itself**
  (the source's own portal, API, or official publication feed), captured
  independently of the pipeline's discovery output.
- Two audits are independent when their ground-truth captures were taken
  separately (different times or separately recorded sessions), and neither
  was produced from the other or from the same discovery artifact.
- Using the pipeline's `discovery.json`/`source_inventory.json` as "ground
  truth" for its own audit is circular and does not count.
- Record how ground truth was obtained (URL, capture time, method) so a
  reviewer can redo the capture.

## Audit slot 1

- Ground-truth capture method/URL: `TODO`
- Ground-truth captured at (UTC): `TODO`
- Independent of audit 2 (yes/no + why): `TODO`
- Discovery artifact compared: `TODO: path to discovery.json`
- Fidelity report path: `TODO: audit_source_fidelity.py --out report dir`
- Exit code / blocking exceptions: `TODO`
- Operator: `TODO (name, date)`
- Result: `TODO (pass|fail)`

## Audit slot 2

- Ground-truth capture method/URL: `TODO`
- Ground-truth captured at (UTC): `TODO`
- Independent of audit 1 (yes/no + why): `TODO`
- Discovery artifact compared: `TODO: path to discovery.json`
- Fidelity report path: `TODO: audit_source_fidelity.py --out report dir`
- Exit code / blocking exceptions: `TODO`
- Operator: `TODO (name, date)`
- Result: `TODO (pass|fail)`

## Completion gate

- [ ] Both audits concluded `pass` with zero blocking exceptions.
- [ ] Both used independent official-source ground truth (not adapter output).
- [ ] Reports and captures are stored and credential-redacted.
- [ ] Reviewer sign-off recorded in the source's `snapshot.json` audits array
      (at most 2 entries, each with `result` and `report_path`).

Activation of any source remains a separate, explicitly authorized catalog
lifecycle change (see the paused/audit holds in `README.md`); two passing
audits are necessary, never sufficient on their own.
