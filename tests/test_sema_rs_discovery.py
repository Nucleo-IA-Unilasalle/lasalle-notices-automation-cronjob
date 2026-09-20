"""Unit tests for ``scripts/discover_sema_rs_candidates.py``.

Ports the SEMA-RS source from
``lasalle-notices-automation/app/services/scraper/sources/sema_rs.py`` into
the cronjob, locking the discovery contract before Phase 3 ships.
Tests exercise the ``extract_sema_rs_detail_urls`` helper plus the
paginated AJAX discovery (keyword sweep + stale-page termination) and
the static service page sweep, year guard, ``is_likely_edital``
prefilter, and the ``process_candidate`` / ``submit_candidates`` handoff.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "sema_rs"


LISTING_BODY_FIXTURE = FIXTURES_DIR / "listing_body.html"
EDITAL_DETAIL_FIXTURE = FIXTURES_DIR / "edital_detail.html"


LISTING_ORIGIN = "https://www.sema.rs.gov.br"
EDITAL_URL_TEMPLATE = (
    "https://www.sema.rs.gov.br/busca/lista-data-table"
    "?currentPage={current_page}&pageSize=20"
    "&form%5Bpalavraschave%5D={keyword}"
    "&form%5Bordem%5D=RECENTES"
)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_json_listing_response(
    body_html: str, pagecount: int | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    payload: dict[str, object] = {"body": body_html}
    if pagecount is not None:
        payload["pagecount"] = pagecount
    response.json.return_value = payload
    return response


class TestExtractSemaRsDetailUrls:
    """The discovery helper is a verbatim port of the FastAPI version."""

    def test_listing_body_yields_detail_urls(self) -> None:
        from discover_sema_rs_candidates import extract_sema_rs_detail_urls

        discovered = extract_sema_rs_detail_urls(
            _read_fixture(LISTING_BODY_FIXTURE), LISTING_ORIGIN,
        )

        assert discovered == [
            "https://www.sema.rs.gov.br/edital-01-de-2024-delta-do-jacui",
            "https://www.sema.rs.gov.br/inscricoes-abertas-edital-002-de-2022-voluntariado-pe-tainhas",
            "https://www.sema.rs.gov.br/governo-do-rs-lanca-chamada-publica-para-municipios-que-queiram-valorizar-residuos-organicos",
        ]

    def test_rejects_off_host_and_signal_less_links(self) -> None:
        from discover_sema_rs_candidates import extract_sema_rs_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="https://example.gov.br/edital-2026">Outro host</a>
            <a href="/institucional">Sem sinal</a>
            <a href="/edital-2026">Com sinal</a>
          </body>
        </html>
        """
        assert extract_sema_rs_detail_urls(listing_html, LISTING_ORIGIN) == [
            "https://www.sema.rs.gov.br/edital-2026",
        ]

    def test_skips_direct_pdf_anchors(self) -> None:
        from discover_sema_rs_candidates import extract_sema_rs_detail_urls

        listing_html = """
        <html>
          <body>
            <a href="/upload/arquivos/edital-2026.pdf">PDF direto</a>
            <a href="/edital-2026">Detalhe</a>
          </body>
        </html>
        """
        assert extract_sema_rs_detail_urls(listing_html, LISTING_ORIGIN) == [
            "https://www.sema.rs.gov.br/edital-2026",
        ]


class TestConstants:
    def test_constants(self) -> None:
        from discover_sema_rs_candidates import (
            SEMA_RS_KEYWORDS,
            SEMA_RS_LISTING_ORIGIN,
            SEMA_RS_LISTING_URL_TEMPLATE,
            SEMA_RS_STATIC_SERVICE_PAGES,
        )

        assert SEMA_RS_LISTING_ORIGIN == "https://www.sema.rs.gov.br"
        assert SEMA_RS_KEYWORDS == ("edital", "chamada")
        assert SEMA_RS_LISTING_URL_TEMPLATE.startswith(
            "https://www.sema.rs.gov.br/busca/lista-data-table",
        )
        assert "currentPage={current_page}" in SEMA_RS_LISTING_URL_TEMPLATE
        assert SEMA_RS_STATIC_SERVICE_PAGES == (
            "https://www.sema.rs.gov.br/residuos-solidos",
        )


class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SEMA_RS_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_sema_rs_candidates"),
        )
        assert module.SEMA_RS_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEMA_RS_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_sema_rs_candidates"),
        )
        assert module.SEMA_RS_MIN_NOTICE_YEAR == 2027
        monkeypatch.delenv("SEMA_RS_MIN_NOTICE_YEAR", raising=False)
        importlib.reload(__import__("discover_sema_rs_candidates"))

    def test_year_extracted_from_pdf_path(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.sema.rs.gov.br/upload/arquivos/202307/03143645-edital-2026.pdf",
        ) == 2026

    def test_year_extracted_from_detail_path(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.sema.rs.gov.br/edital-01-de-2026-delta-do-jacui",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.sema.rs.gov.br/institucional",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_sema_rs_candidates import _passes_year_guard

        url_2024 = "https://www.sema.rs.gov.br/upload/arquivos/2024/edital-2024.pdf"
        url_2026 = "https://www.sema.rs.gov.br/upload/arquivos/2026/edital-2026.pdf"
        url_unknown = "https://www.sema.rs.gov.br/institucional"

        assert _passes_year_guard(url_2024, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        assert _passes_year_guard(url_unknown, min_year=2026) is True


class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_sema_rs_candidates import _candidate_passes_edital_prefilter

        url = "https://www.sema.rs.gov.br/upload/arquivos/2026/edital-2026.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_sema_rs_candidates import _candidate_passes_edital_prefilter

        url = "https://www.sema.rs.gov.br/upload/arquivos/2026/resultado-final.pdf"
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_sema_rs_candidates import _candidate_passes_edital_prefilter

        url = "https://www.sema.rs.gov.br/upload/arquivos/2026/resultado-final.pdf"
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


class TestBuildCandidate:
    def test_build_candidate_records_origin_and_year(self) -> None:
        from datetime import datetime, timezone

        from discover_sema_rs_candidates import build_candidate

        url = "https://www.sema.rs.gov.br/upload/arquivos/2026/edital-2026.pdf"
        detail = "https://www.sema.rs.gov.br/edital-01-de-2026-delta-do-jacui"
        before = datetime.now(timezone.utc)
        candidate = build_candidate(
            url,
            listing_url=LISTING_ORIGIN,
            detail_url=detail,
            origin="detail_page",
        )
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "sema_rs"
        assert meta["listing_url"] == LISTING_ORIGIN
        assert meta["detail_url"] == detail
        assert meta["origin"] == "detail_page"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_sema_rs_candidates import build_candidate

        url = "https://www.sema.rs.gov.br/upload/arquivos/2024/edital-2024.pdf"
        assert build_candidate(url, listing_url=LISTING_ORIGIN) is None

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_sema_rs_candidates import build_candidate

        url = "https://www.sema.rs.gov.br/upload/arquivos/2026/resultado-final.pdf"
        assert build_candidate(url, listing_url=LISTING_ORIGIN) is None


class TestDiscoverCandidates:
    def _listing_response_for_keyword(
        self, body_html: str, keyword: str, current_page: int = 1,
    ) -> MagicMock:
        return _make_json_listing_response(body_html)

    def test_ajax_listing_yields_pdfs_from_each_detail_page(self) -> None:
        from discover_sema_rs_candidates import discover_candidates

        # Override the fixture detail URLs to point at 2026 edital PDFs
        # so they survive the year guard (the recorded fixture carries
        # 2023 and 2020 paths).
        detail_html_2026 = """
        <html>
          <body>
            <article class="artigo">
              <h1 class="artigo__titulo">Edital 01 de 2026</h1>
              <div class="artigo__texto">
                <a href="/upload/arquivos/202601/edital-programa-2026.pdf">Edital 2026</a>
                <a href="/upload/arquivos/202601/anexo-programa-2026.pdf">Anexo 2026</a>
              </div>
            </article>
          </body>
        </html>
        """

        responses: dict[str, object] = {}
        for keyword in ("edital", "chamada"):
            for page in (1, 2):
                responses[EDITAL_URL_TEMPLATE.format(current_page=page, keyword=keyword)] = (
                    _make_json_listing_response(_read_fixture(LISTING_BODY_FIXTURE), pagecount=2)
                )
        responses["https://www.sema.rs.gov.br/edital-01-de-2024-delta-do-jacui"] = (
            make_response(detail_html_2026)
        )
        responses["https://www.sema.rs.gov.br/inscricoes-abertas-edital-002-de-2022-voluntariado-pe-tainhas"] = (
            make_response("<html></html>")
        )
        responses["https://www.sema.rs.gov.br/governo-do-rs-lanca-chamada-publica-para-municipios-que-queiram-valorizar-residuos-organicos"] = (
            make_response("<html></html>")
        )
        responses["https://www.sema.rs.gov.br/residuos-solidos"] = (
            make_response("<html></html>")
        )

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.sema.rs.gov.br/upload/arquivos/202601/edital-programa-2026.pdf"
        ) in urls
        assert (
            "https://www.sema.rs.gov.br/upload/arquivos/202601/anexo-programa-2026.pdf"
        ) in urls
        assert stats["candidates"] == 2
        assert stats["details_fetched"] >= 1

    def test_year_filter_excludes_pre_2026_detail_url(self) -> None:
        from discover_sema_rs_candidates import discover_candidates

        # The fixture has /edital-01-de-2024-delta-do-jacui - a 2024 path.
        # The override here keeps the 2024 detail but the recorded PDF
        # is from 2023; both should be filtered.
        responses: dict[str, object] = {}
        for keyword in ("edital",):
            responses[EDITAL_URL_TEMPLATE.format(current_page=1, keyword=keyword)] = (
                _make_json_listing_response(_read_fixture(LISTING_BODY_FIXTURE), pagecount=1)
            )
        # The "edital-01-de-2024-delta-do-jacui" detail carries a 2024
        # year, which should be rejected.
        responses["https://www.sema.rs.gov.br/edital-01-de-2024-delta-do-jacui"] = (
            make_response(_read_fixture(EDITAL_DETAIL_FIXTURE))
        )
        responses["https://www.sema.rs.gov.br/residuos-solidos"] = (
            make_response("<html></html>")
        )

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        # The 2023 PDF should be filtered out.
        assert (
            "https://www.sema.rs.gov.br/upload/arquivos/202307/03143645-doe-edital-001-2023-modificado-1.pdf"
        ) not in urls
        assert stats["year_rejected"] >= 1

    def test_keyword_pagination_stops_on_stale_pages(self) -> None:
        from discover_sema_rs_candidates import discover_candidates

        empty_listing = "<html><body></body></html>"
        responses: dict[str, object] = {}
        for keyword in ("edital",):
            for page in (1, 2, 3):
                responses[EDITAL_URL_TEMPLATE.format(current_page=page, keyword=keyword)] = (
                    _make_json_listing_response(empty_listing)
                )
        responses["https://www.sema.rs.gov.br/residuos-solidos"] = (
            make_response("<html></html>")
        )

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert stats["candidates"] == 0

    def test_static_page_failure_does_not_block_ajax_results(self) -> None:
        from discover_sema_rs_candidates import discover_candidates

        responses: dict[str, object] = {}
        for keyword in ("edital",):
            for page in (1, 2, 3):
                responses[EDITAL_URL_TEMPLATE.format(current_page=page, keyword=keyword)] = (
                    _make_json_listing_response("<html><body></body></html>")
                )
        responses["https://www.sema.rs.gov.br/residuos-solidos"] = (
            requests.ConnectionError("down")
        )

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        # Errors = 3 chamada keyword page failures (one per page until
        # the consecutive-failure cutoff) + 1 residuos-solidos failure.
        assert stats["errors"] == 4
        assert candidates == []


class TestPaginationContinuation:
    """A signal-less listing page is not the end of results.

    Regression for the live SEMA-RS AJAX behaviour: the endpoint is a
    full-text search whose first pages often carry zero signal-matched
    anchors while later pages contain the real edital detail URLs. The
    discoverer must honour the server-reported ``pagecount`` and only
    stop on article-free placeholder bodies / stale pages.
    """

    def test_signal_less_first_page_still_reaches_later_matches(self) -> None:
        from discover_sema_rs_candidates import discover_candidates

        signal_less_page = """
        <html><body>
          <article class="conteudo-lista__item"><h2><a href="/programa-biogas-rs">Programa Biogás RS</a></h2></article>
          <article class="conteudo-lista__item"><h2><a href="/outorga-aguas-subterraneas">Outorga</a></h2></article>
        </body></html>
        """
        match_page = _read_fixture(LISTING_BODY_FIXTURE)

        responses: dict[str, object] = {}
        for keyword in ("edital",):
            responses[EDITAL_URL_TEMPLATE.format(current_page=1, keyword=keyword)] = (
                _make_json_listing_response(signal_less_page, pagecount=2)
            )
            responses[EDITAL_URL_TEMPLATE.format(current_page=2, keyword=keyword)] = (
                _make_json_listing_response(match_page, pagecount=2)
            )
        # chamada keyword: single empty page.
        responses[EDITAL_URL_TEMPLATE.format(current_page=1, keyword="chamada")] = (
            _make_json_listing_response("<html><body></body></html>", pagecount=1)
        )
        detail_html_2026 = """
        <html><body>
          <article class="artigo"><div class="artigo__texto">
            <a href="/upload/arquivos/202601/edital-programa-2026.pdf">Edital 2026</a>
          </div></article>
        </body></html>
        """
        responses["https://www.sema.rs.gov.br/edital-01-de-2024-delta-do-jacui"] = (
            make_response(detail_html_2026)
        )
        responses["https://www.sema.rs.gov.br/inscricoes-abertas-edital-002-de-2022-voluntariado-pe-tainhas"] = (
            make_response("<html></html>")
        )
        responses["https://www.sema.rs.gov.br/governo-do-rs-lanca-chamada-publica-para-municipios-que-queiram-valorizar-residuos-organicos"] = (
            make_response("<html></html>")
        )
        responses["https://www.sema.rs.gov.br/residuos-solidos"] = (
            make_response("<html></html>")
        )

        with patch_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert (
            "https://www.sema.rs.gov.br/upload/arquivos/202601/edital-programa-2026.pdf"
        ) in urls
        assert stats["details_fetched"] >= 1

    def test_pagecount_stops_pagination_without_extra_fetches(self) -> None:
        from discover_sema_rs_candidates import _paginate_keyword

        match_page = _read_fixture(LISTING_BODY_FIXTURE)
        responses: dict[str, object] = {
            EDITAL_URL_TEMPLATE.format(current_page=1, keyword="edital"): (
                _make_json_listing_response(match_page, pagecount=1)
            ),
        }

        seen: set[str] = set()
        out: list[str] = []
        stats: dict[str, int] = {"errors": 0}
        with patch_request_with_safe_redirects(responses):
            # Any fetch beyond page 1 raises AssertionError in the mock,
            # which would surface as stats["errors"] > 0.
            yielded = _paginate_keyword(
                "edital",
                seen_detail_urls=seen,
                detail_urls_out=out,
                stats=stats,
            )

        assert yielded is True
        assert len(out) == 3
        assert stats["errors"] == 0

    def test_article_free_body_stops_pagination(self) -> None:
        from discover_sema_rs_candidates import _paginate_keyword

        responses: dict[str, object] = {
            EDITAL_URL_TEMPLATE.format(current_page=1, keyword="edital"): (
                _make_json_listing_response("<p>Nenhuma informação a ser exibida.</p>")
            ),
        }

        seen: set[str] = set()
        out: list[str] = []
        stats: dict[str, int] = {"errors": 0}
        with patch_request_with_safe_redirects(responses):
            yielded = _paginate_keyword(
                "edital",
                seen_detail_urls=seen,
                detail_urls_out=out,
                stats=stats,
            )

        assert yielded is False
        assert out == []
        assert stats["errors"] == 0


class TestYearFolderExtraction:
    """YYYYMM upload folders carry the authoritative year."""

    def test_upload_folder_year_rejects_pre_min_year(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url, _passes_year_guard

        url = "https://www.sema.rs.gov.br/upload/arquivos/202307/03143645-doe-edital.pdf"
        assert _extract_year_from_url(url) == 2023
        assert _passes_year_guard(url, min_year=2026) is False

    def test_upload_folder_year_accepts_current_year(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url, _passes_year_guard

        url = "https://www.sema.rs.gov.br/upload/arquivos/202605/22143051-materia.pdf"
        assert _extract_year_from_url(url) == 2026
        assert _passes_year_guard(url, min_year=2026) is True

    def test_percent_encoding_does_not_create_false_years(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url

        # "Lei nº 09.921" must not be read as year 2009 via "%2009".
        url = "https://ww3.al.rs.gov.br/filerepository/replegiscomp/Lei%20n%C2%BA%2009.921.pdf"
        assert _extract_year_from_url(url) is None

    def test_filename_year_still_wins_when_more_recent(self) -> None:
        from discover_sema_rs_candidates import _extract_year_from_url

        url = "https://www.sema.rs.gov.br/upload/arquivos/202307/03143645-edital-2026.pdf"
        assert _extract_year_from_url(url) == 2026


class TestStaticServiceExtractor:
    """The residuos-solidos sweep keeps only open, same-host edital PDFs."""

    PAGE_URL = "https://www.sema.rs.gov.br/residuos-solidos"

    def _extract(self, html: str) -> list[str]:
        from discover_sema_rs_candidates import extract_static_service_pdf_urls

        return extract_static_service_pdf_urls(html, self.PAGE_URL)

    def test_keeps_same_host_signal_pdf_outside_closed_panel(self) -> None:
        html = """
        <html><body>
          <div class="panel panel-default"><div class="panel-body">
            <p><a href="/upload/arquivos/202608/edital-chamada-2026.pdf">Edital de Chamada Pública</a></p>
          </div></div>
        </body></html>
        """
        assert self._extract(html) == [
            "https://www.sema.rs.gov.br/upload/arquivos/202608/edital-chamada-2026.pdf",
        ]

    def test_skips_signal_pdf_in_panel_with_final_result(self) -> None:
        html = """
        <html><body>
          <div class="panel panel-default"><div class="panel-body">
            <p><a href="/upload/arquivos/202605/22143051-materia1309752.pdf">Edital de Chamada Pública</a></p>
            <p><a href="https://www.diariooficial.rs.gov.br/materia?id=1331198">Resultado Final</a></p>
          </div></div>
        </body></html>
        """
        assert self._extract(html) == []

    def test_skips_off_host_and_signal_less_pdfs(self) -> None:
        html = """
        <html><body>
          <p><a href="https://ww3.al.rs.gov.br/filerepository/replegiscomp/Lei%20n%C2%BA%206.503.pdf">Lei Estadual nº 6.503/1972</a></p>
          <p><a href="/upload/arquivos/202605/22142718-comunidade-de-pratica.pdf">Orientações gerais</a></p>
          <p><a href="/upload/arquivos/202602/06105524-br-home-composting.pdf">Diretrizes para a implementação de programa de compostagem domiciliar</a></p>
        </body></html>
        """
        assert self._extract(html) == []

    def test_skips_signal_pdf_with_encerrado_marker(self) -> None:
        html = """
        <html><body>
          <div class="panel-body">
            <p><a href="/upload/arquivos/202601/edital-encerrado-2026.pdf">Edital de Chamada Pública</a></p>
            <p>Inscrições encerradas em 15/01/2026.</p>
          </div>
        </body></html>
        """
        assert self._extract(html) == []


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_sema_rs_source(self) -> None:
        import discover_sema_rs_candidates as dpc

        candidate = {
            "url": "https://www.sema.rs.gov.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "sema_rs"},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00+00:00",
                "validation_outcome": "valid_pdf",
            },
        }

        ocr_mod = MagicMock()
        config_mod = MagicMock()
        module_stubs = {
            "ocr_worker.ocr_extraction_config": config_mod,
            "ocr_worker.pdf_markdown_extractor": ocr_mod,
        }
        with patch.dict(sys.modules, module_stubs):
            with patch.object(dpc, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dpc.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dpc.pipeline_core,
                        "submit_candidates",
                    ) as mock_submit:
                        mock_submit.return_value = {
                            "total": 1,
                            "submitted": 1,
                            "failed_batches": 0,
                            "errors": [],
                        }
                        with patch.dict(
                            "os.environ",
                            {
                                "RENDER_APP_URL": "https://r.example.com",
                                "PIPELINE_SECRET": "tok",
                            },
                        ):
                            dpc.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "sema_rs"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_sema_rs_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_sema_rs_candidates as dpc

        with patch.object(dpc, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dpc.main() == 0