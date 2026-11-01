"""Fundação Grupo Boticário source discoverer for the cronjob pipeline.

Phase 4 port of
``lasalle-notices-automation/app/services/scraper/playwright/fundacao_grupo_boticario.py``.
The original function took a Playwright ``Page`` and called
``ctx.ingest_pdf_url`` (FastAPI/SQLAlchemy coupling). This module
returns candidates only and hands them to ``pipeline_core.process_candidate``
+ ``pipeline_core.submit_candidates(candidates, source="fundacao_grupo_boticario")``
for download / OCR / submit.

The Fundação Grupo Boticário source uses two stages:

1. **Listing stage** — the homepage ``https://fundacaogrupoboticario.org.br/``
   is a marketing page that never links to a chamada (verified live on
   2026-11-01: zero ``edital`` / ``chamada`` / ``sprint`` / ``bolsa``
   anchors, statically or after JavaScript). The foundation publishes every
   chamada as a post on the news index
   ``https://fundacaogrupoboticario.org.br/noticias/``, which renders the
   whole archive (newest first) server-side as ``div.noticias-card`` blocks.
   Both listings are fetched and their detail URLs are unioned (detail URLs
   stay on ``fundacaogrupoboticario.org.br`` or ``goias.gov.br`` under
   ``/fapeg/`` and carry a ``chamada`` / ``edital`` / ``sprint`` / ``bolsa``
   signal token).

2. **Lifecycle + detail stage** — before any detail is fetched, posts whose
   title announces a result (``resultado``, ``contemplados``, ``vencedores``,
   ``selecionados``) are dropped. Posts whose card date is older than
   ``FUNDACAO_GRUPO_BOTICARIO_MAX_POST_AGE_DAYS`` are "stale": they are still
   fetched (a stale call may announce a future deadline or an extension), but
   only after the in-window posts and only with the leftover per-run detail
   budget. Each fetched detail page is fetched once, with a pause of
   ``FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS`` between fetches; an
   explicit inscription deadline found in the article text (``até 9 de março``, ``de 3 a 9 de março``, ``Aberto até
   04 de novembro de 2025``) must not be in the past, and a page with no
   parseable deadline is accepted only if its post date is inside the age
   window. ``.pdf`` anchors are then read from the same static HTML; the
   Playwright PDF-anchor fallback runs only when the static page yields none.

When the static listings yield no detail URLs at all, a Playwright fallback
rebuilds an HTML fragment from each listing's ``<a>`` elements and feeds it
back into the BS4 detail extractor.

The detail-URL helpers are inlined from the FastAPI helper-only module
``app/services/scraper/sources/fundacao_grupo_boticario.py``. That
helper module is intentionally not registered as a discoverer in the
cronjob (it is consumed only by this Playwright source per the FastAPI
``sources/AGENTS.md`` and ``scraper/AGENTS.md`` docs).

Message shape matches the existing PNCP contract so the Render submit
endpoint can ingest it unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

import pipeline_core
from scraper_transport import (
    ensure_safe_url,
    fetch_html_with_retry,
    log_source_failure,
    looks_like_pdf_url,
)


FUNDACAO_GRUPO_BOTICARIO_LISTING_URL = "https://fundacaogrupoboticario.org.br/"
# The homepage carries no chamada anchors; the editais are published as posts
# on the news index, which is the real listing surface.
FUNDACAO_GRUPO_BOTICARIO_NEWS_URL = "https://fundacaogrupoboticario.org.br/noticias/"
FUNDACAO_GRUPO_BOTICARIO_LISTING_URLS = (
    FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
    FUNDACAO_GRUPO_BOTICARIO_NEWS_URL,
)


FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN", "50"),
)
FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN", "40"),
)
FUNDACAO_GRUPO_BOTICARIO_MAX_POST_AGE_DAYS = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_MAX_POST_AGE_DAYS", "180"),
)
# Pause between detail fetches: the site answered HTTP 429 to bursts of
# repeated requests.
FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS = float(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS", "1.0"),
)
FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS", "3"),
)
FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS = float(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS", "2"),
)
FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS", "30"),
)


def is_fundacao_grupo_boticario_host(url: str) -> bool:
    """Return ``True`` if ``url`` is on the foundation's host.

    Inlined verbatim from
    ``app/services/scraper/sources/fundacao_grupo_boticario.py`` so
    the cronjob can reuse the helper without importing the
    FastAPI package.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host == "fundacaogrupoboticario.org.br"


def extract_fundacao_grupo_boticario_detail_urls_from_soup(
    soup: BeautifulSoup, listing_url: str,
) -> list[str]:
    """Discover detail-URL links from the Fundação Grupo Boticário
    listing HTML.

    Inlined verbatim from
    ``app/services/scraper/sources/fundacao_grupo_boticario.py``.
    Keeps only anchors on ``fundacaogrupoboticario.org.br`` /
    ``goias.gov.br`` (the latter gated to ``/fapeg/`` paths) whose
    href / path / text / title / aria-label carries one of the
    ``chamada`` / ``edital`` / ``sprint`` / ``bolsa`` signal tokens.
    """
    discovered: list[str] = []
    seen: set[str] = set()
    signal_pattern = re.compile(r"\b(chamada|edital|sprint|bolsa)\b", re.IGNORECASE)
    allowed_hosts = {"fundacaogrupoboticario.org.br", "goias.gov.br"}

    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue

        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue

        resolved = urljoin(listing_url, href)
        normalized = urlsplit(resolved)
        host = (normalized.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host not in allowed_hosts:
            continue

        path = normalized.path.rstrip("/")
        if not path or path == "/":
            continue

        if host == "goias.gov.br" and not path.startswith("/fapeg/"):
            continue

        if host == "fundacaogrupoboticario.org.br" and path in {
            "/noticias",
            "/quem-somos",
            "/nossa-atuacao",
            "/fale-conosco",
        }:
            continue

        signal_text = " ".join(
            [
                href,
                path,
                link.get_text(" ", strip=True),
                str(link.get("title") or ""),
                str(link.get("aria-label") or ""),
            ]
        )
        if not signal_pattern.search(signal_text):
            continue

        canonical = urlunsplit((normalized.scheme, normalized.netloc, path, "", ""))
        if canonical in seen:
            continue

        seen.add(canonical)
        discovered.append(canonical)

    return discovered


def extract_fundacao_grupo_boticario_detail_urls(
    listing_html: str, listing_url: str,
) -> list[str]:
    soup = BeautifulSoup(listing_html, "html.parser")
    return extract_fundacao_grupo_boticario_detail_urls_from_soup(soup, listing_url)


# ---------------------------------------------------------------------------
# Listing posts + lifecycle gating
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListingPost:
    """A news-index card: the post title and its publication date."""

    title: str
    published: date | None


_CARD_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def _canonical_detail_url(url: str) -> str:
    """Canonical form used for detail URLs (no query/fragment/trailing slash)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def extract_fundacao_grupo_boticario_listing_posts(
    listing_html: str, listing_url: str,
) -> dict[str, ListingPost]:
    """Map canonical post URL -> title/date for the news-index cards.

    The news index renders every post as
    ``div.noticias-card > p.noticias-card__cat ("... | dd/mm/yyyy")`` plus
    ``h4 > a``. Pages without such cards (the homepage) return ``{}``.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    posts: dict[str, ListingPost] = {}
    for card in soup.select("div.noticias-card"):
        link = card.select_one("h4 a[href]") or card.select_one("a[href]")
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        canonical = _canonical_detail_url(urljoin(listing_url, href))
        published: date | None = None
        meta = card.select_one("p.noticias-card__cat")
        if isinstance(meta, Tag):
            match = _CARD_DATE_RE.search(meta.get_text(" ", strip=True))
            if match:
                day, month, year = (int(g) for g in match.groups())
                try:
                    published = date(year, month, day)
                except ValueError:
                    published = None
        posts.setdefault(
            canonical,
            ListingPost(title=link.get_text(" ", strip=True), published=published),
        )
    return posts


def _fold(text: str) -> str:
    """Lower-case and strip accents so vocabulary matching is spelling-agnostic."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


# A post whose title announces who won / was selected is a result, not a call.
_RESULT_TITLE_RE = re.compile(
    r"\b(resultados?|contemplad[oa]s?|vencedor(?:es|as)?|selecionad[oa]s?|"
    r"ganhador(?:es|as)?|disputam o voto)\b"
)

_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}
# ``até 9 de março`` / ``até o dia 04 de novembro de 2025`` and the tail of a
# range (``de 3 a 9 de março``, ``de 28 de março a 15 de maio``).
_DEADLINE_RE = re.compile(
    r"\b(?:ate|a)\s+(?:o\s+dia\s+)?(\d{1,2})o?\s+de\s+"
    rf"({'|'.join(_MONTHS)})(?:\s+de\s+(\d{{4}}))?"
)
# A date only counts as an application deadline when the preceding text talks
# about inscriptions / submissions, so unrelated dates are not mistaken for one.
_DEADLINE_CONTEXT_RE = re.compile(
    r"inscri|prazo|abert|candidatur|submiss|propost|envio|encerr"
)


def is_result_post(title: str, url: str = "") -> bool:
    """Whether the post title/slug announces a result rather than a call."""
    slug = urlsplit(url).path.replace("-", " ").replace("/", " ")
    return bool(_RESULT_TITLE_RE.search(_fold(f"{title} {slug}")))


def extract_application_deadline(
    text: str, *, reference: date | None,
) -> date | None:
    """Latest application deadline mentioned in ``text``, or ``None``.

    ``reference`` (the post date) resolves deadlines written without a year;
    without it only explicit-year deadlines are returned. The latest date wins
    so ``prorrogadas até 27 de abril`` supersedes the original deadline.
    """
    folded = _fold(text)
    deadlines: list[date] = []
    for match in _DEADLINE_RE.finditer(folded):
        context = folded[max(0, match.start() - 200): match.end()]
        if not _DEADLINE_CONTEXT_RE.search(context):
            continue
        day = int(match.group(1))
        month = _MONTHS[match.group(2)]
        year_text = match.group(3)
        try:
            if year_text:
                deadline = date(int(year_text), month, day)
            elif reference is not None:
                deadline = date(reference.year, month, day)
                if deadline < reference:
                    deadline = date(reference.year + 1, month, day)
            else:
                continue
        except ValueError:
            continue
        deadlines.append(deadline)
    return max(deadlines) if deadlines else None


@dataclass(frozen=True)
class DetailLifecycle:
    """Outcome of the lifecycle gate for one fetched detail page."""

    state: str  # "open" | "closed" | "missing"
    deadline: date | None
    published: date | None


def _detail_article_text(soup: BeautifulSoup) -> str:
    article = soup.select_one(".noticia-content")
    return (article or soup).get_text(" ", strip=True)


def _detail_published_date(soup: BeautifulSoup) -> date | None:
    stamp = soup.select_one(".wp-block-post-date time[datetime]")
    if isinstance(stamp, Tag):
        value = str(stamp.get("datetime") or "")[:10]
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def evaluate_detail_lifecycle(
    soup: BeautifulSoup,
    *,
    listing_published: date | None,
    as_of: date,
    max_age_days: int,
) -> DetailLifecycle:
    """Decide whether a fetched detail page describes a call still open.

    * explicit deadline found: open iff ``deadline >= as_of`` (the deadline day
      itself is still open);
    * no deadline: open only if the post date is known and inside the age window;
    * neither: ``missing`` (lifecycle cannot be established, so not a candidate).
    """
    published = listing_published or _detail_published_date(soup)
    deadline = extract_application_deadline(
        _detail_article_text(soup), reference=published,
    )
    if deadline is not None:
        state = "open" if deadline >= as_of else "closed"
    elif published is not None:
        in_window = published >= as_of - timedelta(days=max_age_days)
        state = "open" if in_window else "closed"
    else:
        state = "missing"
    return DetailLifecycle(state=state, deadline=deadline, published=published)


def extract_detail_pdf_urls(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Static ``.pdf`` anchors of a detail page, resolved against ``page_url``."""
    pdf_urls: list[str] = []
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        if isinstance(href, str) and href and looks_like_pdf_url(href):
            pdf_urls.append(urljoin(page_url, href))
    return pdf_urls


async def _collect_listing_anchors(listing_url: str) -> str:
    """Navigate to ``listing_url`` with Playwright and rebuild an HTML
    fragment containing every ``<a>`` element's href. The fragment is
    fed back into ``extract_fundacao_grupo_boticario_detail_urls``
    so the BS4 extractor stays the source of truth for filtering.

    Returns an empty string when no anchors are found.
    """
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    listing_html = "<html><body>"

    async def _read_async_or_value(value: Any) -> str:
        if inspect.isawaitable(value):
            value = await value
        return value if isinstance(value, str) else ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(listing_url)
            listing_links = await page.query_selector_all("a")
            for link in listing_links:
                href = await _read_async_or_value(link.get_attribute("href"))
                if not href:
                    continue
                link_text = await _read_async_or_value(link.inner_text())
                title = await _read_async_or_value(link.get_attribute("title"))
                aria_label = await _read_async_or_value(link.get_attribute("aria-label"))
                safe_href = href.replace('"', "&quot;")
                safe_text = (link_text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                safe_title = (title or "").replace('"', "&quot;")
                safe_aria_label = (aria_label or "").replace('"', "&quot;")
                listing_html += (
                    f'<a href="{safe_href}" title="{safe_title}" '
                    f'aria-label="{safe_aria_label}">{safe_text}</a>'
                )
        finally:
            await browser.close()
    listing_html += "</body></html>"
    return listing_html


def _run_playwright_fallback(
    listing_url: str, *, stats: dict[str, int],
) -> list[str]:
    """Run the Playwright fallback against ``listing_url``.

    Returns the discovered detail URLs (possibly empty). Increments
    ``stats["errors"]`` if Playwright is unavailable or the
    navigation fails.
    """
    try:
        listing_html = asyncio.run(_collect_listing_anchors(listing_url))
    except ImportError:
        log_source_failure(
            "Playwright is not installed; skipping "
            "Fundação Grupo Boticário fallback for %s",
            listing_url,
            exc=ImportError("playwright"),
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []
    except Exception as exc:
        log_source_failure(
            "Failed processing Fundação Grupo Boticário listing page %s: %s",
            listing_url,
            exc,
            exc=exc,
        )
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    return extract_fundacao_grupo_boticario_detail_urls(listing_html, listing_url)


async def _collect_detail_pdf_urls(detail_url: str) -> list[str]:
    """Extract PDF anchors from a detail page rendered by Playwright.

    The foundation host serves some detail pages with client-side content, so
    a successful static response is not evidence that its PDF anchors are
    present in the response HTML.
    """
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    ensure_safe_url(detail_url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(detail_url)
            detail_links = await page.query_selector_all("a")
            pdf_urls: list[str] = []
            for link in detail_links:
                href = await link.get_attribute("href")
                if href and looks_like_pdf_url(href):
                    pdf_urls.append(urljoin(detail_url, href))
            return pdf_urls
        finally:
            await browser.close()


def _run_playwright_detail_fallback(
    detail_url: str, *, stats: dict[str, int],
) -> list[str]:
    """Resolve detail-page PDF anchors through the dynamic browser path."""
    try:
        return asyncio.run(_collect_detail_pdf_urls(detail_url))
    except ImportError:
        log_source_failure(
            "Playwright is not installed; skipping Fundação Grupo Boticário "
            "detail fallback for %s",
            detail_url,
            exc=ImportError("playwright"),
        )
    except Exception as exc:
        log_source_failure(
            "Failed processing Fundação Grupo Boticário detail page %s: %s",
            detail_url,
            exc,
            exc=exc,
        )
    stats["errors"] = stats.get("errors", 0) + 1
    return []


def build_candidate(
    url: str,
    *,
    listing_url: str,
    detail_url: str | None = None,
    origin: str | None = None,
    application_deadline: date | None = None,
    published_at: date | None = None,
) -> dict[str, Any]:
    """Build a ``kind="pdf"`` candidate for the Fundação Grupo
    Boticário source."""
    if origin is None:
        origin = "listing_pdf" if looks_like_pdf_url(url) else "playwright_fallback"

    metadata: dict[str, Any] = {
        "source": "fundacao_grupo_boticario",
        "listing_url": listing_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
    }
    if detail_url is not None:
        metadata["detail_url"] = detail_url
    if published_at is not None:
        metadata["published_at"] = published_at.isoformat()
    if application_deadline is not None:
        metadata["application_deadline"] = application_deadline.isoformat()
        metadata["status"] = "open"

    return {"url": url, "kind": "pdf", "metadata": metadata}


def discover_candidates(
    *, as_of_date: date | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover Fundação Grupo Boticário edital PDF candidates.

    Returns ``(stats, candidates)``. Detail URLs are the union of the
    homepage and the news index (the real surface of the chamadas); the
    Playwright listing fallback runs only when neither static listing yields a
    single detail URL. Posts that announce results are dropped before any detail
    fetch; stale posts (older than the age window) are fetched after the
    in-window ones with the leftover budget, and stale posts beyond the budget
    are only counted in ``skipped_stale_posts`` (not a partial inventory).
    Each fetched detail must pass
    the deadline gate (``evaluate_detail_lifecycle``) before its PDFs become
    candidates, so closed calls never reach the pipeline. ``as_of_date``
    defaults to today in America/Sao_Paulo and exists for replays/tests.
    """
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "details_fetched": 0,
        "candidates": 0,
        "errors": 0,
        "candidate_cap_reached": 0,
        "playwright_fallback_used": 0,
        "detail_urls_found": 0,
        "skipped_result_posts": 0,
        "skipped_stale_posts": 0,
        "open_details": 0,
        "closed_details": 0,
        "missing_lifecycle": 0,
        "detail_cap_reached": 0,
        "detail_browser_fallback_used": 0,
    }
    if as_of_date is None:
        as_of_date = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    age_cutoff = as_of_date - timedelta(
        days=FUNDACAO_GRUPO_BOTICARIO_MAX_POST_AGE_DAYS,
    )
    candidates: list[dict[str, Any]] = []
    seen_pdfs: set[str] = set()

    detail_urls: list[str] = []
    detail_listing: dict[str, str] = {}
    posts: dict[str, ListingPost] = {}

    def _add_detail_urls(urls: list[str], listing_url: str) -> None:
        for url in urls:
            if url not in detail_listing:
                detail_listing[url] = listing_url
                detail_urls.append(url)

    for listing_url in FUNDACAO_GRUPO_BOTICARIO_LISTING_URLS:
        try:
            listing_html = fetch_html_with_retry(
                listing_url,
                timeout=FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS,
                max_attempts=FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS,
                backoff_seconds=FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS,
                allowed_status_codes=(401, 403, 404, 410),
            )
        except Exception as exc:
            log_source_failure(
                "Failed to fetch Fundação Grupo Boticário listing %s: %s",
                listing_url,
                exc,
                exc=exc,
            )
            stats["errors"] += 1
            continue
        stats["listings_fetched"] += 1
        for url, post in extract_fundacao_grupo_boticario_listing_posts(
            listing_html, listing_url,
        ).items():
            posts.setdefault(url, post)
        soup = BeautifulSoup(listing_html, "html.parser")
        _add_detail_urls(
            extract_fundacao_grupo_boticario_detail_urls_from_soup(soup, listing_url),
            listing_url,
        )

    if not detail_urls:
        stats["playwright_fallback_used"] = 1
        for listing_url in FUNDACAO_GRUPO_BOTICARIO_LISTING_URLS:
            _add_detail_urls(
                _run_playwright_fallback(listing_url, stats=stats), listing_url,
            )
    stats["detail_urls_found"] = len(detail_urls)

    # Cheap pre-fetch gate from the listing card: result posts are never
    # fetched. The rest is split into in-window posts (fetched first; their
    # overflow past the budget is a real partial inventory) and stale posts
    # (card date older than the window). A stale post may still announce a
    # future deadline or an extension in its detail page, so stale posts are
    # fetched with whatever detail budget the in-window posts leave over;
    # ``evaluate_detail_lifecycle`` then decides. Stale posts left unfetched
    # are only telemetry (``skipped_stale_posts``) and do not mark the
    # inventory partial, otherwise the source would warn forever.
    in_window: list[str] = []
    stale: list[str] = []
    for detail_url in detail_urls:
        post = posts.get(detail_url)
        if post is not None:
            if is_result_post(post.title, detail_url):
                stats["skipped_result_posts"] += 1
                continue
            if post.published is not None and post.published < age_cutoff:
                stale.append(detail_url)
                continue
        elif is_result_post("", detail_url):
            stats["skipped_result_posts"] += 1
            continue
        in_window.append(detail_url)

    # A stale post can still announce a future deadline, so an unfetched one is
    # uncovered inventory like any other. The budget fits the whole news index.
    budget = FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN
    if len(in_window) + len(stale) > budget:
        stats["detail_cap_reached"] = 1
        stats["partial_inventory"] = 1
    to_fetch = (in_window + stale)[:budget]
    stats["skipped_stale_posts"] += max(len(in_window) + len(stale) - max(budget, len(in_window)), 0)

    for index, detail_url in enumerate(to_fetch):
        if index > 0 and FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS > 0:
            time.sleep(FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS)
        listing_url = detail_listing[detail_url]
        post = posts.get(detail_url)
        try:
            detail_html = fetch_html_with_retry(
                detail_url,
                timeout=FUNDACAO_GRUPO_BOTICARIO_FETCH_TIMEOUT_SECONDS,
                max_attempts=FUNDACAO_GRUPO_BOTICARIO_FETCH_MAX_ATTEMPTS,
                backoff_seconds=FUNDACAO_GRUPO_BOTICARIO_FETCH_BACKOFF_SECONDS,
                allowed_status_codes=(401, 403, 404, 410),
            )
        except Exception as exc:
            log_source_failure(
                "Failed to discover PDFs on Fundação Grupo Boticário detail %s: %s",
                detail_url,
                exc,
                exc=exc,
            )
            stats["errors"] += 1
            continue
        stats["details_fetched"] += 1
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        lifecycle = evaluate_detail_lifecycle(
            detail_soup,
            listing_published=post.published if post else None,
            as_of=as_of_date,
            max_age_days=FUNDACAO_GRUPO_BOTICARIO_MAX_POST_AGE_DAYS,
        )
        if lifecycle.state == "closed":
            stats["closed_details"] += 1
            continue
        if lifecycle.state == "missing":
            stats["missing_lifecycle"] += 1
            continue
        stats["open_details"] += 1

        # The foundation host server-renders its posts (``div.noticia-content``)
        # including the regulation anchors (verified live), so a post without
        # a PDF there genuinely has none. The browser is only a fallback for
        # other hosts or for a foundation page that came back without its
        # server-rendered article body.
        pdf_urls = extract_detail_pdf_urls(detail_soup, detail_url)
        if not pdf_urls and (
            not is_fundacao_grupo_boticario_host(detail_url)
            or detail_soup.select_one(".noticia-content") is None
        ):
            stats["detail_browser_fallback_used"] += 1
            pdf_urls = _run_playwright_detail_fallback(detail_url, stats=stats)
        for pdf_url in pdf_urls:
            if pdf_url in seen_pdfs:
                continue
            seen_pdfs.add(pdf_url)
            candidates.append(
                build_candidate(
                    pdf_url,
                    listing_url=listing_url,
                    detail_url=detail_url,
                    application_deadline=lifecycle.deadline,
                    published_at=lifecycle.published,
                )
            )
            if len(candidates) >= FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    "Stopping after candidate cap "
                    f"{FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN}",
                    file=sys.stderr,
                )
                stats["candidates"] = len(candidates)
                return stats, candidates

    stats["candidates"] = len(candidates)
    return stats, candidates


def main() -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"Fundação Grupo Boticário discovery stats: {stats}")
    print(f"Fundação Grupo Boticário candidates discovered: {len(candidates)}")

    if not candidates:
        print("No new candidates to submit")
        return 0

    _ocr_config, extractor = pipeline_core.make_default_ocr_extractor()
    max_pdf_bytes = pipeline_core.SCRAPE_MAX_PDF_BYTES

    processed: list[dict[str, Any]] = []
    for candidate in candidates:
        if pipeline_core.pdf_download_limit_reached(stats):
            stats["pdf_download_cap_reached"] = 1
            print(
                f"Stopping after PDF download cap {pipeline_core.SCRAPE_MAX_PDFS_PER_RUN}",
                file=sys.stderr,
            )
            break

        result = pipeline_core.process_candidate(
            candidate,
            extractor=extractor,
            max_bytes=max_pdf_bytes,
        )
        processed.append(result)
        if result.get("worker_result"):
            pipeline_core.record_pdf_download(stats)

    stats["processed"] = len(processed)
    stats["ocr_successes"] = sum(1 for r in processed if r.get("worker_result"))
    stats["ocr_failures"] = sum(1 for r in processed if r.get("error"))
    print(f"Fundação Grupo Boticário processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered Fundação Grupo Boticário candidates "
            "failed download/OCR; nothing will be submitted",
            file=sys.stderr,
        )
        return 1

    result = pipeline_core.submit_candidates(
        processed, source="fundacao_grupo_boticario",
    )
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered Fundação Grupo Boticário candidates "
            "produced no Render submissions",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
