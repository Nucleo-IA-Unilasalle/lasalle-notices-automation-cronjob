"""Shared HTTP transport helpers for cronjob discoverers.

Ports the SSRF guard, safe-redirect GET/HEAD, listing-page PDF
discovery, and source-failure classification helpers from
``lasalle-notices-automation/app/services/scraper/transport.py``
into the cronjob so that per-source discoverers can fetch listing
pages and discover PDF URLs without re-implementing these utilities.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Iterable, Literal
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from url_validation import is_safe_url


logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# AJAX/JSON request mode. Sites behind an F5/Cloudflare/Incapsula ASM
# challenge usually answer a plain HTML GET with a 200 JavaScript
# interstitial and only serve the real JSON envelope to XHR callers.
JSON_REQUEST_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 10

HttpMethod = Literal["GET", "HEAD"]
RequestMode = Literal["html", "json"]

# Upstream access denial is a distinct failure class: it must never be
# collapsed into a generic scrape failure and must not consume the full
# retry budget (a burst sustains the block).
ACCESS_DENIED_STATUS_CODES = frozenset({401, 403, 429})
ACCESS_DENIED_MAX_ATTEMPTS = 2

# Strong implementation fingerprints of JavaScript bot challenges. Kept
# deliberately narrow so ordinary pages are never mistaken for a block.
CHALLENGE_MARKERS = (
    "bobcmn",
    "/tspd/",
    "cf-chl",
    "challenge-platform",
    "_incapsula_resource",
    "incapsula incident id",
    "please enable javascript to view the page content",
    "just a moment...",
)

FAILURE_ACCESS_DENIED = "http_access_denied"
FAILURE_PARSER_CHANGED = "parser_changed"
FAILURE_NETWORK = "network_error"
FAILURE_SERVER = "http_server_error"
_FAILURE_PRIORITY = (
    FAILURE_ACCESS_DENIED,
    FAILURE_PARSER_CHANGED,
    FAILURE_NETWORK,
    FAILURE_SERVER,
)

_failure_counts: dict[str, int] = {}
_failure_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


class SourceAccessDeniedError(requests.HTTPError):
    """The origin denied access (401/403/429) or served a JS challenge."""

    def __init__(
        self,
        response: requests.Response | None = None,
        *,
        url: str | None = None,
        message: str | None = None,
    ) -> None:
        self.url = url
        status_code = getattr(response, "status_code", None)
        super().__init__(
            message or f"HTTP {status_code} access denied while fetching {url or 'source'}",
            response=response,
        )


class SourceContentTypeMismatchError(ValueError):
    """A JSON-mode request received HTML (usually a bot challenge page)."""

    def __init__(
        self,
        *,
        url: str | None,
        status_code: int | None,
        content_type: str,
        expected: str = "application/json",
        body_prefix: str = "",
        is_challenge: bool = False,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.content_type = content_type
        self.expected = expected
        self.body_prefix = body_prefix[:512]
        self.is_challenge = is_challenge
        super().__init__(
            f"Expected {expected} from {url or 'source'} but received "
            f"{content_type or 'no content type'}"
            + (" (bot challenge page)" if is_challenge else "")
        )


class SourceChallengeError(SourceContentTypeMismatchError):
    """A 2xx HTML response is a JavaScript/WAF challenge, not the payload."""


class SourceJsonDecodeError(ValueError):
    """The response advertised JSON but could not be decoded."""


def record_source_failure(kind: str, *, url: str | None = None) -> None:
    """Record one transport failure for the current discovery attempt.

    The ledger lets the orchestrator classify a run without every
    source module having to translate its own exceptions. Callers that
    own a source loop still decide their own retry policy; the ledger is
    diagnostic only and is drained once per source by
    ``discover_all_candidates``.
    """
    del url  # reserved for future per-URL diagnostics; never logged (no secrets)
    with _failure_lock:
        _failure_counts[kind] = _failure_counts.get(kind, 0) + 1


def reset_failure_ledger() -> None:
    with _failure_lock:
        _failure_counts.clear()


def failure_counts() -> dict[str, int]:
    with _failure_lock:
        return dict(_failure_counts)


def drain_failure_counts() -> dict[str, int]:
    with _failure_lock:
        counts = dict(_failure_counts)
        _failure_counts.clear()
    return counts


def failure_error_code(counts: dict[str, int] | None = None) -> str | None:
    """Map recorded transport failures to a Repo A error code."""
    observed = failure_counts() if counts is None else counts
    for kind in _FAILURE_PRIORITY:
        if observed.get(kind):
            if kind in (FAILURE_NETWORK, FAILURE_SERVER):
                return "network_error"
            return kind
    return None


def drain_failure_error_code() -> str | None:
    return failure_error_code(drain_failure_counts())


def error_code_for_exception(exc: Exception) -> str | None:
    """Classify one exception into a specific source-run error code."""
    if isinstance(exc, SourceChallengeError):
        return "http_access_denied"
    if isinstance(exc, SourceContentTypeMismatchError):
        return "http_access_denied" if exc.is_challenge else "parser_changed"
    if isinstance(exc, SourceAccessDeniedError):
        return "http_access_denied"
    status_code = extract_status_code_from_exception(exc)
    if status_code in ACCESS_DENIED_STATUS_CODES:
        return "http_access_denied"
    if isinstance(
        exc,
        (requests.ConnectionError, requests.Timeout, requests.TooManyRedirects),
    ):
        return "network_error"
    if status_code is not None and status_code >= 500:
        return "network_error"
    if isinstance(exc, SourceJsonDecodeError):
        return "parser_changed"
    return None


def _response_header(response: requests.Response, name: str) -> str:
    headers = getattr(response, "headers", None)
    value = headers.get(name) if hasattr(headers, "get") else None
    return value if isinstance(value, str) else ""


def response_content_type(response: requests.Response) -> str:
    return _response_header(response, "Content-Type").split(";")[0].strip().lower()


def is_html_content_type(content_type: str) -> bool:
    return content_type in {"text/html", "application/xhtml+xml"} or content_type.endswith("+html")


def is_challenge_html(text: str | None) -> bool:
    lowered = (text or "")[:65536].lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def _looks_like_html(text: str | None) -> bool:
    head = (text or "")[:512].lstrip().lower()
    return head.startswith(
        ("<!doctype html", "<html", "<head", "<body", "<script", "<div", "<meta")
    )


def _response_text(response: requests.Response) -> str:
    text = getattr(response, "text", "")
    return text if isinstance(text, str) else ""


def _inspect_response(
    response: requests.Response,
    *,
    url: str,
    stream: bool,
    request_mode: RequestMode,
    detect_challenges: bool,
) -> None:
    """Record status failures and fail closed on HTML in JSON mode."""
    status_code = response.status_code
    if status_code in ACCESS_DENIED_STATUS_CODES:
        record_source_failure(FAILURE_ACCESS_DENIED, url=url)
    elif status_code >= 500:
        record_source_failure(FAILURE_SERVER, url=url)
    if stream or status_code >= 400:
        return
    content_type = response_content_type(response)
    body = _response_text(response)
    html_like = is_html_content_type(content_type) or (
        not content_type and _looks_like_html(body)
    )
    if not html_like:
        return
    is_challenge = is_challenge_html(body)
    if detect_challenges and is_challenge:
        record_source_failure(FAILURE_ACCESS_DENIED, url=url)
        raise SourceChallengeError(
            url=url,
            status_code=status_code,
            content_type=content_type or "text/html",
            body_prefix=body,
            is_challenge=True,
        )
    if request_mode == "json":
        record_source_failure(FAILURE_PARSER_CHANGED, url=url)
        raise SourceContentTypeMismatchError(
            url=url,
            status_code=status_code,
            content_type=content_type or "text/html",
            body_prefix=body,
            is_challenge=is_challenge,
        )


def decode_json_response(
    response: requests.Response,
    *,
    url: str | None = None,
) -> Any:
    """Decode a JSON response, refusing to parse a 2xx HTML challenge page."""
    content_type = response_content_type(response)
    body = _response_text(response)
    if is_html_content_type(content_type) or _looks_like_html(body):
        is_challenge = is_challenge_html(body)
        record_source_failure(
            FAILURE_ACCESS_DENIED if is_challenge else FAILURE_PARSER_CHANGED,
            url=url,
        )
        error_type = SourceChallengeError if is_challenge else SourceContentTypeMismatchError
        raise error_type(
            url=url,
            status_code=getattr(response, "status_code", None),
            content_type=content_type or "text/html",
            body_prefix=body,
            is_challenge=is_challenge,
        )
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        record_source_failure(FAILURE_PARSER_CHANGED, url=url)
        raise SourceJsonDecodeError(
            f"Non-JSON response from {url or 'source'}: {exc}"
        ) from exc


def ensure_safe_url(url: str) -> None:
    if not is_safe_url(url):
        raise ValueError(f"URL blocked by SSRF protection: {url}")


def request_with_safe_redirects(
    *,
    method: HttpMethod,
    url: str,
    timeout: int,
    stream: bool = False,
    extra_headers: dict[str, str] | None = None,
    request_mode: RequestMode = "html",
    detect_challenges: bool = True,
) -> requests.Response:
    """Issue a GET/HEAD with the SSRF guard and safe redirect handling.

    ``request_mode="json"`` sends ``Accept: application/json`` plus
    ``X-Requested-With: XMLHttpRequest`` and fails closed if a 2xx body
    is HTML instead of JSON. The default ``"html"`` mode keeps the
    historical headers and return value.
    """
    if request_mode not in ("html", "json"):
        raise ValueError(f"request_mode must be 'html' or 'json'; got {request_mode!r}")
    headers = dict(DEFAULT_HEADERS)
    if request_mode == "json":
        headers.update(JSON_REQUEST_HEADERS)
    headers.update(extra_headers or {})
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        ensure_safe_url(current_url)
        try:
            response = requests.request(
                method=method,
                url=current_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=stream,
            )
        except requests.RequestException:
            record_source_failure(FAILURE_NETWORK, url=current_url)
            raise
        if response.status_code not in REDIRECT_STATUS_CODES:
            _inspect_response(
                response,
                url=current_url,
                stream=stream,
                request_mode=request_mode,
                detect_challenges=detect_challenges,
            )
            return response
        location = response.headers.get("Location")
        if not location:
            return response
        response.close()
        current_url = urljoin(current_url, location)
    raise RuntimeError(f"Too many redirects while fetching {url}")


def extract_status_code_from_exception(exc: Exception) -> int | None:
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
    match = re.search(
        r"\bHTTP\s+(\d{3})\b|\b(\d{3})\s+(?:Client|Server)\s+Error\b|\bstatus\s+code\s+(\d{3})\b",
        str(exc),
        re.IGNORECASE,
    )
    if not match:
        return None
    return int(match.group(1) or match.group(2) or match.group(3))


def is_blocking_status_code(status_code: int | None) -> bool:
    return status_code in {401, 403, 429}


def is_expected_source_failure(exc: Exception) -> bool:
    status_code = extract_status_code_from_exception(exc)
    if status_code is not None:
        return status_code in {400, 401, 403, 404, 408, 410, 413, 414, 415, 429, 500, 502, 503, 504}
    return isinstance(exc, (requests.ConnectionError, requests.Timeout, requests.TooManyRedirects))


def log_source_failure(message: str, *args: object, exc: Exception) -> None:
    if is_expected_source_failure(exc):
        logger.warning(message, *args)
    else:
        logger.error(message, *args)


def looks_like_pdf_url(url: str) -> bool:
    return bool(re.search(r"\.pdf($|[?#])", url.lower()))


def _access_denied_attempt_bound(max_attempts: int) -> int:
    return max(1, min(ACCESS_DENIED_MAX_ATTEMPTS, max_attempts))


def _raise_access_denied(exc: Exception, *, url: str) -> SourceAccessDeniedError:
    response = getattr(exc, "response", None)
    return SourceAccessDeniedError(response, url=url)


def fetch_html_with_retry(
    url: str,
    *,
    timeout: int,
    max_attempts: int = 3,
    backoff_seconds: float = 2.0,
    allowed_status_codes: Iterable[int] = (),
) -> str:
    """Fetch ``url`` as HTML and return ``response.text``.

    Generic retry-with-backoff wrapper used by BS4 source discoverers
    to fetch listing pages. The transport honours
    ``request_with_safe_redirects`` for SSRF protection and applies a
    linear backoff (``backoff_seconds * attempt``) between attempts.

    Status codes listed in ``allowed_status_codes`` raise immediately
    rather than retry — these are typically permanent client errors
    (``404``, ``410``) or auth failures (``401``, ``403``) that the
    caller wants to surface without waiting for the retry budget.

    Access denial (``401``/``403``/``429``) and JS challenge pages are
    raised as :class:`SourceAccessDeniedError` / :class:`SourceChallengeError`
    after at most ``ACCESS_DENIED_MAX_ATTEMPTS`` attempts, so a WAF
    block never consumes the full retry ladder.
    """
    last_error: Exception | None = None
    non_retryable_statuses = frozenset(allowed_status_codes)
    access_denied_attempts = 0
    access_denied_bound = _access_denied_attempt_bound(max_attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            response = request_with_safe_redirects(
                method="GET", url=url, timeout=timeout,
            )
            response.raise_for_status()
            return response.text
        except SourceContentTypeMismatchError:
            # 2xx HTML challenge: retrying sustains the block.
            raise
        except Exception as exc:
            last_error = exc
            status_code = extract_status_code_from_exception(exc)
            if status_code is None:
                status_code = getattr(exc, "status_code", None)
            if status_code in ACCESS_DENIED_STATUS_CODES:
                access_denied_attempts += 1
                if status_code != 429 or access_denied_attempts >= access_denied_bound:
                    raise _raise_access_denied(exc, url=url) from exc
            if status_code in non_retryable_statuses:
                raise
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    assert last_error is not None
    raise last_error


def fetch_json_with_retry(
    url: str,
    *,
    timeout: int,
    max_attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> Any:
    """Fetch ``url`` in AJAX/JSON mode and return the decoded payload.

    Sends ``Accept: application/json`` and
    ``X-Requested-With: XMLHttpRequest`` so WAF-fronted data-table
    endpoints serve their JSON envelope. A 2xx ``text/html`` body is
    raised as :class:`SourceChallengeError` (or
    :class:`SourceContentTypeMismatchError`) instead of being handed to
    a JSON decoder.
    """
    last_error: Exception | None = None
    access_denied_attempts = 0
    access_denied_bound = _access_denied_attempt_bound(max_attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            response = request_with_safe_redirects(
                method="GET",
                url=url,
                timeout=timeout,
                request_mode="json",
            )
            response.raise_for_status()
            return decode_json_response(response, url=url)
        except SourceContentTypeMismatchError:
            raise
        except SourceJsonDecodeError:
            raise
        except Exception as exc:
            last_error = exc
            status_code = extract_status_code_from_exception(exc)
            if status_code is None:
                status_code = getattr(exc, "status_code", None)
            if status_code in ACCESS_DENIED_STATUS_CODES:
                access_denied_attempts += 1
                if status_code != 429 or access_denied_attempts >= access_denied_bound:
                    raise _raise_access_denied(exc, url=url) from exc
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    assert last_error is not None
    raise last_error


def discover_pdf_urls_on_page(
    page_url: str,
    *,
    stats: dict[str, int] | None = None,
    extractor: Callable[[BeautifulSoup, str], list[str]] | None = None,
) -> list[str]:
    try:
        response = request_with_safe_redirects(method="GET", url=page_url, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        log_source_failure("Failed to fetch listing page %s: %s", page_url, exc, exc=exc)
        if stats is not None:
            stats["errors"] = stats.get("errors", 0) + 1
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    if extractor is not None:
        return [urljoin(page_url, href) for href in extractor(soup, page_url)]
    discovered_urls: list[str] = []
    for link in soup.find_all("a", href=lambda href: bool(href and looks_like_pdf_url(href))):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if isinstance(href, str) and href:
            discovered_urls.append(urljoin(page_url, href))
    if not discovered_urls:
        logger.info("No PDF links found at %s", page_url)
    return discovered_urls
