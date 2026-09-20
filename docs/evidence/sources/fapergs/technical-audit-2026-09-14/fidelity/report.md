# Source Fidelity Report

## Quantitative Gates

- Inventory accounting: 100.0% (1/1)
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

- key=('fapergs', 'https://fapergs.rs.gov.br/upload/arquivos/202607/27144415-edital-06-2026-profix-cb.pdf') method=stable_id
  - status: inv=open discovery=unknown dashboard=unknown match=True
  - deadline: inv=unknown discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True

## Exceptions

- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: open
  - origin: discovery
- [non_blocking] out_of_scope
  - origin: inventory
  - record: {'source_key': 'fapergs', 'source_record_id': 'chamada-confap-propostas-do-programa-desafios-da-amazonia-2026-iniciativa-amazonia-10', 'canonical_url': 'https://fapergs.rs.gov.br/chamada-confap-propostas-do-programa-desafios-da-amazonia-2026-iniciativa-amazonia-10', 'title': 'CHAMADA CONFAP - PROPOSTAS DO PROGRAMA DESAFIOS DA AMAZONIA (2026) - Iniciativa Amazonia +10', 'status': 'open', 'published_at': None, 'deadline': None, 'document_urls': [], 'document_hashes': [], 'reason_code': 'out_of_scope'}
- [non_blocking] out_of_scope
  - origin: inventory
  - record: {'source_key': 'fapergs', 'source_record_id': 'programa-horizon-europe-da-comunidade-europeia', 'canonical_url': 'https://fapergs.rs.gov.br/programa-horizon-europe-da-comunidade-europeia', 'title': 'Programa Horizon Europe da Comunidade Europeia (permanent program page; guidelines PDF 2024 year-guard rejected)', 'status': 'open', 'published_at': None, 'deadline': None, 'document_urls': ['https://fapergs.rs.gov.br/upload/arquivos/202410/03160733-pt-horizon-europe-fapergs-guidelines-2024-v4.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope'}
