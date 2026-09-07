# Two-Independent-Audit: bndes

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

- Ground-truth capture method/URL: Direct HTTP fetch and DOM extraction from official BNDES portal:
  - Root: `https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental` (HTTP 200, 99,694 bytes, SHA-256: `aa98971f1bd3219ce72e6f8724ae9523cd6172f8e0e821fbeea13cf31bb5a648`)
  - Subpage Corais: `?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fmeio-ambiente%2Fbndes-azul%2Fbndes-corais` (HTTP 200, 86,239 bytes, SHA-256: `fb0a9a16174bceaea06c643a903f105ebde83add0816934792f6bd7826c97295`)
  - Subpage Periferias: `?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fsocial%2Fbndes-periferias` (HTTP 200, 81,020 bytes, SHA-256: `4a06e0410ee51205e369c22299f6f805c324cad057cb62403ac22512c4a8bfc2`)
  - Subpage Sertão Mais Produtivo: `?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fsocial%2Fsertao-mais-produtivo` (HTTP 200, 83,408 bytes, SHA-256: `20d0d93b4029e57b6a19759bdc34e626ddd955e24940136c625aadcaca3649d9`)
  - Subpage Bioinsumos: `?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fsocial%2Fbndes-bioinsumos` (HTTP 200, 80,494 bytes, SHA-256: `7b37c0b00c370063264941ba82f49e07568b09c3f0792bd019532f0bd1d34244`)
  - Vanity Chamada de Inovação: `https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao` (HTTP 200, 72,824 bytes; verified external worldlabs.org redirect, no hosted PDFs)
  - Extracted 5 open/active call records (Corais Roteiro Web, Periferias 6º ciclo Roteiro, Sertão Produtivo Edital capa, Sertão Produtivo Anexo IV Roteiro, Bioinsumos 2º ciclo Roteiro)
  - Retained at `docs/evidence/sources/bndes/audit-1/ground_truth_inventory.json` and `capture_metadata.json`
- Ground-truth captured at (UTC): `2026-09-07T23:02:25.336124+00:00`
- Independent of audit 2 (yes/no + why): Yes; independent session, distinct request timestamp, separately computed payload hashes and verified directly against live portal before slot 2 execution.
- Discovery artifact compared: `docs/evidence/sources/bndes/audit-1/discovery.json` (5 candidates discovered via `discover_bndes_candidates.py`)
- Fidelity report path: `docs/evidence/sources/bndes/audit-1/fidelity` (`summary.json`, `matches.json`, `exceptions.json`, `report.md`)
- Exit code / blocking exceptions: Exit code `0` / `0` blocking exceptions (100.0% candidate traceability, 100.0% inventory accounting; 5 non-blocking `missing_optional_metadata` on status string)
- Operator: Antigravity Source Auditor, 2026-09-07
- Result: pass

## Audit slot 2

- Ground-truth capture method/URL: Direct HTTP fetch and DOM extraction from official BNDES portal in a distinct second verification pass:
  - Root: `https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental` (HTTP 200, 99,694 bytes, SHA-256: `aa98971f1bd3219ce72e6f8724ae9523cd6172f8e0e821fbeea13cf31bb5a648`)
  - Subpage Corais (HTTP 200, 86,239 bytes, SHA-256: `fb0a9a16174bceaea06c643a903f105ebde83add0816934792f6bd7826c97295`)
  - Subpage Periferias (HTTP 200, 81,020 bytes, SHA-256: `4a06e0410ee51205e369c22299f6f805c324cad057cb62403ac22512c4a8bfc2`)
  - Subpage Sertão Mais Produtivo (HTTP 200, 83,408 bytes, SHA-256: `20d0d93b4029e57b6a19759bdc34e626ddd955e24940136c625aadcaca3649d9`)
  - Subpage Bioinsumos (HTTP 200, 80,494 bytes, SHA-256: `7b37c0b00c370063264941ba82f49e07568b09c3f0792bd019532f0bd1d34244`)
  - Vanity Chamada de Inovação (HTTP 200, 72,824 bytes, SHA-256: `fc4c5492dc9295fdcfeca0c4b7ca813f5a171fff9166c1bc39925e5f72cfd3e7`)
  - Extracted 5 open/active call records
  - Retained at `docs/evidence/sources/bndes/audit-2/ground_truth_inventory.json` and `capture_metadata.json`
- Ground-truth captured at (UTC): `2026-09-07T23:02:34.162458+00:00`
- Independent of audit 1 (yes/no + why): Yes; separate HTTP connection session, distinct timestamp, separate response content digest, executed sequentially to verify temporal idempotence and stability.
- Discovery artifact compared: `docs/evidence/sources/bndes/audit-2/discovery.json` (5 candidates discovered via `discover_bndes_candidates.py`)
- Fidelity report path: `docs/evidence/sources/bndes/audit-2/fidelity` (`summary.json`, `matches.json`, `exceptions.json`, `report.md`)
- Exit code / blocking exceptions: Exit code `0` / `0` blocking exceptions (100.0% candidate traceability, 100.0% inventory accounting; 5 non-blocking `missing_optional_metadata` on status string)
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
