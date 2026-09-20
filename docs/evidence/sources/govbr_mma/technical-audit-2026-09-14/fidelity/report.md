# Source Fidelity Report

## Quantitative Gates

- Inventory accounting: 100.0% (0/0)
- Candidate traceability: 100.0% (5/5)

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

- key=('govbr_mma', 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-chamamento-publico-locacao-correio.pdf') method=stable_id
  - status: inv=closed discovery=unknown dashboard=unknown match=True
  - deadline: inv=unknown discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True
- key=('govbr_mma', 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-chamamento-publico-locacao-dou.pdf') method=stable_id
  - status: inv=closed discovery=unknown dashboard=unknown match=True
  - deadline: inv=unknown discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True
- key=('govbr_mma', 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-chamamento-publico-locacao-jornal-brasilia.pdf') method=stable_id
  - status: inv=closed discovery=unknown dashboard=unknown match=True
  - deadline: inv=unknown discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True
- key=('govbr_mma', 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso.pdf') method=stable_id
  - status: inv=closed discovery=unknown dashboard=unknown match=True
  - deadline: inv=unknown discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True
- key=('govbr_mma', 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/edital-de-chamamento-publico-locacao-imovel-02.pdf') method=stable_id
  - status: inv=closed discovery=unknown dashboard=unknown match=True
  - deadline: inv=2017-01-20T00:00:00Z discovery=unknown dashboard=unknown match=True
  - renderable: inv=unknown discovery=unknown dashboard=unknown match=True

## Exceptions

- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: deadline
  - inventory: 2017-01-20T00:00:00Z
  - origin: discovery
- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: closed
  - origin: discovery
- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: closed
  - origin: discovery
- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: closed
  - origin: discovery
- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: closed
  - origin: discovery
- [non_blocking] missing_optional_metadata
  - discovery: None
  - field: status
  - inventory: closed
  - origin: discovery
- [non_blocking] out_of_scope
  - exclusion: EDITAL_EXCLUSION_PATTERNS errata; correct prefilter rejection of closed 2017 chamamento companion document
  - origin: inventory
  - record: {'source_key': 'govbr_mma', 'source_record_id': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/chamamento-publico-aviso-de-errata.pdf', 'canonical_url': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/chamamento-publico-aviso-de-errata.pdf', 'title': 'Aviso de Errata - Chamamento Público Locação de Imóvel (excluded: errata prefilter)', 'status': 'closed', 'published_at': None, 'deadline': None, 'document_urls': ['https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/chamamento-publico-aviso-de-errata.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope', 'evidence': {'exclusion': 'EDITAL_EXCLUSION_PATTERNS errata; correct prefilter rejection of closed 2017 chamamento companion document'}}
- [non_blocking] out_of_scope
  - exclusion: EDITAL_EXCLUSION_PATTERNS resultado; result notice of closed 2017 chamamento
  - origin: inventory
  - record: {'source_key': 'govbr_mma', 'source_record_id': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-correiobraziliense.pdf', 'canonical_url': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-correiobraziliense.pdf', 'title': 'Aviso de Resultado - Chamamento Público - Correio Braziliense (excluded: resultado prefilter)', 'status': 'closed', 'published_at': None, 'deadline': None, 'document_urls': ['https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-correiobraziliense.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope', 'evidence': {'exclusion': 'EDITAL_EXCLUSION_PATTERNS resultado; result notice of closed 2017 chamamento'}}
- [non_blocking] out_of_scope
  - exclusion: EDITAL_EXCLUSION_PATTERNS resultado; result notice of closed 2017 chamamento
  - origin: inventory
  - record: {'source_key': 'govbr_mma', 'source_record_id': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-dou.pdf', 'canonical_url': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-dou.pdf', 'title': 'Aviso de Resultado - Chamamento Público - DOU (excluded: resultado prefilter)', 'status': 'closed', 'published_at': None, 'deadline': None, 'document_urls': ['https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-dou.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope', 'evidence': {'exclusion': 'EDITAL_EXCLUSION_PATTERNS resultado; result notice of closed 2017 chamamento'}}
- [non_blocking] out_of_scope
  - exclusion: EDITAL_EXCLUSION_PATTERNS resultado; result notice of closed 2017 chamamento
  - origin: inventory
  - record: {'source_key': 'govbr_mma', 'source_record_id': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-jornaldebrasilia.pdf', 'canonical_url': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-jornaldebrasilia.pdf', 'title': 'Aviso de Resultado - Chamamento Público - Jornal de Brasília (excluded: resultado prefilter)', 'status': 'closed', 'published_at': None, 'deadline': None, 'document_urls': ['https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/chamamento-publico-locacao-de-imovel/aviso-resultado-chamamento-jornaldebrasilia.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope', 'evidence': {'exclusion': 'EDITAL_EXCLUSION_PATTERNS resultado; result notice of closed 2017 chamamento'}}
- [non_blocking] out_of_scope
  - exclusion: extracted_year=2016 rejected by GOVBR_MMA_MIN_NOTICE_YEAR=2026; administrative portaria, not an open call
  - origin: inventory
  - record: {'source_key': 'govbr_mma', 'source_record_id': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/portarias/PORTARIAPREGOEIROSn22026_10_2016.pdf', 'canonical_url': 'https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/portarias/PORTARIAPREGOEIROSn22026_10_2016.pdf', 'title': 'Portaria MMA nº 220 de 26/10/2016 - Equipe de Pregão (excluded: year guard 2016 < 2026)', 'status': 'closed', 'published_at': None, 'deadline': None, 'document_urls': ['https://www.gov.br/mma/pt-br/acesso-a-informacao/licitacoes-e-contratos/editais/portarias/PORTARIAPREGOEIROSn22026_10_2016.pdf'], 'document_hashes': [], 'reason_code': 'out_of_scope', 'evidence': {'exclusion': 'extracted_year=2016 rejected by GOVBR_MMA_MIN_NOTICE_YEAR=2026; administrative portaria, not an open call'}}
