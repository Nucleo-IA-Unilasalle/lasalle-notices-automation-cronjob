"""Structured IBAMA opportunity discovery.

IBAMA publishes calls through several Plone pages rather than a single API.
This module deliberately uses the editorial bodies and the official RSS feeds
as an inventory, then fetches the linked detail pages with the shared safe GET
transport.  A detail page is the canonical opportunity URL; files linked from
that page are documents belonging to the same opportunity.

The source is intentionally conservative.  Results, administrative
decisions, notifications, firefighting calls, ordinary procurement, and news
without call evidence are not opportunities.  A parser or transport failure
is reported in the returned stats instead of looking like a healthy empty
inventory.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
import sys
import unicodedata
from collections import OrderedDict
from datetime import datetime, time, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from scraper_transport import fetch_html_with_retry


SOURCE_KEY = "ibama"
IBAMA_SOURCE_KEY = SOURCE_KEY
IBAMA_CHAMAMENTOS_URL = (
    "https://www.gov.br/ibama/pt-br/acesso-a-informacao/"
    "editais-e-convites/chamamentos-publicos/chamamentos-publicos"
)
IBAMA_EDITAIS_URL = (
    "https://www.gov.br/ibama/pt-br/acesso-a-informacao/"
    "editais-e-convites/editais-e-convites"
)
IBAMA_NOTAS_URL = "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/"
IBAMA_CHAMAMENTOS_RSS_URL = (
    "https://www.gov.br/ibama/pt-br/acesso-a-informacao/"
    "editais-e-convites/chamamentos-publicos/RSS"
)
IBAMA_NOTAS_RSS_URL = "https://www.gov.br/ibama/pt-br/assuntos/notas/2026/RSS"

# Compatibility aliases make the source constants easy to discover in audit
# tooling and keep the URLs in one place.
IBAMA_CHAMAMENTOS_LISTING_URL = IBAMA_CHAMAMENTOS_URL
IBAMA_EDITAIS_LISTING_URL = IBAMA_EDITAIS_URL
IBAMA_NOTAS_LISTING_URL = IBAMA_NOTAS_URL

IBAMA_MIN_NOTICE_YEAR = int(os.environ.get("IBAMA_MIN_NOTICE_YEAR", "2026"))
IBAMA_MAX_OPPORTUNITIES_PER_RUN = int(
    os.environ.get("IBAMA_MAX_OPPORTUNITIES_PER_RUN", "40")
)
IBAMA_MAX_DETAILS_PER_RUN = int(
    os.environ.get("IBAMA_MAX_DETAILS_PER_RUN", "60")
)
IBAMA_MAX_LISTING_RECORDS = int(
    os.environ.get("IBAMA_MAX_LISTING_RECORDS", "250")
)
IBAMA_MAX_RSS_ITEMS = int(os.environ.get("IBAMA_MAX_RSS_ITEMS", "250"))
IBAMA_MAX_DOCUMENTS_PER_OPPORTUNITY = int(
    os.environ.get("IBAMA_MAX_DOCUMENTS_PER_OPPORTUNITY", "20")
)
IBAMA_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("IBAMA_FETCH_TIMEOUT_SECONDS", "30")
)
IBAMA_FETCH_MAX_ATTEMPTS = int(
    os.environ.get("IBAMA_FETCH_MAX_ATTEMPTS", "3")
)
IBAMA_FETCH_BACKOFF_SECONDS = float(
    os.environ.get("IBAMA_FETCH_BACKOFF_SECONDS", "2")
)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
UTC = timezone.utc

_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-]((?:19|20)\d{2}))?(?!\d)"
)
_PT_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+de\s+"
    r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)"
    r"(?:\s+de\s+((?:19|20)\d{2}))?(?!\d)",
    re.I,
)
_MONTH_NUMBERS = {
    month: number
    for number, month in enumerate(
        (
            "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        ),
        start=1,
    )
}
_ISO_RE = re.compile(
    r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{1,2}):?(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:?\d{2})?)?\b"
)
_TIME_RE = re.compile(r"\b(\d{1,2})(?:[:h](\d{2}))?\s*h?\b", re.I)
_EDICT_NUMBERED_RE = re.compile(
    r"\b(?:edital|chamamento|chamada)\b[^\d\n]{0,60}"
    r"(?:n[º°]|n[uú]mero)\s*([0-9]{1,5}(?:\s*[/.-]\s*[0-9]{2,4})?)",
    re.I,
)
_EDICT_DIRECT_RE = re.compile(
    r"\b(?:edital|chamamento|chamada)[\s:.-]+"
    r"([0-9]{1,5}(?:\s*[/.-]\s*[0-9]{2,4})?)",
    re.I,
)
_PROCESS_RE = re.compile(
    r"\bprocesso(?:\s+(?:seletivo|administrativo|sei|n[ºo°]?))?\s*"
    r"(?:n[ºo°]?\s*)?"
    r"([0-9][0-9./-]{3,})",
    re.I,
)

_SUPPORTED_EXTENSIONS = OrderedDict(
    (
        (".pdf", ("pdf", "application/pdf")),
        (".zip", ("zip", "application/zip")),
        (
            ".docx",
            (
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
        # Repo A's coordinated contract represents spreadsheet formats as
        # ``other`` while preserving their exact MIME type and filename.
        (".ods", ("other", "application/vnd.oasis.opendocument.spreadsheet")),
    )
)

_RELATED_TERMS = re.compile(
    r"\b(retific(?:acao|acoes|a|ado|ada|ados|adas)|erratas?|adendos?|resultados?|"
    r"atas?|decis(?:ao|oes)|homologac(?:ao|oes)|notificac(?:ao|oes)|"
    r"intimac(?:ao|oes)|embargos?|classificac(?:ao|oes)|anexos?|"
    r"manual|modelo|formul[aá]rio|perguntas\s+e\s+respostas?|"
    r"termo\s+de\s+(?:refer[eê]ncia|ades[aã]o)|declara(?:c|ç)(?:a|ã)o)\b",
    re.I,
)
_OUT_OF_SCOPE_TERMS = re.compile(
    r"\b(resultados?|atas?|decis(?:ao|oes)|homologac(?:ao|oes)|notificac(?:ao|oes)|"
    r"intimac(?:ao|oes)|embargos?|concursos?|brigadistas?|brigadas?|doac(?:ao|oes)|"
    r"leiloes?|locac(?:ao|oes)|licitac(?:ao|oes)|pregoes?|"
    r"dispensas?|contratac(?:ao|oes)|compras?|aviso\s+de\s+contratac(?:ao|oes)|"
    r"fun(?:c|ç)(?:a|ã)o\s+comissionada|for(?:c|ç)a\s+de\s+trabalho|"
    r"sele(?:c|ç)(?:a|ã)o\s+de\s+servidor|not[ií]cia\s+sem\s+edital)\b",
    re.I,
)
_POSITIVE_TERMS = re.compile(
    r"\b(edital|chamamento|chamada|credencia(?:mento|r)|projetos?|"
    r"recupera(?:c|ç)(?:a|ã)o|organiza(?:c|ç)(?:a|ã)o\s+da\s+sociedade\s+civil|"
    r"\bosc\b|sociedade\s+cooperativa|consulta\s+p[uú]blica|"
    r"manifesta(?:c|ç)(?:a|ã)o\s+de\s+interesse|propostas?|inscri(?:c|ç)(?:o|õ)es?)\b",
    re.I,
)
_GENERIC_NEWS_TERMS = re.compile(
    r"\b(webin[aá]rio|balan(?:c|ç)o|nota\s+de\s+pesar|expediente|"
    r"indisponibilidade|golpe|homenagem|semin[aá]rio|evento)\b",
    re.I,
)
_EXCLUDED_ADMINISTRATIVE_TERMS = re.compile(
    r"\b(notificac(?:ao|oes)|intimac(?:ao|oes)|embargos?)\b", re.I
)
_PNCP_RE = re.compile(
    r"\bpncp\b|(?:n[uú]mero|identificador)\s+de\s+controle\s+pncp|"
    r"\b\d{14}-\d-\d{6}/\d{4}\b",
    re.I,
)


def _fold(value: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", value).casefold()
        if not unicodedata.combining(ch)
    )


def canonical_url(url: str) -> str:
    """Canonicalize a Gov.br page while retaining the functional URL shape."""
    parsed = urlsplit(html_lib.unescape(str(url).strip()))
    path = parsed.path or "/"
    # Plone adds /view to links in related-content widgets.  The underlying
    # object URL is stable and is the canonical detail page.
    if path.lower().endswith("/view"):
        path = path[:-5]
    # Some Plone file links use /@@download/file.  Remove that suffix only
    # when the preceding path already identifies a file; otherwise the
    # download endpoint is the only known functional URL and is preserved.
    marker = "/@@download/file"
    if path.lower().endswith(marker):
        base = path[: -len(marker)]
        if re.search(r"\.[a-z0-9]{2,5}$", base, re.I):
            path = base
    path = re.sub(r"/{2,}", "/", path)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, "")
    )


def normalize_document_url(url: str) -> str:
    """Return a stable file URL without destroying its source URL."""
    return canonical_url(url)


def _source_url_fields(url: str) -> tuple[str, str]:
    original = html_lib.unescape(str(url).strip())
    return normalize_document_url(original), original


def _year_from_url(url: str) -> int | None:
    years = [int(match.group(1)) for match in _YEAR_RE.finditer(url)]
    return max(years) if years else None


def _year_from_text(text: str) -> int | None:
    years = [int(match.group(1)) for match in _YEAR_RE.finditer(text)]
    return max(years) if years else None


def _iso(value: Any, *, default_year: int | None = None) -> str | None:
    """Parse an ISO or Portuguese Gov.br date into a timezone-aware ISO string."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", html_lib.unescape(str(value))).strip()
    if not text:
        return None
    iso_match = _ISO_RE.search(text)
    if iso_match:
        year, month, day = map(int, iso_match.group(1, 2, 3))
        hour = int(iso_match.group(4) or 0)
        minute = int(iso_match.group(5) or 0)
        second = int(iso_match.group(6) or 0)
        offset = iso_match.group(7)
        try:
            if offset == "Z":
                tz = UTC
            elif offset:
                tz = datetime.fromisoformat(
                    f"2000-01-01T00:00:00{offset.replace('Z', '+00:00')}"
                ).tzinfo
            else:
                tz = SAO_PAULO
            return datetime(year, month, day, hour, minute, second, tzinfo=tz).isoformat()
        except (TypeError, ValueError):
            return None
    date_match = _DATE_RE.search(text)
    pt_date_match = _PT_DATE_RE.search(text) if not date_match else None
    if date_match:
        day, month = int(date_match.group(1)), int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else default_year
    elif pt_date_match:
        day = int(pt_date_match.group(1))
        month = _MONTH_NUMBERS[_fold(pt_date_match.group(2))]
        year = (
            int(pt_date_match.group(3))
            if pt_date_match.group(3)
            else default_year
        )
    else:
        return None
    if year is None:
        return None
    hour = 0
    minute = 0
    time_match = re.search(r"\b(\d{1,2})[h:](\d{2})\b|\b(\d{1,2})h\b", text)
    if time_match:
        hour = int(time_match.group(1) or time_match.group(3))
        minute = int(time_match.group(2) or 0)
    try:
        return datetime(year, month, day, hour, minute, tzinfo=SAO_PAULO).isoformat()
    except ValueError:
        return None


def _date_value(
    value: str,
    *,
    default_year: int | None,
    end_of_day: bool = False,
    explicit_time: bool = False,
) -> str | None:
    parsed = _iso(value, default_year=default_year)
    if parsed is None:
        return None
    current = datetime.fromisoformat(parsed)
    if end_of_day and not explicit_time:
        current = current.replace(hour=23, minute=59, second=59)
    return current.isoformat()


def _extract_date_tokens(text: str, *, default_year: int | None) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for regex in (_DATE_RE, _PT_DATE_RE):
        for match in regex.finditer(text):
            raw = match.group(0)
            value = _iso(raw, default_year=default_year)
            if value is not None:
                result.append((value, match.start()))
    return sorted(result, key=lambda item: item[1])


def _extract_schedule(
    text: str, *, default_year: int | None
) -> tuple[str | None, str | None]:
    """Extract proposal opening and closing dates from schedule prose."""
    folded = _fold(text)
    keyword_re = re.compile(
        r"\b(propostas?|inscricoes?|recebimento|submiss(?:a|ã)o|envio|"
        r"candidaturas?|manifestac(?:a|ã)o|contribui(?:r|cao|coes)|"
        r"participac(?:ao|oes)|periodo|prazo|encerramento)\b", re.I,
    )
    clauses: list[tuple[str, int]] = []
    for match in re.finditer(r"[^\n]+", text):
        clause = match.group(0).strip()
        if keyword_re.search(_fold(clause)):
            clauses.append((clause, match.start()))
    if not clauses:
        clauses = [
            (text[match.start() : match.end()], match.start())
            for match in re.finditer(
                r"(?:propostas?|inscricoes?|recebimento|submiss(?:a|ã)o|"
                r"envio|candidaturas?|manifestac(?:a|ã)o|contribui(?:r|cao|coes)|"
                r"participac(?:ao|oes)|periodo|prazo|encerramento).{0,160}",
                folded,
                re.I | re.S,
            )
        ]
    ranges: list[tuple[str | None, str | None, int, bool, bool]] = []
    for clause, position in clauses:
        tokens = _extract_date_tokens(clause, default_year=default_year)
        if not tokens:
            continue
        # A date range's final date is the deadline; for a single date use the
        # end of that day unless the source supplied a time.
        first = tokens[0][0]
        last = tokens[-1][0]
        range_start = first if len(tokens) > 1 and re.search(
            r"\b(?:de|entre|a\s+partir)\b", _fold(clause)
        ) else None
        explicit_time = bool(re.search(r"\d{1,2}(?:h|:\d{2})", clause, re.I))
        end = _date_value(last, default_year=default_year, end_of_day=True, explicit_time=explicit_time)
        if explicit_time and end:
            date_matches = list(_DATE_RE.finditer(clause))
            if date_matches:
                time_match = re.search(
                    r"(?:às|as|ate|até)?\s*(\d{1,2})(?:[:h](\d{2}))?\s*h?\b",
                    clause[date_matches[-1].end() :],
                    re.I,
                )
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2) or 0)
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        end = datetime.fromisoformat(end).replace(
                            hour=hour, minute=minute, second=0
                        ).isoformat()
        proposal_clause = bool(re.search(
            r"\b(propostas|inscricoes?|recebimento|submiss(?:a|ã)o|envio|"
            r"candidaturas?|contribui(?:r|cao|coes)|participac(?:ao|oes))\b",
            _fold(clause), re.I,
        ))
        deadline_clause = bool(re.search(
            r"\b(?:ate|periodo|prazo|encerramento)\b|\bde\b.{0,100}\ba\b",
            _fold(clause),
            re.I,
        ))
        ranges.append((range_start, end, position, proposal_clause, deadline_clause))
    if not ranges:
        return None, None
    # Prefer a proposal/submission clause over a generic publication clause,
    # such as a later predicted-result date.
    selected = max(ranges, key=lambda item: (item[3], item[4], item[2]))
    return selected[0], selected[1]


def _content_root(soup: BeautifulSoup) -> Tag | None:
    for selector in (
        "#content-core #parent-fieldname-text",
        "#content-core",
        "article [property='rnews:articleBody']",
        "article",
        "main",
        "#content",
    ):
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return None


def _clean_text(node: Tag | None) -> str:
    if not isinstance(node, Tag):
        return ""
    for unwanted in node.select("script, style, nav, footer, .conteudo-relacionado"):
        unwanted.extract()
    paragraphs: list[str] = []
    for child in node.find_all(["p", "li", "h2", "h3", "h4"], recursive=True):
        text = re.sub(r"\s+", " ", child.get_text(" ", strip=True)).strip()
        if text and text not in paragraphs:
            paragraphs.append(text)
    if paragraphs:
        return "\n\n".join(paragraphs)
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _is_supported_file(url: str, label: str = "") -> tuple[str, str] | None:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    for extension, descriptor in _SUPPORTED_EXTENSIONS.items():
        if path.endswith(extension):
            return descriptor
    # A Plone download endpoint can omit the extension.  Use the anchor text
    # as a constrained hint, never as a reason to fetch an arbitrary link.
    if path.lower().endswith("/@@download/file"):
        evidence = _fold(f"{path} {label}")
        if ".pdf" in evidence or re.search(r"\bpdf\b", evidence):
            return _SUPPORTED_EXTENSIONS[".pdf"]
        if ".zip" in evidence or re.search(r"\bzip\b", evidence):
            return _SUPPORTED_EXTENSIONS[".zip"]
        if ".docx" in evidence or re.search(r"\bdocx\b", evidence):
            return _SUPPORTED_EXTENSIONS[".docx"]
        if ".ods" in evidence or re.search(r"\bods\b|planilha", evidence):
            return _SUPPORTED_EXTENSIONS[".ods"]
    return None


def _filename(url: str, label: str, kind: str) -> str:
    name = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if name.lower() in {"file", "download"} or "." not in name:
        name = re.sub(r"[^a-z0-9]+", "-", _fold(label)).strip("-") or "documento"
        extension = "ods" if kind == "other" else kind
        name = f"{name}.{extension}"
    return name


def _document_descriptor(url: str, label: str, *, related: bool) -> dict[str, Any] | None:
    normalized, original = _source_url_fields(url)
    kind_mime = _is_supported_file(normalized, label) or _is_supported_file(original, label)
    if kind_mime is None:
        return None
    kind, mime = kind_mime
    evidence = _fold(f"{label} {original}")
    if _EXCLUDED_ADMINISTRATIVE_TERMS.search(evidence):
        return None
    principal_hint = bool(
        re.search(r"\b(edital|chamamento|chamada|regulamento|processo)\b", evidence)
    ) and not related
    document_id = "ibama:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    descriptor: dict[str, Any] = {
        "source_document_id": document_id,
        "document_kind": kind,
        "url": normalized,
        "filename": _filename(normalized, label, kind),
        "mime_type": mime,
        "is_principal": principal_hint,
        "is_renderable": False,
    }
    return descriptor


def _extract_documents(
    root: Tag | None, detail_url: str
) -> list[dict[str, Any]]:
    if not isinstance(root, Tag):
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in root.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        resolved = urljoin(detail_url, html_lib.unescape(href.strip()))
        label = link.get_text(" ", strip=True)
        descriptor = _document_descriptor(resolved, label, related=False)
        if descriptor is None:
            continue
        key = descriptor["url"]
        if key in seen:
            continue
        seen.add(key)
        evidence = _fold(f"{label} {resolved}")
        descriptor["is_related"] = bool(_RELATED_TERMS.search(evidence))
        if descriptor["is_related"]:
            descriptor["is_principal"] = False
        elif not descriptor["is_principal"] and not found:
            # If a page exposes only a generically named official file, keep
            # it as the principal attachment rather than losing the call.
            descriptor["is_principal"] = True
        found.append(descriptor)
    return found


def _extract_meta_date(soup: BeautifulSoup, selector: str, *, default_year: int | None) -> str | None:
    node = soup.select_one(selector)
    if not isinstance(node, Tag):
        return None
    value = node.get("content") or node.get("datetime") or node.get_text(" ", strip=True)
    return _iso(value, default_year=default_year)


def _extract_detail_dates(soup: BeautifulSoup, text: str, *, default_year: int | None) -> tuple[str | None, str | None]:
    published = (
        _extract_meta_date(soup, ".documentPublished .value", default_year=default_year)
        or _extract_meta_date(soup, "meta[property='article:published_time']", default_year=default_year)
        or _extract_meta_date(soup, "meta[name='DC.date.created']", default_year=default_year)
    )
    modified = (
        _extract_meta_date(soup, ".documentModified .value", default_year=default_year)
        or _extract_meta_date(soup, "meta[property='article:modified_time']", default_year=default_year)
        or _extract_meta_date(soup, "meta[name='DC.date.modified']", default_year=default_year)
    )
    if published is None:
        json_dates = re.findall(r'"datePublished"\s*:\s*"([^"]+)"', str(soup))
        if json_dates:
            published = _iso(json_dates[0], default_year=default_year)
    if modified is None:
        json_dates = re.findall(r'"dateModified"\s*:\s*"([^"]+)"', str(soup))
        if json_dates:
            modified = _iso(json_dates[0], default_year=default_year)
    if published is None:
        match = re.search(r"publicad[oa]\s+em\s+([^.;\n]+)", _fold(text), re.I)
        if match:
            published = _iso(match.group(1), default_year=default_year)
    return published, modified


def _extract_title(soup: BeautifulSoup, fallback: str) -> str:
    for selector in (
        "h1.documentFirstHeading",
        "h1[property='rnews:headline']",
        "#content h1",
        "h1",
    ):
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            title = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if title:
                return title
    return re.sub(r"\s+", " ", fallback).strip()


def _all_identity_tokens(text: str) -> list[tuple[str, int]]:
    matches: list[tuple[str, int]] = []
    for regex in (_PROCESS_RE, _EDICT_NUMBERED_RE, _EDICT_DIRECT_RE):
        for match in regex.finditer(text):
            raw = re.sub(r"\s+", "", match.group(1)).replace(".", "-")
            raw = re.sub(r"[-/]+", "-", raw).strip("-")
            if raw:
                prefix = "processo" if regex is _PROCESS_RE else "edital"
                matches.append((f"{prefix}-{raw}", match.start()))
    return sorted(matches, key=lambda item: item[1])


def source_record_id(title: str, canonical_detail_url: str, description: str = "") -> str:
    """Return the stable identity preferred by source numbers/process IDs."""
    combined = f"{title} {description}"
    tokens = _all_identity_tokens(combined)
    if not tokens:
        tokens = _all_identity_tokens(canonical_detail_url)
    related = bool(_RELATED_TERMS.search(_fold(title)))
    if tokens:
        # Retification pages frequently name their own number first and the
        # principal edital last (e.g. 26 retifies 22).  Attach to the latter.
        token = tokens[-1][0] if related and len(tokens) > 1 else tokens[0][0]
        return token
    parsed = urlsplit(canonical_url(canonical_detail_url))
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    slug_number = re.search(
        r"\b(?:edital|chamamento|chamada)\b.{0,100}?-no-(\d{1,5})-(\d{4})(?:-|$)",
        _fold(slug),
    )
    if slug_number:
        return f"edital-{slug_number.group(1)}-{slug_number.group(2)}"
    return "slug-" + (slug or hashlib.sha256(canonical_detail_url.encode()).hexdigest()[:20])


def _is_related_page(title: str, url: str, description: str = "") -> bool:
    del description
    # Principal pages commonly state in their opening paragraph that the call
    # was retified. Only the page title/slug can classify the page as related.
    return bool(_RELATED_TERMS.search(_fold(f"{title} {url}")))


def _is_pncp(text: str, url: str = "") -> bool:
    return bool(_PNCP_RE.search(_fold(f"{text} {url}")))


def _scope_disposition(title: str, url: str, description: str = "") -> str:
    """Return ``eligible``, ``related``, ``pncp`` or an exclusion reason."""
    evidence = f"{title} {url}"
    if _is_pncp(f"{evidence} {description}"):
        return "pncp"
    lead = description.lstrip().split("\n\n", 1)[0][:300]
    lead_evidence = f"{evidence} {lead}"
    if _EXCLUDED_ADMINISTRATIVE_TERMS.search(_fold(lead_evidence)):
        return "out_of_scope"
    if _is_related_page(title, url, description):
        return "related"
    folded = _fold(evidence)
    if _OUT_OF_SCOPE_TERMS.search(_fold(lead_evidence)):
        return "out_of_scope"
    if not _POSITIVE_TERMS.search(folded):
        # Detail prose can establish an opportunity when the listing title is
        # terse, but generic annual news still needs a call signal.
        if not _POSITIVE_TERMS.search(_fold(description)):
            return "out_of_scope"
    return "eligible"


def _detail_is_call(title: str, description: str, documents: list[dict[str, Any]]) -> bool:
    evidence = _fold(f"{title} {description}")
    if not _POSITIVE_TERMS.search(evidence):
        return False
    # Annual-notes pages often advertise webinars or seminars about a call;
    # without an owned attachment they are news, not a second opportunity.
    if not documents and _GENERIC_NEWS_TERMS.search(evidence):
        return False
    if documents:
        return True
    return bool(
        re.search(
            r"\b(edital|chamamento|chamada|credencia|propostas?|inscricoes?|"
            r"manifestac(?:a|ã)o|prazo)\b",
            evidence,
        )
    )


def _status(text: str, deadline: str | None, now: datetime | None) -> str:
    folded = _fold(text)
    if re.search(r"\b(cancelad|anulad|suspens)", folded):
        return "cancelled" if re.search(r"cancelad|anulad", folded) else "suspended"
    if re.search(r"\b(encerrad|finalizad|fechad)", folded):
        return "closed"
    if deadline:
        current = now or datetime.now(SAO_PAULO)
        if current.tzinfo is None:
            current = current.replace(tzinfo=SAO_PAULO)
        try:
            return "open" if datetime.fromisoformat(deadline) >= current else "closed"
        except ValueError:
            pass
    if re.search(r"\b(abert|vigent|recebendo|prorrogad|disponivel)", folded):
        return "open"
    return "unknown"


def _opportunity_type(title: str, description: str) -> str:
    del title, description
    # Repo A's coordinated enum is funding/procurement/consultancy/other.
    # IBAMA's mixed public calls and consultations are not ordinary procurement.
    return "other"


def _build_markdown(
    *,
    title: str,
    canonical: str,
    description: str,
    status: str,
    published: str | None,
    modified: str | None,
    opens: str | None,
    deadline: str | None,
    documents: list[dict[str, Any]],
) -> str:
    lines = [f"# {title}", "", "## Fonte oficial", "", canonical]
    fields = (
        ("Descricao", description),
        ("Situacao", status),
        ("Publicado em", published),
        ("Atualizado em", modified),
        ("Abertura de propostas", opens),
        ("Prazo final", deadline),
    )
    for label, value in fields:
        if value:
            lines.extend(("", f"## {label}", "", value))
    if documents:
        lines.extend(("", "## Documentos oficiais", ""))
        for document in documents:
            relation = "relacionado" if document.get("is_related") else "principal"
            label = document.get("title") or document.get("filename") or document["url"]
            lines.append(f"- {label} ({document['document_kind']}, {relation}): {document['url']}")
    return "\n".join(lines).strip()


def parse_detail(
    detail_url: str,
    detail_html: str,
    *,
    fallback_title: str = "",
    fallback_published_at: str | None = None,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Parse one official detail page into a structured opportunity."""
    soup = BeautifulSoup(detail_html, "html.parser")
    root = _content_root(soup)
    if not isinstance(root, Tag):
        raise ValueError("IBAMA detail content area not found")
    title = _extract_title(soup, fallback_title)
    if not title:
        raise ValueError("IBAMA detail title not found")
    description = _clean_text(root)
    documents = _extract_documents(root, detail_url)
    canonical = canonical_url(detail_url)
    # The source's title and body are authoritative for identity and scope.
    disposition = _scope_disposition(title, canonical, description)
    if disposition in {"pncp", "out_of_scope"}:
        return None
    published, modified = _extract_detail_dates(
        soup, description, default_year=_year_from_url(canonical)
    )
    published = published or fallback_published_at
    default_year = _year_from_url(canonical) or (
        int(published[:4]) if published else None
    )
    opens, deadline = _extract_schedule(description, default_year=default_year)
    status = _status(f"{title}\n{description}", deadline, now)
    if not _detail_is_call(title, description, documents):
        return None
    record_id = source_record_id(title, canonical, description)
    snapshot = snapshot_at or datetime.now(UTC)
    if snapshot.tzinfo is None:
        snapshot = snapshot.replace(tzinfo=UTC)
    markdown = _build_markdown(
        title=title,
        canonical=canonical,
        description=description,
        status=status,
        published=published,
        modified=modified,
        opens=opens,
        deadline=deadline,
        documents=documents,
    )
    return {
        "source_key": SOURCE_KEY,
        "source_record_id": record_id,
        "source_kind": "web",
        "opportunity_type": _opportunity_type(title, description),
        "canonical_url": canonical,
        "title": title,
        "description": description or None,
        "authoritative_status": status,
        "source_published_at": published,
        "source_updated_at": modified,
        "proposal_opens_at": opens,
        "application_deadline": deadline,
        "source_snapshot_at": snapshot.astimezone(UTC).isoformat(),
        "source_markdown": markdown,
        "source_content_hash": "",
        "documents": documents,
        "_related_page": disposition == "related",
    }


def _valid_page_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        (parsed.hostname or "").lower().rstrip(".") == "www.gov.br"
        and parsed.path.lower().startswith("/ibama/")
    )


def _record_seed(
    url: str,
    title: str,
    *,
    listing_url: str,
    published_at: str | None = None,
    direct_document: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    canonical = canonical_url(url)
    if not _valid_page_url(canonical) or canonical == canonical_url(listing_url):
        return None
    return {
        "url": canonical,
        "title": re.sub(r"\s+", " ", html_lib.unescape(title)).strip(),
        "listing_url": listing_url,
        "published_at": published_at,
        "documents": [direct_document] if direct_document else [],
    }


def extract_listing_records(
    listing_html: str,
    listing_url: str,
    *,
    min_year: int = IBAMA_MIN_NOTICE_YEAR,
) -> tuple[list[dict[str, Any]], bool]:
    """Extract detail/file links only from the official editorial listing body."""
    soup = BeautifulSoup(listing_html, "html.parser")
    if "notas/" in listing_url:
        roots = soup.select("ul.noticias.listagem-noticias-com-foto, ul.noticias")
    else:
        roots = soup.select("#content-core #parent-fieldname-text, #content-core")
    root = next((node for node in roots if isinstance(node, Tag)), None)
    if not isinstance(root, Tag):
        return [], False
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in root.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        resolved = canonical_url(urljoin(listing_url, html_lib.unescape(href.strip())))
        if not _valid_page_url(resolved) or resolved in seen:
            continue
        label = link.get_text(" ", strip=True)
        if not label:
            label = urlsplit(resolved).path.rstrip("/").rsplit("/", 1)[-1]
        record_year = _year_from_url(resolved) or _year_from_text(label)
        if record_year is not None and record_year < min_year:
            continue
        if resolved.lower().endswith(tuple(_SUPPORTED_EXTENSIONS)):
            descriptor = _document_descriptor(resolved, label, related=False)
            if descriptor is None:
                continue
            # A direct file on a listing is retained as an attachment of the
            # nearest detail identity only when it carries an explicit call id.
            title = label
            seed_url = listing_url
            parent = link.find_parent("li")
            if isinstance(parent, Tag):
                parent_link = parent.find("a", href=lambda value: isinstance(value, str) and not _is_supported_file(value))
                if isinstance(parent_link, Tag) and parent_link.get("href"):
                    seed_url = urljoin(listing_url, str(parent_link["href"]))
                    title = parent_link.get_text(" ", strip=True) or title
            seed = _record_seed(seed_url, title, listing_url=listing_url, direct_document=descriptor)
            if seed is not None:
                records.append(seed)
                seen.add(resolved)
            continue
        parsed = _record_seed(resolved, label, listing_url=listing_url)
        if parsed is None:
            continue
        # Skip links to parent indexes, RSS, image assets and navigation pages.
        path = urlsplit(resolved).path.lower()
        if path.endswith(("/rss", "/rss.xml", "/atom.xml")) or "/@@" in path:
            continue
        seen.add(resolved)
        records.append(parsed)
    return records, True


def parse_rss_records(
    rss_xml: str,
    rss_url: str,
    *,
    min_year: int = IBAMA_MIN_NOTICE_YEAR,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse RDF/RSS or Atom records without relying on a JS search endpoint."""
    soup = BeautifulSoup(rss_xml, "xml")
    nodes = soup.find_all(["item", "entry"])
    if not nodes:
        return [], False
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes[:IBAMA_MAX_RSS_ITEMS]:
        if not isinstance(node, Tag):
            continue
        link_node = node.find("link")
        href = None
        if isinstance(link_node, Tag):
            href = link_node.get("href") or link_node.get_text(" ", strip=True)
        href = href or node.get("rdf:about") or node.get("about")
        if not isinstance(href, str) or not href:
            continue
        url = canonical_url(urljoin(rss_url, html_lib.unescape(href.strip())))
        if not _valid_page_url(url) or url in seen:
            continue
        title_node = node.find("title")
        title = title_node.get_text(" ", strip=True) if isinstance(title_node, Tag) else ""
        date_node = node.find(["date", "published", "updated", "pubDate"])
        published = _iso(
            date_node.get_text(" ", strip=True) if isinstance(date_node, Tag) else None,
            default_year=_year_from_url(url),
        )
        record_year = _year_from_url(url) or _year_from_text(title)
        if record_year is not None and record_year < min_year:
            continue
        seed = _record_seed(url, title, listing_url=rss_url, published_at=published)
        if seed is not None:
            records.append(seed)
            seen.add(url)
    return records, True


def _rss_item_count(rss_xml: str) -> int:
    soup = BeautifulSoup(rss_xml, "xml")
    return len(soup.find_all(["item", "entry"]))


def _document_limit() -> int:
    # Repo A currently accepts at most 20 document descriptors per submission.
    return max(0, min(20, IBAMA_MAX_DOCUMENTS_PER_OPPORTUNITY))


def _merge_documents(target: dict[str, Any], source: dict[str, Any]) -> int:
    existing = {document.get("url") for document in target.get("documents", [])}
    added = 0
    for document in source.get("documents", []):
        if document.get("url") not in existing:
            target.setdefault("documents", []).append(document)
            existing.add(document.get("url"))
            added += 1
    # A richer principal detail should win, but preserve the canonical URL of
    # the first non-related page chosen by the deterministic source ranking.
    for key in (
        "description",
        "source_published_at",
        "source_updated_at",
        "proposal_opens_at",
        "application_deadline",
    ):
        if not target.get(key) and source.get(key):
            target[key] = source[key]
    return added


def _source_rank(url: str) -> tuple[int]:
    path = urlsplit(url).path
    if "/chamamentos-publicos/" in path:
        rank = 0
    elif "/editais-e-convites/" in path:
        rank = 1
    elif "/assuntos/notas/" in path:
        rank = 2
    else:
        rank = 3
    # Keep the original inventory order for ties.  This makes the canonical
    # page stable when an annual-notes index repeats a longer chamamentos URL.
    return (rank,)


def _fetcher(fetch_html: Callable[[str], str] | None) -> Callable[[str], str]:
    if fetch_html is not None:
        return fetch_html
    return lambda url: fetch_html_with_retry(
        url,
        timeout=IBAMA_FETCH_TIMEOUT_SECONDS,
        max_attempts=IBAMA_FETCH_MAX_ATTEMPTS,
        backoff_seconds=IBAMA_FETCH_BACKOFF_SECONDS,
        allowed_status_codes=(401, 403, 404, 410),
    )


def discover_opportunities(
    *,
    fetch_html: Callable[[str], str] | None = None,
    fetch_rss: Callable[[str], str] | None = None,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
    min_year: int | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover bounded, deduplicated IBAMA opportunities from official feeds."""
    year_guard = IBAMA_MIN_NOTICE_YEAR if min_year is None else min_year
    fetch = _fetcher(fetch_html)
    fetch_feed = fetch_rss or fetch
    stats: dict[str, int] = {
        "listings_fetched": 0,
        "rss_fetched": 0,
        "records": 0,
        "details_fetched": 0,
        "opportunities": 0,
        "errors": 0,
        "policy_rejected": 0,
        "pncp_rejected": 0,
        "related_documents": 0,
        "retifications_merged": 0,
        "unsupported_documents": 0,
        "inventory_parse_failed": 0,
        "partial_inventory": 0,
        "cap_reached": 0,
        "candidate_cap_reached": 0,
        "document_cap_reached": 0,
    }
    seeds_by_url: OrderedDict[str, dict[str, Any]] = OrderedDict()
    feed_urls = (
        (IBAMA_CHAMAMENTOS_URL, "listing"),
        (IBAMA_EDITAIS_URL, "listing"),
        (IBAMA_NOTAS_URL, "listing"),
        (IBAMA_CHAMAMENTOS_RSS_URL, "rss"),
        (IBAMA_NOTAS_RSS_URL, "rss"),
    )
    for feed_url, feed_kind in feed_urls:
        try:
            raw = fetch_feed(feed_url) if feed_kind == "rss" else fetch(feed_url)
            if feed_kind == "rss":
                if _rss_item_count(raw) > IBAMA_MAX_RSS_ITEMS:
                    stats["cap_reached"] = 1
                    stats["candidate_cap_reached"] = 1
                    stats["partial_inventory"] = 1
                records, present = parse_rss_records(raw, feed_url, min_year=year_guard)
                stats["rss_fetched"] += 1
            else:
                records, present = extract_listing_records(raw, feed_url, min_year=year_guard)
                stats["listings_fetched"] += 1
            if not present:
                stats["inventory_parse_failed"] = 1
                stats["partial_inventory"] = 1
                stats["errors"] += 1
                continue
            for record in records:
                if len(seeds_by_url) >= IBAMA_MAX_LISTING_RECORDS:
                    stats["cap_reached"] = 1
                    stats["candidate_cap_reached"] = 1
                    stats["partial_inventory"] = 1
                    break
                existing = seeds_by_url.get(record["url"])
                if existing is None:
                    seeds_by_url[record["url"]] = record
                else:
                    if not existing.get("title") and record.get("title"):
                        existing["title"] = record["title"]
                    if not existing.get("published_at") and record.get("published_at"):
                        existing["published_at"] = record["published_at"]
                    existing["documents"] = existing.get("documents", []) + record.get("documents", [])
        except Exception as exc:
            print(f"warning: IBAMA feed failed {feed_url}: {exc}", file=sys.stderr)
            stats["errors"] += 1
            stats["inventory_parse_failed"] = 1
            stats["partial_inventory"] = 1
    stats["records"] = len(seeds_by_url)
    if not seeds_by_url:
        stats["inventory_parse_failed"] = 1
        stats["opportunities"] = 0
        return stats, []

    parsed_pages: list[dict[str, Any]] = []
    related_pages: list[dict[str, Any]] = []
    details_seen: set[str] = set()
    for seed in seeds_by_url.values():
        disposition = _scope_disposition(seed["title"], seed["url"])
        if disposition == "pncp":
            stats["pncp_rejected"] += 1
            continue
        if disposition == "out_of_scope":
            stats["policy_rejected"] += 1
            continue
        if stats["details_fetched"] >= IBAMA_MAX_DETAILS_PER_RUN:
            stats["cap_reached"] = 1
            stats["candidate_cap_reached"] = 1
            stats["partial_inventory"] = 1
            break
        detail_url = seed["url"]
        if detail_url in details_seen:
            continue
        details_seen.add(detail_url)
        try:
            detail_html = fetch(detail_url)
            stats["details_fetched"] += 1
            parsed = parse_detail(
                detail_url,
                detail_html,
                fallback_title=seed.get("title", ""),
                fallback_published_at=seed.get("published_at"),
                snapshot_at=snapshot_at,
                now=now,
            )
        except Exception as exc:
            print(f"warning: IBAMA detail failed {detail_url}: {exc}", file=sys.stderr)
            stats["errors"] += 1
            stats["partial_inventory"] = 1
            continue
        if parsed is None:
            if _is_pncp(f"{seed['title']} {detail_url}"):
                stats["pncp_rejected"] += 1
            else:
                stats["policy_rejected"] += 1
            continue
        # Preserve direct documents discovered on a listing page.
        for document in seed.get("documents", []):
            if document.get("url") not in {item.get("url") for item in parsed["documents"]}:
                parsed["documents"].append(document)
        if parsed.pop("_related_page", False):
            related_pages.append(parsed)
        else:
            parsed_pages.append(parsed)

    if stats["cap_reached"]:
        stats["inventory_parse_failed"] = 1
    if stats["errors"]:
        stats["inventory_parse_failed"] = 1

    # Merge duplicate principal pages by deterministic source identity.
    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for page in sorted(parsed_pages, key=lambda item: _source_rank(item["canonical_url"])):
        identity = page["source_record_id"]
        current = merged.get(identity)
        if current is None:
            merged[identity] = page
        else:
            stats["retifications_merged"] += 1
            stats["related_documents"] += _merge_documents(current, page)
    for page in related_pages:
        identity = page["source_record_id"]
        target = merged.get(identity)
        if target is None:
            stats["policy_rejected"] += 1
            continue
        stats["retifications_merged"] += 1
        stats["related_documents"] += _merge_documents(target, page)
    opportunities = list(merged.values())
    for opportunity in opportunities:
        document_limit = _document_limit()
        if len(opportunity.get("documents", [])) > document_limit:
            opportunity["documents"] = opportunity["documents"][:document_limit]
            stats["document_cap_reached"] = 1
            stats["cap_reached"] = 1
            stats["candidate_cap_reached"] = 1
            stats["partial_inventory"] = 1
        for document in opportunity.get("documents", []):
            if document.get("document_kind") not in {
                descriptor[0] for descriptor in _SUPPORTED_EXTENSIONS.values()
            }:
                stats["unsupported_documents"] += 1
        opportunity["source_markdown"] = _build_markdown(
            title=opportunity["title"],
            canonical=opportunity["canonical_url"],
            description=opportunity.get("description") or "",
            status=opportunity.get("authoritative_status") or "unknown",
            published=opportunity.get("source_published_at"),
            modified=opportunity.get("source_updated_at"),
            opens=opportunity.get("proposal_opens_at"),
            deadline=opportunity.get("application_deadline"),
            documents=opportunity.get("documents", []),
        )
        for document in opportunity.get("documents", []):
            if document.pop("is_related", False):
                stats["related_documents"] += 1
    if len(opportunities) > IBAMA_MAX_OPPORTUNITIES_PER_RUN:
        opportunities = opportunities[:IBAMA_MAX_OPPORTUNITIES_PER_RUN]
        stats["cap_reached"] = 1
        stats["candidate_cap_reached"] = 1
        stats["partial_inventory"] = 1
        stats["inventory_parse_failed"] = 1
    stats["opportunities"] = len(opportunities)
    if stats["partial_inventory"]:
        stats["inventory_parse_failed"] = 1
    return stats, opportunities


def discover_candidates(**kwargs: Any) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Compatibility wrapper; IBAMA is structured and emits no PDF candidates."""
    del kwargs
    return {"inventory_parse_failed": 1, "opportunities": 0}, []


def main() -> int:
    """Audit-only CLI entry point; production submission belongs to orchestrator."""
    if not os.environ.get("DISCOVERY_AUDIT_DIR"):
        print("error: DISCOVERY_AUDIT_DIR is required for IBAMA audit", file=sys.stderr)
        return 2
    stats, opportunities = discover_opportunities()
    print(f"IBAMA discovery stats: {stats}")
    print(f"IBAMA opportunities discovered: {len(opportunities)}")
    return 1 if stats.get("inventory_parse_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
