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


SCRIPTS_DIR = "scripts"


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
                assert main() == 0
                assert mock_disc.call_count == 2

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
                                assert main() == 1

        assert mock_submit.call_count == 1
        assert mock_submit.call_args.kwargs["source"] == "brde"

    def test_respects_shared_pdf_download_cap_across_sources(self) -> None:
        from discover_all_candidates import main
        import pipeline_core

        _stub_ocr_modules()
        original_cap = pipeline_core.SCRAPE_MAX_PDFS_PER_RUN
        pipeline_core.SCRAPE_MAX_PDFS_PER_RUN = 1
        try:
            env = {
                "RENDER_APP_URL": "https://r.example.com",
                "PIPELINE_SECRET": "tok",
                "SOURCES": "bndes,brde,wwf",
            }

            candidates_bndes = [_candidate("https://x.com/b.pdf", "bndes")]
            candidates_brde = [_candidate("https://x.com/r.pdf", "brde")]

            discoverer_bndes = MagicMock()
            discoverer_brde = MagicMock()
            discoverer_wwf = MagicMock()
            discoverer_bndes._source = "bndes"
            discoverer_brde._source = "brde"
            discoverer_wwf._source = "wwf"
            discoverer_bndes.discover_candidates.return_value = (
                {"candidates": 1}, candidates_bndes,
            )
            discoverer_brde.discover_candidates.return_value = (
                {"candidates": 1}, candidates_brde,
            )
            discoverer_wwf.discover_candidates.return_value = (
                {"candidates": 1}, [_candidate("https://x.com/w.pdf", "wwf")],
            )

            def fake_load(source: str):
                return {
                    "bndes": discoverer_bndes,
                    "brde": discoverer_brde,
                    "wwf": discoverer_wwf,
                }[source]

            def fake_discover(discoverer, **_: Any):
                return discoverer.discover_candidates()

            submitted_sources: list[str] = []

            def fake_process(candidates, *, stats, **_: Any):
                # Pretend the first candidate succeeded, cap is reached
                # after that, so the next call short-circuits with [].
                if "pdfs_downloaded" not in stats:
                    stats["pdfs_downloaded"] = 1
                    return [_processed(c["url"]) for c in candidates]
                return []

            def fake_submit(processed, **kwargs: Any):
                submitted_sources.append(kwargs["source"])
                return {
                    "total": len(processed),
                    "submitted": sum(
                        1 for p in processed if p.get("worker_result")
                    ),
                    "failed_batches": 0,
                    "errors": [],
                }

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
                            side_effect=fake_process,
                        ):
                            with patch(
                                "discover_all_candidates.pipeline_core"
                                ".submit_candidates",
                                side_effect=fake_submit,
                            ):
                                with patch(
                                    "discover_all_candidates.pipeline_core"
                                    ".make_default_ocr_extractor",
                                    return_value=(MagicMock(), MagicMock()),
                                ):
                                    main()
        finally:
            pipeline_core.SCRAPE_MAX_PDFS_PER_RUN = original_cap

        assert submitted_sources == ["bndes"]

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