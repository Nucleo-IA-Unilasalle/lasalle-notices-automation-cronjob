# WWF Trusted-Network Audit Runner

## Why It Exists

WWF returns HTTP 403 to GitHub-hosted runners before discovery can begin.
This was reproduced on both Ubuntu and macOS hosted pools:

- https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/actions/runs/30145224254
- https://github.com/Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob/actions/runs/30145302509

The public acquisitions page and the official open/closed RSS endpoints are
all blocked from those runner networks. Changing browser headers, using the
official feeds, and changing hosted-runner operating systems did not change
the response. Do not route this audit through a public proxy or scraping
service.

## Runner Design

Use a dedicated, repository-scoped GitHub Actions self-hosted runner on an
existing trusted host whose network can fetch the WWF page. Give it both the
default `self-hosted` label and the custom `wwf-audit` label. The workflow
`.github/workflows/pipeline-wwf-trusted-audit.yml` targets both labels, so it
cannot run on an unrelated shared runner.

The runner must:

- Run as an unprivileged account with a dedicated work directory.
- Be repository-scoped, not organization-wide.
- Carry no Render, database, Drive, or production submission credentials.
- Have outbound access only as required for GitHub Actions, Python packages,
  `www.wwf.org.br`, and `wwfbrnew.awsassets.panda.org`.
- Accept only manual runs from trusted repository maintainers.
- Be updated and removed through GitHub's runner controls; never commit its
  short-lived registration token.

Prefer an ephemeral runner if the host automation can recreate it for each
audit. Otherwise stop the runner process when it is not in use.

## Audit Contract

Dispatch `WWF trusted-network audit`. It:

1. Installs only the lightweight discovery dependencies.
2. Runs discovery with `--audit-dir`, so OCR and submission are impossible.
3. Runs the deterministic source-fidelity comparator.
4. Uploads inventory, discovery, opportunities, candidates, statistics, and
   fidelity reports as `wwf-trusted-fidelity-<run-id>`.

The run is acceptable only when `fidelity/summary.json` reports:

- `inventory_accounting_pct: 100.0`
- `candidate_traceability_pct: 100.0`
- `total_blocking_exceptions: 0`
- `pass: true`

Provisioning the runner is intentionally separate from source code. Until a
runner with the `wwf-audit` label is online, the trusted workflow will remain
queued and WWF production enablement remains blocked.
