"""Offline regression tests for the transport hardening and run classification.

Covers the foundation fix for three observed failure modes:

* AJAX/JSON request mode sends ``Accept: application/json`` and
  ``X-Requested-With: XMLHttpRequest`` and refuses to parse a 2xx HTML
  challenge page as JSON (SEMA-RS F5 ASM).
* HTTP 401/403/429 is classified as ``http_access_denied`` and is not
  retried beyond a small bound (BRDE edge 403).
* The orchestrator stops collapsing every failure into
  ``scraping_failed``: access denial and transport failures keep their own
  code, and zero candidates after a completed fetch is not forced to
  ``failed`` (FAPERGS connect timeout / silent AJAX).

No test performs network I/O.
"""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

import conftest  # noqa: F401  (bootstraps scripts/ onto sys.path)
import scraper_transport


F5_CHALLENGE_HTML = (
    '<html><head><script>window["bobcmn"] = "x";</script>'
    '<script src="/TSPD/08002f41f1ab1e0e5f4"></script></head>'
    "<body><noscript>Please enable JavaScript to view the page content."
    "</noscript></body></html>"
)


def _response(
    *,
    status_code: int = 200,
    text: str = "",
    headers: dict[str, str] | None = None,
    json_payload: Any = None,
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}", response=resp,
        )
    resp.json = MagicMock(return_value=json_payload)
    resp.close = MagicMock()
    return resp


@pytest.fixture(autouse=True)
def reset_transport_ledger() -> None:
    scraper_transport.reset_failure_ledger()
    yield
    scraper_transport.reset_failure_ledger()


# ---------------------------------------------------------------------------
# AJAX / JSON request mode
# ---------------------------------------------------------------------------


class TestJsonRequestMode:
    def test_json_mode_sends_ajax_headers(self) -> None:
        resp = _response(
            text='{"recordcount": 251}',
            headers={"Content-Type": "application/json"},
        )
        with patch.object(
            scraper_transport.requests, "request", return_value=resp,
        ) as mock_request:
            scraper_transport.request_with_safe_redirects(
                method="GET",
                url="https://www.sema.rs.gov.br/busca/lista-data-table",
                timeout=30,
                request_mode="json",
            )

        headers = mock_request.call_args.kwargs["headers"]
        assert headers["Accept"].startswith("application/json")
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_html_mode_keeps_default_headers(self) -> None:
        resp = _response(text="<html><body>ok</body></html>",
                         headers={"Content-Type": "text/html; charset=utf-8"})
        with patch.object(
            scraper_transport.requests, "request", return_value=resp,
        ) as mock_request:
            scraper_transport.request_with_safe_redirects(
                method="GET", url="https://example.com/listing", timeout=30,
            )

        headers = mock_request.call_args.kwargs["headers"]
        assert headers["Accept"] == scraper_transport.DEFAULT_HEADERS["Accept"]
        assert "X-Requested-With" not in headers

    def test_decode_json_response_returns_payload(self) -> None:
        resp = _response(
            text='{"recordcount": 1}',
            headers={"Content-Type": "application/json"},
            json_payload={"recordcount": 1},
        )
        assert scraper_transport.decode_json_response(resp) == {"recordcount": 1}

    def test_fetch_json_with_retry_uses_ajax_mode(self) -> None:
        resp = _response(
            text='{"recordcount": 1}',
            headers={"Content-Type": "application/json"},
            json_payload={"recordcount": 1},
        )
        with patch.object(
            scraper_transport,
            "request_with_safe_redirects",
            return_value=resp,
        ) as mock_request:
            payload = scraper_transport.fetch_json_with_retry(
                "https://example.com/ajax", timeout=30,
            )

        assert payload == {"recordcount": 1}
        assert mock_request.call_args.kwargs["request_mode"] == "json"


class TestHtmlVsJsonMismatch:
    def test_200_html_is_detected_as_mismatch(self) -> None:
        resp = _response(
            text="<html><body>not the payload</body></html>",
            headers={"Content-Type": "text/html"},
        )
        with patch.object(
            scraper_transport, "request_with_safe_redirects", return_value=resp,
        ):
            with pytest.raises(scraper_transport.SourceContentTypeMismatchError) as info:
                scraper_transport.fetch_json_with_retry(
                    "https://example.com/ajax", timeout=30,
                )

        assert info.value.status_code == 200
        assert info.value.content_type == "text/html"
        assert info.value.is_challenge is False

    def test_200_f5_challenge_is_detected_as_access_denied(self) -> None:
        resp = _response(
            text=F5_CHALLENGE_HTML,
            headers={"Content-Type": "text/html"},
        )
        with patch.object(
            scraper_transport, "request_with_safe_redirects", return_value=resp,
        ):
            with pytest.raises(scraper_transport.SourceChallengeError) as info:
                scraper_transport.fetch_json_with_retry(
                    "https://www.sema.rs.gov.br/busca/lista-data-table",
                    timeout=30,
                )

        assert info.value.is_challenge is True
        assert scraper_transport.failure_error_code() == "http_access_denied"

    def test_decode_refuses_challenge_instead_of_json_error(self) -> None:
        resp = _response(
            text=F5_CHALLENGE_HTML,
            headers={"Content-Type": "text/html"},
        )
        with pytest.raises(scraper_transport.SourceChallengeError):
            scraper_transport.decode_json_response(resp)
        resp.json.assert_not_called()

    def test_html_mode_raises_on_challenge_before_json_decode(self) -> None:
        """Legacy HTML callers (SEMA-RS today) never feed the WAF page to json()."""
        resp = _response(
            text=F5_CHALLENGE_HTML,
            headers={"Content-Type": "text/html"},
        )
        with patch.object(
            scraper_transport.requests, "request", return_value=resp,
        ):
            with pytest.raises(scraper_transport.SourceChallengeError):
                scraper_transport.fetch_html_with_retry(
                    "https://www.sema.rs.gov.br/busca/lista-data-table",
                    timeout=30,
                )


# ---------------------------------------------------------------------------
# Access denial classification and retry bounds
# ---------------------------------------------------------------------------


class TestAccessDenied:
    def test_403_maps_to_access_denied_without_retry(self) -> None:
        resp = _response(status_code=403, text="Forbidden")
        with patch.object(
            scraper_transport.requests, "request", return_value=resp,
        ) as mock_request:
            with pytest.raises(scraper_transport.SourceAccessDeniedError):
                scraper_transport.fetch_html_with_retry(
                    "https://www.brde.com.br/palacete/editais/", timeout=30,
                )

        assert mock_request.call_count == 1
        assert scraper_transport.failure_error_code() == "http_access_denied"

    def test_429_retries_at_most_small_bound(self) -> None:
        resp = _response(status_code=429, text="Too Many Requests")
        with patch.object(
            scraper_transport.requests, "request", return_value=resp,
        ) as mock_request:
            with patch.object(scraper_transport.time, "sleep"):
                with pytest.raises(scraper_transport.SourceAccessDeniedError):
                    scraper_transport.fetch_html_with_retry(
                        "https://example.com/listing",
                        timeout=30,
                        max_attempts=5,
                    )

        assert mock_request.call_count == scraper_transport.ACCESS_DENIED_MAX_ATTEMPTS

    def test_challenge_is_not_retried(self) -> None:
        with patch.object(
            scraper_transport,
            "request_with_safe_redirects",
            side_effect=scraper_transport.SourceChallengeError(
                url="https://example.com/ajax",
                status_code=200,
                content_type="text/html",
                is_challenge=True,
            ),
        ) as mock_request:
            with patch.object(scraper_transport.time, "sleep") as mock_sleep:
                with pytest.raises(scraper_transport.SourceChallengeError):
                    scraper_transport.fetch_html_with_retry(
                        "https://example.com/ajax", timeout=30,
                    )

        assert mock_request.call_count == 1
        assert mock_sleep.call_count == 0

    def test_error_code_for_exception(self) -> None:
        assert scraper_transport.error_code_for_exception(
            requests.HTTPError(response=MagicMock(status_code=403))
        ) == "http_access_denied"
        assert scraper_transport.error_code_for_exception(
            requests.ConnectTimeout("timeout")
        ) == "network_error"
        assert scraper_transport.error_code_for_exception(
            scraper_transport.SourceJsonDecodeError("bad json")
        ) == "parser_changed"
        assert scraper_transport.error_code_for_exception(RuntimeError("boom")) is None


# ---------------------------------------------------------------------------
# Orchestrator classification
# ---------------------------------------------------------------------------


class TestClassifyDiscoveryOutcome:
    def test_access_denied_zero_candidates_is_warning_with_specific_code(self) -> None:
        from discover_all_candidates import classify_discovery_outcome

        assert classify_discovery_outcome(
            {"candidates": 0, "errors": 2, "listings_fetched": 0, "access_denied": 2},
            record_count=0,
            transport_error_code=None,
        ) == ("warning", "http_access_denied")

    def test_clean_zero_candidate_after_fetch_is_not_a_failure(self) -> None:
        from discover_all_candidates import classify_discovery_outcome

        assert classify_discovery_outcome(
            {"candidates": 0, "errors": 0, "listings_fetched": 2, "details_fetched": 8},
            record_count=0,
            transport_error_code=None,
        ) == (None, None)

    def test_zero_candidate_with_partial_error_is_warning_not_failed(self) -> None:
        from discover_all_candidates import classify_discovery_outcome

        assert classify_discovery_outcome(
            {"candidates": 0, "errors": 1, "listings_fetched": 1, "details_fetched": 2},
            record_count=0,
            transport_error_code=None,
        ) == ("warning", "scraping_failed")

    def test_unreachable_source_keeps_network_error(self) -> None:
        from discover_all_candidates import classify_discovery_outcome

        assert classify_discovery_outcome(
            {"candidates": 0, "errors": 1, "listings_fetched": 0, "details_fetched": 0},
            record_count=0,
            transport_error_code="network_error",
        ) == ("failed", "network_error")

    def test_swallowed_transport_failure_is_surfaced(self) -> None:
        from discover_all_candidates import classify_discovery_outcome

        assert classify_discovery_outcome(
            {"candidates": 0, "errors": 0, "listings_fetched": 1, "details_fetched": 3},
            record_count=0,
            transport_error_code="network_error",
        ) == ("warning", "network_error")


# ---------------------------------------------------------------------------
# main() telemetry
# ---------------------------------------------------------------------------


def _stub_ocr_modules() -> None:
    sys.modules.setdefault("ocr_worker.ocr_extraction_config", MagicMock())
    sys.modules.setdefault("ocr_worker.pdf_markdown_extractor", MagicMock())


def _run_main(
    discover_return: tuple[dict[str, Any], list[dict[str, Any]]] | None = None,
    *,
    discover_side_effect: Any = None,
    source: str = "brde",
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    from discover_all_candidates import main

    _stub_ocr_modules()
    env = {
        "RENDER_APP_URL": "https://r.example.com",
        "PIPELINE_SECRET": "tok",
        "SOURCES": source,
        "SOURCE_RUN_REPORTING_ENABLED": "true",
        **(extra_env or {}),
    }
    start = MagicMock(status_code=201)
    start.json.return_value = {"id": "run-1"}

    def finish_response(*_args: Any, **kwargs: Any) -> MagicMock:
        payload = kwargs.get("json") or {}
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"status": payload.get("status", "success")}
        return resp

    discoverer = MagicMock()
    patch_kwargs: dict[str, Any] = {}
    if discover_side_effect is not None:
        patch_kwargs["side_effect"] = discover_side_effect
    else:
        patch_kwargs["return_value"] = discover_return
    with patch.dict(os.environ, env, clear=True), patch(
        "discover_all_candidates.load_discoverer", return_value=discoverer,
    ), patch(
        "discover_all_candidates.discover_source", **patch_kwargs,
    ), patch(
        "discover_all_candidates.pipeline_core.make_default_ocr_extractor",
        return_value=(MagicMock(), MagicMock()),
    ), patch(
        "source_run_reporting.requests.post", return_value=start,
    ), patch(
        "source_run_reporting.requests.patch", side_effect=finish_response,
    ) as patch_finish:
        exit_code = main()
    return exit_code, patch_finish.call_args.kwargs["json"]


class TestMainClassification:
    def test_access_denied_zero_candidate_run_is_warning_not_failed(self) -> None:
        def denied(*_: Any, **__: Any):
            scraper_transport.record_source_failure(
                scraper_transport.FAILURE_ACCESS_DENIED,
            )
            return (
                {"candidates": 0, "errors": 2, "listings_fetched": 0},
                [],
            )

        exit_code, body = _run_main(discover_side_effect=denied)

        assert exit_code == 1
        assert body["status"] == "warning"
        assert body["error_code"] == "http_access_denied"
        assert body["errors"] == 2
        assert body["inventory_seen"] == 0

    def test_clean_zero_candidate_after_successful_fetch_is_success(self) -> None:
        exit_code, body = _run_main(
            ({"candidates": 0, "errors": 0, "listings_fetched": 2, "details_fetched": 8}, []),
        )

        assert exit_code == 0
        assert body["status"] == "success"
        assert body["errors"] == 0
        assert body["inventory_seen"] == 0

    def test_zero_candidate_partial_fetch_warns_instead_of_failing(self) -> None:
        exit_code, body = _run_main(
            ({"candidates": 0, "errors": 1, "listings_fetched": 1, "details_fetched": 2}, []),
        )

        assert exit_code == 1
        assert body["status"] == "warning"
        assert body["error_code"] == "scraping_failed"

    def test_swallowed_ajax_failure_does_not_report_healthy_success(self) -> None:
        def swallowed(*_: Any, **__: Any):
            scraper_transport.record_source_failure(
                scraper_transport.FAILURE_SERVER,
            )
            return (
                {"candidates": 0, "errors": 0, "listings_fetched": 1, "details_fetched": 3},
                [],
            )

        exit_code, body = _run_main(discover_side_effect=swallowed)

        assert exit_code == 1
        assert body["status"] == "warning"
        assert body["error_code"] == "network_error"
        assert body["errors"] == 1

    def test_discovery_timeout_is_network_error(self) -> None:
        exit_code, body = _run_main(
            discover_side_effect=requests.ConnectTimeout("connect timeout=30"),
        )

        assert exit_code == 1
        assert body["status"] == "failed"
        assert body["error_code"] == "network_error"

    def test_submitted_equals_persistence_outcomes(self) -> None:
        candidate = {"url": "https://example.com/edital.pdf", "kind": "pdf"}
        processed = [{**candidate, "worker_result": {"ocr_markdown": "# Edital"}}]
        outcomes = {"inserted": 2, "updated": 1, "reactivated": 0, "duplicates": 2}
        with patch(
            "discover_all_candidates.process_source_candidates",
            return_value=processed,
        ), patch(
            "discover_all_candidates.pipeline_core.submit_candidates",
            return_value={
                "submitted": 5,
                "failed_batches": 0,
                "outcome_counts": outcomes,
            },
        ):
            exit_code, body = _run_main(
                ({"candidates": 1, "errors": 0, "listings_fetched": 1}, [candidate]),
                source="bndes",
            )

        assert exit_code == 0
        assert body["submitted"] == 5
        assert body["submitted"] == (
            body["inserted"] + body["updated"]
            + body["reactivated"] + body["duplicates"]
        )
