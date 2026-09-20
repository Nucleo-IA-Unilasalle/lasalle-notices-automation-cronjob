# Source Fidelity Report

## Quantitative Gates

- Inventory accounting: 100.0% (0/0)
- Candidate traceability: 100.0% (1/1)

### Blocking exception counts
- authoritative_deadline_mismatch: 0
- authoritative_status_mismatch: 0
- duplicate_identity: 0
- extra_submission: 0
- identity_mismatch: 0
- missing_open: 0
- parser_failure: 0
- renderability_mismatch: 0

Total blocking exceptions: 0

## Matches

- key=('worldbank', 'https://thedocs.worldbank.org/en/doc/15fc51eee03c29f8e5ed847b76ed9d55-0090052026/original/SIEF-Call-8-EdTech-040926.pdf') method=stable_id
  - status: inv=closed discovery=unknown dashboard=unknown match=True
  - deadline: inv=2026-05-19T00:00:00Z discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True

## Exceptions

- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: deadline
  - inventory: 2026-05-19T00:00:00Z
  - origin: discovery
- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: closed
  - origin: discovery
- [non_blocking] out_of_scope
  - origin: inventory
  - rationale: Funding-decision announcement PDF linked under RELATED > Funding decisions. No adapter signal token (call for proposals, request for proposals, expression of interest, eoi, procurement, funding strategy, resolution) in href, path, link text, title or aria-label; outside the adapter signal-token contract. HEAD 200 application/pdf 228904 bytes (2026-09-14T21:47:56Z).
  - record: {'source_key': 'worldbank', 'source_record_id': 'https://thedocs.worldbank.org/en/doc/8edffdcd096b9275c8786996b33c21ce-0090052026/original/Call-8-announcement.pdf', 'canonical_url': 'https://thedocs.worldbank.org/en/doc/8edffdcd096b9275c8786996b33c21ce-0090052026/original/Call-8-announcement.pdf', 'title': 'Presenting the evaluations of the EdTech for Foundational Learning Window - funding-decision announcement PDF', 'status': 'excluded', 'published_at': None, 'deadline': None, 'document_urls': ['https://thedocs.worldbank.org/en/doc/8edffdcd096b9275c8786996b33c21ce-0090052026/original/Call-8-announcement.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope', 'evidence': {'rationale': 'Funding-decision announcement PDF linked under RELATED > Funding decisions. No adapter signal token (call for proposals, request for proposals, expression of interest, eoi, procurement, funding strategy, resolution) in href, path, link text, title or aria-label; outside the adapter signal-token contract. HEAD 200 application/pdf 228904 bytes (2026-09-14T21:47:56Z).'}}
