# WWF technical audit 2026-09-14

## Result

RESULT: fixed
SOURCE: wwf
EXPECTED CONTRACT: candidate; module=discover_wwf_candidates; group=c; rollout ingest; schedule_owner=pipeline-discovery-group-c.yml; interval 60min; detail_limit=20, page_limit=5, attachment_limit=25; browser_required=false; catalog active; official entry `https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/` (EDITAIS ABERTOS / EDITAIS ENCERRADOS structural sections)
OBSERVED CONTRACT: candidate — post-fix audit-only discovery emits unique per-document candidate identities under each edital row; all open PDF-bearing rows traced; DOCX-only open edital 95223 is out_of_scope for the PDF candidate pipeline
LIFECYCLE HOLD: none in registry (ingest/active). No snapshot/RR-05/P5/P6 change claimed.
OFFICIAL INVENTORY: open=7 (6 with PDFs in-scope + 1 DOCX-only out_of_scope), closed=13, upcoming=0, excluded=0, unknown=0; rows=10; detail cap not reached (10/20)
DISCOVERY: emitted=19, rejected: prefilter_rejected=2 (resultado PDFs), year_rejected=0; errors=0; partial=false; cap_reached=false; section_parse_failed=0; detail_parse_failed=0; details_fetched=10
FIDELITY: exit code=0, blockers=0, accounting%=100.0 (6/6 open in-scope), traceability%=100.0 (19/19); non_blocking=1 (out_of_scope DOCX-only)
TESTS: `py -3.13 --version` → Python 3.13.5; `py -3.13 -m pytest tests/test_wwf_discovery.py -q` → 37 passed (36 prior + 1 new regression on unique document IDs; trace test extended for `row_source_record_id`)
CHANGES:
- scripts/discover_wwf_candidates.py — `_document_source_record_id` composes `<row_id>::<pdf_filename>`; candidates set `metadata.source_record_id` (unique per document) and `metadata.row_source_record_id`; `_write_audit_artifacts` groups discovery records by `row_source_record_id` so the module `--audit-dir` path stays one-inventory-record-per-edital-row
- tests/test_wwf_discovery.py — `test_candidates_trace_to_specific_row` asserts per-document IDs + parent row id; new `test_document_source_record_ids_are_unique`
EVIDENCE: docs/evidence/sources/wwf/technical-audit-2026-09-14/{RESULT.md,commands.md,capture-log.md,independent-inventory.json,independent-capture-summary.json,capture-log.json,discovery.json,orchestrator-source_inventory.json,candidates.json,stats.json,stats-prefix.json,fidelity/}
RISKS: live WWF heading wording or detail template (`div.template433`/`div.page-content`) drift still fail-closes via section_parse_failed/detail_parse_failed; DOCX-only open editals remain out of the PDF candidate contract (operator should monitor for conversion to PDF); per-document IDs change candidate metadata identity shape consumed by Repo A (source_record_id no longer equals bare process number — production ingest of this identity change was NOT exercised in this audit)
PRODUCTION ACTIONS: none

## Ground truth

- Independent capture via direct `requests` of the official WWF listing + 10 detail pages, 2026-09-14 ~21:48–21:54 UTC; both edital section headings present.
- Open rows (process numbers): 005936 (detail 95221), 005945 (95184), 005943 (95182), plus DOCX-only 95223 (no process number in title; content area has only `.docx` TDR links).
- Closed rows (process numbers): 005874, 005746, 005789, 005812, 005845, 005722 — provenance only (closed expected for WWF).
- Principal open documents: `carta_convite*` / `carta-convite*` PDFs plus `divulgacao_*` announcement PDFs on `wwfbrnew.awsassets.panda.org`.
- Detail cap 20 not reached (10 details). No listing pagination beyond the single official page.

## Pre-fix baseline (this session, retained for provenance)

- First audit-only run (`audit-run-1`) emitted 19 candidates with shared process-number `source_record_id`s. Orchestrator `write_candidate_audit` flattens one inventory/discovery record per candidate PDF → 18 blocking `duplicate_identity` exceptions; internal fidelity exit 1; accounting/traceability not passable.
- Root cause: candidate-contract audit artifacts are written per candidate, but multi-PDF edital rows reused one process-number identity. Fix is source-local (wwf adapter candidate metadata + module audit grouping).
- External fidelity against the independent per-document inventory and post-fix discovery: exit 0, 0 blockers, 100%/100%.
