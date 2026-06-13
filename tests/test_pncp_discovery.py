from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from discover_pncp_candidates import (
    PNCP_DOCUMENT_TYPE_PRIORITIES,
    PNCP_MAX_PAGES_PER_QUERY,
    PNCP_PAGE_SIZE,
    build_candidate,
    fetch_pncp_records,
    pncp_document_priority,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    *,
    control: str = "2026-0001",
    ano: int = 2026,
    seq: int = 1,
    modality_id: int = 6,
    modality_nome: str = "Pregão Eletrônico",
    cnpj: str = "12345678000190",
    status: str = "1",
    data_atualizacao_global: str = "20260612150000",
    data_atualizacao: str = "20260612140000",
    data_publicacao: str = "20260612",
    data_abertura: str | None = "20260620100000",
    data_encerramento: str | None = "20260625180000",
    sequencial_documento: int | None = 1,
    tipo_documento_nome: str = "Edital",
    titulo: str = "Test Title",
    processo: str = "001/2026",
    info_complementar: str = "",
    link_sistema: str = "https://example.com",
    link_processo: str = "https://example.com/processo",
    municipio: str = "São Paulo",
    uf: str = "SP",
) -> dict[str, Any]:
    return {
        "numeroControlePNCP": control,
        "anoCompra": ano,
        "sequencialCompra": seq,
        "numeroCompra": f"{seq:04d}",
        "modalidadeId": modality_id,
        "modalidadeNome": modality_nome,
        "srp": True,
        "objetoCompra": "Aquisição de materiais",
        "processo": processo,
        "informacaoComplementar": info_complementar,
        "situacaoCompraId": int(status),
        "situacaoCompraNome": "Aberta" if status == "1" else "Fechada",
        "dataPublicacaoPncp": data_publicacao,
        "dataAberturaProposta": data_abertura,
        "dataEncerramentoProposta": data_encerramento,
        "dataAtualizacaoGlobal": data_atualizacao_global,
        "dataAtualizacao": data_atualizacao,
        "orgaoEntidade": {"cnpj": cnpj},
        "unidadeOrgao": {"municipioNome": municipio, "ufSigla": uf},
        "linkSistemaOrigem": link_sistema,
        "linkProcessoEletronico": link_processo,
    }


def _make_doc(
    *,
    sequencial: int = 1,
    tipo: str = "Edital",
    titulo: str = "Test Title",
    url: str = "https://example.com/doc.pdf",
) -> dict[str, Any]:
    return {
        "sequencialDocumento": sequencial,
        "tipoDocumentoNome": tipo,
        "titulo": titulo,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Modality code constants
# ---------------------------------------------------------------------------

class TestModalityCodes:
    def test_modality_codes_are_6_8_4(self) -> None:
        from discover_pncp_candidates import PNCP_DEFAULT_MODALITY_CODES
        assert PNCP_DEFAULT_MODALITY_CODES == ("6", "8", "4")

    def test_pregao_eletronico_is_modality_6(self) -> None:
        from discover_pncp_candidates import PNCP_MODALITY_NAMES
        assert PNCP_MODALITY_NAMES["6"] == "Pregão Eletrônico"

    def test_dispensa_is_modality_8(self) -> None:
        from discover_pncp_candidates import PNCP_MODALITY_NAMES
        assert PNCP_MODALITY_NAMES["8"] == "Dispensa de Licitação"

    def test_concorrencia_eletronica_is_modality_4(self) -> None:
        from discover_pncp_candidates import PNCP_MODALITY_NAMES
        assert PNCP_MODALITY_NAMES["4"] == "Concorrência Eletrônica"


# ---------------------------------------------------------------------------
# Endpoint configuration
# ---------------------------------------------------------------------------

class TestEndpoints:
    def test_proposta_url_exists(self) -> None:
        from discover_pncp_candidates import PNCP_PROPOSTA_URL
        assert PNCP_PROPOSTA_URL == "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"

    def test_publicacao_url_exists(self) -> None:
        from discover_pncp_candidates import PNCP_API_URL
        assert PNCP_API_URL == "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"

    def test_atualizacao_url_exists(self) -> None:
        from discover_pncp_candidates import PNCP_ATUALIZACAO_URL
        assert PNCP_ATUALIZACAO_URL == "https://pncp.gov.br/api/consulta/v1/contratacoes/atualizacao"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_pagination_starts_at_1(self) -> None:
        from discover_pncp_candidates import fetch_pncp_search_pages
        with patch("discover_pncp_candidates.fetch_json") as mock_fetch:
            mock_fetch.return_value = {"data": [], "totalPaginas": 1}
            fetch_pncp_search_pages("https://example.com/api", {"foo": "bar"})
            call_url = mock_fetch.call_args[0][0]
            assert "pagina=1" in call_url

    def test_page_size_is_50(self) -> None:
        from discover_pncp_candidates import fetch_pncp_search_pages
        with patch("discover_pncp_candidates.fetch_json") as mock_fetch:
            mock_fetch.return_value = {"data": [], "totalPaginas": 1}
            fetch_pncp_search_pages("https://example.com/api", {"foo": "bar"})
            call_url = mock_fetch.call_args[0][0]
            assert "tamanhoPagina=50" in call_url


# ---------------------------------------------------------------------------
# Empty / 204 responses
# ---------------------------------------------------------------------------

class TestEmptyResponses:
    def test_204_response_succeeds(self) -> None:
        from discover_pncp_candidates import fetch_pncp_search_pages
        with patch("discover_pncp_candidates.fetch_json") as mock_fetch:
            mock_fetch.return_value = {"data": None, "totalPaginas": 1}
            records = fetch_pncp_search_pages("https://example.com/api", {})
            assert records == []

    def test_empty_data_list_succeeds(self) -> None:
        from discover_pncp_candidates import fetch_pncp_search_pages
        with patch("discover_pncp_candidates.fetch_json") as mock_fetch:
            mock_fetch.return_value = {"data": [], "totalPaginas": 1}
            records = fetch_pncp_search_pages("https://example.com/api", {})
            assert records == []


# ---------------------------------------------------------------------------
# /proposta behavior
# ---------------------------------------------------------------------------

class TestPropostaEndpoint:
    def test_proposta_filtered_locally_by_modality(self) -> None:
        from discover_pncp_candidates import PNCP_PROPOSTA_URL
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = [
                _make_record(modality_id=6),
                _make_record(modality_id=5, control="OTHER-001"),
                _make_record(modality_id=8, control="OTHER-002"),
                _make_record(modality_id=4, control="OTHER-003"),
                _make_record(modality_id=10, control="OTHER-004"),
            ]
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    with patch("discover_pncp_candidates.fetch_pncp_documents", return_value=([], False)):
                        records = fetch_pncp_records()
            modality_ids = {r["modalidadeId"] for r in records}
            assert modality_ids.issubset({6, 8, 4})


# ---------------------------------------------------------------------------
# /publicacao queries per modality
# ---------------------------------------------------------------------------

class TestPublicacaoEndpoint:
    def test_publicacao_queried_per_modality(self) -> None:
        from discover_pncp_candidates import PNCP_API_URL, PNCP_DEFAULT_MODALITY_CODES
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = []
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    with patch("discover_pncp_candidates.fetch_pncp_documents", return_value=([], False)):
                        fetch_pncp_records()
        publicacao_calls = [
            c for c in mock_search.call_args_list
            if c[0][0] == PNCP_API_URL
        ]
        assert len(publicacao_calls) == len(PNCP_DEFAULT_MODALITY_CODES)
        for call in publicacao_calls:
            assert "codigoModalidadeContratacao" in call[0][1]


# ---------------------------------------------------------------------------
# /atualizacao checkpoint behavior
# ---------------------------------------------------------------------------

class TestAtualizacaoCheckpoint:
    def test_atualizacao_uses_checkpoint(self) -> None:
        from discover_pncp_candidates import PNCP_ATUALIZACAO_URL
        checkpoint_time = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = []
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=checkpoint_time):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    with patch("discover_pncp_candidates.fetch_pncp_documents", return_value=([], False)):
                        fetch_pncp_records()
        atualizacao_calls = [
            c for c in mock_search.call_args_list
            if c[0][0] == PNCP_ATUALIZACAO_URL
        ]
        assert len(atualizacao_calls) == 3

    def test_atualizacao_two_hour_overlap(self) -> None:
        from discover_pncp_candidates import PNCP_ATUALIZACAO_URL
        checkpoint_time = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = []
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=checkpoint_time):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    fetch_pncp_records()
        atualizacao_calls = [
            c for c in mock_search.call_args_list
            if c[0][0] == PNCP_ATUALIZACAO_URL
        ]
        overlap_start = datetime(2026, 6, 12, 8, 0, 0, tzinfo=timezone.utc)
        assert atualizacao_calls[0][0][1]["dataInicial"] == overlap_start.strftime("%Y%m%d%H%M%S")

    def test_missing_checkpoint_uses_48h_window(self) -> None:
        from discover_pncp_candidates import PNCP_ATUALIZACAO_URL
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = []
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    fetch_pncp_records()
        atualizacao_calls = [
            c for c in mock_search.call_args_list
            if c[0][0] == PNCP_ATUALIZACAO_URL
        ]
        assert len(atualizacao_calls) > 0
        data_inicial = atualizacao_calls[0][0][1]["dataInicial"]
        data_final = atualizacao_calls[0][0][1]["dataFinal"]
        fmt = "%Y%m%d%H%M%S"
        start = datetime.strptime(data_inicial, fmt)
        end = datetime.strptime(data_final, fmt)
        assert (end - start).total_seconds() == 48 * 3600


# ---------------------------------------------------------------------------
# Checkpoint advancement
# ---------------------------------------------------------------------------

class TestCheckpointAdvancement:
    def test_checkpoint_advanced_only_on_clean_run(self) -> None:
        with patch("discover_pncp_candidates.fetch_pncp_search_pages", return_value=[]):
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None) as mock_load:
                with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                    with patch("discover_pncp_candidates.fetch_pncp_documents", return_value=([], False)):
                        fetch_pncp_records()
            assert mock_save.called

    def test_failed_run_does_not_advance_checkpoint(self) -> None:
        with patch("discover_pncp_candidates.fetch_pncp_search_pages", side_effect=Exception("network")):
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                    try:
                        fetch_pncp_records()
                    except Exception:
                        pass
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_duplicate_records_retain_newest_by_data_atualizacao_global(self) -> None:
        old = _make_record(control="DUP-001", data_atualizacao_global="20260610100000", data_abertura=None)
        new = _make_record(control="DUP-001", data_atualizacao_global="20260612100000", data_abertura=None)
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = [old, new]
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    with patch("discover_pncp_candidates.fetch_pncp_documents", return_value=([], False)):
                        records = fetch_pncp_records()
        dup_records = [r for r in records if r["numeroControlePNCP"] == "DUP-001"]
        assert len(dup_records) == 1
        assert dup_records[0]["dataAtualizacaoGlobal"] == "20260612100000"

    def test_duplicate_records_fallback_to_data_atualizacao(self) -> None:
        old = _make_record(
            control="DUP-002",
            data_atualizacao_global="20260612100000",
            data_atualizacao="20260610100000",
            data_abertura=None,
        )
        new = _make_record(
            control="DUP-002",
            data_atualizacao_global="20260612100000",
            data_atualizacao="20260612120000",
            data_abertura=None,
        )
        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = [old, new]
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint"):
                    with patch("discover_pncp_candidates.fetch_pncp_documents", return_value=([], False)):
                        records = fetch_pncp_records()
        dup_records = [r for r in records if r["numeroControlePNCP"] == "DUP-002"]
        assert len(dup_records) == 1
        assert dup_records[0]["dataAtualizacao"] == "20260612120000"


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestTimestampParsing:
    def test_brasilia_timestamp_parses(self) -> None:
        from discover_pncp_candidates import parse_pncp_datetime
        result = parse_pncp_datetime("20260612150000")
        assert result is not None
        assert result.year == 2026

    def test_explicit_offset_parses(self) -> None:
        from discover_pncp_candidates import parse_pncp_datetime
        result = parse_pncp_datetime("2026-06-12T15:00:00-03:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_normalized_to_utc(self) -> None:
        from discover_pncp_candidates import parse_pncp_datetime
        result = parse_pncp_datetime("2026-06-12T15:00:00-03:00")
        assert result is not None
        assert result.utcoffset() == timedelta(hours=-3)


# ---------------------------------------------------------------------------
# Record filtering / exclusion
# ---------------------------------------------------------------------------

class TestRecordFiltering:
    def test_upcoming_records_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="1", data_encerramento="20270101180000")
        assert is_pncp_record_actionable(record) is False

    def test_expired_deadline_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="1", data_encerramento="20200101180000")
        assert is_pncp_record_actionable(record) is False

    def test_revoked_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="2")
        assert is_pncp_record_actionable(record) is False

    def test_annulled_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="3")
        assert is_pncp_record_actionable(record) is False

    def test_suspended_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="4")
        assert is_pncp_record_actionable(record) is False

    def test_missing_deadline_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="1", data_encerramento=None)
        assert is_pncp_record_actionable(record) is False

    def test_malformed_date_excluded(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        record = _make_record(status="1", data_encerramento="not-a-date")
        assert is_pncp_record_actionable(record) is False

    def test_actionable_record_accepted(self) -> None:
        from discover_pncp_candidates import is_pncp_record_actionable
        future = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y%m%d%H%M%S")
        record = _make_record(status="1", data_encerramento=future, data_abertura=None)
        assert is_pncp_record_actionable(record) is True


# ---------------------------------------------------------------------------
# Pre-download validation
# ---------------------------------------------------------------------------

class TestPreDownloadValidation:
    def test_missing_control_number_rejected(self) -> None:
        from discover_pncp_candidates import validate_pncp_record_for_download
        record = _make_record()
        record["numeroControlePNCP"] = ""
        assert validate_pncp_record_for_download(record) is False

    def test_missing_sequencial_compra_rejected(self) -> None:
        from discover_pncp_candidates import validate_pncp_record_for_download
        record = _make_record()
        record["sequencialCompra"] = None
        assert validate_pncp_record_for_download(record) is False

    def test_missing_ano_compra_rejected(self) -> None:
        from discover_pncp_candidates import validate_pncp_record_for_download
        record = _make_record()
        record["anoCompra"] = None
        assert validate_pncp_record_for_download(record) is False

    def test_valid_record_accepted(self) -> None:
        from discover_pncp_candidates import validate_pncp_record_for_download
        record = _make_record()
        assert validate_pncp_record_for_download(record) is True


# ---------------------------------------------------------------------------
# Metadata capture
# ---------------------------------------------------------------------------

class TestMetadataCapture:
    def test_build_candidate_captures_all_metadata_fields(self) -> None:
        record = _make_record()
        doc = _make_doc()
        candidate = build_candidate(record, doc)
        assert candidate is not None
        meta = candidate["metadata"]
        assert meta["numeroControlePNCP"] == "2026-0001"
        assert meta["anoCompra"] == 2026
        assert meta["sequencialCompra"] == 1
        assert meta["numeroCompra"] == "0001"
        assert meta["sequencialDocumento"] == 1
        assert meta["tipoDocumentoNome"] == "Edital"
        assert meta["titulo"] == "Test Title"
        assert meta["priority"] == PNCP_DOCUMENT_TYPE_PRIORITIES["edital"]
        assert meta["dataPublicacaoPncp"] == "20260612"
        assert meta["dataAberturaProposta"] == "20260620100000"
        assert meta["dataEncerramentoProposta"] == "20260625180000"
        assert meta["situacaoCompraId"] == 1
        assert meta["situacaoCompraNome"] == "Aberta"
        assert meta["dataAtualizacaoGlobal"] == "20260612150000"
        assert meta["dataAtualizacao"] == "20260612140000"
        assert meta["modalidadeId"] == 6
        assert meta["modalidadeNome"] == "Pregão Eletrônico"
        assert meta["srp"] is True
        assert meta["objetoCompra"] == "Aquisição de materiais"
        assert meta["processo"] == "001/2026"
        assert meta["informacaoComplementar"] == ""
        assert meta["linkSistemaOrigem"] == "https://example.com"
        assert meta["linkProcessoEletronico"] == "https://example.com/processo"
        assert meta["cnpj"] == "12345678000190"
        assert meta["municipioNome"] == "São Paulo"
        assert meta["ufSigla"] == "SP"

    def test_priority_is_from_document_priority_function(self) -> None:
        record = _make_record()
        doc = _make_doc(tipo="Edital", titulo="Edital de Pregão")
        candidate = build_candidate(record, doc)
        assert candidate is not None
        assert candidate["metadata"]["priority"] == pncp_document_priority(doc)


# ---------------------------------------------------------------------------
# Document priority
# ---------------------------------------------------------------------------

class TestDocumentPriority:
    def test_edital_highest_priority(self) -> None:
        doc = _make_doc(tipo="Edital")
        assert pncp_document_priority(doc) == 10

    def test_aviso_contratacao_direta_priority(self) -> None:
        doc = _make_doc(tipo="Aviso de Contratação Direta")
        assert pncp_document_priority(doc) == 20

    def test_termo_referencia_priority(self) -> None:
        doc = _make_doc(tipo="Termo de Referência")
        assert pncp_document_priority(doc) == 30

    def test_unknown_type_lowest_priority(self) -> None:
        doc = _make_doc(tipo="Unknown Document Type")
        assert pncp_document_priority(doc) == 100
