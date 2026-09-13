# B5 Correction Rerun Failure

Status: **REVIEW**. This retained failed local validation attempt made no
hosted request or mutation.

The wrapper started `py -3.13 -m pytest -q` with its working directory set to
this evidence directory rather than the B repository root. Its stdout reports
`no tests ran in 0.01s`; the exit-code marker is empty due to the same wrapper
defect. This attempt verifies nothing and is not overwritten. The corrected
repository-root rerun is retained separately in
`b5-final-validation-2026-09-08T180900Z`.

