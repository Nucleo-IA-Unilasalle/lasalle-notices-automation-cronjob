# P1 BRDE Post-Repair Harness - 2026-09-13T07:14:29Z

Status: **BLOCKED/FAILED (retained diagnostic evidence)**

The first post-repair invocation used an incorrect password for the disposable
loopback PostgreSQL container. Repo A's database ping failed before any scenario
ran, so the report could not confirm schema cleanup through that unauthenticated
connection. A later local container query confirmed that neither the failed-run
schema nor the successful-rerun schema existed. The container remained isolated
and healthy; the successful rerun used its existing private local credential.

Machine evidence: [`p1-isolated-harness.json`](p1-brde-postrepair-20260913T071418Z/p1-isolated-harness.json).

No production endpoint, data, credential, source, workflow, or deployment was
used or changed.
