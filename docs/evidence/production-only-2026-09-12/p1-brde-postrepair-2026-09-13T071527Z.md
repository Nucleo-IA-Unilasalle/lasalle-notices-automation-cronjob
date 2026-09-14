# P1 BRDE Post-Repair Harness - 2026-09-13T07:15:27Z

Status: **PASS (isolated frozen-code evidence, pending final P4 acceptance)**

The harness ran the selected `brde` / `candidate` boundary from Repo A
`a5275dae46f223da74dc54d0734051acc66a8a9f` and Repo B
`2e0dd74ee64b999318dea4cc1767df4985b384ee`. It used loopback PostgreSQL 17,
created scratch schema `p1_harness_5ac7935045b9`, and reported
`schema_dropped=true`.

- Worker termination/recovery, submit and finish lost-ACK replay,
  changed-content replay, and poison backoff/quarantine passed for `brde`.
- The aggregate cap admitted three claims and rejected one with
  `capacity_full`; 51 requests had zero 5xx/transport failures and zero
  timeouts.
- Warm catalog p95 was 31.91 ms and peak DB use was 5 of 97 usable
  connections. Storage headroom was 99.09% of the declared disposable 1 GiB
  allowance.
- Twelve descriptors drained in 1.043 seconds, measuring 41,437.3 per hour
  against the declared arrival rate of 22 per hour. Peak RSS was 36,368,384
  bytes.

Machine evidence: [`p1-isolated-harness.json`](p1-brde-postrepair-20260913T071540Z/p1-isolated-harness.json)
and [`summary.txt`](p1-brde-postrepair-20260913T071540Z/summary.txt).

No production endpoint, data, credential, source, workflow, or deployment was
used or changed. P2, two clean post-repair audits, P3, and P4 remain separate
gates.
