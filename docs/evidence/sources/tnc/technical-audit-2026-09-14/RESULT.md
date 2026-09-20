# RESULT — TNC Source-Adapter Verification (2026-09-14)

RESULT: fixed

## Summary

Independent official capture (direct HTTP of the Trabalhe Conosco consultancy page, not via
the repo adapter) found **49** consultancy blocks: **1 open** (PEPSA/PA TDR, deadline
2026-09-25 23:59 America/Sao_Paulo) and **48 closed/expired**. Audit-only discovery
(`DISCOVERY_AUDIT_ONLY=true`, opportunity contract, audit rollout untouched) initially
emitted 49 opportunities but built-in fidelity failed with **2 identity_mismatch**
blockers: two distinct expired blocks share one TDR PDF URL
(`tdr-empresa-especializada-nap.pdf`); the adapter reassigned distinct fallback stable IDs
but left the shared document URL on both records. **Source-local fix** applied in
`scripts/discover_tnc_candidates.py` (clear `documents` when applying fallback identity for
a reused TDR; keep the URL as free-text provenance in `source_markdown`) with a regression
test. Post-fix: audit-only discovery exit 0, built-in fidelity OK, official fidelity CLI vs
independent inventory **exit 0, 0 blocking exceptions, 100% open-record accounting (1/1),
100% candidate traceability (49/49)**. Focused tests **26/26 pass**.

## Structured fields

- RESULT: fixed
- SOURCE: tnc
- EXPECTED CONTRACT: opportunity (structured) — discover_tnc_candidates, group b, rollout
  **audit**, owner pipeline-discovery-group-b.yml, interval 60 min, detail_limit=20,
  page_limit=5, attachment_limit=25, browser_required=false; catalog active.
- OBSERVED CONTRACT: opportunity (audit-only path ran via `scripts/discover_all_candidates.py`
  with `SUBMISSION_CONTRACT=opportunity` and `OPPORTUNITY_SOURCES=tnc`; adapter module and
  registry entry match; no contract drift).
- LIFECYCLE HOLD: **rollout_mode=audit preserved** (registry unchanged; catalog stays active
  as a separate lifecycle). No audit/paused holds removed; AGENTS.md two-audit hold for
  tnc/funbio is **not** signed off; no activation authorized.
- OFFICIAL INVENTORY: open=1, closed=48, upcoming=0, excluded=0, unknown=0
  (Trabalhe Conosco single static page, HTTP 200 @ 2026-09-14T20:37:36Z, 91671 bytes;
  49 consultancy blocks fully enumerated; news listing HTTP 200 @ 20:37:37Z, 0 signal
  detail URLs; no pagination caps; open principal PDF 200 application/pdf 140858 bytes
  SHA-256 ac35f49cca7ee6d888e6caaa60870bf5c3555877f1a9cfe275abee6ffa733e9d).
- DISCOVERY: emitted=49, rejected=0, errors=0, partial=no, cap reached=no
  (stats: blocks=49, opportunities=49, malformed_blocks=0; detail/page caps not reached;
  `per_source_submitted={'tnc': 0}`).
- FIDELITY: exit code 0; blockers=0; open-record accounting=100.0% (1/1); candidate
  traceability=100.0% (49/49); non_blocking exceptions=0; no hidden cap/partial.
  Open match key stable_id ('tnc', TDR URL); status open=open; deadline
  2026-09-26T02:59:00Z both sides.
- TESTS: `py -3.13 -m pytest tests/test_tnc_discovery.py tests/test_tnc_opportunities.py -q`
  → **26 passed in 6.34s** (post-fix).
- CHANGES:
  - scripts/discover_tnc_candidates.py — when fallback identity is applied for a reused TDR
    URL, clear `documents` and append shared-URL provenance to `source_markdown` (prevents
    identity_mismatch from two stable IDs sharing one document_url).
  - tests/test_tnc_opportunities.py — regression: reused-TDR blocks get empty `documents`
    and keep the shared link in `source_markdown`.
- EVIDENCE:
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/RESULT.md
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/commands.md
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/capture-log.json
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/independent-inventory.json
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/discovery.json
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/opportunities.json
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/stats.json
  - docs/evidence/sources/tnc/technical-audit-2026-09-14/fidelity/{summary.json,report.md,matches.json,exceptions.json}
- RISKS:
  1. The two expired blocks that share `tdr-empresa-especializada-nap.pdf` appear to be a
     content error on the official page (distinct titles/deadlines, same PDF). After the
     fix they no longer carry a structured document; if TNC later publishes distinct PDFs
     for those blocks, documents will be restored automatically on next discovery.
  2. The news listing currently has zero signal detail pages; the legacy candidate path is
     idle under the opportunity contract by design.
  3. Expired blocks remain in discovery output as status=expired provenance; Repo A ingest
     (if ever enabled) must tolerate non-open structured rows. Fidelity only requires open
     records in-scope.
  4. Direct `py`/`python` worked this session (Python 3.13.5); no shell permission friction
     observed.
- ESCALATION: none.
- PRODUCTION ACTIONS: none (no commits, pushes, workflow dispatches, deploys, submissions,
  or catalog mutations). Audit-only dry run submitted nothing.

## Follow-up (non-blocking)

- Keep the audit hold until the normal two-audit + soak path; this verification does not
  sign off RR-05 or authorize ingest. One clean audit is recorded here; a second independent
  clean audit (different capture window) remains outstanding per AGENTS.md.
