"""Structured opportunity discovery for the Diario Oficial de Canoas.

The DOMC day endpoint is the authoritative low-cost inventory.  It exposes
publication ids, titles, edition/page context, and an individual publication
PDF.  When a matching Prefeitura WordPress ``licitacoes`` page exists, the
page is resolved to preserve the canonical URL and the complete edital
attachments; the DOMC PDF remains attached as source evidence/fallback.

This source is deliberately opt-in.  Its rolling local-date window and caps
are conservative because a day can contain many ordinary municipal acts.
"""

from __future__ import annotations

import html as html_lib
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote_plus, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Comment, Tag

from scraper_transport import request_with_safe_redirects


CANOAS_DOMC_BASE_URL = "https://sistemas.canoas.rs.gov.br/domc"
CANOAS_API_BASE_URL = f"{CANOAS_DOMC_BASE_URL}/api/public"
CANOAS_DIARY_BY_DAY_URL = f"{CANOAS_API_BASE_URL}/diary-by-day"
CANOAS_DIARY_URL_TEMPLATE = f"{CANOAS_DIARY_BY_DAY_URL}?day={{day}}"
CANOAS_PUBLICATION_FILE_URL_TEMPLATE = (
    f"{CANOAS_DOMC_BASE_URL}/api/publication-file/{{publication_id}}"
)
CANOAS_EDITION_FILE_URL_TEMPLATE = (
    f"{CANOAS_DOMC_BASE_URL}/api/edition-file/{{edition_id}}"
)
CANOAS_SEARCH_URL = f"{CANOAS_DOMC_BASE_URL}/pesquisar"
CANOAS_WP_API_BASE_URL = "https://www.canoas.rs.gov.br/wp-json/wp/v2"
CANOAS_WP_LICITACOES_URL = f"{CANOAS_WP_API_BASE_URL}/licitacoes"

# Compatibility aliases used by source tooling/tests.
CANOAS_BASE_URL = CANOAS_DOMC_BASE_URL
CANOAS_DIARY_API_URL = CANOAS_DIARY_BY_DAY_URL
CANOAS_PUBLICATION_URL_TEMPLATE = CANOAS_PUBLICATION_FILE_URL_TEMPLATE

SOURCE_KEY = "canoas"
CANOAS_TIMEZONE = ZoneInfo("America/Sao_Paulo")
CANOAS_INCREMENTAL_WINDOW_DAYS = int(
    os.environ.get("CANOAS_INCREMENTAL_WINDOW_DAYS", "3")
)
CANOAS_MAX_DAYS_PER_RUN = int(os.environ.get("CANOAS_MAX_DAYS_PER_RUN", "3"))
CANOAS_MAX_PUBLICATIONS_PER_RUN = int(
    os.environ.get("CANOAS_MAX_PUBLICATIONS_PER_RUN", "300")
)
CANOAS_MAX_OPPORTUNITIES_PER_RUN = int(
    os.environ.get("CANOAS_MAX_OPPORTUNITIES_PER_RUN", "25")
)
CANOAS_MAX_WORDPRESS_LOOKUPS_PER_RUN = int(
    os.environ.get("CANOAS_MAX_WORDPRESS_LOOKUPS_PER_RUN", "20")
)
CANOAS_MAX_ATTACHMENTS_PER_OPPORTUNITY = int(
    os.environ.get("CANOAS_MAX_ATTACHMENTS_PER_OPPORTUNITY", "15")
)
CANOAS_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("CANOAS_FETCH_TIMEOUT_SECONDS", "30")
)
CANOAS_FETCH_MAX_ATTEMPTS = int(
    os.environ.get("CANOAS_FETCH_MAX_ATTEMPTS", "3")
)
CANOAS_FETCH_BACKOFF_SECONDS = float(
    os.environ.get("CANOAS_FETCH_BACKOFF_SECONDS", "2")
)
CANOAS_MAX_RESPONSE_BYTES = int(
    os.environ.get("CANOAS_MAX_RESPONSE_BYTES", "5000000")
)
CANOAS_MAX_CONTENT_CHARS = int(
    os.environ.get("CANOAS_MAX_CONTENT_CHARS", "2000000")
)


_YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-]((?:19|20)\d{2}))?(?!\d)"
)
_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_POST_ACT_RE = re.compile(
    r"\b(resultado|ata|homologac(?:ao|oes)|errata|retificac(?:ao|oes)|"
    r"notificac(?:ao|oes)|apostila|termo\s+de\s+(?:contrato|homologac(?:ao|oes)|"
    r"adjudicac(?:ao|oes)|revogac(?:ao|oes)|rescis(?:ao|oes)|designacao)|"
    r"revogac(?:ao|oes)|cancelament(?:o|os)|"
    r"suspens(?:ao|oes)|extrato\s+de\s+credenciamento)\b",
    re.IGNORECASE,
)
_PROCUREMENT_RE = re.compile(
    r"\b(preg(?:ao|oes)|concorren(?:cia|cias)|licitac(?:ao|oes)|"
    r"tomada\s+de\s+precos?|registro\s+de\s+precos?|"
    r"dispensa|inexigibilidade|documento\s+oficial\s+licitatorio|"
    r"disputa\s+eletronica)\b|"
    r"\b(?:aquisic(?:ao|oes)|contratac(?:ao|oes))\s+de\s+"
    r"(?:empresa|servicos?|obras?|bens?|materiais?|fornecimento)\b",
    re.IGNORECASE,
)
_SIGNAL_RE = re.compile(
    r"\b(edital(?:s)?|chamamento(?:s)?|chamada\s+publica|"
    r"credenciamento|processo\s+seletivo|selec(?:ao|oes)\s+publica)\b",
    re.IGNORECASE,
)
_BLOCKED_ATTACHMENT_RE = re.compile(
    r"\b(resultado|ata|homologac(?:ao|oes)|errata|retificac(?:ao|oes)|"
    r"notificac(?:ao|oes)|termo\s+de\s+(?:homologac(?:ao|oes)|"
    r"adjudicac(?:ao|oes)|revogac(?:ao|oes)|rescis(?:ao|oes)))\b",
    re.IGNORECASE,
)
_YEAR_NUMBER_RE = re.compile(
    r"\b(?:edital|chamamento|chamada|credenciamento)?\D{0,15}"
    r"(\d{1,4})\s*[/-]\s*((?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def _fold(value: Any) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value or "")).lower()
        if not unicodedata.combining(character)
    )


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=CANOAS_TIMEZONE)
    return value


def _is_wordpress_url(url: str, *, attachment: bool = False) -> bool:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or (parts.hostname or "").lower()
        not in {"www.canoas.rs.gov.br", "canoas.rs.gov.br"}
    ):
        return False
    prefix = "/wp-content/uploads/" if attachment else "/licitacoes/"
    return parts.path.lower().startswith(prefix)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )


def _parse_date(value: Any, *, default_year: int | None = None) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    iso = re.search(
        r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)",
        text,
    )
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    match = _DATE_PATTERN.search(text)
    if match:
        year = int(match.group(3)) if match.group(3) else default_year
        if year is not None:
            try:
                return date(year, int(match.group(2)), int(match.group(1)))
            except ValueError:
                return None
    folded = _fold(text)
    months = "|".join(_MONTHS)
    match = re.search(
        rf"\b(\d{{1,2}})\s+(?:de\s+)?({months})"
        rf"(?:\s+de\s+((?:19|20)\d{{2}}))?\b",
        folded,
    )
    if match:
        year = int(match.group(3)) if match.group(3) else default_year
        if year is not None:
            try:
                return date(year, _MONTHS[match.group(2)], int(match.group(1)))
            except ValueError:
                return None
    return None


def _date_from_day(day: date | datetime | str) -> date:
    if isinstance(day, datetime):
        return _aware_datetime(day).astimezone(CANOAS_TIMEZONE).date()
    if isinstance(day, date):
        return day
    parsed = _parse_date(day)
    if parsed is None:
        raise ValueError(f"invalid Canoas date: {day!r}")
    return parsed


def _local_datetime(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=CANOAS_TIMEZONE)


def _iso_datetime(value: Any, *, default_year: int | None = None) -> str | None:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=CANOAS_TIMEZONE)
        return parsed.astimezone(timezone.utc).isoformat()
    text = _clean_text(value)
    if text:
        try:
            parsed_datetime = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed_datetime = None
        if parsed_datetime is not None:
            if parsed_datetime.tzinfo is None:
                parsed_datetime = parsed_datetime.replace(tzinfo=CANOAS_TIMEZONE)
            return parsed_datetime.astimezone(timezone.utc).isoformat()
    parsed = _parse_date(value, default_year=default_year)
    if parsed is None:
        return None
    return _local_datetime(parsed).isoformat()


def normalize_html(html: str) -> str:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "nav", "footer", "header"]):
        node.decompose()
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for node in soup.find_all(["br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"]):
        if isinstance(node, Tag):
            node.insert_before("\n")
    text = html_lib.unescape(soup.get_text(" ", strip=False)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def build_diary_url(day: date | datetime | str) -> str:
    parsed = _date_from_day(day)
    return CANOAS_DIARY_URL_TEMPLATE.format(day=quote_plus(parsed.strftime("%d/%m/%Y")))


def build_wordpress_search_url(title: str, *, per_page: int = 20) -> str:
    match = _YEAR_NUMBER_RE.search(_fold(title))
    if match:
        query = f"{match.group(1)} {match.group(2)}"
    else:
        query = _clean_text(title)[:80]
    params = {"search": query, "per_page": str(max(1, min(per_page, 100)))}
    return f"{CANOAS_WP_LICITACOES_URL}?{urlencode(params)}"


def extract_publications(
    payload: dict[str, Any], *, default_day: date | datetime | str | None = None
) -> list[dict[str, Any]]:
    """Flatten one DOMC day response into publication records."""
    if payload == {}:
        # DOMC represents dates without an edition (weekends/future dates) as
        # an empty object rather than an object with ``editions: []``.
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("editions"), list):
        raise ValueError("Canoas diary response is missing editions")
    day = _parse_date(payload.get("day"))
    if day is None and default_day is not None:
        day = _date_from_day(default_day)
    records: list[dict[str, Any]] = []
    for edition in payload["editions"]:
        if not isinstance(edition, dict):
            raise ValueError("Canoas diary contains a non-object edition")
        edition_id = edition.get("id")
        if edition_id is None:
            raise ValueError("Canoas diary edition is missing id")
        edition_title = _clean_text(edition.get("title"))
        index = edition.get("index")
        if not isinstance(index, list):
            raise ValueError("Canoas diary edition is missing index")
        for item in index:
            if not isinstance(item, dict):
                raise ValueError("Canoas diary index contains a non-object row")
            publication_id = item.get("publication_id")
            title = _clean_text(item.get("publication_title"))
            if (
                publication_id is None
                or not str(publication_id).isdigit()
                or not title
            ):
                raise ValueError("Canoas diary publication is missing identity/title")
            records.append(
                {
                    "source_record_id": str(publication_id),
                    "publication_id": str(publication_id),
                    "title": title,
                    "day": day.isoformat() if day else None,
                    "edition_id": str(edition_id),
                    "edition_title": edition_title,
                    "page_start": _clean_text(item.get("page_start")) or None,
                    "page_end": _clean_text(item.get("page_end")) or None,
                }
            )
    return records


def _policy_reason(title: str) -> str | None:
    folded = _fold(title)
    if folded.startswith("diario oficial canoas"):
        return "historical_index_notice"
    if _POST_ACT_RE.search(folded):
        return "post_act"
    if _PROCUREMENT_RE.search(folded):
        return "pncp_procurement"
    if not _SIGNAL_RE.search(folded):
        return "no_opportunity_signal"
    return None


def is_likely_opportunity(title: str) -> bool:
    return _policy_reason(title) is None


def _record_number_year(title: str) -> tuple[str, str] | None:
    match = _YEAR_NUMBER_RE.search(_fold(title))
    if not match:
        return None
    return match.group(1), match.group(2)


def _wordpress_title(record: dict[str, Any]) -> str:
    title = record.get("title")
    if isinstance(title, dict):
        title = title.get("rendered")
    return _clean_text(title)


def _match_tokens(value: Any) -> set[str]:
    ignored = {
        "edital", "numero", "publico", "publica", "canoas", "interessados",
        "modalidade", "servicos", "2026",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _fold(value))
        if len(token) > 3 and token not in ignored and not token.isdigit()
    }


def _match_families(value: Any) -> set[str]:
    folded = _fold(value)
    families: set[str] = set()
    if re.search(r"\b(?:chamamento|chamada\s+publica)\b", folded):
        families.add("public_call")
    if re.search(r"\bcredenciamento\b", folded):
        families.add("credential")
    if re.search(r"\b(?:selecao|processo\s+seletivo|concurso\s+publico)\b", folded):
        families.add("selection")
    return families


def match_wordpress_record(
    records: list[dict[str, Any]],
    publication: dict[str, Any],
) -> dict[str, Any] | None:
    """Select only an exact edital number/year match from WP search results."""
    wanted = _record_number_year(publication.get("title", ""))
    wanted_title = _fold(publication.get("title"))
    publication_families = _match_families(publication.get("title"))
    publication_tokens = _match_tokens(publication.get("title"))
    best: tuple[int, dict[str, Any]] | None = None
    tied = False
    for candidate in records:
        if not isinstance(candidate, dict):
            continue
        title = _wordpress_title(candidate)
        if not title:
            continue
        link = _clean_text(candidate.get("link"))
        if candidate.get("status") not in {None, "publish"} or not _is_wordpress_url(link):
            continue
        classes = " ".join(
            str(item) for item in candidate.get("class_list", [])
            if isinstance(item, str)
        )
        class_evidence = _fold(classes.replace("-", " "))
        candidate_policy = _policy_reason(title)
        if candidate_policy not in {None, "no_opportunity_signal"}:
            continue
        if re.search(
            r"\bmodalidade\s+(?:concorrencia|pregao|dispensa|inexigibilidade|"
            r"tomada|registro\s+de\s+precos)",
            class_evidence,
        ):
            continue
        if (
            candidate_policy == "no_opportunity_signal"
            and not _match_families(f"{title} {classes}")
        ):
            continue
        candidate_number = _record_number_year(title)
        score = 0
        if wanted and candidate_number == wanted:
            score += 100
        elif wanted:
            continue
        else:
            tokens = [token for token in re.findall(r"[a-z0-9]+", wanted_title) if len(token) > 3]
            score += sum(token in _fold(title) for token in tokens[:8])
        candidate_date = _parse_date(candidate.get("date"))
        publication_date = _parse_date(publication.get("day"))
        if candidate_date and publication_date:
            distance = abs((candidate_date - publication_date).days)
            if distance <= 7:
                score += 10
            else:
                continue
        elif wanted:
            continue
        candidate_evidence = f"{title} {classes}"
        shared_families = publication_families & _match_families(candidate_evidence)
        shared_tokens = publication_tokens & _match_tokens(candidate_evidence)
        if not shared_families and len(shared_tokens) < 2:
            # Number/year alone is not unique across municipal departments.
            continue
        score += 20 * len(shared_families) + len(shared_tokens)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = score, candidate
            tied = False
        elif score == best[0]:
            tied = True
    return best[1] if best and not tied else None


def extract_wordpress_page(
    html: str,
    page_url: str,
    *,
    max_attachments: int = CANOAS_MAX_ATTACHMENTS_PER_OPPORTUNITY,
) -> dict[str, Any]:
    """Extract canonical text and source-owned attachments from one WP page."""
    soup = BeautifulSoup(str(html or ""), "html.parser")
    canonical_tag = soup.select_one('link[rel="canonical"]')
    canonical_candidate = (
        urljoin(page_url, str(canonical_tag.get("href")))
        if isinstance(canonical_tag, Tag) and canonical_tag.get("href")
        else page_url
    )
    canonical_parts = urlsplit(canonical_candidate)
    if not _is_wordpress_url(canonical_candidate):
        canonical_candidate = page_url
    if not _is_wordpress_url(canonical_candidate):
        raise ValueError("Canoas WordPress canonical URL is outside licitacoes")
    canonical = canonical_url(canonical_candidate)
    root = soup.select_one("article .entry-content, article, main, .entry-content, .content")
    if not isinstance(root, Tag):
        root = soup.body
    if not isinstance(root, Tag):
        raise ValueError("Canoas WordPress page has no content body")
    # Related result/errata links are common on WordPress pages. Remove their
    # visible text before normalizing the edital body as well as excluding the
    # corresponding files below, so later acts cannot contaminate evidence.
    for link in list(root.find_all("a")):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        linked_url = canonical_url(urljoin(page_url, href.strip()))
        if not urlsplit(linked_url).path.lower().endswith(
            (".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".zip")
        ):
            continue
        if _BLOCKED_ATTACHMENT_RE.search(
            _fold(f"{link.get_text(' ', strip=True)} {linked_url}")
        ):
            link.decompose()
    title_node = root.find(["h1", "h2"])
    title = title_node.get_text(" ", strip=True) if isinstance(title_node, Tag) else ""
    content = normalize_html(str(root))
    if len(content) > CANOAS_MAX_CONTENT_CHARS:
        raise ValueError("Canoas WordPress content exceeds configured size limit")
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in root.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        url = canonical_url(urljoin(page_url, href.strip()))
        parsed = urlsplit(url)
        if not _is_wordpress_url(url, attachment=True):
            continue
        path = parsed.path.lower()
        suffix = path.rsplit("/", 1)[-1]
        if not path.endswith(
            (".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".zip")
        ):
            continue
        evidence = _fold(f"{link.get_text(' ', strip=True)} {url}")
        if _BLOCKED_ATTACHMENT_RE.search(evidence) or url in seen:
            continue
        seen.add(url)
        if len(documents) >= max(0, max_attachments):
            continue
        if suffix.endswith(".pdf"):
            kind, mime = "pdf", "application/pdf"
        elif suffix.endswith(".zip"):
            kind, mime = "zip", "application/zip"
        elif suffix.endswith(".docx"):
            kind, mime = "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif suffix.endswith(".odt"):
            kind, mime = "other", "application/vnd.oasis.opendocument.text"
        elif suffix.endswith(".doc"):
            kind, mime = "other", "application/msword"
        elif suffix.endswith(".xlsx"):
            kind, mime = "other", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            kind, mime = "other", "application/vnd.ms-excel"
        document_identity = hashlib.sha256(
            f"{canonical}|{url}".encode("utf-8")
        ).hexdigest()
        documents.append(
            {
                "source_document_id": f"canoas:wp:{document_identity}",
                "document_kind": kind,
                "url": url,
                "filename": suffix,
                "mime_type": mime,
                "is_principal": kind == "pdf" and not any(
                    item.get("document_kind") == "pdf" for item in documents
                ),
                "is_renderable": False,
            }
        )
    return {
        "canonical_url": canonical,
        "title": title,
        "content": content,
        "documents": documents,
        "attachment_cap_reached": len(seen) > len(documents),
    }


def _deadline(
    text: str,
    *,
    default_year: int | None = None,
    now: datetime | None = None,
) -> str | None:
    folded = _fold(text)
    current = _aware_datetime(now or datetime.now(timezone.utc))
    reference_date = current.astimezone(CANOAS_TIMEZONE).date()
    cues = list(
        re.finditer(
            r"\b(?:ate|encerramento|inscric(?:ao|oes)|propostas?|candidaturas?|"
            r"prazo\s+(?:final|para|de\s+(?:inscric(?:ao|oes)|envio|"
            r"apresentacao|submissao|propostas?|candidaturas?)))\b.{0,180}",
            folded,
        )
    )
    candidates: list[date] = []
    for cue in cues:
        snippet = cue.group(0)
        for match in _DATE_PATTERN.finditer(snippet):
            parsed = _parse_date(match.group(0), default_year=default_year)
            if parsed:
                if (
                    match.group(3) is None
                    and reference_date.month - parsed.month >= 6
                ):
                    parsed = parsed.replace(year=parsed.year + 1)
                candidates.append(parsed)
        for match in re.finditer(
            r"(?<!\d)(?:19|20)\d{2}-\d{1,2}-\d{1,2}(?!\d)",
            snippet,
        ):
            parsed = _parse_date(match.group(0))
            if parsed:
                candidates.append(parsed)
        months = "|".join(_MONTHS)
        for match in re.finditer(
            rf"\b\d{{1,2}}\s+(?:de\s+)?(?:{months})"
            rf"(?:\s+de\s+(?:19|20)\d{{2}})?\b",
            snippet,
        ):
            parsed = _parse_date(match.group(0), default_year=default_year)
            if parsed:
                candidates.append(parsed)
    if not candidates:
        return None
    value = max(candidates)
    return datetime.combine(
        value, datetime.max.time().replace(microsecond=0), tzinfo=CANOAS_TIMEZONE
    ).astimezone(timezone.utc).isoformat()


def extract_application_deadline(
    text: str,
    *,
    default_year: int | None = None,
    now: datetime | None = None,
) -> str | None:
    return _deadline(text, default_year=default_year, now=now)


def _status(text: str, *, deadline: str | None, now: datetime) -> str:
    now = _aware_datetime(now)
    folded = _fold(text)
    if re.search(
        r"\b(?:inscric(?:ao|oes)|propostas?|candidaturas?|prazo|edital)\b"
        r"\s+(?:(?:esta|estao|encontra-se|foi|foram)\s+)?"
        r"(?:encerrad|finalizad|expirad|suspens|cancelad|revogad)\w*\b",
        folded,
    ):
        return "closed"
    if deadline:
        try:
            deadline_date = (
                datetime.fromisoformat(deadline)
                .astimezone(CANOAS_TIMEZONE)
                .date()
            )
            if deadline_date < now.astimezone(CANOAS_TIMEZONE).date():
                return "closed"
            return "open"
        except ValueError:
            pass
    if re.search(r"\b(inscric(?:ao|oes)|propostas?|candidaturas?).{0,30}\babert", folded):
        return "open"
    return "unknown"


def _domc_document(publication_id: str, *, principal: bool) -> dict[str, Any]:
    url = CANOAS_PUBLICATION_FILE_URL_TEMPLATE.format(publication_id=publication_id)
    return {
        "source_document_id": f"domc:{publication_id}",
        "document_kind": "pdf",
        "url": url,
        "filename": f"domc-publication-{publication_id}.pdf",
        "mime_type": "application/pdf",
        "is_principal": principal,
        "is_renderable": False,
    }


def parse_canoas_opportunity(
    publication: dict[str, Any],
    *,
    wordpress: dict[str, Any] | None = None,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Normalize one publication, preserving WP documents when available."""
    publication_id = str(publication.get("publication_id") or publication.get("source_record_id") or "").strip()
    title = _clean_text(publication.get("title"))
    if not publication_id.isdigit() or not title:
        return None
    wp_title = _clean_text((wordpress or {}).get("title"))
    effective_title = wp_title or title
    if _policy_reason(effective_title) is not None:
        return None
    published_day = _parse_date(publication.get("day"))
    if published_day is None:
        return None
    current = _aware_datetime(
        now or snapshot_at or datetime.now(timezone.utc)
    )
    content = _clean_text((wordpress or {}).get("content"))
    if not content:
        content = f"Publicacao {title}. Diario Oficial de Canoas, {published_day.isoformat()}."
    deadline = _deadline(
        content, default_year=published_day.year, now=current
    )
    status = _status(content, deadline=deadline, now=current)
    if status == "closed":
        return None
    documents = list((wordpress or {}).get("documents") or [])
    wp_has_pdf = any(item.get("document_kind") == "pdf" for item in documents if isinstance(item, dict))
    documents.append(_domc_document(publication_id, principal=not wp_has_pdf))
    canonical = _clean_text((wordpress or {}).get("canonical_url")) or CANOAS_PUBLICATION_FILE_URL_TEMPLATE.format(publication_id=publication_id)
    source_published = _local_datetime(published_day).isoformat()
    modified = _iso_datetime((wordpress or {}).get("modified"), default_year=published_day.year)
    snapshot = _aware_datetime(snapshot_at or datetime.now(timezone.utc))
    lines = [f"# {effective_title}", "", "## Fonte oficial", "", canonical, "", "## Publicacao", "", source_published]
    context = [
        ("Diario", publication.get("edition_title")),
        ("Paginas", f"{publication.get('page_start') or '?'}-{publication.get('page_end') or publication.get('page_start') or '?'}"),
        ("Situacao", status),
        ("Prazo", deadline),
        ("Conteudo", content),
    ]
    for label, value in context:
        if value:
            lines.extend(("", f"## {label}", "", str(value)))
    lines.extend(("", "## Documentos", ""))
    for document in documents:
        lines.append(f"- {document['filename']}: {document['url']}")
    return {
        "source_key": SOURCE_KEY,
        "source_record_id": publication_id,
        "source_kind": "api",
        "opportunity_type": "other",
        "canonical_url": canonical,
        "title": effective_title,
        "description": content[:100_000],
        "authoritative_status": status,
        "source_published_at": source_published,
        "source_updated_at": modified,
        "proposal_opens_at": None,
        "application_deadline": deadline,
        "source_snapshot_at": snapshot.astimezone(timezone.utc).isoformat(),
        "source_markdown": "\n".join(lines).strip(),
        "source_content_hash": "",
        "documents": documents,
    }


def record_to_opportunity(
    publication: dict[str, Any],
    *,
    wordpress: dict[str, Any] | None = None,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    return parse_canoas_opportunity(
        publication, wordpress=wordpress, snapshot_at=snapshot_at, now=now
    )


def _coerce_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    method = getattr(value, "json", None)
    if callable(method):
        return method()
    raise ValueError("Canoas response is not JSON")


def _fetch_json(url: str) -> Any:
    response = request_with_safe_redirects(
        method="GET", url=url, timeout=CANOAS_FETCH_TIMEOUT_SECONDS,
        extra_headers={"Accept": "application/json"},
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        try:
            too_large = content_length and int(content_length) > CANOAS_MAX_RESPONSE_BYTES
        except (TypeError, ValueError):
            too_large = False
        if too_large:
            raise ValueError("Canoas response exceeds configured size limit")
        payload = response.text
        if len(payload.encode("utf-8")) > CANOAS_MAX_RESPONSE_BYTES:
            raise ValueError("Canoas response exceeds configured size limit")
        return _coerce_json(payload)
    finally:
        response.close()


def _fetch_html(url: str) -> str:
    response = request_with_safe_redirects(
        method="GET", url=url, timeout=CANOAS_FETCH_TIMEOUT_SECONDS,
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        try:
            too_large = (
                content_length
                and int(content_length) > CANOAS_MAX_RESPONSE_BYTES
            )
        except (TypeError, ValueError):
            too_large = False
        if too_large:
            raise ValueError("Canoas HTML response exceeds configured size limit")
        payload = response.text
        if len(payload.encode("utf-8")) > CANOAS_MAX_RESPONSE_BYTES:
            raise ValueError("Canoas HTML response exceeds configured size limit")
        return payload
    finally:
        response.close()


def _with_retry(url: str, fetch: Callable[[str], Any]) -> Any:
    last_error: Exception | None = None
    attempts = max(1, CANOAS_FETCH_MAX_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        try:
            return fetch(url)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(CANOAS_FETCH_BACKOFF_SECONDS * attempt)
    assert last_error is not None
    raise last_error


def _window_dates(
    *,
    now: datetime | None = None,
    start_date: date | datetime | str | None = None,
    end_date: date | datetime | str | None = None,
    window_days: int | None = None,
) -> list[date]:
    current = _aware_datetime(
        now or datetime.now(timezone.utc)
    ).astimezone(CANOAS_TIMEZONE).date()
    end = _date_from_day(end_date) if end_date is not None else current
    if start_date is not None:
        start = _date_from_day(start_date)
    else:
        days = max(1, min(window_days or CANOAS_INCREMENTAL_WINDOW_DAYS, CANOAS_MAX_DAYS_PER_RUN))
        start = end - timedelta(days=days - 1)
    if start > end:
        raise ValueError("Canoas start date must not be after end date")
    actual_days = (end - start).days + 1
    if actual_days > CANOAS_MAX_DAYS_PER_RUN:
        raise ValueError("Canoas date window exceeds configured day cap")
    return [start + timedelta(days=offset) for offset in range(actual_days)]


def _default_stats() -> dict[str, int]:
    return {
        "days_requested": 0,
        "days_fetched": 0,
        "daily_failures": 0,
        "records": 0,
        "publication_cap_reached": 0,
        "duplicates": 0,
        "policy_rejected": 0,
        "wordpress_lookups": 0,
        "wordpress_matches": 0,
        "wordpress_pages_fetched": 0,
        "wordpress_failures": 0,
        "wordpress_lookup_cap_reached": 0,
        "attachment_cap_reached": 0,
        "opportunities": 0,
        "candidate_cap_reached": 0,
        "errors": 0,
    }


def discover_opportunities(
    *,
    fetch_json: Callable[[str], Any] | None = None,
    fetch_html: Callable[[str], str] | None = None,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
    min_year: int | None = None,
    start_date: date | datetime | str | None = None,
    end_date: date | datetime | str | None = None,
    window_days: int | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover Canoas opportunities from a bounded local-date window."""
    stats = _default_stats()
    try:
        days = _window_dates(
            now=now or snapshot_at,
            start_date=start_date,
            end_date=end_date,
            window_days=window_days,
        )
    except Exception:
        stats["errors"] = 1
        stats["inventory_parse_failed"] = 1
        return stats, []
    stats["days_requested"] = len(days)
    fetch_j = fetch_json or _fetch_json
    fetch_h = fetch_html or _fetch_html
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for day_index, day in enumerate(days):
        try:
            payload = _coerce_json(_with_retry(build_diary_url(day), fetch_j))
            day_records = extract_publications(payload, default_day=day)
            stats["days_fetched"] += 1
        except Exception:
            stats["daily_failures"] += 1
            stats["errors"] += 1
            continue
        for record_index, record in enumerate(day_records):
            if len(records) >= max(0, CANOAS_MAX_PUBLICATIONS_PER_RUN):
                stats["publication_cap_reached"] = 1
                stats["inventory_parse_failed"] = 1
                break
            record_id = record["source_record_id"]
            if record_id in seen_ids:
                stats["duplicates"] += 1
                continue
            seen_ids.add(record_id)
            records.append(record)
            if len(records) >= max(0, CANOAS_MAX_PUBLICATIONS_PER_RUN):
                if (
                    record_index + 1 < len(day_records)
                    or day_index + 1 < len(days)
                ):
                    stats["publication_cap_reached"] = 1
                    stats["inventory_parse_failed"] = 1
                break
        if len(records) >= max(0, CANOAS_MAX_PUBLICATIONS_PER_RUN):
            break
    stats["records"] = len(records)
    if stats["daily_failures"] and not records:
        stats["inventory_parse_failed"] = 1
        return stats, []
    if stats["daily_failures"]:
        # A partial day can hide an open notice; preserve the data but fail the
        # source audit explicitly so operators do not treat it as complete.
        stats["inventory_parse_failed"] = 1

    opportunities: list[dict[str, Any]] = []
    wp_lookups = 0
    current = _aware_datetime(
        now or snapshot_at or datetime.now(timezone.utc)
    )
    for record in records:
        title = record.get("title", "")
        if min_year is not None:
            published = _parse_date(record.get("day"))
            if published and published.year < min_year:
                stats["policy_rejected"] += 1
                continue
        if _policy_reason(title) is not None:
            stats["policy_rejected"] += 1
            continue
        wordpress: dict[str, Any] | None = None
        if wp_lookups < CANOAS_MAX_WORDPRESS_LOOKUPS_PER_RUN:
            wp_lookups += 1
            stats["wordpress_lookups"] += 1
            try:
                search_payload = _coerce_json(
                    _with_retry(build_wordpress_search_url(title), fetch_j)
                )
                if not isinstance(search_payload, list):
                    raise ValueError("Canoas WordPress search must return a list")
                candidates = search_payload
                matched = match_wordpress_record(candidates, record)
                if matched is not None:
                    stats["wordpress_matches"] += 1
                    page_url = _clean_text(matched.get("link"))
                    if page_url:
                        wordpress = extract_wordpress_page(
                            _with_retry(page_url, fetch_h), page_url
                        )
                        modified_gmt = _clean_text(matched.get("modified_gmt"))
                        wordpress["modified"] = (
                            f"{modified_gmt}Z"
                            if modified_gmt
                            else matched.get("modified")
                        )
                        if wordpress.get("attachment_cap_reached"):
                            stats["attachment_cap_reached"] = 1
                            stats["inventory_parse_failed"] = 1
                        stats["wordpress_pages_fetched"] += 1
                    else:
                        raise ValueError("Canoas WordPress match has no page URL")
            except Exception:
                stats["wordpress_failures"] += 1
                stats["errors"] += 1
                stats["inventory_parse_failed"] = 1
        else:
            stats["wordpress_lookup_cap_reached"] = 1
            stats["inventory_parse_failed"] = 1
        opportunity = parse_canoas_opportunity(
            record, wordpress=wordpress, snapshot_at=snapshot_at or current, now=current
        )
        if opportunity is None:
            stats["policy_rejected"] += 1
            continue
        opportunities.append(opportunity)
        if len(opportunities) >= CANOAS_MAX_OPPORTUNITIES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            stats["inventory_parse_failed"] = 1
            break
    stats["opportunities"] = len(opportunities)
    return stats, opportunities


__all__ = [
    "CANOAS_API_BASE_URL",
    "CANOAS_DIARY_BY_DAY_URL",
    "CANOAS_DIARY_URL_TEMPLATE",
    "CANOAS_PUBLICATION_FILE_URL_TEMPLATE",
    "CANOAS_TIMEZONE",
    "SOURCE_KEY",
    "build_diary_url",
    "build_wordpress_search_url",
    "canonical_url",
    "discover_opportunities",
    "extract_application_deadline",
    "extract_publications",
    "extract_wordpress_page",
    "is_likely_opportunity",
    "match_wordpress_record",
    "normalize_html",
    "parse_canoas_opportunity",
    "record_to_opportunity",
]
