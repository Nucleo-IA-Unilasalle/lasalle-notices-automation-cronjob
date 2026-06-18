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
    _save_update_checkpoint,
    build_candidate,
    fetch_pncp_records,
    pncp_document_priority,
    process_candidate,
)
from pncp_http import DownloadResult, DownloadError, download_pncp_pdf


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
                        records, _ = fetch_pncp_records()
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
        overlap_start = datetime(2026, 6, 12, 5, 0, 0)
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
    def test_checkpoint_not_saved_when_no_candidates(self) -> None:
        from discover_pncp_candidates import main
        with patch("discover_pncp_candidates.fetch_pncp_search_pages", return_value=[]):
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                    with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
                        result = main()
        assert result == 0
        mock_save.assert_not_called()

    def test_failed_run_does_not_advance_checkpoint(self) -> None:
        from discover_pncp_candidates import main
        with patch("discover_pncp_candidates.fetch_json", side_effect=Exception("network")):
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                    with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
                        result = main()
        assert result == 1
        mock_save.assert_not_called()

    def test_submission_batch_failure_prevents_checkpoint(self) -> None:
        from discover_pncp_candidates import main
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "X-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }
        import sys
        ocr_mod = MagicMock()
        config_mod = MagicMock()
        sys.modules["ocr_worker.ocr_extraction_config"] = config_mod
        sys.modules["ocr_worker.pdf_markdown_extractor"] = ocr_mod
        try:
            with patch("discover_pncp_candidates.discover_candidates") as mock_disc:
                mock_disc.return_value = (
                    {"records": 1, "candidates": 1},
                    [candidate],
                    datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
                )
                with patch("discover_pncp_candidates.submit_candidates") as mock_submit:
                    mock_submit.return_value = {
                        "total": 1,
                        "submitted": 0,
                        "failed_batches": 1,
                        "errors": ["batch 1: HTTP 503"],
                    }
                    with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
                        with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                            main()
                    mock_save.assert_not_called()
        finally:
            sys.modules.pop("ocr_worker.ocr_extraction_config", None)
            sys.modules.pop("ocr_worker.pdf_markdown_extractor", None)

    def test_all_ocr_failures_fail_run_and_do_not_advance_checkpoint(self) -> None:
        from discover_pncp_candidates import main

        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "OCR-001", "sequencialDocumento": 1},
        }
        failed_result = {
            "url": "https://example.com/doc.pdf",
            "metadata": candidate["metadata"],
            "error": "ocr: Paddle runtime failure",
        }

        import sys
        ocr_mod = MagicMock()
        config_mod = MagicMock()
        sys.modules["ocr_worker.ocr_extraction_config"] = config_mod
        sys.modules["ocr_worker.pdf_markdown_extractor"] = ocr_mod
        try:
            with patch("discover_pncp_candidates.discover_candidates") as mock_disc:
                mock_disc.return_value = (
                    {"records": 1, "candidates": 1},
                    [candidate],
                    datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
                )
                with patch("discover_pncp_candidates.process_candidate", return_value=failed_result):
                    with patch("discover_pncp_candidates.submit_candidates") as mock_submit:
                        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
                            with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                                result = main()

            assert result == 1
            mock_submit.assert_not_called()
            mock_save.assert_not_called()
        finally:
            sys.modules.pop("ocr_worker.ocr_extraction_config", None)
            sys.modules.pop("ocr_worker.pdf_markdown_extractor", None)

    def test_processing_continues_past_bad_pdfs_until_submit_cap(self) -> None:
        from discover_pncp_candidates import main

        bad = {
            "url": "https://example.com/bad.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "BAD-001", "sequencialDocumento": 1},
        }
        good = {
            "url": "https://example.com/good.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "OK-001", "sequencialDocumento": 1},
        }
        skipped = {
            "url": "https://example.com/skipped.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "SKIP-001", "sequencialDocumento": 1},
        }
        failed_result = {
            "url": bad["url"],
            "metadata": bad["metadata"],
            "error": "download: not a valid PDF",
        }
        success_result = {
            **good,
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        import sys
        ocr_mod = MagicMock()
        config_mod = MagicMock()
        sys.modules["ocr_worker.ocr_extraction_config"] = config_mod
        sys.modules["ocr_worker.pdf_markdown_extractor"] = ocr_mod
        try:
            with patch("discover_pncp_candidates.discover_candidates") as mock_disc:
                mock_disc.return_value = (
                    {"records": 3, "candidates": 3},
                    [bad, good, skipped],
                    datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
                )
                with patch("discover_pncp_candidates.process_candidate", side_effect=[failed_result, success_result]) as mock_process:
                    with patch("discover_pncp_candidates.submit_candidates") as mock_submit:
                        mock_submit.return_value = {
                            "total": 2,
                            "submitted": 1,
                            "failed_batches": 0,
                            "errors": [],
                        }
                        with patch("discover_pncp_candidates.PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN", 1, create=True):
                            with patch("discover_pncp_candidates.PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN", 3, create=True):
                                with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
                                    with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                                        result = main()

            assert result == 0
            assert [call.args[0]["url"] for call in mock_process.call_args_list] == [
                bad["url"],
                good["url"],
            ]
            mock_submit.assert_called_once_with([failed_result, success_result])
            mock_save.assert_called_once()
        finally:
            sys.modules.pop("ocr_worker.ocr_extraction_config", None)
            sys.modules.pop("ocr_worker.pdf_markdown_extractor", None)

    def test_checkpoint_saved_after_successful_pipeline(self) -> None:
        from discover_pncp_candidates import main
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "OK-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }
        import sys
        ocr_mod = MagicMock()
        config_mod = MagicMock()
        sys.modules["ocr_worker.ocr_extraction_config"] = config_mod
        sys.modules["ocr_worker.pdf_markdown_extractor"] = ocr_mod
        try:
            with patch("discover_pncp_candidates.discover_candidates") as mock_disc:
                mock_disc.return_value = (
                    {"records": 1, "candidates": 1},
                    [candidate],
                    datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
                )
                with patch("discover_pncp_candidates.process_candidate", return_value=candidate):
                    with patch("discover_pncp_candidates.submit_candidates") as mock_submit:
                        mock_submit.return_value = {
                            "total": 1,
                            "submitted": 1,
                            "failed_batches": 0,
                            "errors": [],
                        }
                        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
                            with patch("discover_pncp_candidates._save_update_checkpoint") as mock_save:
                                main()
                        mock_save.assert_called_once()
        finally:
            sys.modules.pop("ocr_worker.ocr_extraction_config", None)
            sys.modules.pop("ocr_worker.pdf_markdown_extractor", None)


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
                        records, _ = fetch_pncp_records()
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
                        records, _ = fetch_pncp_records()
        dup_records = [r for r in records if r["numeroControlePNCP"] == "DUP-002"]
        assert len(dup_records) == 1
        assert dup_records[0]["dataAtualizacao"] == "20260612120000"


# ---------------------------------------------------------------------------
# 2026 eligibility filter
# ---------------------------------------------------------------------------

class TestEligibilityYearFilter:
    def test_fetch_records_excludes_pre_2026_notices(self) -> None:
        old = _make_record(control="OLD-2025", ano=2025, data_abertura=None)
        current = _make_record(control="NEW-2026", ano=2026, data_abertura=None)

        with patch("discover_pncp_candidates.fetch_pncp_search_pages") as mock_search:
            mock_search.return_value = [old, current]
            with patch("discover_pncp_candidates._load_update_checkpoint", return_value=None):
                records, _ = fetch_pncp_records()

        assert [record["numeroControlePNCP"] for record in records] == ["NEW-2026"]


# ---------------------------------------------------------------------------
# Candidate run cap
# ---------------------------------------------------------------------------

class TestCandidateRunCap:
    def test_discover_candidates_stops_at_configured_candidate_cap(self) -> None:
        from discover_pncp_candidates import discover_candidates

        records = [
            _make_record(control="CAP-001", seq=1),
            _make_record(control="CAP-002", seq=2),
        ]

        def docs_for(record: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
            return (
                [
                    _make_doc(
                        url=f"https://example.com/{record['numeroControlePNCP']}.pdf",
                    )
                ],
                False,
            )

        with patch("discover_pncp_candidates.fetch_pncp_records") as mock_records:
            mock_records.return_value = (records, datetime(2026, 6, 12, tzinfo=timezone.utc))
            with patch("discover_pncp_candidates.fetch_pncp_documents", side_effect=docs_for):
                with patch("discover_pncp_candidates.PNCP_MAX_CANDIDATES_PER_RUN", 1, create=True):
                    stats, candidates, _ = discover_candidates()

        assert stats["candidates"] == 1
        assert [c["metadata"]["numeroControlePNCP"] for c in candidates] == ["CAP-001"]


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


# ---------------------------------------------------------------------------
# Download, validate, and OCR processing
# ---------------------------------------------------------------------------


class TestDownloadPncpPdf:
    def test_valid_pdf_returns_bytes_and_hash(self) -> None:
        import hashlib
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/pdf"}
            resp.iter_content.return_value = [b"%PDF-1.4 test"]
            resp.close.return_value = None
            session.get.return_value = resp
            result = download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
            assert result.content == b"%PDF-1.4 test"
            assert result.content_hash == hashlib.sha256(b"%PDF-1.4 test").hexdigest()
            assert result.content_length == len(b"%PDF-1.4 test")

    def test_html_response_raises_error(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "text/html"}
            resp.iter_content.return_value = [b"<html>"]
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="not a valid PDF"):
                download_pncp_pdf("https://example.com/page.html", max_bytes=5_000_000)

    def test_json_response_raises_error(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/json"}
            resp.iter_content.return_value = [b'{"error": "not a pdf"}']
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="not a valid PDF"):
                download_pncp_pdf("https://example.com/data.json", max_bytes=5_000_000)

    def test_404_raises_permanent_failure(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 404
            resp.headers = {}
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="(?i)permanent"):
                download_pncp_pdf("https://example.com/missing.pdf", max_bytes=5_000_000)

    def test_410_raises_permanent_failure(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 410
            resp.headers = {}
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="(?i)permanent"):
                download_pncp_pdf("https://example.com/gone.pdf", max_bytes=5_000_000)

    def test_422_raises_permanent_failure(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 422
            resp.headers = {}
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="(?i)permanent"):
                download_pncp_pdf("https://example.com/bad.pdf", max_bytes=5_000_000)

    def test_429_retries(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_429.headers = {}
            resp_429.close.return_value = None
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4 retry"]
            resp_ok.close.return_value = None
            session.get.side_effect = [resp_429, resp_ok]
            with patch("pncp_http.time.sleep"):
                result = download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                assert result.content == b"%PDF-1.4 retry"

    def test_503_retries(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_503 = MagicMock()
            resp_503.status_code = 503
            resp_503.headers = {}
            resp_503.close.return_value = None
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4 ok"]
            resp_ok.close.return_value = None
            session.get.side_effect = [resp_503, resp_ok]
            with patch("pncp_http.time.sleep"):
                result = download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                assert result.content == b"%PDF-1.4 ok"

    def test_408_retries(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_408 = MagicMock()
            resp_408.status_code = 408
            resp_408.headers = {}
            resp_408.close.return_value = None
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4 ok"]
            resp_ok.close.return_value = None
            session.get.side_effect = [resp_408, resp_ok]
            with patch("pncp_http.time.sleep"):
                result = download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                assert result.content == b"%PDF-1.4 ok"

    def test_425_retries(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_425 = MagicMock()
            resp_425.status_code = 425
            resp_425.headers = {}
            resp_425.close.return_value = None
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4 ok"]
            resp_ok.close.return_value = None
            session.get.side_effect = [resp_425, resp_ok]
            with patch("pncp_http.time.sleep"):
                result = download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                assert result.content == b"%PDF-1.4 ok"

    def test_network_error_retries(self) -> None:
        import requests as req_lib
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4 ok"]
            resp_ok.close.return_value = None
            session.get.side_effect = [
                req_lib.ConnectionError("network down"),
                resp_ok,
            ]
            with patch("pncp_http.time.sleep"):
                result = download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                assert result.content == b"%PDF-1.4 ok"

    def test_max_retries_exhausted(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 503
            resp.headers = {}
            resp.close.return_value = None
            session.get.return_value = resp
            with patch("pncp_http.time.sleep"):
                with pytest.raises(DownloadError, match="attempts"):
                    download_pncp_pdf(
                        "https://example.com/doc.pdf",
                        max_bytes=5_000_000,
                        max_attempts=4,
                    )

    def test_retry_after_header_honored(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_429.headers = {"Retry-After": "5"}
            resp_429.close.return_value = None
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4"]
            resp_ok.close.return_value = None
            session.get.side_effect = [resp_429, resp_ok]
            with patch("pncp_http.time.sleep") as mock_sleep:
                download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                mock_sleep.assert_called_with(5)

    def test_retry_after_capped_at_120(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_429.headers = {"Retry-After": "300"}
            resp_429.close.return_value = None
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"Content-Type": "application/pdf"}
            resp_ok.iter_content.return_value = [b"%PDF-1.4"]
            resp_ok.close.return_value = None
            session.get.side_effect = [resp_429, resp_ok]
            with patch("pncp_http.time.sleep") as mock_sleep:
                download_pncp_pdf("https://example.com/doc.pdf", max_bytes=5_000_000)
                mock_sleep.assert_called_with(120)

    def test_unsafe_url_rejected(self) -> None:
        with pytest.raises(DownloadError, match="Unsafe"):
            download_pncp_pdf("http://127.0.0.1/secret.pdf", max_bytes=5_000_000)

    def test_oversized_response_rejected(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/pdf"}
            resp.iter_content.return_value = [b"X" * 100]
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="exceeded"):
                download_pncp_pdf("https://example.com/big.pdf", max_bytes=50)

    def test_non_pdf_bytes_rejected(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/pdf"}
            resp.iter_content.return_value = [b"NOT_PDF_CONTENT"]
            resp.close.return_value = None
            session.get.return_value = resp
            with pytest.raises(DownloadError, match="not a valid PDF"):
                download_pncp_pdf("https://example.com/fake.pdf", max_bytes=5_000_000)

    def test_redirect_validates_new_url(self) -> None:
        with patch("pncp_http.requests.Session") as MockSession:
            session = MockSession.return_value.__enter__.return_value
            resp_redirect = MagicMock()
            resp_redirect.status_code = 302
            resp_redirect.headers = {"Location": "http://127.0.0.1/evil.pdf"}
            resp_redirect.close.return_value = None
            session.get.return_value = resp_redirect
            with pytest.raises(DownloadError, match="(?i)unsafe"):
                download_pncp_pdf("https://example.com/redir.pdf", max_bytes=5_000_000)


class TestProcessCandidate:
    def test_valid_pdf_produces_worker_result(self) -> None:
        import hashlib
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "2026-0001"},
        }
        pdf_bytes = b"%PDF-1.4 test content"
        result_hash = hashlib.sha256(pdf_bytes).hexdigest()

        async def fake_extract(data: bytes) -> str:
            return "# Edital\nTest content"

        mock_extractor = MagicMock()
        mock_extractor.extract = fake_extract

        with patch("discover_pncp_candidates.download_pncp_pdf") as mock_dl:
            mock_dl.return_value = DownloadResult(
                content=pdf_bytes,
                content_hash=result_hash,
                content_length=len(pdf_bytes),
            )
            result = process_candidate(candidate, extractor=mock_extractor, max_bytes=5_000_000)

        assert result is not None
        assert result["worker_result"]["ocr_markdown"] == "# Edital\nTest content"
        assert result["worker_result"]["content_hash"] == result_hash
        assert result["worker_result"]["content_length"] == len(pdf_bytes)
        assert result["worker_result"]["validation_outcome"] == "valid_pdf"
        assert "validated_at" in result["worker_result"]

    def test_download_failure_returns_error(self) -> None:
        candidate = {
            "url": "https://example.com/missing.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "2026-0002"},
        }

        async def fake_extract(data: bytes) -> str:
            return "never called"

        mock_extractor = MagicMock()
        mock_extractor.extract = fake_extract

        with patch("discover_pncp_candidates.download_pncp_pdf") as mock_dl:
            mock_dl.side_effect = DownloadError("HTTP 404 permanent")
            result = process_candidate(candidate, extractor=mock_extractor, max_bytes=5_000_000)

        assert "error" in result
        assert "download" in result["error"]
        assert result["url"] == "https://example.com/missing.pdf"

    def test_ocr_failure_returns_error(self) -> None:
        import hashlib
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "2026-0003"},
        }
        pdf_bytes = b"%PDF-1.4 content"

        async def failing_extract(data: bytes) -> str:
            raise RuntimeError("OCR crashed")

        mock_extractor = MagicMock()
        mock_extractor.extract = failing_extract

        with patch("discover_pncp_candidates.download_pncp_pdf") as mock_dl:
            mock_dl.return_value = DownloadResult(
                content=pdf_bytes,
                content_hash=hashlib.sha256(pdf_bytes).hexdigest(),
                content_length=len(pdf_bytes),
            )
            result = process_candidate(candidate, extractor=mock_extractor, max_bytes=5_000_000)

        assert "error" in result
        assert "ocr" in result["error"]
        assert result["url"] == "https://example.com/doc.pdf"

    def test_bytes_released_after_result(self) -> None:
        import gc
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "2026-0004"},
        }
        pdf_bytes = b"%PDF-1.4 content"

        async def fake_extract(data: bytes) -> str:
            return "markdown"

        mock_extractor = MagicMock()
        mock_extractor.extract = fake_extract

        with patch("discover_pncp_candidates.download_pncp_pdf") as mock_dl:
            mock_dl.return_value = DownloadResult(
                content=pdf_bytes,
                content_hash="abc",
                content_length=len(pdf_bytes),
            )
            result = process_candidate(candidate, extractor=mock_extractor, max_bytes=5_000_000)

        assert result is not None
        assert "content" not in result
        gc.collect()

    def test_metadata_preserved_in_result(self) -> None:
        import hashlib
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {
                "numeroControlePNCP": "2026-0005",
                "anoCompra": 2026,
                "titulo": "Edital Teste",
            },
        }
        pdf_bytes = b"%PDF-1.4"

        async def fake_extract(data: bytes) -> str:
            return "markdown"

        mock_extractor = MagicMock()
        mock_extractor.extract = fake_extract

        with patch("discover_pncp_candidates.download_pncp_pdf") as mock_dl:
            mock_dl.return_value = DownloadResult(
                content=pdf_bytes,
                content_hash=hashlib.sha256(pdf_bytes).hexdigest(),
                content_length=len(pdf_bytes),
            )
            result = process_candidate(candidate, extractor=mock_extractor, max_bytes=5_000_000)

        assert result["metadata"]["numeroControlePNCP"] == "2026-0005"
        assert result["metadata"]["titulo"] == "Edital Teste"


# ---------------------------------------------------------------------------
# Submission: only valid results submitted
# ---------------------------------------------------------------------------

class TestSubmissionFiltering:
    def test_only_valid_results_submitted(self) -> None:
        from discover_pncp_candidates import submit_candidates
        valid = {
            "url": "https://example.com/good.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "V-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "abc",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }
        error_item = {
            "url": "https://example.com/bad.pdf",
            "metadata": {"numeroControlePNCP": "E-001"},
            "error": "download: HTTP 404",
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inserted": 1,
            "updated": 0,
            "reactivated": 0,
            "duplicates": 0,
            "outcomes": {"V-001:1": "inserted"},
        }
        with patch.dict(os.environ, {"RENDER_APP_URL": "https://render.example.com", "PIPELINE_SECRET": "tok"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp) as mock_post:
                result = submit_candidates([valid, error_item])

        sent_body = mock_post.call_args[1]["json"]
        assert len(sent_body["candidates"]) == 1
        assert sent_body["candidates"][0]["url"] == "https://example.com/good.pdf"
        assert result["total"] == 2
        assert result["submitted"] == 1


class TestSubmissionContract:
    def test_request_includes_worker_result_no_pdf_bytes(self) -> None:
        from discover_pncp_candidates import submit_candidates
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "C-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "sha256hash",
                "content_length": 12345,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp) as mock_post:
                submit_candidates([candidate])

        body = mock_post.call_args[1]["json"]
        assert body["source"] == "pncp"
        c = body["candidates"][0]
        assert c["url"] == "https://example.com/doc.pdf"
        assert c["kind"] == "pdf"
        assert c["metadata"]["numeroControlePNCP"] == "C-001"
        assert c["worker_result"]["ocr_markdown"] == "# Edital"
        assert c["worker_result"]["content_hash"] == "sha256hash"
        assert "content" not in c
        assert "pdf_bytes" not in c

    def test_markdown_respects_configured_size_limit(self) -> None:
        from discover_pncp_candidates import submit_candidates, RENDER_SUBMIT_BATCH_SIZE
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "M-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "x" * 1_000_001,
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp) as mock_post:
                submit_candidates([candidate])

        body = mock_post.call_args[1]["json"]
        md = body["candidates"][0]["worker_result"]["ocr_markdown"]
        assert len(md) <= 1_000_000


class TestSubmissionRetryBehavior:
    def test_transient_errors_retry(self) -> None:
        from discover_pncp_candidates import submit_candidates
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "R-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.json.return_value = {}
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {"inserted": 1, "outcomes": {}}

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", side_effect=[resp_503, resp_ok]) as mock_post:
                with patch("discover_pncp_candidates.time.sleep"):
                    result = submit_candidates([candidate])

        assert mock_post.call_count == 2
        assert result["submitted"] == 1

    def test_auth_failure_stops_immediately(self) -> None:
        from discover_pncp_candidates import submit_candidates
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "A-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        import requests as _requests
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.json.return_value = {"error": "unauthorized"}
        resp_401.raise_for_status.side_effect = _requests.HTTPError(response=resp_401)

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=resp_401) as mock_post:
                result = submit_candidates([candidate])

        assert mock_post.call_count == 1
        assert result["submitted"] == 0
        assert result["failed_batches"] == 1


class TestSubmissionTerminalOutcomes:
    def test_inserted_response_succeeds(self) -> None:
        from discover_pncp_candidates import submit_candidates
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "I-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inserted": 1,
            "updated": 0,
            "reactivated": 0,
            "duplicates": 0,
            "outcomes": {"I-001:1": "inserted"},
        }

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp):
                result = submit_candidates([candidate])

        assert result["submitted"] == 1
        assert result["last_result"]["outcomes"]["I-001:1"] == "inserted"

    def test_duplicate_response_succeeds(self) -> None:
        from discover_pncp_candidates import submit_candidates
        candidate = {
            "url": "https://example.com/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "D-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inserted": 0,
            "updated": 0,
            "reactivated": 0,
            "duplicates": 1,
            "outcomes": {"D-001:1": "duplicate"},
        }

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp):
                result = submit_candidates([candidate])

        assert result["submitted"] == 1

    def test_successful_items_not_retried_after_partial_batch(self) -> None:
        from discover_pncp_candidates import submit_candidates
        c1 = {
            "url": "https://example.com/a.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "P-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# A",
                "content_hash": "h1",
                "content_length": 10,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }
        c2 = {
            "url": "https://example.com/b.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "P-002", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# B",
                "content_hash": "h2",
                "content_length": 20,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inserted": 1,
            "updated": 0,
            "reactivated": 0,
            "duplicates": 0,
            "outcomes": {"P-001:1": "inserted", "P-002:1": "duplicate"},
        }

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp) as mock_post:
                result = submit_candidates([c1, c2])

        assert mock_post.call_count == 1
        assert result["submitted"] == 2

    def test_response_has_identity_keyed_outcomes_and_counts(self) -> None:
        from discover_pncp_candidates import submit_candidates
        c1 = {
            "url": "https://example.com/a.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "K-001", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# A",
                "content_hash": "h1",
                "content_length": 10,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }
        c2 = {
            "url": "https://example.com/b.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "K-002", "sequencialDocumento": 1},
            "worker_result": {
                "ocr_markdown": "# B",
                "content_hash": "h2",
                "content_length": 20,
                "validated_at": "2026-06-12T12:00:00Z",
                "validation_outcome": "valid_pdf",
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "inserted": 1,
            "updated": 1,
            "reactivated": 0,
            "duplicates": 0,
            "outcomes": {
                "K-001:1": "inserted",
                "K-002:1": "updated",
            },
        }

        with patch.dict(os.environ, {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "t"}):
            with patch("discover_pncp_candidates.requests.post", return_value=mock_resp):
                result = submit_candidates([c1, c2])

        lr = result["last_result"]
        assert "outcomes" in lr
        assert lr["outcomes"]["K-001:1"] == "inserted"
        assert lr["outcomes"]["K-002:1"] == "updated"
        assert lr["inserted"] == 1
        assert lr["updated"] == 1
