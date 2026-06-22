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
from typing import Callable, Literal
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from ocr_worker.url_validation import is_safe_url


logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 10

HttpMethod = Literal["GET", "HEAD"]


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
) -> requests.Response:
    headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        ensure_safe_url(current_url)
        response = requests.request(
            method=method,
            url=current_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=stream,
        )
        if response.status_code not in REDIRECT_STATUS_CODES:
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
