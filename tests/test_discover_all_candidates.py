"""Unit tests for ``scripts/discover_all_candidates.py`` (Phase 5 orchestrator).

Verifies the unified discovery / download / OCR / submit shell that
loops over a ``SOURCES`` env var and delegates to the per-source
discoverer modules. PNCP is intentionally NOT exercised here (plan §5
recommends keeping ``pipeline-pncp-discovery.yml`` separate).
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from conftest import make_response  # noqa: F401  (re-exported for fixture reuse)


@pytest.fixture(autouse=True)
def reset_telemetry_breaker():
    import source_run_reporting as reporting
    reporting._process_breaker = reporting._TelemetryCircuitBreaker()


SCRIPTS_DIR = "scripts"


def test_stats_adapters_match_candidate_discoverer_shape() -> None:
    from discover_all_candidates import normalize_inventory_seen, normalize_in_scope, normalize_policy_rejected, normalize_stats
    stats = {"candidates": 3, "year_rejected": 2, "prefilter_rejected": 1, "ocr_failures": 1, "pdf_download_cap_reached": 1}
    assert normalize_inventory_seen(stats) == 3
    assert normalize_in_scope(stats) == 3
    assert normalize_policy_rejected(stats) == 3
    assert normalize_stats(stats)["cap_reached"] is True
    assert normalize_stats(stats)["ocr_failures"] == 1


def test_stats_adapters_keep_structured_inventory_distinct() -> None:
    from discover_all_candidates import normalize_inventory_seen, normalize_in_scope, normalize_policy_rejected
    stats = {"records": 9, "opportunities": 4, "year_rejected": 2, "prefilter_rejected": 1}
    assert normalize_inventory_seen(stats) == 9
    assert normalize_in_scope(stats) == 4
    assert normalize_policy_rejected(stats) == 3


def test_remaining_stats_adapters_and_fidelity_mapping() -> None:
    from discover_all_candidates import normalize_fidelity_blockers, normalize_stats
    stats = {"section_parse_failed": 1, "inventory_parse_failed": 2,
             "download_failures": 3, "submission_failures": 4,
             "detail_parse_failures": 5}
    normalized = normalize_stats(stats)
    assert normalized["parser_failures"] == 8
    assert normalized["download_failures"] == 3
    assert normalized["submission_failures"] == 4
    assert normalize_fidelity_blockers(stats) == 3


# ---------------------------------------------------------------------------
# SOURCES parsing
# ---------------------------------------------------------------------------


class TestParseSources:
    def test_empty_string_returns_empty_list(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("") == []

    def test_none_returns_empty_list(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources(None) == []

    def test_single_source(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("bndes") == ["bndes"]

    def test_comma_separated(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("bndes,brde,wwf") == ["bndes", "brde", "wwf"]

    def test_tolerates_whitespace_around_entries(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources(" bndes , brde ,  wwf  ") == [
            "bndes", "brde", "wwf",
        ]

    def test_drops_empty_entries(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("bndes,,brde,") == ["bndes", "brde"]

    def test_deduplicates_repeated_entries(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("bndes,brde,bndes,wwf,brde") == [
            "bndes", "brde", "wwf",
        ]

    def test_preserves_order(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("wwf,brde,bndes") == ["wwf", "brde", "bndes"]

    def test_whitespace_only_entries_are_dropped(self) -> None:
        from discover_all_candidates import parse_sources

        assert parse_sources("bndes, , ,brde") == ["bndes", "brde"]


# ---------------------------------------------------------------------------
# Dynamic import
# ---------------------------------------------------------------------------


ALL_REGISTERED_SOURCES = (
    "bndes",
    "brde",
    "fapergs",
    "funbio",
    "govbr_mma",
    "govbr_mma_public_calls",
    "govbr_mma_fnma",
    "iis_rio",
    "sema_rs",
    "tnc",
    "unep",
    "worldbank",
    "wwf",
    "fao",
    "fundacao_grupo_boticario",
    "kfw",
    "msgov",
    "ibama",
)


class TestLoadDiscoverer:
    def test_unknown_source_raises_unknown_source_error(self) -> None:
        from discover_all_candidates import (
            UnknownSourceError,
            load_discoverer,
        )

        with pytest.raises(UnknownSourceError):
            load_discoverer("not_a_real_source")

    def test_pncp_is_not_registered(self) -> None:
        """Plan §5 keeps PNCP on its own workflow; it must not appear
        in the orchestrator's source registry."""
        from discover_all_candidates import SOURCE_MODULES

        assert "pncp" not in SOURCE_MODULES

    @pytest.mark.parametrize("source", ALL_REGISTERED_SOURCES)
    def test_each_registered_source_imports_successfully(
        self, source: str,
    ) -> None:
        from discover_all_candidates import load_discoverer

        module = load_discoverer(source)
        assert callable(getattr(module, "discover_candidates", None))
        assert callable(getattr(module, "main", None))

    @pytest.mark.parametrize("source", ALL_REGISTERED_SOURCES)
    def test_each_registered_source_has_matching_module_name(
        self, source: str,
    ) -> None:
        from discover_all_candidates import SOURCE_MODULES

        assert SOURCE_MODULES[source] == f"discover_{source}_candidates"


# ---------------------------------------------------------------------------
# discover_source — inspect-driven param pass-through
# ---------------------------------------------------------------------------


BS4_SAMPLE = "bndes"
PLAYWRIGHT_SAMPLE = "fao"


class TestDiscoverSource:
    def test_bs4_discoverer_receives_filter_policy_and_min_year(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from discover_all_candidates import discover_source

        discoverer = importlib.import_module("discover_bndes_candidates")
        captured: dict[str, Any] = {}

        def fake_discover_candidates(
            *, filter_policy: str, min_year: int,
        ) -> tuple[dict[str, int], list[dict[str, Any]]]:
            captured["filter_policy"] = filter_policy
            captured["min_year"] = min_year
            return {"candidates": 0}, []

        monkeypatch.setattr(
            discoverer, "discover_candidates", fake_discover_candidates,
        )

        _, candidates = discover_source(
            discoverer, filter_policy="include_tdr", min_year=2027,
        )

        assert captured == {"filter_policy": "include_tdr", "min_year": 2027}
        assert candidates == []

    def test_playwright_discoverer_receives_no_extra_kwargs(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from discover_all_candidates import discover_source

        discoverer = importlib.import_module("discover_fao_candidates")
        captured: dict[str, Any] = {}

        def fake_discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]]]:
            captured["called"] = True
            return {"candidates": 0}, []

        monkeypatch.setattr(
            discoverer, "discover_candidates", fake_discover_candidates,
        )

        discover_source(
            discoverer, filter_policy="default", min_year=2026,
        )

        assert captured == {"called": True}

    def test_returns_stats_and_candidates_tuple(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from discover_all_candidates import discover_source

        discoverer = importlib.import_module("discover_bndes_candidates")
        sample_stats: dict[str, int] = {"candidates": 2, "errors": 1}
        sample_candidates: list[dict[str, Any]] = [
            {"url": "https://example.com/a.pdf", "kind": "pdf",
             "metadata": {"source": "bndes"}},
        ]

        def fake_discover_candidates(
            *, filter_policy: str, min_year: int,
        ) -> tuple[dict[str, int], list[dict[str, Any]]]:
            return sample_stats, sample_candidates

        monkeypatch.setattr(
            discoverer, "discover_candidates", fake_discover_candidates,
        )

        stats, candidates = discover_source(
            discoverer, filter_policy="default", min_year=2026,
        )
        assert stats == sample_stats
        assert candidates == sample_candidates


class TestDiscoverSourceOpportunities:
    def test_discards_optional_checkpoint_from_pncp_style_result(self) -> None:
        from discover_all_candidates import discover_source_opportunities

        discoverer = MagicMock()
        discoverer.__dict__["discover_opportunities"] = lambda: (
            {"opportunities": 1},
            [{"source_record_id": "2026-0001"}],
            "2026-07-23T00:00:00+00:00",
        )

        result = discover_source_opportunities(discoverer, min_year=2026)

        assert result == (
            {"opportunities": 1},
            [{"source_record_id": "2026-0001"}],
        )


# ---------------------------------------------------------------------------
# process_source_candidates — shared cap behaviour
# ---------------------------------------------------------------------------


def _fake_processed(url: str, *, ok: bool) -> dict[str, Any]:
    if ok:
        return {
            "url": url,
            "kind": "pdf",
            "metadata": {"source": "bndes"},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 10,
                "validated_at": "2026-06-12T12:00:00+00:00",
                "validation_outcome": "valid_pdf",
            },
        }
    return {
        "url": url,
        "metadata": {"source": "bndes"},
        "error": "download: HTTP 404",
    }


class TestProcessSourceCandidates:
    def test_returns_processed_list_and_records_downloads(self) -> None:
        from discover_all_candidates import process_source_candidates

        candidates = [
            {"url": "https://example.com/a.pdf", "kind": "pdf",
             "metadata": {"source": "bndes"}},
            {"url": "https://example.com/b.pdf", "kind": "pdf",
             "metadata": {"source": "bndes"}},
        ]

        with patch(
            "discover_all_candidates.pipeline_core.process_candidate",
            side_effect=lambda c, **_: _fake_processed(c["url"], ok=True),
        ) as mock_process:
            processed = process_source_candidates(
                candidates, extractor=MagicMock(), stats={},
            )

        assert len(processed) == 2
        assert mock_process.call_count == 2
        assert all(r.get("worker_result") for r in processed)

    def test_stops_at_pdf_download_cap(self) -> None:
        from discover_all_candidates import process_source_candidates
        import pipeline_core

        original_cap = pipeline_core.SCRAPE_MAX_PDFS_PER_RUN
        pipeline_core.SCRAPE_MAX_PDFS_PER_RUN = 2
        try:
            candidates = [
                {"url": f"https://example.com/{i}.pdf", "kind": "pdf",
                 "metadata": {"source": "bndes"}}
                for i in range(5)
            ]
            stats: dict[str, int] = {}

            with patch(
                "discover_all_candidates.pipeline_core.process_candidate",
                side_effect=lambda c, **_: _fake_processed(c["url"], ok=True),
            ) as mock_process:
                processed = process_source_candidates(
                    candidates, extractor=MagicMock(), stats=stats,
                )
        finally:
            pipeline_core.SCRAPE_MAX_PDFS_PER_RUN = original_cap

        assert mock_process.call_count == 2
        assert len(processed) == 2
        assert stats["pdfs_downloaded"] == 2
        assert stats.get("pdf_download_cap_reached") == 1

    def test_failed_downloads_do_not_increment_counter(self) -> None:
        from discover_all_candidates import process_source_candidates

        candidates = [
            {"url": "https://example.com/a.pdf", "kind": "pdf",
             "metadata": {"source": "bndes"}},
            {"url": "https://example.com/b.pdf", "kind": "pdf",
             "metadata": {"source": "bndes"}},
        ]

        side_effects = [
            _fake_processed("https://example.com/a.pdf", ok=False),
            _fake_processed("https://example.com/b.pdf", ok=True),
        ]

        with patch(
            "discover_all_candidates.pipeline_core.process_candidate",
            side_effect=side_effects,
        ):
            processed = process_source_candidates(
                candidates, extractor=MagicMock(), stats={},
            )

        assert len(processed) == 2
        assert processed[0].get("error")
        assert processed[1].get("worker_result")

    def test_skips_candidates_when_cap_already_reached(self) -> None:
        from discover_all_candidates import process_source_candidates
        import pipeline_core

        original_cap = pipeline_core.SCRAPE_MAX_PDFS_PER_RUN
        pipeline_core.SCRAPE_MAX_PDFS_PER_RUN = 1
        try:
            candidates = [
                {"url": "https://example.com/a.pdf", "kind": "pdf",
                 "metadata": {"source": "bndes"}},
                {"url": "https://example.com/b.pdf", "kind": "pdf",
                 "metadata": {"source": "bndes"}},
            ]
            stats: dict[str, int] = {"pdfs_downloaded": 1}

            with patch(
                "discover_all_candidates.pipeline_core.process_candidate",
            ) as mock_process:
                processed = process_source_candidates(
                    candidates, extractor=MagicMock(), stats=stats,
                )
        finally:
            pipeline_core.SCRAPE_MAX_PDFS_PER_RUN = original_cap

        assert mock_process.call_count == 0
        assert processed == []
        assert stats.get("pdf_download_cap_reached") == 1


# ---------------------------------------------------------------------------
# main() — env-var validation
# ---------------------------------------------------------------------------


def _stub_ocr_modules() -> None:
    """Inject ``MagicMock`` placeholders for the OCR worker modules so
    ``make_default_ocr_extractor`` does not require Paddle at import
    time."""
    ocr_mod = MagicMock()
    config_mod = MagicMock()
    sys.modules.setdefault(
        "ocr_worker.ocr_extraction_config", config_mod,
    )
    sys.modules.setdefault(
        "ocr_worker.pdf_markdown_extractor", ocr_mod,
    )


class TestMainEnvValidation:
    def test_audit_only_does_not_require_render_credentials(self) -> None:
        from discover_all_candidates import main

        env = {
            "SOURCES": "bndes",
            "DISCOVERY_AUDIT_ONLY": "true",
            "DISCOVERY_AUDIT_DIR": "artifacts/test-audit",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.discover_source",
            return_value=({"candidates": 0}, []),
        ), patch(
            "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
        ) as mock_extractor:
            assert main() == 0
        mock_extractor.assert_not_called()

    def test_audit_only_requires_artifact_directory(self) -> None:
        from discover_all_candidates import main

        with patch.dict(os.environ, {
            "SOURCES": "bndes",
            "DISCOVERY_AUDIT_ONLY": "true",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_render_app_url_missing(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "SOURCES": "bndes",
            "PIPELINE_SECRET": "tok",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_pipeline_secret_missing(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "SOURCES": "bndes",
            "RENDER_APP_URL": "https://r.example.com",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_sources_missing(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_sources_empty_string(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "  ,, ",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_sources_contains_unknown(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes,not_a_real_source",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_min_notice_year_not_integer(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes",
            "MIN_NOTICE_YEAR": "twentytwenty-six",
        }, clear=True):
            assert main() == 2

    def test_returns_2_when_filter_policy_invalid(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        with patch.dict(os_environ_clean(), {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes",
            "FILTER_POLICY": "everything",
        }, clear=True):
            assert main() == 2


def os_environ_clean() -> dict[str, str]:
    """Return an empty dict for use with ``patch.dict(..., clear=True)``."""
    return {}


# ---------------------------------------------------------------------------
# main() — orchestration loop
# ---------------------------------------------------------------------------


def _candidate(url: str, source: str) -> dict[str, Any]:
    return {
        "url": url,
        "kind": "pdf",
        "metadata": {"source": source},
    }


def _processed(url: str, *, ok: bool = True) -> dict[str, Any]:
    return _fake_processed(url, ok=ok)


class TestMainOrchestration:
    def test_telemetry_failure_preserves_ingestion_but_propagates_exit_code(self) -> None:
        from discover_all_candidates import main
        _stub_ocr_modules()
        d = MagicMock(); candidate = _candidate("https://x/a.pdf", "bndes")
        env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok",
               "SOURCES": "bndes", "SOURCE_RUN_REPORTING_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.load_discoverer", return_value=d), patch("discover_all_candidates.discover_source", return_value=({"candidates": 1}, [candidate])), patch("discover_all_candidates.process_source_candidates", return_value=[_processed(candidate["url"])]), patch("discover_all_candidates.pipeline_core.submit_candidates", return_value={"submitted": 1, "failed_batches": 0}), patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor", return_value=(MagicMock(), MagicMock())), patch("source_run_reporting.requests.post", side_effect=__import__('requests').ConnectionError), patch("source_run_reporting.time.sleep"):
            assert main() != 0

    def test_discovery_failure_is_reported_as_failed(self) -> None:
        from discover_all_candidates import main
        _stub_ocr_modules(); d = MagicMock()
        env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok", "SOURCES": "bndes", "SOURCE_RUN_REPORTING_ENABLED": "true"}
        start = MagicMock(status_code=201); start.json.return_value = {"id": "r"}
        finish = MagicMock(status_code=200); finish.json.return_value = {"status": "failed"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.load_discoverer", return_value=d), patch("discover_all_candidates.discover_source", side_effect=RuntimeError("boom")), patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor", return_value=(MagicMock(), MagicMock())), patch("source_run_reporting.requests.post", return_value=start), patch("source_run_reporting.requests.patch", return_value=finish) as p:
            assert main() == 1
        assert p.call_args.kwargs["json"]["status"] == "failed"
        assert p.call_args.kwargs["json"]["error_code"] == "scraping_failed"

    def test_parser_failure_is_reported_failed_not_warning(self) -> None:
        from discover_all_candidates import main
        _stub_ocr_modules(); d = MagicMock(); env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok", "SOURCES": "bndes", "SOURCE_RUN_REPORTING_ENABLED": "true"}
        start = MagicMock(status_code=201); start.json.return_value = {"id": "r"}; finish = MagicMock(status_code=200); finish.json.return_value = {"status": "failed"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.load_discoverer", return_value=d), patch("discover_all_candidates.discover_source", return_value=({"candidates": 0, "section_parse_failed": 1}, [])), patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor", return_value=(MagicMock(), MagicMock())), patch("source_run_reporting.requests.post", return_value=start), patch("source_run_reporting.requests.patch", return_value=finish) as p:
            assert main() == 1
        assert p.call_args.kwargs["json"]["status"] == "failed"

    def test_multi_source_ingest_is_rejected_before_discovery(self) -> None:
        from discover_all_candidates import main
        env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok", "SOURCES": "bndes,brde"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.load_discoverer") as discover, patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor") as ocr:
            assert main() == 2
        discover.assert_not_called()
        ocr.assert_not_called()

    def test_submission_counts_map_invalid_and_failed_batches_to_errors(self) -> None:
        from discover_all_candidates import main
        _stub_ocr_modules(); c = _candidate("https://x/a.pdf", "bndes"); env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok", "SOURCES": "bndes", "SOURCE_RUN_REPORTING_ENABLED": "true"}
        start = MagicMock(status_code=201); start.json.return_value = {"id": "r"}; finish = MagicMock(status_code=200); finish.json.return_value = {"status": "warning"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.load_discoverer", return_value=MagicMock()), patch("discover_all_candidates.discover_source", return_value=({"candidates": 1}, [c])), patch("discover_all_candidates.process_source_candidates", return_value=[_processed(c["url"])]), patch("discover_all_candidates.pipeline_core.submit_candidates", return_value={"submitted": 1, "failed_batches": 1, "outcome_counts": {"invalid": 2}}), patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor", return_value=(MagicMock(), MagicMock())), patch("source_run_reporting.requests.post", return_value=start), patch("source_run_reporting.requests.patch", return_value=finish) as p:
            assert main() == 1
        body = p.call_args.kwargs["json"]; assert body["errors"] == 4 and body["status"] == "warning"

    def test_flag_off_does_not_call_telemetry(self) -> None:
        from discover_all_candidates import main
        _stub_ocr_modules(); env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok", "SOURCES": "bndes"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.discover_source", return_value=({"candidates": 0}, [])), patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor", return_value=(MagicMock(), MagicMock())), patch("source_run_reporting.requests.post") as post:
            assert main() == 0
        post.assert_not_called()

    def test_ibama_requires_explicit_structured_opt_in_for_submission(self) -> None:
        from discover_all_candidates import main

        ibama = MagicMock()
        ibama.__dict__["discover_opportunities"] = lambda: (
            {"opportunities": 1},
            [{"source_key": "ibama"}],
        )
        ibama.__dict__["discover_candidates"] = lambda **_: (
            {"inventory_parse_failed": 1},
            [],
        )
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "ibama",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.load_discoverer", return_value=ibama,
        ), patch(
            "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
            return_value=(MagicMock(), MagicMock()),
        ), patch(
            "discover_all_candidates.pipeline_core.submit_opportunities",
        ) as submit:
            assert main() == 1
        submit.assert_not_called()

        env["OPPORTUNITY_SOURCES"] = "ibama"
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.load_discoverer", return_value=ibama,
        ), patch(
            "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
            return_value=(MagicMock(), MagicMock()),
        ), patch(
            "discover_all_candidates.pipeline_core.process_opportunity",
            side_effect=lambda opportunity, **_: opportunity,
        ), patch(
            "discover_all_candidates.pipeline_core.submit_opportunities",
            return_value={"submitted": 1},
        ) as submit:
            assert main() == 0
        submit.assert_called_once()

    def test_manual_finep_and_fbds_use_structured_route_without_allowlist(self) -> None:
        from discover_all_candidates import main

        def structured_discover():
            return {"opportunities": 1}, [{"source_key": "structured"}]

        finep = MagicMock()
        finep.__dict__["discover_opportunities"] = structured_discover
        fbds = MagicMock()
        fbds.__dict__["discover_opportunities"] = structured_discover

        with patch.dict(os.environ, {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "finep,fbds",
        }, clear=True), patch(
            "discover_all_candidates.load_discoverer",
            side_effect={"finep": finep, "fbds": fbds}.get,
        ), patch(
            "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
            return_value=(MagicMock(), MagicMock()),
        ), patch(
            "discover_all_candidates.pipeline_core.process_opportunity",
            side_effect=lambda opportunity, **_: opportunity,
        ), patch(
            "discover_all_candidates.pipeline_core.submit_opportunities",
            return_value={"submitted": 1},
        ) as submit:
            os.environ["SOURCES"] = "finep"
            assert main() == 0
            os.environ["SOURCES"] = "fbds"
            assert main() == 0

        assert [call.args[0][0]["source_key"] for call in submit.call_args_list] == [
            "structured", "structured"
        ]

    def test_dopa_requires_explicit_structured_opt_in_for_submission(self) -> None:
        from discover_all_candidates import main

        dopa = MagicMock()
        dopa.__dict__["discover_opportunities"] = lambda: (
            {"opportunities": 1},
            [{"source_key": "dopa"}],
        )
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "dopa",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.load_discoverer", return_value=dopa,
        ), patch(
            "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
            return_value=(MagicMock(), MagicMock()),
        ), patch(
            "discover_all_candidates.pipeline_core.submit_opportunities",
        ) as submit:
            assert main() == 1
        submit.assert_not_called()

        env["OPPORTUNITY_SOURCES"] = "dopa"
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.load_discoverer", return_value=dopa,
        ), patch(
            "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
            return_value=(MagicMock(), MagicMock()),
        ), patch(
            "discover_all_candidates.pipeline_core.process_opportunity",
            side_effect=lambda opportunity, **_: opportunity,
        ), patch(
            "discover_all_candidates.pipeline_core.submit_opportunities",
            return_value={"submitted": 1},
        ) as submit:
            assert main() == 0
        submit.assert_called_once()

    def test_audit_only_never_processes_or_submits_opportunities(
        self, tmp_path,
    ) -> None:
        from discover_all_candidates import main

        opportunity = {
            "source_key": "finep",
            "source_record_id": "42",
            "canonical_url": "https://example.com/42",
            "title": "Chamada",
            "documents": [],
        }
        discoverer = MagicMock()
        discoverer.__dict__["discover_opportunities"] = lambda: (
            {"opportunities": 1},
            [opportunity],
        )
        env = {
            "SOURCES": "finep",
            "DISCOVERY_AUDIT_ONLY": "true",
            "DISCOVERY_AUDIT_DIR": str(tmp_path),
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.load_discoverer",
            return_value=discoverer,
        ), patch(
            "discover_all_candidates.pipeline_core.process_opportunity",
        ) as mock_process, patch(
            "discover_all_candidates.pipeline_core.submit_opportunities",
        ) as mock_submit:
            assert main() == 0

        mock_process.assert_not_called()
        mock_submit.assert_not_called()
        assert (tmp_path / "finep" / "opportunities.json").exists()

    def test_returns_0_when_all_sources_yield_no_candidates(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes,brde",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.discover_source",
                return_value=({"candidates": 0}, []),
            ) as mock_disc:
                os.environ["SOURCES"] = "bndes"
                assert main() == 0
                os.environ["SOURCES"] = "brde"
                assert main() == 0
                assert mock_disc.call_count == 2

    def test_returns_1_when_source_reports_parser_failure(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "wwf",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.discover_source",
                return_value=(
                    {"candidates": 0, "errors": 1, "section_parse_failed": 1},
                    [],
                ),
            ):
                assert main() == 1

    def test_returns_1_when_candidate_submission_is_partial(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        candidate = _candidate("https://example.com/edital.pdf", "bndes")
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "discover_all_candidates.discover_source",
            return_value=({"candidates": 1}, [candidate]),
        ), patch(
            "discover_all_candidates.process_source_candidates",
            return_value=[_processed(candidate["url"])],
        ), patch(
            "discover_all_candidates.pipeline_core.submit_candidates",
            return_value={"submitted": 1, "failed_batches": 1},
        ):
            assert main() == 1

    def test_partial_source_error_does_not_discard_valid_candidates(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        candidate = {"url": "https://example.com/edital.pdf", "kind": "pdf"}
        processed = [{**candidate, "worker_result": {"ocr_markdown": "# Edital"}}]
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "govbr_mma_public_calls",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.discover_source",
                return_value=({"candidates": 1, "errors": 1}, [candidate]),
            ), patch(
                "discover_all_candidates.process_source_candidates",
                return_value=processed,
            ) as mock_process, patch(
                "discover_all_candidates.pipeline_core.submit_candidates",
                return_value={"submitted": 1},
            ) as mock_submit:
                assert main() == 0
        mock_process.assert_called_once()
        mock_submit.assert_called_once()

    def test_calls_submit_candidates_with_correct_source_per_source(
        self,
    ) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes,brde",
        }

        discoverer_bndes = MagicMock()
        discoverer_brde = MagicMock()

        candidates_bndes = [_candidate("https://x.com/b.pdf", "bndes")]
        candidates_brde = [_candidate("https://x.com/r.pdf", "brde")]

        discover_returns = {
            "bndes": ({"candidates": 1}, candidates_bndes),
            "brde": ({"candidates": 1}, candidates_brde),
        }

        def fake_discover_source(discoverer, **_: Any):
            return discover_returns[discoverer._name]

        discoverer_bndes._name = "bndes"
        discoverer_brde._name = "brde"
        # Force discover_candidates on each discoverer to return the
        # candidates we want to process. discover_source() in the
        # orchestrator inspects the signature, so we just call through.
        discoverer_bndes.discover_candidates.return_value = discover_returns["bndes"]
        discoverer_brde.discover_candidates.return_value = discover_returns["brde"]

        def fake_load_discoverer(source: str):
            return {"bndes": discoverer_bndes, "brde": discoverer_brde}[source]

        processed_calls: list[str] = []

        def fake_process(candidates, **_: Any):
            processed_calls.extend(c["url"] for c in candidates)
            return [_processed(c["url"]) for c in candidates]

        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.load_discoverer",
                side_effect=fake_load_discoverer,
            ):
                with patch(
                    "discover_all_candidates.discover_source",
                    side_effect=fake_discover_source,
                ):
                    with patch(
                        "discover_all_candidates.process_source_candidates",
                        side_effect=fake_process,
                    ):
                        with patch(
                            "discover_all_candidates.pipeline_core"
                            ".submit_candidates",
                            return_value={
                                "total": 1,
                                "submitted": 1,
                                "failed_batches": 0,
                                "errors": [],
                            },
                        ) as mock_submit:
                            with patch(
                                "discover_all_candidates.pipeline_core"
                                ".make_default_ocr_extractor",
                                return_value=(MagicMock(), MagicMock()),
                            ):
                                os.environ["SOURCES"] = "bndes"
                                assert main() == 0
                                os.environ["SOURCES"] = "brde"
                                assert main() == 0

        assert mock_submit.call_count == 2
        submitted_sources = [
            call.kwargs["source"]
            for call in mock_submit.call_args_list
        ]
        assert submitted_sources == ["bndes", "brde"]
        assert processed_calls == [
            "https://x.com/b.pdf", "https://x.com/r.pdf",
        ]

    def test_continues_after_per_source_failure(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes,brde,fapergs",
        }

        candidates_brde = [_candidate("https://x.com/r.pdf", "brde")]

        discoverer_bndes = MagicMock()
        discoverer_brde = MagicMock()
        discoverer_fapergs = MagicMock()
        discoverer_bndes._source = "bndes"
        discoverer_brde._source = "brde"
        discoverer_fapergs._source = "fapergs"
        discoverer_brde.discover_candidates.return_value = (
            {"candidates": 1}, candidates_brde,
        )

        def fake_load(source: str):
            return {
                "bndes": discoverer_bndes,
                "brde": discoverer_brde,
                "fapergs": discoverer_fapergs,
            }[source]

        def fake_discover(discoverer, **_: Any):
            if discoverer._source == "bndes":
                raise RuntimeError("network down")
            return discoverer.discover_candidates()

        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.load_discoverer",
                side_effect=fake_load,
            ):
                with patch(
                    "discover_all_candidates.discover_source",
                    side_effect=fake_discover,
                ):
                    with patch(
                        "discover_all_candidates.process_source_candidates",
                        return_value=[_processed("https://x.com/r.pdf")],
                    ):
                        with patch(
                            "discover_all_candidates.pipeline_core"
                            ".submit_candidates",
                            return_value={
                                "total": 1,
                                "submitted": 1,
                                "failed_batches": 0,
                                "errors": [],
                            },
                        ) as mock_submit:
                            with patch(
                                "discover_all_candidates.pipeline_core"
                                ".make_default_ocr_extractor",
                                return_value=(MagicMock(), MagicMock()),
                            ):
                                os.environ["SOURCES"] = "bndes"
                                assert main() == 1
                                os.environ["SOURCES"] = "brde"
                                assert main() == 0
                                os.environ["SOURCES"] = "wwf"
                                assert main() == 1

        assert mock_submit.call_count == 1
        assert mock_submit.call_args.kwargs["source"] == "brde"

    def test_multi_source_ingest_never_initializes_ocr(self) -> None:
        from discover_all_candidates import main
        env = {"RENDER_APP_URL": "https://r.example.com", "PIPELINE_SECRET": "tok", "SOURCES": "bndes,brde"}
        with patch.dict(os.environ, env, clear=True), patch("discover_all_candidates.load_discoverer") as discover, patch("discover_all_candidates.pipeline_core.make_default_ocr_extractor") as ocr:
            assert main() == 2
        discover.assert_not_called()
        ocr.assert_not_called()

    def test_returns_1_when_all_candidates_fail_ocr(self) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes",
        }

        discoverer_bndes = MagicMock()
        discoverer_bndes.discover_candidates.return_value = (
            {"candidates": 1},
            [_candidate("https://x.com/bad.pdf", "bndes")],
        )

        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.load_discoverer",
                return_value=discoverer_bndes,
            ):
                with patch(
                    "discover_all_candidates.discover_source",
                    return_value=discoverer_bndes.discover_candidates.return_value,
                ):
                    with patch(
                        "discover_all_candidates.process_source_candidates",
                        return_value=[_processed(
                            "https://x.com/bad.pdf", ok=False,
                        )],
                    ):
                        with patch(
                            "discover_all_candidates.pipeline_core"
                            ".submit_candidates",
                        ) as mock_submit:
                            with patch(
                                "discover_all_candidates.pipeline_core"
                                ".make_default_ocr_extractor",
                                return_value=(MagicMock(), MagicMock()),
                            ):
                                assert main() == 1

        mock_submit.assert_not_called()

    def test_returns_1_when_submit_returns_zero_for_known_candidates(
        self,
    ) -> None:
        from discover_all_candidates import main

        _stub_ocr_modules()
        env = {
            "RENDER_APP_URL": "https://r.example.com",
            "PIPELINE_SECRET": "tok",
            "SOURCES": "bndes",
        }

        discoverer_bndes = MagicMock()
        discoverer_bndes.discover_candidates.return_value = (
            {"candidates": 1},
            [_candidate("https://x.com/b.pdf", "bndes")],
        )

        with patch.dict(os.environ, env, clear=True):
            with patch(
                "discover_all_candidates.load_discoverer",
                return_value=discoverer_bndes,
            ):
                with patch(
                    "discover_all_candidates.discover_source",
                    return_value=discoverer_bndes.discover_candidates.return_value,
                ):
                    with patch(
                        "discover_all_candidates.process_source_candidates",
                        return_value=[_processed("https://x.com/b.pdf")],
                    ):
                        with patch(
                            "discover_all_candidates.pipeline_core"
                            ".submit_candidates",
                            return_value={
                                "total": 1,
                                "submitted": 0,
                                "failed_batches": 1,
                                "errors": ["batch 1/1: HTTP 500"],
                            },
                        ) as mock_submit:
                            with patch(
                                "discover_all_candidates.pipeline_core"
                                ".make_default_ocr_extractor",
                                return_value=(MagicMock(), MagicMock()),
                            ):
                                assert main() == 1

        mock_submit.assert_called_once()
        assert mock_submit.call_args.kwargs["source"] == "bndes"

    def test_min_notice_year_defaults_to_2026(self) -> None:
        from discover_all_candidates import _resolve_min_year

        with patch.dict(os.environ, {}, clear=True):
            assert _resolve_min_year() == 2026

    def test_min_notice_year_honours_env_override(self) -> None:
        from discover_all_candidates import _resolve_min_year

        with patch.dict(os.environ, {"MIN_NOTICE_YEAR": "2030"}, clear=True):
            assert _resolve_min_year() == 2030

    def test_filter_policy_defaults_to_default(self) -> None:
        from discover_all_candidates import _resolve_filter_policy

        with patch.dict(os.environ, {}, clear=True):
            assert _resolve_filter_policy() == "default"

    def test_filter_policy_accepts_known_values(self) -> None:
        from discover_all_candidates import _resolve_filter_policy

        for value in ("default", "include_tdr", "no_prefilter"):
            with patch.dict(os.environ, {"FILTER_POLICY": value}, clear=True):
                assert _resolve_filter_policy() == value


# ---------------------------------------------------------------------------
# Importing discover_all_candidates reloads cleanly after env edits
# ---------------------------------------------------------------------------


class TestModuleReload:
    def test_imports_cleanly_with_minimal_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("discover_all_candidates")
            assert module.SOURCE_MODULES["bndes"] == "discover_bndes_candidates"


class TestPerSourceTelemetryIsolation:
    """Plan 02: per-source counters must never absorb cumulative shared_stats,
    and downloads must be counted separately from OCR successes."""

    def test_merge_shared_caps_keeps_only_cap_flags_from_shared_stats(self):
        from discover_all_candidates import merge_shared_caps

        source_stats = {"download_failures": 2, "detail_parse_failures": 1}
        shared_stats = {
            "pdfs_downloaded": 9,
            "pdf_download_cap_reached": 1,
            "download_failures": 7,  # accumulated from prior sources
        }
        merged = merge_shared_caps(source_stats, shared_stats)
        assert merged["download_failures"] == 2
        assert merged["detail_parse_failures"] == 1
        assert merged["pdf_download_cap_reached"] == 1
        assert "pdfs_downloaded" not in merged

    def test_merge_shared_caps_without_shared_flags_is_pure_source_stats(self):
        from discover_all_candidates import merge_shared_caps

        source_stats = {"ocr_failures": 3}
        assert merge_shared_caps(source_stats, {"pdfs_downloaded": 5}) == {"ocr_failures": 3}

    def test_count_processed_outcomes_separates_downloads_from_ocr(self):
        from discover_all_candidates import count_processed_outcomes

        processed = [
            {"url": "a", "worker_result": {"ocr_markdown": "x"}},
            {"url": "b", "worker_result": {"ocr_markdown": "y"}},
            {"url": "c", "error": "ocr: paddle exploded"},
            {"url": "d", "error": "download: connection reset"},
            {"url": "e", "error": "download: http 403"},
        ]
        downloaded, ocr_ok, download_failures, ocr_failures = count_processed_outcomes(processed)
        # 2 OCR successes + 1 OCR failure downloaded bytes; the 2 download
        # failures consumed no bytes and are not counted as downloads.
        assert (downloaded, ocr_ok, download_failures, ocr_failures) == (3, 2, 2, 1)
