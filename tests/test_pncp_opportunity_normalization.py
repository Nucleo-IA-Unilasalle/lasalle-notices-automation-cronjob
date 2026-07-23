from datetime import datetime, timezone

from discover_pncp_candidates import build_opportunity


def _record():
    return {
        "numeroControlePNCP": "12345678000190-1-000001/2026",
        "anoCompra": 2026,
        "sequencialCompra": 1,
        "orgaoEntidade": {"cnpj": "12345678000190"},
        "objetoCompra": "Contratacao de servicos ambientais",
        "processo": "001/2026",
        "situacaoCompraNome": "Aberta",
        "modalidadeNome": "Pregao Eletronico",
        "dataPublicacaoPncp": "20260701090000",
        "dataAberturaProposta": "20260701100000",
        "dataEncerramentoProposta": "20260801180000",
        "dataAtualizacaoGlobal": "20260722120000",
    }


def test_api_only_record_has_parent_without_fake_document_sequence():
    opportunity = build_opportunity(
        _record(), [], snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc)
    )
    assert opportunity is not None
    assert opportunity["source_record_id"] == "12345678000190-1-000001/2026"
    assert opportunity["documents"] == []
    assert opportunity["opportunity_type"] == "procurement"


def test_multiple_sequences_are_children_sorted_by_priority():
    documents = [
        {
            "sequencialDocumento": 2,
            "tipoDocumentoNome": "Termo de Referencia",
            "titulo": "TDR",
            "url": "https://pncp.gov.br/doc/2.pdf",
        },
        {
            "sequencialDocumento": 1,
            "tipoDocumentoNome": "Edital",
            "titulo": "Edital",
            "url": "https://pncp.gov.br/doc/1.pdf",
        },
    ]
    opportunity = build_opportunity(
        _record(), documents, snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc)
    )
    assert opportunity is not None
    assert [item["source_document_id"] for item in opportunity["documents"]] == [
        "1",
        "2",
    ]
