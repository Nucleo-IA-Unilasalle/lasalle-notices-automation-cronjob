# B0 Authorized Read-Only Target Identity Collection

Status: **BLOCKED**. This evidence records the authorized, read-only target
identity collection performed on 2026-09-08. It is neither deployment,
schedule, source activation, database migration, backup, restore, nor staging
mutation authorization.

## Run Identity

- Task: `B0` continuation, target identity collection.
- Executor: `/root` (actual session).
- Separate reviewer: not yet assigned for this new collection.
- UTC end: `2026-09-08T17:49:20Z`. The command start timestamp was not
  instrumented; it preceded this end time in the same interactive session.
- A candidate SHA: `e9422dca8cd9c77f4bf23bc89d7e211ae8bcc693`.
- B candidate SHA: `4211ddf6c99fa4b527f09ff3cad4f86996a1092c`.
- A worktree was clean at the final observation. B had 41 pre-existing or
  concurrent changed/untracked paths, all preserved and not attributed to this
  collection.

## Access And Method

Only `GET` requests to the authorized Render control plane and pipeline API,
read-only GitHub metadata requests, and an attempted explicit PostgreSQL
`BEGIN READ ONLY` transaction were used. Service environment values, database
coordinates, credentials, pipeline secrets, API response bodies, source keys,
claim tokens, and personal data stayed in process memory and are not retained
here. GitHub Actions exposes secret metadata but never secret values.

## Sanitized Identity And State Booleans

`false` under a `*_match_proven` field means the required exact identity was
not proven. It is not a claimed mismatch unless the row says `observed
mismatch`.

| Observation | Sanitized result | Qualification |
|---|---:|---|
| Authorized Render production API service discovered | true | Read-only control-plane service inventory succeeded. |
| Authorized Render staging API service discovered | true | Read-only control-plane service inventory succeeded. |
| Production deployed A SHA matches candidate A | false | Observed mismatch to the candidate. Do not infer which unrelated revision is safe. |
| Staging deployed A SHA matches candidate A | false | Observed mismatch to the candidate; the prior historical staging deployment must not be assumed current. |
| Production API health GET succeeds | true | Point-in-time public health response only. |
| Staging API health GET succeeds | true | Point-in-time public health response only. |
| Production pipeline capabilities match the current candidate contract | false | The authenticated response did not expose the expected current claim-enforcement field. |
| Staging pipeline capabilities recognize claim enforcement | true | Authenticated read-only response exposed a recognized compatible/strict value. |
| Production scheduler enabled | false | Read-only service environment observation. |
| Production source-run maintenance enabled | false | Read-only service environment observation. |
| Staging scheduler enabled | false | Read-only service environment observation. |
| Staging source-run maintenance enabled | false | Read-only service environment observation. |
| Production/staging database identity separation proven | false | Both service DB configurations were present, but complete comparable coordinates were not exposed by this path. |
| Production schema v3 proven | false | The explicit read-only PostgreSQL transaction failed with sanitized `OperationalError`; no schema result was accepted. |
| Staging schema v3 proven in this run | false | No database connection or schema endpoint was used; no allowlist mutation was authorized or attempted. |
| Production API recent pipeline run is pending/running | false | Authenticated `GET /api/pipeline/runs?limit=100` had no active status in its returned window. |
| Staging API recent pipeline run is pending/running | false | Authenticated `GET /api/pipeline/runs?limit=100` had no active status in its returned window. |
| Staging due list has a live source claim | false | Authenticated read-only due-list response had none. |
| Production due-list claim state known | false | The deployed production route returned HTTP 4xx; it is an unsupported/absent contract observation, not evidence of no claim. |
| Production source-work pending/claimed state known | false | Requires the failed production database read or an authorized read-only API/DB view. |
| Production OCR active-claim state known | false | Requires the failed production database read or an authorized read-only API/DB view. |
| Staging source-work/OCR pending-claim state known | false | No read-only endpoint supplied these aggregates, and no staging DB read was performed. |
| B default branch SHA matches candidate B | false | Observed mismatch via read-only GitHub branch metadata. |
| Enabled B workflows present | true | GitHub workflow metadata reported enabled workflows. |
| Enabled scheduled B workflows present | true | Active YAML workflow definitions contain schedule triggers. |
| Legacy scheduled-writer risk present on B default branch | true | Current default-branch scheduled workflow state remains an operational cutover blocker. |
| Queued/running B Actions runs present | false | Point-in-time read of the latest 100 default-branch runs. |
| Actions runs on candidate B present | false | Point-in-time read of the latest 100 default-branch runs. |
| Render production pipeline secret present | true | Presence only; the value was not recorded. |
| Render staging pipeline secret present | true | Presence only; the value was not recorded. |
| GitHub `PIPELINE_SECRET` metadata present | true | Metadata only; GitHub did not reveal its value. |
| GitHub secret target match proven | false | Secret values cannot be compared through the read-only GitHub metadata API. |
| Production deployed executor/worker identity matches candidate B | false | No deployed B worker/executor identity endpoint or artifact mapping was available. |

## Commands And Results

All successful requests were read-only and emitted only sanitized booleans.

| Command family | Result |
|---|---|
| Python 3.13 Render `GET /v1/services`, `GET /env-vars`, and `GET /deploys` | Succeeded; collected service/deployment/config-presence booleans without retaining values. |
| Authenticated pipeline `GET /health`, `/capabilities`, `/runs`, and `/source-schedule/due` | Staging reads succeeded. Production health/runs succeeded; its due route returned HTTP 4xx and is therefore unknown. |
| SQLAlchemy `BEGIN READ ONLY`; aggregate schema/work/claim queries | Failed before an accepted result with `OperationalError`; transaction facts are not inferred. |
| `gh api` branch/workflow/secret metadata and `gh run list` | Succeeded on retry; reported only workflow/run/secret-presence booleans. |

## Retained Failed Attempts

1. The first Render helper attempted to obtain `RENDER_API_KEY` from Repo A's
   dotenv file. It exited with `KeyError` because the credential was supplied
   only through the process environment. No value was printed or retained.
2. A combined cross-target API probe exceeded the local command time budget
   before emitting a result. It made no mutation; the per-target retries above
   are the only accepted observations.
3. The production database read-only attempt failed with `OperationalError`.
   No retry with altered credentials, network policy, or database setting was
   attempted.
4. The first GitHub workflow-content scan included a non-YAML dynamic entry and
   failed. The retry filters to YAML workflow paths and succeeded; it did not
   alter GitHub state.

## B0 Disposition And Next Action

`B0` remains **BLOCKED**. Current evidence now proves active legacy scheduled
writes on B's default branch and candidate/deployment identity mismatches, but
does not establish production database/schema state, production or staging
source-work/OCR aggregates, a deployed B worker identity, or the GitHub-to-
service secret value match.

Next action: a named platform/database owner must provide an authorized
read-only production DB route (or a read-only aggregate endpoint), an approved
read-only staging schema/aggregate route, the deployed worker/executor artifact
identity, and a secret-target attestation that compares values outside public
evidence. A separate B0 reviewer must then assess this continuation.

