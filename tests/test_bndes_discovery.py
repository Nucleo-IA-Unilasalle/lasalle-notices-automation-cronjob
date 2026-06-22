"""Unit tests for ``scripts/discover_bndes_candidates.py``.

Ports the BNDE source from
``lasalle-notices-automation/app/services/scraper/sources/bndes.py`` into
the cronjob, locking the discovery contract before Phase 3 scales it to
the remaining BS4 sources. Tests exercise the same ``extract_*``
helper used by the FastAPI version plus the new cronjob plumbing
(year guard, ``is_likely_edital`` prefilter, second-stage detail
discovery, ``process_candidate`` / ``submit_candidates`` handoff).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "bndes"


@pytest.fixture(autouse=True)
def _reset_bndes_env() -> None:
    """Restore the BNDE env-driven module constants between tests.

    Mirrors the pattern in ``tests/test_pipeline_core.py``. The
    ``BNDES_*`` constants are captured at import time, so the
    ``TestYearGuard`` reload tests permanently change the value for
    the rest of the suite unless we reload back after they run.
    """
    yield
    importlib.reload(importlib.import_module("discover_bndes_candidates"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LISTING_FUNDO = FIXTURES_DIR / "listing_fundo_socioambiental.html"
LISTING_INOVACAO = FIXTURES_DIR / "listing_chamada_inovacao.html"
DETAIL_PERIFERIAS = FIXTURES_DIR / "detail_periferias.html"
DETAIL_CORAIS = FIXTURES_DIR / "detail_corais.html"


FUNDO_LISTING_URL = (
    "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/"
    "bndes-fundo-socioambiental"
)
INOVACAO_LISTING_URL = "https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao"


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}", response=resp,
        )
    return resp


# ---------------------------------------------------------------------------
# Discovery helper (extract_bndes_detail_and_pdf_urls) — same as FastAPI
# ---------------------------------------------------------------------------

class TestExtractBndesDetailAndPdfUrls:
    """The discovery helper is a verbatim port of the FastAPI version;
    these tests lock its behaviour against the recorded fixtures."""

    def test_fundo_listing_yields_detail_url_and_direct_pdf(self) -> None:
        from discover_bndes_candidates import extract_bndes_detail_and_pdf_urls

        discovered = extract_bndes_detail_and_pdf_urls(
            _read_fixture(LISTING_FUNDO), FUNDO_LISTING_URL,
        )

        assert discovered == [
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "financiamento/produto/bndes-fundo-socioambiental/"
                "chamada-publica-periferias-2026"
            ),
            (
                "https://www.bndes.gov.br/wps/wcm/connect/site/"
                "4f71d4b2-0a9a-4ca1-93f8-45d011e3074a/"
                "edital-fundo-socioambiental-2026.pdf?"
                "MOD=AJPERES&CVID=q123"
            ),
        ]

    def test_inovacao_listing_yields_detail_url_and_direct_pdf(self) -> None:
        from discover_bndes_candidates import extract_bndes_detail_and_pdf_urls

        discovered = extract_bndes_detail_and_pdf_urls(
            _read_fixture(LISTING_INOVACAO), INOVACAO_LISTING_URL,
        )

        assert discovered == [
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "transparencia/chamadas/chamada-inovacao-cpsi-corais"
            ),
            (
                "https://www.bndes.gov.br/wps/wcm/connect/site/"
                "bf28f4f7-dff7-4f95-bc22-616ee1d06754/"
                "cpsi-corais-edital.pdf?MOD=AJPERES"
            ),
        ]

    def test_rejects_unrelated_or_weak_signal_links(self) -> None:
        from discover_bndes_candidates import extract_bndes_detail_and_pdf_urls

        listing_html = """
        <html>
          <body>
            <a href="/wps/portal/site/home/financiamento/credito">Credito geral</a>
            <a href="/wps/wcm/connect/site/a1/informativo-mensal.pdf">Informativo mensal</a>
            <a href="/wps/portal/site/home/imprensa/noticias/bndes-divulga-balanco">Noticias</a>
            <a href="https://outro-dominio.com/chamada-edital.pdf">Externo</a>
          </body>
        </html>
        """
        discovered = extract_bndes_detail_and_pdf_urls(listing_html, FUNDO_LISTING_URL)
        assert discovered == []

    def test_query_style_detail_links_for_known_routes(self) -> None:
        from discover_bndes_candidates import extract_bndes_detail_and_pdf_urls

        listing_html = """
        <html>
          <body>
            <a href="?1dmy&amp;urile=wcm:path:/bndes_institucional/home/onde-atuamos/social/bndes-periferias">Periferias</a>
            <a href="?1dmy&amp;urile=wcm:path:/bndes_institucional/home/onde-atuamos/bndes-azul/bndes-corais">Corais</a>
            <a href="?1dmy&amp;urile=wcm:path:/bndes_institucional/home/onde-atuamos/social/sertao-mais-produtivo">Sertao</a>
          </body>
        </html>
        """
        discovered = extract_bndes_detail_and_pdf_urls(listing_html, FUNDO_LISTING_URL)

        assert discovered == [
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "financiamento/produto/bndes-fundo-socioambiental?"
                "urile=wcm:path:/bndes_institucional/home/onde-atuamos/"
                "social/bndes-periferias"
            ),
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "financiamento/produto/bndes-fundo-socioambiental?"
                "urile=wcm:path:/bndes_institucional/home/onde-atuamos/"
                "bndes-azul/bndes-corais"
            ),
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "financiamento/produto/bndes-fundo-socioambiental?"
                "urile=wcm:path:/bndes_institucional/home/onde-atuamos/"
                "social/sertao-mais-produtivo"
            ),
        ]

    def test_canonicalises_query_style_urls_for_dedup_stability(self) -> None:
        from discover_bndes_candidates import extract_bndes_detail_and_pdf_urls

        listing_html = """
        <html>
          <body>
            <a href="?foo=bar&amp;1dmy&amp;urile=wcm:path:/bndes_institucional/home/onde-atuamos/social/bndes-periferias&amp;utm_source=x">Periferias A</a>
            <a href="?urile=wcm:path:/bndes_institucional/home/onde-atuamos/social/bndes-periferias&amp;z=1">Periferias B</a>
          </body>
        </html>
        """
        discovered = extract_bndes_detail_and_pdf_urls(listing_html, FUNDO_LISTING_URL)
        assert discovered == [
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "financiamento/produto/bndes-fundo-socioambiental?"
                "urile=wcm:path:/bndes_institucional/home/onde-atuamos/"
                "social/bndes-periferias"
            )
        ]

    def test_rejects_query_style_links_with_irrelevant_urile_routes(self) -> None:
        from discover_bndes_candidates import extract_bndes_detail_and_pdf_urls

        listing_html = """
        <html>
          <body>
            <a href="?1dmy&amp;urile=wcm:path:/bndes_institucional/home/financiamento">Financiamento</a>
            <a href="?1dmy&amp;urile=wcm:path:/bndes_institucional/home/imprensa/noticias/bndes-publica-release">Noticias</a>
          </body>
        </html>
        """
        assert extract_bndes_detail_and_pdf_urls(listing_html, FUNDO_LISTING_URL) == []


# ---------------------------------------------------------------------------
# Listing URLs (constant)
# ---------------------------------------------------------------------------

class TestListingUrls:
    def test_default_listing_urls(self) -> None:
        from discover_bndes_candidates import BNDES_LISTING_URLS

        assert BNDES_LISTING_URLS == [
            (
                "https://www.bndes.gov.br/wps/portal/site/home/"
                "financiamento/produto/bndes-fundo-socioambiental"
            ),
            "https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao",
        ]


# ---------------------------------------------------------------------------
# Year guard (BNDES_MIN_NOTICE_YEAR)
# ---------------------------------------------------------------------------

class TestYearGuard:
    def test_default_min_notice_year_is_2026(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BNDES_MIN_NOTICE_YEAR", raising=False)
        module = importlib.reload(
            __import__("discover_bndes_candidates"),
        )
        assert module.BNDES_MIN_NOTICE_YEAR == 2026

    def test_min_notice_year_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BNDES_MIN_NOTICE_YEAR", "2027")
        module = importlib.reload(
            __import__("discover_bndes_candidates"),
        )
        assert module.BNDES_MIN_NOTICE_YEAR == 2027

    def test_year_extracted_from_url_path(self) -> None:
        from discover_bndes_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.bndes.gov.br/wps/portal/site/home/financiamento/"
            "produto/bndes-fundo-socioambiental/chamada-publica-periferias-2026",
        ) == 2026

    def test_year_extracted_from_pdf_filename(self) -> None:
        from discover_bndes_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.bndes.gov.br/wps/wcm/connect/site/4f71d4b2/"
            "edital-fundo-socioambiental-2026.pdf?MOD=AJPERES",
        ) == 2026

    def test_no_year_returns_none(self) -> None:
        from discover_bndes_candidates import _extract_year_from_url

        assert _extract_year_from_url(
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "transparencia/chamadas/chamada-inovacao-cpsi-corais",
        ) is None

    def test_year_below_minimum_is_rejected(self) -> None:
        from discover_bndes_candidates import _passes_year_guard

        url_2025 = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "financiamento/produto/bndes-fundo-socioambiental/"
            "chamada-publica-periferias-2025"
        )
        url_2026 = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "financiamento/produto/bndes-fundo-socioambiental/"
            "chamada-publica-periferias-2026"
        )
        url_unknown = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "transparencia/chamadas/chamada-inovacao-cpsi-corais"
        )

        assert _passes_year_guard(url_2025, min_year=2026) is False
        assert _passes_year_guard(url_2026, min_year=2026) is True
        # BNDE listings do not always expose a year in the URL; missing
        # metadata is recorded explicitly (see plan §9) and the candidate
        # passes through for downstream filtering.
        assert _passes_year_guard(url_unknown, min_year=2026) is True


# ---------------------------------------------------------------------------
# Edital prefilter integration
# ---------------------------------------------------------------------------

class TestEditalPrefilter:
    def test_candidate_passes_is_likely_edital_with_edital_in_url(self) -> None:
        from discover_bndes_candidates import _candidate_passes_edital_prefilter

        url = (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "4f71d4b2/edital-fundo-socioambiental-2026.pdf"
        )
        assert _candidate_passes_edital_prefilter(url, "default") is True

    def test_candidate_rejected_when_filename_matches_exclusion(self) -> None:
        from discover_bndes_candidates import _candidate_passes_edital_prefilter

        url = (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "abc123/resultado-final-2026.pdf"
        )
        assert _candidate_passes_edital_prefilter(url, "default") is False

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        from discover_bndes_candidates import _candidate_passes_edital_prefilter

        url = (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "abc123/resultado-final-2026.pdf"
        )
        assert _candidate_passes_edital_prefilter(url, "no_prefilter") is True


# ---------------------------------------------------------------------------
# build_candidate
# ---------------------------------------------------------------------------

class TestBuildCandidate:
    def test_build_candidate_has_pdf_kind_and_metadata(self) -> None:
        from discover_bndes_candidates import build_candidate
        from datetime import datetime, timezone

        url = (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "4f71d4b2/edital-fundo-socioambiental-2026.pdf"
        )
        before = datetime.now(timezone.utc)
        candidate = build_candidate(url, listing_url=FUNDO_LISTING_URL)
        after = datetime.now(timezone.utc)

        assert candidate is not None
        assert candidate["url"] == url
        assert candidate["kind"] == "pdf"
        meta = candidate["metadata"]
        assert meta["source"] == "bndes"
        assert meta["listing_url"] == FUNDO_LISTING_URL
        assert meta["origin"] == "listing_pdf"
        assert meta["extracted_year"] == 2026
        discovered_at = datetime.fromisoformat(meta["discovered_at"])
        assert before <= discovered_at <= after

    def test_build_candidate_records_unknown_origin_when_not_pdf(self) -> None:
        from discover_bndes_candidates import build_candidate

        url = (
            "https://www.bndes.gov.br/wps/portal/site/home/financiamento/"
            "produto/bndes-fundo-socioambiental/chamada-publica-periferias-2026"
        )
        candidate = build_candidate(url, listing_url=FUNDO_LISTING_URL)
        assert candidate is not None
        assert candidate["metadata"]["origin"] == "listing_detail"
        assert candidate["metadata"]["extracted_year"] == 2026

    def test_build_candidate_returns_none_for_non_edital_url(self) -> None:
        from discover_bndes_candidates import build_candidate

        url = (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "abc123/resultado-final-2026.pdf"
        )
        assert build_candidate(url, listing_url=FUNDO_LISTING_URL) is None

    def test_build_candidate_returns_none_for_pre_min_year(self) -> None:
        from discover_bndes_candidates import build_candidate

        url = (
            "https://www.bndes.gov.br/wps/portal/site/home/financiamento/"
            "produto/bndes-fundo-socioambiental/chamada-publica-periferias-2025"
        )
        assert build_candidate(url, listing_url=FUNDO_LISTING_URL) is None


# ---------------------------------------------------------------------------
# discover_candidates — end-to-end against fixtures
# ---------------------------------------------------------------------------

def _patched_request_with_safe_redirects(responses: dict[str, MagicMock]) -> MagicMock:
    """Patch ``request_with_safe_redirects`` at every import site the
    discoverer actually uses.

    The BNDE discoverer fetches listings through
    ``request_with_safe_redirects`` and discovers detail-page PDFs
    through ``scraper_transport.discover_pdf_urls_on_page`` which itself
    calls ``request_with_safe_redirects``. Both reference sites need
    to be patched for an end-to-end mock.
    """

    def fake_request(*, method: str, url: str, timeout: int, **_: object) -> MagicMock:
        if url not in responses:
            raise AssertionError(f"unexpected URL in test: {url}")
        return responses[url]

    p1 = patch(
        "discover_bndes_candidates.request_with_safe_redirects",
        side_effect=fake_request,
    )
    p2 = patch(
        "scraper_transport.request_with_safe_redirects",
        side_effect=fake_request,
    )

    class _Combined:
        def __enter__(self) -> None:
            p1.__enter__()
            p2.__enter__()

        def __exit__(self, *args: object) -> None:
            p2.__exit__(*args)
            p1.__exit__(*args)

    return _Combined()


class TestDiscoverCandidates:
    def test_returns_direct_pdfs_and_detail_page_pdfs(self) -> None:
        from discover_bndes_candidates import discover_candidates

        fundo_html = _read_fixture(LISTING_FUNDO)
        inovacao_html = _read_fixture(LISTING_INOVACAO)
        periferias_html = _read_fixture(DETAIL_PERIFERIAS)
        corais_html = _read_fixture(DETAIL_CORAIS)

        periferias_detail_url = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "financiamento/produto/bndes-fundo-socioambiental/"
            "chamada-publica-periferias-2026"
        )
        corais_detail_url = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "transparencia/chamadas/chamada-inovacao-cpsi-corais"
        )

        responses = {
            FUNDO_LISTING_URL: _make_response(fundo_html),
            INOVACAO_LISTING_URL: _make_response(inovacao_html),
            periferias_detail_url: _make_response(periferias_html),
            corais_detail_url: _make_response(corais_html),
        }

        with _patched_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        # 2 direct PDFs from listings + 4 PDFs from the two detail pages.
        assert stats["candidates"] == 6
        assert stats["listings_fetched"] == 2
        assert stats["details_fetched"] == 2
        assert stats["prefilter_rejected"] == 0

        assert (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "4f71d4b2-0a9a-4ca1-93f8-45d011e3074a/"
            "edital-fundo-socioambiental-2026.pdf?"
            "MOD=AJPERES&CVID=q123"
        ) in urls
        assert (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "bf28f4f7-dff7-4f95-bc22-616ee1d06754/"
            "cpsi-corais-edital.pdf?MOD=AJPERES"
        ) in urls
        assert (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "7e0d2f44-9c9d-4daa-a712-f1a8f6d95d5f/"
            "chamada-periferias-edital.pdf?MOD=AJPERES"
        ) in urls
        assert (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "e5e73f95-b03f-48ec-9d66-66ce4284f7a2/"
            "periferias-guia-inscricao.pdf?MOD=AJPERES"
        ) in urls
        assert (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "5cc7f2c9-9d4e-4af6-b24a-53d42de40bc9/"
            "chamada-corais-cpsi.pdf?MOD=AJPERES"
        ) in urls
        assert (
            "https://www.bndes.gov.br/wps/wcm/connect/site/"
            "f4c9fd8e-515e-44d0-98d4-4f90c11e7d16/"
            "corais-anexo-tecnico.pdf?MOD=AJPERES"
        ) in urls

        # Every candidate is a PDF with the bndes source and a discover timestamp.
        for candidate in candidates:
            assert candidate["kind"] == "pdf"
            assert candidate["metadata"]["source"] == "bndes"
            assert "discovered_at" in candidate["metadata"]
            assert candidate["metadata"]["listing_url"] in (
                FUNDO_LISTING_URL, INOVACAO_LISTING_URL,
            )

    def test_inherits_year_from_detail_url_for_detail_discovered_pdfs(self) -> None:
        """Detail-page PDFs that have no year in their own URL inherit
        the year from the detail URL when it is present (plan §9)."""
        from discover_bndes_candidates import discover_candidates

        fundo_html = _read_fixture(LISTING_FUNDO)
        periferias_html = _read_fixture(DETAIL_PERIFERIAS)
        periferias_detail_url = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "financiamento/produto/bndes-fundo-socioambiental/"
            "chamada-publica-periferias-2026"
        )

        responses = {
            FUNDO_LISTING_URL: _make_response(fundo_html),
            INOVACAO_LISTING_URL: _make_response("<html></html>"),
            periferias_detail_url: _make_response(periferias_html),
        }

        with _patched_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        detail_discovered = [
            c for c in candidates
            if c["metadata"].get("origin") == "detail_page"
        ]
        assert len(detail_discovered) == 2
        for candidate in detail_discovered:
            assert candidate["metadata"]["extracted_year"] == 2026
            assert candidate["metadata"]["detail_url"] == periferias_detail_url

    def test_year_filter_excludes_pre_2026_urls(self) -> None:
        from discover_bndes_candidates import discover_candidates

        fundo_listing_2025 = """
        <html>
          <body>
            <a href="/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental/chamada-publica-periferias-2025">
              Chamada 2025
            </a>
            <a href="/wps/wcm/connect/site/xyz/edital-2025.pdf?MOD=AJPERES">Edital 2025</a>
          </body>
        </html>
        """
        responses = {
            FUNDO_LISTING_URL: _make_response(fundo_listing_2025),
            INOVACAO_LISTING_URL: _make_response("<html></html>"),
        }

        with _patched_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        assert candidates == []
        assert stats["year_rejected"] == 1
        assert stats["candidates"] == 0

    def test_edital_prefilter_drops_non_edital_pdfs(self) -> None:
        from discover_bndes_candidates import discover_candidates

        # Both anchors carry the "edital" signal in the href so the
        # BNDE extractor passes them through; the prefilter then drops
        # the one whose filename matches an EDITAL exclusion pattern.
        listing_html = """
        <html>
          <body>
            <a href="/wps/wcm/connect/site/xyz/edital-relatorio-final.pdf?MOD=AJPERES">Resultado</a>
            <a href="/wps/wcm/connect/site/abc/edital-2026.pdf?MOD=AJPERES">Edital</a>
          </body>
        </html>
        """
        responses = {
            FUNDO_LISTING_URL: _make_response(listing_html),
            INOVACAO_LISTING_URL: _make_response("<html></html>"),
        }

        with _patched_request_with_safe_redirects(responses):
            stats, candidates = discover_candidates()

        urls = [c["url"] for c in candidates]
        assert len(urls) == 1
        assert urls[0].endswith("/edital-2026.pdf?MOD=AJPERES")
        assert stats["prefilter_rejected"] == 1

    def test_listing_fetch_failure_is_logged_in_stats(self) -> None:
        from discover_bndes_candidates import discover_candidates

        periferias_detail_url = (
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "financiamento/produto/bndes-fundo-socioambiental/"
            "chamada-publica-periferias-2026"
        )

        responses = {
            FUNDO_LISTING_URL: _make_response(_read_fixture(LISTING_FUNDO)),
            INOVACAO_LISTING_URL: _make_response(_read_fixture(LISTING_INOVACAO)),
            periferias_detail_url: _make_response("<html></html>"),
            "https://www.bndes.gov.br/wps/portal/site/home/"
            "transparencia/chamadas/chamada-inovacao-cpsi-corais": _make_response(
                "<html></html>",
            ),
        }

        def fake_request(*, method: str, url: str, timeout: int, **_: object) -> MagicMock:
            if url == periferias_detail_url:
                raise requests.ConnectionError("network down")
            if url not in responses:
                raise AssertionError(f"unexpected URL in test: {url}")
            return responses[url]

        with patch(
            "discover_bndes_candidates.request_with_safe_redirects",
            side_effect=fake_request,
        ):
            with patch(
                "scraper_transport.request_with_safe_redirects",
                side_effect=fake_request,
            ):
                stats, candidates = discover_candidates()

        assert stats["errors"] == 1
        # The fundo listing's direct PDF should still be there.
        urls = [c["url"] for c in candidates]
        assert any("edital-fundo-socioambiental-2026.pdf" in url for url in urls)


# ---------------------------------------------------------------------------
# Submit handoff
# ---------------------------------------------------------------------------

class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_bndes_source(self) -> None:
        import discover_bndes_candidates as dpc

        candidate = {
            "url": "https://www.bndes.gov.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "bndes"},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-12T12:00:00+00:00",
                "validation_outcome": "valid_pdf",
            },
        }

        # Stub the OCR worker modules before main() runs.
        ocr_mod = MagicMock()
        config_mod = MagicMock()
        sys.modules["ocr_worker.ocr_extraction_config"] = config_mod
        sys.modules["ocr_worker.pdf_markdown_extractor"] = ocr_mod
        try:
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
            assert call_args.kwargs["source"] == "bndes"
        finally:
            sys.modules.pop("ocr_worker.ocr_extraction_config", None)
            sys.modules.pop("ocr_worker.pdf_markdown_extractor", None)

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_bndes_candidates as dpc

        with patch.dict("os.environ", {}, clear=True):
            assert dpc.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_bndes_candidates as dpc

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
