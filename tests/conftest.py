"""Shared pytest fixtures and helpers for the cronjob test suite.

Centralises three concerns so the per-source tests do not each repeat
the same boilerplate:

* Bootstrapping ``scripts/`` onto ``sys.path`` once for the whole test
  package (previously repeated in every test module).
* Resetting env-driven module constants between tests. Discoverers
  capture ``BNDES_MIN_NOTICE_YEAR`` / ``SCRAPE_MAX_*`` at import time,
  so per-test ``monkeypatch`` plus a post-test ``importlib.reload``
  keeps the suite deterministic.
* Patching ``scraper_transport.request_with_safe_redirects`` (the
  single seam that both ``scraper_transport.discover_pdf_urls_on_page``
  and ``scraper_transport.fetch_html_with_retry`` call through) so
  listing-page and detail-page fetches can be mocked from one place.

The helpers here are plain functions and fixtures — they are imported
by name from each test module rather than referenced through the
``request`` fixture, which keeps them easy to compose.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Union
from unittest.mock import MagicMock, patch

import pytest
import requests


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


ResponseLike = Union[MagicMock, Exception]
RequestCallable = Callable[..., ResponseLike]
ResponseMap = Mapping[str, ResponseLike]


# ---------------------------------------------------------------------------
# Response / request helpers
# ---------------------------------------------------------------------------


def make_response(text: str = "", status_code: int = 200) -> MagicMock:
    """Build a MagicMock ``requests.Response`` carrying ``text`` + a wired
    ``raise_for_status`` that raises on 4xx/5xx."""
    resp = MagicMock(spec=requests.Response)
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}", response=resp,
        )
    return resp


def _build_fake_request(
    responses_or_callable: Union[ResponseMap, RequestCallable],
) -> RequestCallable:
    """Normalise ``responses_or_callable`` into the ``(method, url,
    timeout, **_) -> Response | Exception`` shape that
    ``request_with_safe_redirects`` is invoked with.

    * ``Mapping[str, Response | Exception]`` -> dict-style lookup with
      ``AssertionError`` on unknown URLs (matches the historical
      behaviour the BNDE/PNCP tests rely on).
    * Callable -> forwarded as-is. Callables are called with the same
      kwargs the patched helper receives, so they can either be a
      ``(url) -> ...`` shim or a richer dispatcher.
    """
    if callable(responses_or_callable):
        def fake_request(*, method: str, url: str, timeout: int, **_: object) -> ResponseLike:
            return responses_or_callable(method=method, url=url, timeout=timeout, **_)

        return fake_request

    responses = responses_or_callable

    def fake_request(*, method: str, url: str, timeout: int, **_: object) -> ResponseLike:
        value = responses.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected URL in test: {url}")
        return value

    return fake_request


def patch_request_with_safe_redirects(
    responses_or_callable: Union[ResponseMap, RequestCallable],
) -> object:
    """Patch ``scraper_transport.request_with_safe_redirects`` with a fake.

    Returns a context manager that activates both
    ``scraper_transport.request_with_safe_redirects`` (used by
    ``scraper_transport.discover_pdf_urls_on_page``) on entry/exit so
    listing-page and detail-page fetches resolve to the same fake in a
    single ``with`` block.

    Accepts either a ``{url: Response | Exception}`` mapping (static
    lookup with an ``AssertionError`` on missing URLs) or a callable
    matching ``request_with_safe_redirects``'s call signature.
    """
    fake_request = _build_fake_request(responses_or_callable)

    p1 = patch(
        "scraper_transport.request_with_safe_redirects",
        side_effect=fake_request,
    )

    class _Combined:
        def __enter__(self) -> None:
            p1.__enter__()

        def __exit__(self, *args: object) -> None:
            p1.__exit__(*args)

    return _Combined()


# ---------------------------------------------------------------------------
# Module-env reset
# ---------------------------------------------------------------------------


_TRACKED_MODULES = (
    "discover_bndes_candidates",
    "pipeline_core",
    "discover_pncp_candidates",
)
_TRACKED_ENV_VARS = (
    "BNDES_MIN_NOTICE_YEAR",
    "SCRAPE_MAX_PDF_BYTES",
    "SCRAPE_MAX_PDFS_PER_RUN",
)


@pytest.fixture(autouse=True)
def reset_module_env() -> None:
    """Restore env-driven module constants between tests.

    Discoverers capture ``*_MIN_NOTICE_YEAR`` / ``SCRAPE_MAX_*`` at
    import time, so per-test ``monkeypatch`` plus a post-test
    ``importlib.reload`` keeps the suite deterministic across modules
    that share those constants.

    The pop + reload runs after the test body (post-``yield``). It is
    a no-op for tracked env vars that ``monkeypatch`` already restored,
    and reloads each tracked module that is currently in ``sys.modules``
    (so test files that never import ``discover_bndes_candidates`` are
    not forced to import it just to satisfy the fixture).
    """
    yield
    for env_var in _TRACKED_ENV_VARS:
        os.environ.pop(env_var, None)
    for module_name in _TRACKED_MODULES:
        if module_name not in sys.modules:
            continue
        try:
            importlib.reload(sys.modules[module_name])
        except ImportError:
            continue