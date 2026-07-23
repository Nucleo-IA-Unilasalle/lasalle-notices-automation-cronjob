"""Deterministic FUNBIO news inventory and canonical-call lead resolver."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup


FUNBIO_NEWS_URL = "https://chamadas.funbio.org.br/noticias"
FUNBIO_NEWS_LOOKBACK_DAYS = int(os.environ.get("FUNBIO_NEWS_LOOKBACK_DAYS", "45"))
FUNBIO_NEWS_MAX_DETAILS = int(os.environ.get("FUNBIO_NEWS_MAX_DETAILS", "20"))
_CALL_SIGNAL = re.compile(r"\b(edital|chamada|sele(?:cao|ção))\b", re.I)
_URL_PATTERN = re.compile(r"https?://chamadas\.funbio\.org\.br/[^\s<\"']+", re.I)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _canonical_call_url(url: str) -> str | None:
    parts = urlsplit(url.rstrip(".,);"))
    if (parts.hostname or "").lower() != "chamadas.funbio.org.br":
        return None
    path = parts.path.rstrip("/")
    if not re.fullmatch(r"/[a-z0-9-]+", path, re.I):
        return None
    if path in {"/noticias", "/quem-somos", "/calendario-chamadas"}:
        return None
    return urlunsplit(("https", "chamadas.funbio.org.br", path, "", ""))


def parse_news_inventory(
    html: str,
    *,
    now: datetime | None = None,
    lookback_days: int = FUNBIO_NEWS_LOOKBACK_DAYS,
    max_items: int = FUNBIO_NEWS_MAX_DETAILS,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("script", id="__NEXT_DATA__")
    if node is None or not node.string:
        return []
    payload = json.loads(node.string)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=lookback_days)
    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _walk(payload):
        if "idNoticia" not in item or "titulo" not in item:
            continue
        news_id = str(item["idNoticia"])
        if news_id in seen:
            continue
        published = item.get("dataPublicacao")
        published_dt = None
        if published:
            try:
                published_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                published_dt = None
        if published_dt and published_dt < cutoff:
            continue
        content = str(item.get("conteudo") or "")
        content_soup = BeautifulSoup(content, "html.parser")
        urls = [
            href
            for link in content_soup.find_all("a")
            if isinstance((href := link.get("href")), str)
        ]
        urls.extend(_URL_PATTERN.findall(content_soup.get_text(" ", strip=True)))
        call_urls = sorted(
            {
                canonical
                for url in urls
                if (canonical := _canonical_call_url(url)) is not None
            }
        )
        object_id = str(item.get("idobjeto") or "")
        article_url = (
            "https://chamadas.funbio.org.br/noticia-chamada"
            f"?idobjetoChamada={object_id}&idNoticia={news_id}"
        )
        inventory.append(
            {
                "news_id": news_id,
                "article_url": article_url,
                "title": str(item.get("titulo") or "").strip(),
                "published_at": (
                    published_dt.astimezone(timezone.utc).isoformat()
                    if published_dt
                    else None
                ),
                "call_urls": call_urls,
                "source_object_id": object_id or None,
                "content_text": content_soup.get_text(" ", strip=True),
            }
        )
        seen.add(news_id)
        if len(inventory) >= max_items:
            break
    return sorted(inventory, key=lambda item: (item["published_at"] or "", item["news_id"]), reverse=True)


def resolve_news_leads(
    news_inventory: list[dict[str, Any]],
    canonical_inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve only exact canonical URL, slug, or source-ID evidence."""
    by_url = {
        str(item.get("canonical_url") or "").rstrip("/"): item
        for item in canonical_inventory
        if item.get("canonical_url")
    }
    by_id = {
        str(item.get("source_record_id")): item
        for item in canonical_inventory
        if item.get("source_record_id")
    }
    resolutions: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for news in news_inventory:
        resolved: dict[str, Any] | None = None
        evidence = None
        for url in news.get("call_urls", []):
            normalized = str(url).rstrip("/")
            slug = urlsplit(normalized).path.strip("/")
            resolved = by_url.get(normalized) or by_id.get(slug)
            if resolved:
                evidence = normalized
                break
        if resolved:
            identity = str(resolved["source_record_id"])
            pair = (str(news["news_id"]), identity)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            resolutions.append(
                {
                    "news_id": news["news_id"],
                    "article_url": news["article_url"],
                    "resolution": "resolved",
                    "source_record_id": identity,
                    "canonical_url": resolved.get("canonical_url"),
                    "evidence": {"explicit_call_url": evidence},
                }
            )
        elif news.get("call_urls"):
            resolutions.append(
                {
                    "news_id": news["news_id"],
                    "article_url": news["article_url"],
                    "resolution": "explicit_new_call",
                    "canonical_url": news["call_urls"][0],
                    "evidence": {"explicit_call_url": news["call_urls"][0]},
                }
            )
        elif _CALL_SIGNAL.search(f"{news.get('title', '')} {news.get('content_text', '')}"):
            resolutions.append(
                {
                    "news_id": news["news_id"],
                    "article_url": news["article_url"],
                    "resolution": "unresolved_lead",
                    "reason_code": "unresolved_news_lead",
                    "evidence": {"explicit_identity": False},
                }
            )
    return sorted(resolutions, key=lambda item: (item["news_id"], item["resolution"]))

