# Exit-Code Ledger

All timestamps are UTC. The restore and API process intervals were captured directly. Worker durations were captured by a bounded parent-process stopwatch; the worker child output and exit code were retained only in private scratch space and securely deleted after sanitization.

| Phase | Start | End | Duration (s) | Exit/result |
| --- | --- | --- | ---: | --- |
| restore validation, archive test/extract/restore | 2026-09-13T07:06:37.5233392Z | 2026-09-13T07:06:50.9161610Z | 13.393 | archive test `0`; extract `0`; `pg_restore` `0`; outer `0` |
| migration run 1 | 2026-09-13T07:06:48.2213410Z | 2026-09-13T07:06:49.7118110Z | 1.490 | `0` |
| migration run 2 (repeat safety) | 2026-09-13T07:06:49.7119328Z | 2026-09-13T07:06:50.4471526Z | 0.735 | `0` |
| closed-beta API/probe/stop | 2026-09-13T07:07:17.179Z | 2026-09-13T07:10:04.689Z | 167.510 | API process `0`; probes passed |
| resume API/probe/stop | 2026-09-13T07:10:34.927Z | 2026-09-13T07:12:15.465Z | 100.538 | API process `0`; probes passed |
| first legacy-worker compatibility run | 2026-09-13T07:12:30.771Z | 2026-09-13T07:15:20.953Z | 170.182 | API process `0`; bounded compatibility run |
| final timed legacy-worker compatibility phase | 2026-09-13T07:16:45.521Z | 2026-09-13T07:18:16.921Z | 91.400 | API process `0`; two worker children `0` |
| historical worker child 1 | captured within final phase | captured within final phase | 1.143 | `0`; inserted |
| historical worker child 2 | captured within final phase | captured within final phase | 1.143 | `0`; updated |
| target teardown | after verification | after verification | bounded command | `docker rm -fv` successful; target/volume absent |

No production command appears in this ledger. No commit or push was performed by this attempt.
