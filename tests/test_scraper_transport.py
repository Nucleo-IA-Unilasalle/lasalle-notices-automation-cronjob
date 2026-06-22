"""Unit tests for scripts/scraper_transport.py.

Ports and locks the behavior of the FastAPI transport helpers
(`app/services/scraper/transport.py`) inside the cronjob.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import scraper_transport


# ---------------------------------------------------------------------------
# looks_like_pdf_url
# ---------------------------------------------------------------------------

class TestLooksLikePdfUrl:
    def test_matches_plain_pdf_link(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/docs/edital.pdf") is True

    def test_matches_pdf_with_query_string(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/docs/edital.pdf?MOD=AJPERES") is True

    def test_matches_pdf_with_fragment(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/docs/edital.pdf#page=2") is True

    def test_matches_uppercase_extension(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/docs/EDITAL.PDF") is True

    def test_does_not_match_html_link(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/listing") is False

    def test_does_not_match_zip_link(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/docs/edital.zip") is False

    def test_does_not_match_pdf_in_path_segment_only(self) -> None:
        assert scraper_transport.looks_like_pdf_url("https://example.com/pdf-doc/edit") is False


# ---------------------------------------------------------------------------
# ensure_safe_url
# ---------------------------------------------------------------------------

class TestEnsureSafeUrl:
    def test_raises_for_unsafe_url(self) -> None:
        with pytest.raises(ValueError, match="SSRF"):
            scraper_transport.ensure_safe_url("http://127.0.0.1/secret.pdf")

    def test_does_not_raise_for_public_https(self) -> None:
        scraper_transport.ensure_safe_url("https://www.gov.br/mma/pt-br/edital.pdf")


# ---------------------------------------------------------------------------
# request_with_safe_redirects
# ---------------------------------------------------------------------------

class TestRequestWithSafeRedirects:
    def test_returns_response_when_no_redirect(self) -> None:
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200

        with patch.object(scraper_transport.requests, "request", return_value=resp) as mock_req:
            response = scraper_transport.request_with_safe_redirects(
                method="GET",
                url="https://example.com/page",
                timeout=30,
            )

        assert response is resp
        assert mock_req.call_count == 1
        assert mock_req.call_args.kwargs["allow_redirects"] is False
        assert mock_req.call_args.kwargs["method"] == "GET"

    def test_follows_single_redirect_to_safe_url(self) -> None:
        resp_redirect = MagicMock(spec=requests.Response)
        resp_redirect.status_code = 302
        resp_redirect.headers = {"Location": "https://example.com/elsewhere"}
        resp_redirect.close = MagicMock()
        resp_final = MagicMock(spec=requests.Response)
        resp_final.status_code = 200

        with patch.object(
            scraper_transport.requests,
            "request",
            side_effect=[resp_redirect, resp_final],
        ) as mock_req:
            response = scraper_transport.request_with_safe_redirects(
                method="GET",
                url="https://example.com/page",
                timeout=30,
            )

        assert response is resp_final
        assert mock_req.call_count == 2
        resp_redirect.close.assert_called_once()

    def test_relative_redirect_is_resolved_against_initial_url(self) -> None:
        resp_redirect = MagicMock(spec=requests.Response)
        resp_redirect.status_code = 301
        resp_redirect.headers = {"Location": "/elsewhere"}
        resp_redirect.close = MagicMock()
        resp_final = MagicMock(spec=requests.Response)
        resp_final.status_code = 200

        with patch.object(
            scraper_transport.requests,
            "request",
            side_effect=[resp_redirect, resp_final],
        ) as mock_req:
            scraper_transport.request_with_safe_redirects(
                method="GET",
                url="https://example.com/page",
                timeout=30,
            )

        second_url = mock_req.call_args_list[1].kwargs["url"]
        assert second_url == "https://example.com/elsewhere"

    def test_redirect_to_unsafe_url_raises(self) -> None:
        resp_redirect = MagicMock(spec=requests.Response)
        resp_redirect.status_code = 302
        resp_redirect.headers = {"Location": "http://127.0.0.1/evil.pdf"}
        resp_redirect.close = MagicMock()

        with patch.object(scraper_transport.requests, "request", return_value=resp_redirect):
            with pytest.raises(ValueError, match="SSRF|blocked"):
                scraper_transport.request_with_safe_redirects(
                    method="GET",
                    url="https://example.com/page",
                    timeout=30,
                )

    def test_redirect_without_location_header_returns_redirect_response(self) -> None:
        resp_redirect = MagicMock(spec=requests.Response)
        resp_redirect.status_code = 302
        resp_redirect.headers = {}

        with patch.object(scraper_transport.requests, "request", return_value=resp_redirect) as mock_req:
            response = scraper_transport.request_with_safe_redirects(
                method="GET",
                url="https://example.com/page",
                timeout=30,
            )

        assert response is resp_redirect
        assert mock_req.call_count == 1

    def test_extra_headers_merged_with_defaults(self) -> None:
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200

        with patch.object(scraper_transport.requests, "request", return_value=resp) as mock_req:
            scraper_transport.request_with_safe_redirects(
                method="GET",
                url="https://example.com/page",
                timeout=30,
                extra_headers={"Accept-Language": "pt-BR,pt;q=0.9"},
            )

        headers = mock_req.call_args.kwargs["headers"]
        assert headers["Accept-Language"] == "pt-BR,pt;q=0.9"
        assert "User-Agent" in headers


# ---------------------------------------------------------------------------
# discover_pdf_urls_on_page
# ---------------------------------------------------------------------------

class TestDiscoverPdfUrlsOnPage:
    def test_returns_absolute_pdf_urls(self) -> None:
        html = (
            '<html><body>'
            '<a href="/docs/edital.pdf">Edital</a>'
            '<a href="/docs/page.pdf/view">Page</a>'
            '<a href="/listing">Listing</a>'
            '</body></html>'
        )
        resp = MagicMock(spec=requests.Response)
        resp.text = html
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        with patch.object(scraper_transport, "request_with_safe_redirects", return_value=resp):
            urls = scraper_transport.discover_pdf_urls_on_page("https://example.com/listing")

        assert urls == ["https://example.com/docs/edital.pdf"]

    def test_uses_explicit_extractor(self) -> None:
        html = '<html><body><a href="/result/1">Result</a></body></html>'
        resp = MagicMock(spec=requests.Response)
        resp.text = html
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        with patch.object(scraper_transport, "request_with_safe_redirects", return_value=resp):
            urls = scraper_transport.discover_pdf_urls_on_page(
                "https://example.com/listing",
                extractor=lambda soup, _url: [str(soup.a["href"])],
            )

        assert urls == ["https://example.com/result/1"]

    def test_returns_empty_list_and_increments_stats_on_failure(self) -> None:
        stats = {"errors": 0}

        with patch.object(
            scraper_transport,
            "request_with_safe_redirects",
            side_effect=requests.ConnectionError("network down"),
        ):
            urls = scraper_transport.discover_pdf_urls_on_page(
                "https://example.com/listing",
                stats=stats,
            )

        assert urls == []
        assert stats["errors"] == 1

    def test_returns_empty_list_when_no_pdf_links(self) -> None:
        html = '<html><body><a href="/listing">No PDFs here</a></body></html>'
        resp = MagicMock(spec=requests.Response)
        resp.text = html
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        with patch.object(scraper_transport, "request_with_safe_redirects", return_value=resp):
            urls = scraper_transport.discover_pdf_urls_on_page("https://example.com/listing")

        assert urls == []

    def test_skips_anchor_tags_without_href(self) -> None:
        html = '<html><body><a>no href</a><a href="/docs/edital.pdf">Edital</a></body></html>'
        resp = MagicMock(spec=requests.Response)
        resp.text = html
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        with patch.object(scraper_transport, "request_with_safe_redirects", return_value=resp):
            urls = scraper_transport.discover_pdf_urls_on_page("https://example.com/listing")

        assert urls == ["https://example.com/docs/edital.pdf"]


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

class TestFailureClassification:
    def test_extracts_status_code_from_http_error(self) -> None:
        resp = MagicMock()
        resp.status_code = 503
        exc = requests.HTTPError(response=resp)
        assert scraper_transport.extract_status_code_from_exception(exc) == 503

    def test_extracts_status_code_from_message(self) -> None:
        assert scraper_transport.extract_status_code_from_exception(RuntimeError("HTTP 429")) == 429
        assert scraper_transport.extract_status_code_from_exception(RuntimeError("500 Server Error")) == 500
        assert scraper_transport.extract_status_code_from_exception(RuntimeError("status code 404")) == 404

    def test_extract_returns_none_for_unrelated_exceptions(self) -> None:
        assert scraper_transport.extract_status_code_from_exception(RuntimeError("boom")) is None

    def test_blocking_status_codes_are_marked(self) -> None:
        assert scraper_transport.is_blocking_status_code(401) is True
        assert scraper_transport.is_blocking_status_code(403) is True
        assert scraper_transport.is_blocking_status_code(429) is True
        assert scraper_transport.is_blocking_status_code(200) is False
        assert scraper_transport.is_blocking_status_code(500) is False
        assert scraper_transport.is_blocking_status_code(None) is False

    def test_expected_failures_include_known_status_codes(self) -> None:
        for code in (400, 401, 403, 404, 408, 410, 413, 414, 415, 429, 500, 502, 503, 504):
            resp = MagicMock()
            resp.status_code = code
            exc = requests.HTTPError(response=resp)
            assert scraper_transport.is_expected_source_failure(exc) is True

    def test_expected_failures_include_connection_errors(self) -> None:
        assert scraper_transport.is_expected_source_failure(requests.ConnectionError("x")) is True
        assert scraper_transport.is_expected_source_failure(requests.Timeout("x")) is True
        assert scraper_transport.is_expected_source_failure(requests.TooManyRedirects("x")) is True

    def test_unexpected_exceptions_are_not_expected_failures(self) -> None:
        assert scraper_transport.is_expected_source_failure(RuntimeError("unexpected")) is False

    def test_log_source_failure_uses_warning_for_expected(self) -> None:
        warning_calls: list[tuple[object, ...]] = []
        error_calls: list[tuple[object, ...]] = []

        with patch.object(
            scraper_transport.logger,
            "warning",
            side_effect=lambda *args, **kwargs: warning_calls.append(args),
        ):
            with patch.object(
                scraper_transport.logger,
                "error",
                side_effect=lambda *args, **kwargs: error_calls.append(args),
            ):
                scraper_transport.log_source_failure(
                    "Error: %s", "boom", exc=requests.ConnectionError("x"),
                )

        assert len(warning_calls) == 1
        assert error_calls == []

    def test_log_source_failure_uses_error_for_unexpected(self) -> None:
        warning_calls: list[tuple[object, ...]] = []
        error_calls: list[tuple[object, ...]] = []

        with patch.object(
            scraper_transport.logger,
            "warning",
            side_effect=lambda *args, **kwargs: warning_calls.append(args),
        ):
            with patch.object(
                scraper_transport.logger,
                "error",
                side_effect=lambda *args, **kwargs: error_calls.append(args),
            ):
                scraper_transport.log_source_failure(
                    "Error: %s", "boom", exc=RuntimeError("unexpected"),
                )

        assert warning_calls == []
        assert len(error_calls) == 1
