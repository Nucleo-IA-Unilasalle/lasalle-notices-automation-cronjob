"""Unit tests for scripts/scraper_filters.py.

Ports the EDITAL inclusion/exclusion patterns, ``is_likely_edital``
URL/filename filter, and ``build_diagnostic_message`` helper from
``lasalle-notices-automation/app/services/scraper/{types,ingestion}.py``
into the cronjob. The cronjob only needs the URL/filename filter
(no DB), so the filter is kept alongside the patterns in one module.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import scraper_filters


# ---------------------------------------------------------------------------
# Pattern lists
# ---------------------------------------------------------------------------

class TestEditalPatterns:
    def test_inclusion_patterns_cover_expected_tokens(self) -> None:
        joined = " ".join(scraper_filters.EDITAL_INCLUSION_PATTERNS).lower()
        for token in ("edital", "chamada", "selecao", "bolsa", "auxilio"):
            assert token in joined, f"missing inclusion token: {token}"

    def test_exclusion_patterns_cover_expected_tokens(self) -> None:
        joined = " ".join(scraper_filters.EDITAL_EXCLUSION_PATTERNS).lower()
        for token in ("relatorio", "resultado", "manual", "modelo", "formulario", "errata"):
            assert token in joined, f"missing exclusion token: {token}"

    def test_tdr_pattern_is_a_separate_constant(self) -> None:
        assert scraper_filters.TDR_PATTERN in scraper_filters.EDITAL_EXCLUSION_PATTERNS


# ---------------------------------------------------------------------------
# resolve_filter_policy
# ---------------------------------------------------------------------------

class TestResolveFilterPolicy:
    def test_default_policy_prefilters_and_keeps_tdr_excluded(self) -> None:
        prefilter, exclusions = scraper_filters.resolve_filter_policy("default")
        assert prefilter is True
        assert scraper_filters.TDR_PATTERN in exclusions

    def test_include_tdr_policy_removes_tdr_exclusion(self) -> None:
        prefilter, exclusions = scraper_filters.resolve_filter_policy("include_tdr")
        assert prefilter is True
        assert scraper_filters.TDR_PATTERN not in exclusions

    def test_no_prefilter_policy_skips_filtering_but_returns_exclusions(self) -> None:
        prefilter, exclusions = scraper_filters.resolve_filter_policy("no_prefilter")
        assert prefilter is False
        assert scraper_filters.TDR_PATTERN in exclusions

    def test_unknown_policy_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="Unknown filter_policy"):
            scraper_filters.resolve_filter_policy("not-a-policy")


# ---------------------------------------------------------------------------
# is_likely_edital
# ---------------------------------------------------------------------------

class TestIsLikelyEdital:
    def test_accepts_edital_filename(self) -> None:
        assert scraper_filters.is_likely_edital(
            "edital_2026.pdf", "https://example.com/edital_2026.pdf"
        ) is True

    def test_accepts_edital_url_with_query(self) -> None:
        assert scraper_filters.is_likely_edital(
            "doc.pdf", "https://example.com/edital.pdf?MOD=AJPERES"
        ) is True

    def test_accepts_chamada_filename(self) -> None:
        assert scraper_filters.is_likely_edital(
            "chamada_publica_2026.pdf", "https://example.com/chamada_publica_2026.pdf"
        ) is True

    def test_rejects_resultado_filename(self) -> None:
        assert scraper_filters.is_likely_edital(
            "resultado_final.pdf", "https://example.com/resultado_final.pdf"
        ) is False

    def test_rejects_relatorio_filename(self) -> None:
        assert scraper_filters.is_likely_edital(
            "relatorio_anual.pdf", "https://example.com/relatorio_anual.pdf"
        ) is False

    def test_rejects_errata_filename(self) -> None:
        assert scraper_filters.is_likely_edital(
            "errata_01.pdf", "https://example.com/errata_01.pdf"
        ) is False

    def test_default_policy_still_excludes_tdr_like_documents(self) -> None:
        assert scraper_filters.is_likely_edital(
            "termo_de_referencia_chamada.pdf",
            "https://example.org/termo_de_referencia_chamada.pdf",
            filter_policy="default",
        ) is False

    def test_include_tdr_policy_accepts_tdr_like_documents(self) -> None:
        assert scraper_filters.is_likely_edital(
            "termo_de_referencia_chamada.pdf",
            "https://example.org/termo_de_referencia_chamada.pdf",
            filter_policy="include_tdr",
        ) is True

    def test_no_prefilter_policy_accepts_everything(self) -> None:
        assert scraper_filters.is_likely_edital(
            "resultado_final.pdf",
            "https://example.com/resultado_final.pdf",
            filter_policy="no_prefilter",
        ) is True

    def test_accepts_bolsas_filename(self) -> None:
        assert scraper_filters.is_likely_edital(
            "bolsas_estudo.pdf", "https://example.com/bolsas_estudo.pdf"
        ) is True

    def test_accepts_filename_without_url_token(self) -> None:
        # Empty filename + an edital-like URL should still match.
        assert scraper_filters.is_likely_edital(
            "", "https://example.com/chamada.pdf"
        ) is True

    def test_strips_diacritics_for_lookup(self) -> None:
        # The FastAPI original normalises á/é/í/ó/ú/ã/õ/ç before regex lookup.
        assert scraper_filters.is_likely_edital(
            "edital_chamada.pdf", "https://example.com/editais_publicados.pdf"
        ) is True


# ---------------------------------------------------------------------------
# build_diagnostic_message
# ---------------------------------------------------------------------------

class TestBuildDiagnosticMessage:
    def test_minimal_message(self) -> None:
        msg = scraper_filters.build_diagnostic_message(
            source_name="bndes",
            listing_url="https://example.com/listing",
            reason="no_pdfs_found",
        )
        assert msg == {
            "source": "bndes",
            "url": "https://example.com/listing",
            "kind": "diagnostic",
            "reason": "no_pdfs_found",
        }

    def test_message_with_status_code(self) -> None:
        msg = scraper_filters.build_diagnostic_message(
            source_name="brde",
            listing_url="https://example.com/listing",
            reason="blocking_status",
            status_code=403,
        )
        assert msg["status_code"] == 403
        assert msg["reason"] == "blocking_status"
        assert msg["kind"] == "diagnostic"
