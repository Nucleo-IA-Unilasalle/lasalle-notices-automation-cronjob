# Two-Independent-Audit: brde

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

- Ground-truth capture method/URL: Direct HTTP fetch and DOM extraction from official BRDE portals:
  - `https://www.brde.com.br/palacete/editais/` (HTTP 200, 74,197 bytes, SHA-256: `9ec3baa2d6341602442f53981bb25c855d637923d010b506cbe749e74143047b`)
  - Verified `https://www.brde.com.br/editais/` returns HTTP 404 (WordPress default not found)
  - Verified `https://www.brde.com.br/fsa/chamadas-de-investimento/` (HTTP 200, historical 2014–2018 minutes only, no active 2026 notices)
  - Extracted 1 open in-scope notice: "Edital de Patrocínio BRDE Cultural – Palacete dos Leões 2026" (`https://www.brde.com.br/palacete/wp-content/uploads/2025/05/Edital-de-Patrocinio-BRDE-Cultural-–-Palacete-dos-Leoes-2026-1.pdf`)
  - Retained at `docs/evidence/sources/brde/audit-1/ground_truth_inventory.json` and `capture_metadata.json`
- Ground-truth captured at (UTC): `2026-09-07T23:02:01.184360+00:00`
- Independent of audit 2 (yes/no + why): Yes; independent session, distinct request timestamp, separately computed payload hash and verified directly against live portal before slot 2 execution.
- Discovery artifact compared: `docs/evidence/sources/brde/audit-1/discovery.json` (1 candidate discovered via `discover_brde_candidates.py`)
- Fidelity report path: `docs/evidence/sources/brde/audit-1/fidelity` (`summary.json`, `matches.json`, `exceptions.json`, `report.md`)
- Exit code / blocking exceptions: Exit code `0` / `0` blocking exceptions (100.0% candidate traceability, 100.0% inventory accounting; 1 non-blocking `missing_optional_metadata` on status string)
- Operator: Antigravity Source Auditor, 2026-09-07
- Result: pass

## Audit slot 2

- Ground-truth capture method/URL: Direct HTTP fetch and DOM extraction from official BRDE portals in a distinct second verification pass:
  - `https://www.brde.com.br/palacete/editais/` (HTTP 200, 74,197 bytes, SHA-256: `024dd4daa5f82c4c44e40470278143cb893e5598f42d23240311f1aac0c313a3`)
  - Verified `https://www.brde.com.br/editais/` (HTTP 404)
  - Verified `https://www.brde.com.br/fsa/chamadas-de-investimento/` (HTTP 200)
  - Extracted 1 open in-scope notice: "Edital de Patrocínio BRDE Cultural – Palacete dos Leões 2026" (`https://www.brde.com.br/palacete/wp-content/uploads/2025/05/Edital-de-Patrocinio-BRDE-Cultural-–-Palacete-dos-Leoes-2026-1.pdf`)
  - Retained at `docs/evidence/sources/brde/audit-2/ground_truth_inventory.json` and `capture_metadata.json`
- Ground-truth captured at (UTC): `2026-09-07T23:02:09.655045+00:00`
- Independent of audit 1 (yes/no + why): Yes; separate HTTP connection session, distinct timestamp, separate response content digest, executed sequentially to verify temporal idempotence and stability.
- Discovery artifact compared: `docs/evidence/sources/brde/audit-2/discovery.json` (1 candidate discovered via `discover_brde_candidates.py`)
- Fidelity report path: `docs/evidence/sources/brde/audit-2/fidelity` (`summary.json`, `matches.json`, `exceptions.json`, `report.md`)
- Exit code / blocking exceptions: Exit code `0` / `0` blocking exceptions (100.0% candidate traceability, 100.0% inventory accounting; 1 non-blocking `missing_optional_metadata` on status string)
- Operator: Antigravity Source Auditor, 2026-09-07
- Result: pass

## Completion gate

- [x] Both audits concluded `pass` with zero blocking exceptions.
- [x] Both used independent official-source ground truth (not adapter output).
- [x] Reports and captures are stored and credential-redacted.
- [x] Reviewer sign-off recorded in the source's `snapshot.json` audits array
      (at most 2 entries, each with `result` and `report_path`).

Activation of any source remains a separate, explicitly authorized catalog
lifecycle change (see the paused/audit holds in `README.md`); two passing
audits are necessary, never sufficient on their own.
