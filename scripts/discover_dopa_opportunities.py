"""Structured opportunity discovery for Porto Alegre's official DOPA API.

The DOPA (Diario Oficial de Porto Alegre) API exposes a searchable list of
published contents and a JSON detail endpoint containing the authoritative HTML
and attachments.  This module deliberately treats one ``idConteudo`` as one
opportunity; a whole-edition PDF is never used as a candidate because it would
mix unrelated municipal acts.

The source is intentionally conservative.  It keeps recent executive notices
whose title identifies an edital/chamamento (or another public-selection call),
rejects post-publication acts such as results and errata, and drops ordinary
procurement notices already represented by PNCP.  These rules are deterministic
and are recorded in the source-fidelity inventory through the returned stats.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Comment, Tag

from scraper_transport import request_with_safe_redirects


DOPA_API_BASE_URL = (
    "https://apigateway.procempa.com.br/apiman-gateway/"
    "administracao-planejamento/dopa/1.1"
)
# Short aliases make the official API boundary obvious to callers and tests.
DOPA_BASE_URL = DOPA_API_BASE_URL
DOPA_SEARCH_URL = f"{DOPA_API_BASE_URL}/api/diarios/busca-avancada"
DOPA_API_URL = DOPA_SEARCH_URL
DOPA_DETAIL_BASE_URL = f"{DOPA_API_BASE_URL}/api/diarios/conteudo"
DOPA_DETAIL_URL_TEMPLATE = f"{DOPA_API_BASE_URL}/api/diarios/conteudo/{{id}}/detalhes"
DOPA_EXPORT_PDF_URL_TEMPLATE = (
    f"{DOPA_API_BASE_URL}/api/diarios/conteudo/{{id}}/exportar-pdf"
)

SOURCE_KEY = "dopa"
DOPA_ESCOPOS: tuple[str, ...] = ("executivo",)
DOPA_TIMEZONE = ZoneInfo("America/Sao_Paulo")
DOPA_API_HOST = "apigateway.procempa.com.br"
DOPA_ATTACHMENT_HOSTS = frozenset(
    {"dopaonlineupload.procempa.com.br", DOPA_API_HOST}
)

# Daily DOPA volume can approach 300 rows and a three-day response can exceed
# 400. Keep the rolling window and the explicit fail-loud client cap bounded.
DOPA_INCREMENTAL_WINDOW_DAYS = int(
    os.environ.get("DOPA_INCREMENTAL_WINDOW_DAYS", "3")
)
DOPA_WINDOW_DAYS = DOPA_INCREMENTAL_WINDOW_DAYS
DOPA_MAX_SEARCH_RESULTS = int(os.environ.get("DOPA_MAX_SEARCH_RESULTS", "1000"))
DOPA_MAX_OPPORTUNITIES_PER_RUN = int(
    os.environ.get("DOPA_MAX_OPPORTUNITIES_PER_RUN", "25")
)
DOPA_MAX_DETAILS_PER_RUN = int(
    os.environ.get("DOPA_MAX_DETAILS_PER_RUN", "50")
)
DOPA_MAX_ATTACHMENTS_PER_OPPORTUNITY = int(
    os.environ.get("DOPA_MAX_ATTACHMENTS_PER_OPPORTUNITY", "25")
)
DOPA_FETCH_TIMEOUT_SECONDS = int(
    os.environ.get("DOPA_FETCH_TIMEOUT_SECONDS", "30")
)
DOPA_FETCH_MAX_ATTEMPTS = int(
    os.environ.get("DOPA_FETCH_MAX_ATTEMPTS", "3")
)
DOPA_FETCH_BACKOFF_SECONDS = float(
    os.environ.get("DOPA_FETCH_BACKOFF_SECONDS", "2")
)
DOPA_MAX_RESPONSE_BYTES = int(
    os.environ.get("DOPA_MAX_RESPONSE_BYTES", "5000000")
)
DOPA_MAX_CONTENT_CHARS = int(
    os.environ.get("DOPA_MAX_CONTENT_CHARS", "2000000")
)


_YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-]((?:19|20)\d{2}))?(?!\d)"
)
_ISO_DATE_PATTERN = re.compile(
    r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)"
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

# A title containing one of these terms represents a later act or an ordinary
# procurement event, rather than an open edital.  Matching is accent-folded.
_POST_ACT_PATTERNS = (
    r"\bresultado(?:s)?\b",
    r"\bata(?:s)?\b",
    r"\bhomologac(?:ao|oes)\b",
    r"\bdispensa(?:s)?\b",
    r"\binexigibilidade(?:s)?\b",
    r"\bnotificac(?:ao|oes)\b",
    r"\berrata(?:s)?\b",
    r"\bretificac(?:ao|oes)\b",
    r"\bclassificac(?:ao|oes)\b",
    r"\bconvocac(?:ao|oes)\b",
    r"\badjudicac(?:ao|oes)\b",
    r"\brevogac(?:ao|oes)\b",
    r"\bcancelament(?:o|os)\b",
    r"\bimpugnac(?:ao|oes)\b",
    r"\blistas?\s+(?:preliminares?|finais?)\b",
    r"\bjustificativa\s+(?:de\s+)?(?:ausencia|inexigibilidade|inex)\b",
    r"\bcadastramento\s+de\s+logradouro\b",
    r"\b(?:instauracao|anulacao)\s+(?:de\s+)?reurb\b",
    r"\btorna\s+sem\s+efeito\b",
    r"\bextrato\s+de\s+termo\s+de\s+credenciamento\b",
    r"\bcertificado\s+de\s+credenciamento\b",
    r"\bavaliacao\s+d(?:o|a|os|as)\s+cotistas?\b",
    r"\bdesigna\b",
    r"\bcontrato\s+\d",
)
_POST_ACT_RE = re.compile("|".join(_POST_ACT_PATTERNS), re.IGNORECASE)
_DETAIL_POST_ACT_RE = re.compile(
    r"\bedital\s+(?:de\s+)?convocacao\b|"
    r"\btorna\s+public\w*\s+(?:a\s+)?convocacao\b|"
    r"\btorna\s+public\w*\s+o\s+convite.{0,240}\bselecionad\w*\b|"
    r"\blistas?\s+(?:preliminares?|finais?)\b|"
    r"\bjustificativa\s+(?:de\s+)?(?:ausencia|inexigibilidade|inex)\b|"
    r"\bcadastramento\s+de\s+logradouro\b|"
    r"\b(?:instauracao|anulacao)\s+(?:de\s+)?reurb\b|"
    r"\bgabaritos?\s+oficiais?\b|"
    r"\bresultado\s+(?:provisorio|final|das?\s+provas?|das?\s+avaliac)\w*\b",
    re.IGNORECASE,
)

# Common PNCP procurement modalities and their publication vocabulary.  Do not
# reject a generic edital solely because it contains "contratacao": an edital
# for a temporary public selection may use that word in its body.
_PNCP_PROCUREMENT_PATTERNS = (
    r"\bpreg(?:ao|oes)\b",
    r"\bconcorren(?:cia|cias)\b",
    r"\btomada\s+de\s+precos?\b",
    r"\bregistro\s+de\s+precos?\b",
    r"\blicitac(?:ao|oes)\b",
    r"\bdisputa\s+eletronica\b",
    r"\bcompras?\s+publicas?\b",
    r"\bcontratac(?:ao|oes)\s+de\s+(?:empresa|servicos?|obras?)\b",
    r"\baquisic(?:ao|oes)\s+de\b",
    r"\bcooperativ\w*\b.*\bchamada\s+publica\b",
    r"\bchamada\s+publica\b.*\bcooperativ\w*\b",
    r"\bagricultura\s+familiar\b",
    r"\bdlc\s*[-:]",
)
_PNCP_PROCUREMENT_RE = re.compile(
    "|".join(_PNCP_PROCUREMENT_PATTERNS), re.IGNORECASE
)

_OPPORTUNITY_PATTERNS = (
    r"\bedital(?:s)?\b",
    r"\bchamamento(?:s)?\b",
    r"\bchamada\s+publica\b",
    r"\bprocesso\s+seletivo\b",
    r"\bselec(?:ao|oes)\s+(?:publica|de)\b",
    r"\bmanifestac(?:ao|oes)\s+de\s+interesse\b",
    r"\bconcurso(?:s)?\s+publico\b",
    r"\bcredenciamento\b",
)
_OPPORTUNITY_RE = re.compile("|".join(_OPPORTUNITY_PATTERNS), re.IGNORECASE)
_SUBSTANTIVE_OPPORTUNITY_RE = re.compile(
    r"\bchamamento(?:s)?\b|"
    r"\bchamada\s+publica\b|"
    r"\bprocesso\s+seletivo\b|"
    r"\bselec(?:ao|oes)\s+(?:publica|de\s+(?:interessados|candidatos|projetos))\b|"
    r"\bmanifestac(?:ao|oes)\s+de\s+interesse\b|"
    r"\bconcurso(?:s)?\s+publico\b|"
    r"\bcredenciamento\b|"
    r"\binscric(?:ao|oes)\s+(?:estao\s+)?abert\w*\b|"
    r"\b(?:recebimento|apresentacao)\s+de\s+propostas?\b",
    re.IGNORECASE,
)

_ATTACHMENT_BLOCK_PATTERNS = (
    r"^resultado(?:[-_ .]|$)",
    r"^ata(?:[-_ .]|$)",
    r"^homologac(?:ao|oes)(?:[-_ .]|$)",
    r"^dispensa(?:[-_ .]|$)",
    r"^inexigibilidade(?:[-_ .]|$)",
    r"^notificac(?:ao|oes)(?:[-_ .]|$)",
    r"^errata(?:[-_ .]|$)",
    r"^retificac(?:ao|oes)(?:[-_ .]|$)",
)
_ATTACHMENT_BLOCK_RE = re.compile(
    "|".join(_ATTACHMENT_BLOCK_PATTERNS), re.IGNORECASE
)


def _fold(value: Any) -> str:
    """Return accent-insensitive lower-case text for policy matching."""
    text = "" if value is None else str(value)
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text).lower()
        if not unicodedata.combining(character)
    )


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=DOPA_TIMEZONE)
    return value


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _allowed_dopa_host(url: str, *, attachment: bool = False) -> bool:
    parts = urlsplit(url)
    allowed_hosts = DOPA_ATTACHMENT_HOSTS if attachment else {DOPA_API_HOST}
    return (
        parts.scheme in {"http", "https"}
        and (parts.hostname or "").lower() in allowed_hosts
    )


def _resolve_dopa_url(value: str) -> str:
    """Resolve API-relative paths without dropping the gateway prefix."""
    raw = str(value or "").strip()
    if raw.startswith("//"):
        return _canonical_url(f"https:{raw}")
    if raw.startswith("/"):
        return _canonical_url(f"{DOPA_API_BASE_URL}{raw}")
    resolved = _canonical_url(urljoin(DOPA_API_BASE_URL + "/", raw))
    parts = urlsplit(resolved)
    if parts.scheme == "http" and (parts.hostname or "").lower() in DOPA_ATTACHMENT_HOSTS:
        resolved = urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    return resolved


def _parse_date_value(value: Any, *, default_year: int | None = None) -> date | None:
    """Parse DOPA's Portuguese date labels and common ISO/BR date values."""
    if value is None:
        return None
    text = _clean_text(value)
    if not text:
        return None

    # Prefer a four-digit date embedded in the value (the API labels include
    # weekday and words such as ``Publicacao:`` before the actual date).
    match = _DATE_PATTERN.search(text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else default_year
        if year is not None:
            try:
                return date(year, month, day)
            except ValueError:
                return None

    folded = _fold(text)
    month_pattern = "|".join(_MONTHS)
    month_match = re.search(
        rf"\b(\d{{1,2}})\s+(?:de\s+)?({month_pattern})(?:\s+de\s+((?:19|20)\d{{2}}))?\b",
        folded,
    )
    if month_match:
        year = (
            int(month_match.group(3))
            if month_match.group(3)
            else default_year
        )
        month = _MONTHS[month_match.group(2)]
        if year is not None:
            try:
                return date(year, month, int(month_match.group(1)))
            except ValueError:
                return None

    # ISO datetime/date is not matched by _DATE_PATTERN because it is in
    # year-month-day order.
    iso_match = re.search(r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso_match:
        try:
            return date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
            )
        except ValueError:
            return None
    return None


def _date_iso(value: Any, *, default_year: int | None = None) -> str | None:
    parsed = _parse_date_value(value, default_year=default_year)
    return parsed.isoformat() if parsed else None


def _datetime_iso(value: Any, *, default_year: int | None = None) -> str | None:
    parsed_date = _parse_date_value(value, default_year=default_year)
    if parsed_date is None:
        return None
    return datetime.combine(
        parsed_date, datetime.min.time(), tzinfo=DOPA_TIMEZONE
    ).astimezone(timezone.utc).isoformat()


def normalize_html(html: str) -> str:
    """Normalize source HTML into deterministic, readable plain text.

    DOPA stores presentation markup (font/span/div wrappers) rather than a
    semantic document.  Removing scripts/comments and collapsing whitespace
    gives stable source Markdown and avoids persisting arbitrary markup.
    """
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for node in soup.find_all(["script", "style", "noscript"]):
        node.decompose()
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for node in soup.find_all(["br", "p", "div", "li", "tr", "h1", "h2", "h3"]):
        if isinstance(node, Tag):
            node.insert_before("\n")
    # Block separators inserted above are meaningful; a single space between
    # inline siblings prevents adjacent ``span``/``strong`` text from being
    # concatenated when the source omitted whitespace.
    text = soup.get_text(" ", strip=False)
    text = html_lib.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


# Public aliases used by source-fidelity tooling and offline tests.
normalize_source_html = normalize_html
html_to_text = normalize_html


def _extract_date_after_keyword(
    text: str,
    *,
    default_year: int | None,
    reference_date: date | None = None,
) -> date | None:
    folded = _fold(text)
    # Require whole deadline words. In particular, ``ate`` must not match the
    # beginning of ``atendimento`` and turn a nearby law date into a deadline.
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
            parsed = _parse_date_value(
                match.group(0), default_year=default_year
            )
            if parsed:
                if (
                    match.group(3) is None
                    and reference_date is not None
                    and reference_date.month - parsed.month >= 6
                ):
                    try:
                        parsed = parsed.replace(year=parsed.year + 1)
                    except ValueError:
                        pass
                candidates.append(parsed)
        for match in _ISO_DATE_PATTERN.finditer(snippet):
            parsed = _parse_date_value(match.group(0))
            if parsed:
                candidates.append(parsed)
        month_pattern = "|".join(_MONTHS)
        for match in re.finditer(
            rf"\b\d{{1,2}}\s+(?:de\s+)?(?:{month_pattern})"
            rf"(?:\s+de\s+(?:19|20)\d{{2}})?\b",
            snippet,
        ):
            parsed = _parse_date_value(
                match.group(0), default_year=default_year
            )
            if parsed:
                candidates.append(parsed)
    return max(candidates) if candidates else None


def extract_deadline(
    text: str,
    *,
    default_year: int | None = None,
    now: datetime | None = None,
) -> str | None:
    """Extract an application deadline as a UTC end-of-day ISO timestamp."""
    current = _aware_datetime(now or datetime.now(timezone.utc))
    parsed = _extract_date_after_keyword(
        text,
        default_year=default_year,
        reference_date=current.astimezone(DOPA_TIMEZONE).date(),
    )
    if parsed is None:
        return None
    return datetime.combine(
        parsed,
        datetime.max.time().replace(microsecond=0),
        tzinfo=DOPA_TIMEZONE,
    ).astimezone(timezone.utc).isoformat()


def extract_application_deadline(
    text: str,
    *,
    default_year: int | None = None,
    now: datetime | None = None,
) -> str | None:
    return extract_deadline(text, default_year=default_year, now=now)


def _status_from_text(text: str, *, deadline: str | None, now: datetime) -> str:
    now = _aware_datetime(now)
    folded = _fold(text)
    deadline_date: date | None = None
    if deadline:
        try:
            deadline_date = (
                datetime.fromisoformat(deadline)
                .astimezone(DOPA_TIMEZONE)
                .date()
            )
        except ValueError:
            deadline_date = None
    # A stale deadline wins over a generic sentence such as "inscricoes
    # abertas" that may be quoted in a later republication.
    local_today = now.astimezone(DOPA_TIMEZONE).date()
    if deadline_date is not None and deadline_date < local_today:
        return "closed"
    if re.search(
        r"\b(?:inscric(?:ao|oes)|propostas?|candidaturas?|prazo|edital)\b"
        r"\s+(?:(?:esta|estao|encontra-se|foi|foram)\s+)?"
        r"(?:encerrad|finalizad|suspens|revogad|cancelad)\w*\b",
        folded,
    ):
        return "closed"
    if re.search(
        r"\b(inscric(?:ao|oes)|propostas?|candidaturas?|participac(?:ao|oes))"
        r"\s+(?:estao\s+)?abert|\bprorrogad\w*\b",
        folded,
    ):
        return "open"
    if deadline_date is not None:
        return "open"
    return "unknown"


def build_search_url(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    *,
    term: str | None = None,
    scopes: Iterable[str] = DOPA_ESCOPOS,
) -> str:
    """Build a bounded official API search URL with ISO dates."""
    def as_iso(value: date | datetime | str) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        parsed = _parse_date_value(value)
        if parsed is None:
            # Accept an already-ISO value only if it is a valid date prefix.
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value).strip()):
                return str(value).strip()
            raise ValueError(f"invalid DOPA date: {value!r}")
        return parsed.isoformat()

    params: list[tuple[str, str]] = [
        ("dataInicial", as_iso(start_date)),
        ("dataFinal", as_iso(end_date)),
    ]
    if term:
        params.append(("termo", term))
    for scope in scopes:
        if scope:
            params.append(("escopo", str(scope).lower()))
    return f"{DOPA_SEARCH_URL}?{urlencode(params)}"


def _window_dates(
    *,
    now: datetime | None = None,
    window_days: int = DOPA_INCREMENTAL_WINDOW_DAYS,
) -> tuple[date, date]:
    current = _aware_datetime(
        now or datetime.now(timezone.utc)
    ).astimezone(DOPA_TIMEZONE).date()
    days = max(1, min(int(window_days), 31))
    return current - timedelta(days=days - 1), current


def _coerce_json_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    json_method = getattr(value, "json", None)
    if callable(json_method):
        return json_method()
    raise ValueError("DOPA response is not JSON")


def _fetch_json_from_api(url: str) -> Any:
    response = request_with_safe_redirects(
        method="GET",
        url=url,
        timeout=DOPA_FETCH_TIMEOUT_SECONDS,
        extra_headers={"Accept": "application/json"},
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        try:
            content_length_value = int(content_length) if content_length else None
        except (TypeError, ValueError):
            content_length_value = None
        if (
            content_length_value is not None
            and content_length_value > DOPA_MAX_RESPONSE_BYTES
        ):
            raise ValueError("DOPA response exceeds configured size limit")
        payload_text = response.text
        if len(payload_text.encode("utf-8")) > DOPA_MAX_RESPONSE_BYTES:
            raise ValueError("DOPA response exceeds configured size limit")
        return _coerce_json_payload(payload_text)
    finally:
        response.close()


def _fetch_with_retry(
    url: str,
    fetch_json: Callable[[str], Any],
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, max(1, DOPA_FETCH_MAX_ATTEMPTS) + 1):
        try:
            return _coerce_json_payload(fetch_json(url))
        except Exception as exc:
            last_error = exc
            if attempt < max(1, DOPA_FETCH_MAX_ATTEMPTS):
                time.sleep(DOPA_FETCH_BACKOFF_SECONDS * attempt)
    assert last_error is not None
    raise last_error


def fetch_search_results(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    *,
    fetch_json: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch and validate one bounded DOPA search response."""
    fetch = fetch_json or _fetch_json_from_api
    payload = _fetch_with_retry(
        build_search_url(start_date, end_date), fetch
    )
    if isinstance(payload, dict):
        for key in ("items", "resultados", "publicacoes", "content"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError("DOPA search response must be a list")
    if any(not isinstance(item, dict) for item in payload):
        raise ValueError("DOPA search response contains a non-object row")
    return payload


def _record_id(record: dict[str, Any], detail: dict[str, Any] | None = None) -> str | None:
    for source in (record, detail or {}):
        for key in ("idConteudo", "protocolo", "id"):
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _record_title(record: dict[str, Any], detail: dict[str, Any] | None = None) -> str:
    for source in (record, detail or {}):
        for key in ("tituloConteudo", "titulo", "title"):
            value = _clean_text(source.get(key))
            if value:
                return value
    text = normalize_html(str((detail or {}).get("textoConteudo") or ""))
    return text.splitlines()[0][:300] if text else ""


def _record_year(record: dict[str, Any], detail: dict[str, Any] | None = None) -> int | None:
    for source in (record, detail or {}):
        for key in ("dataConteudo", "dataPublicacao", "dataDivulgacao"):
            parsed = _parse_date_value(source.get(key))
            if parsed:
                return parsed.year
    title = _record_title(record, detail)
    years = [int(match.group(0)) for match in _YEAR_PATTERN.finditer(title)]
    return max(years) if years else None


def _is_executive(record: dict[str, Any], detail: dict[str, Any] | None = None) -> bool:
    values = [record.get("tipo"), (detail or {}).get("hierarquiaPoderSecao")]
    values = [_fold(value) for value in values if value]
    return not values or any("executivo" in value for value in values)


def _policy_reason(
    title: str,
    *,
    detail: dict[str, Any] | None = None,
) -> str | None:
    folded_title = _fold(title)
    if _POST_ACT_RE.search(folded_title):
        return "post_act"
    if detail:
        # A few DOPA rows have terse titles. Inspect the bounded opening of the
        # authoritative body, where the act identifies itself, without letting
        # later references to expected results reject an edital.
        raw_html = str(detail.get("textoConteudo") or detail.get("texto") or "")
        opening_text = normalize_html(raw_html)[:1500]
        folded_opening = _fold(opening_text)
        if _DETAIL_POST_ACT_RE.search(folded_opening):
            return "post_act"
    if _PNCP_PROCUREMENT_RE.search(folded_title):
        return "pncp_procurement"
    if detail and _PNCP_PROCUREMENT_RE.search(folded_opening):
        return "pncp_procurement"
    if not _OPPORTUNITY_RE.search(folded_title):
        # A detail classified as Editais can occasionally have a terse title;
        # allow it only when the authoritative hierarchy confirms the section.
        hierarchy = _fold((detail or {}).get("hierarquiaTipoConteudo"))
        if "edital" not in hierarchy and "chamamento" not in hierarchy:
            return "no_opportunity_signal"
    if detail and not _SUBSTANTIVE_OPPORTUNITY_RE.search(
        f"{folded_title}\n{folded_opening}"
    ):
        # DOPA classifies many tax, sanitary, land-registry, and hearing
        # notices as "Editais". A bare edital label is not an opportunity.
        return "no_opportunity_signal"
    return None


def is_likely_opportunity(
    title: str,
    *,
    detail: dict[str, Any] | None = None,
) -> bool:
    return _policy_reason(title, detail=detail) is None


def _is_blocked_attachment(label: str, url: str) -> bool:
    evidence = _fold(f"{label} {url}")
    filename = _fold(urlsplit(url).path.rsplit("/", 1)[-1])
    label_text = _fold(label).strip()
    return bool(
        _ATTACHMENT_BLOCK_RE.search(label_text)
        or _ATTACHMENT_BLOCK_RE.search(filename)
        or re.search(r"\b(resultado|homologacao|errata|retificacao|notificacao)\b", evidence)
    )


def _is_pdf_attachment(label: str, url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(".pdf") or ".pdf?" in url.lower() or bool(
        re.search(r"\bpdf\b", _fold(label))
    )


def extract_attachments(
    detail: dict[str, Any],
    *,
    record_id: str,
    max_attachments: int = DOPA_MAX_ATTACHMENTS_PER_OPPORTUNITY,
) -> list[dict[str, Any]]:
    """Return only bounded PDF attachments owned by this publication."""
    documents, _ = _extract_attachments_with_stats(
        detail, record_id=record_id, max_attachments=max_attachments
    )
    return documents


def _extract_attachments_with_stats(
    detail: dict[str, Any],
    *,
    record_id: str,
    max_attachments: int = DOPA_MAX_ATTACHMENTS_PER_OPPORTUNITY,
) -> tuple[list[dict[str, Any]], int]:
    """Keep only bounded PDF attachments owned by this DOPA publication."""
    raw = detail.get("anexos")
    if not isinstance(raw, list):
        return [], 0
    documents: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            rejected += 1
            continue
        label = _clean_text(item.get("texto") or item.get("titulo") or "")
        raw_url = item.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            rejected += 1
            continue
        url = _resolve_dopa_url(raw_url)
        if not _allowed_dopa_host(url, attachment=True) or not _is_pdf_attachment(label, url):
            rejected += 1
            continue
        if _is_blocked_attachment(label, url):
            rejected += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        if len(documents) >= max(0, max_attachments):
            rejected += 1
            continue
        filename = urlsplit(url).path.rsplit("/", 1)[-1] or f"anexo-{len(documents) + 1}.pdf"
        documents.append(
            {
                "source_document_id": f"{record_id}:attachment:{filename}",
                "document_kind": "pdf",
                "url": url,
                "filename": filename,
                "mime_type": "application/pdf",
                "is_principal": False,
                "is_renderable": False,
            }
        )
    return documents, rejected


def _detail_url(record_id: str) -> str:
    return DOPA_DETAIL_URL_TEMPLATE.format(id=record_id)


def _export_pdf_url(record_id: str) -> str:
    return DOPA_EXPORT_PDF_URL_TEMPLATE.format(id=record_id)


def _parse_dopa_detail(
    record: dict[str, Any],
    detail: dict[str, Any],
    *,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, str | None, int]:
    """Parse one DOPA detail, returning opportunity, reject reason, attachments."""
    record_id = _record_id(record, detail)
    title = _record_title(record, detail)
    if not record_id or not title:
        return None, "malformed", 0
    if not _is_executive(record, detail):
        return None, "non_executive", 0
    reason = _policy_reason(title, detail=detail)
    if reason:
        return None, reason, 0

    raw_html = str(detail.get("textoConteudo") or detail.get("texto") or "")
    normalized_content = normalize_html(raw_html)
    if not normalized_content:
        return None, "empty_content", 0
    if len(normalized_content) > DOPA_MAX_CONTENT_CHARS:
        return None, "content_limit", 0

    reference_year = _record_year(record, detail)
    current = _aware_datetime(
        now or snapshot_at or datetime.now(timezone.utc)
    )
    deadline = extract_deadline(
        normalized_content, default_year=reference_year, now=current
    )
    status = _status_from_text(normalized_content, deadline=deadline, now=current)
    # A closed notice is kept out of the submission stream. It remains
    # observable through search stats and can be retained in a future inventory
    # mode without creating a current opportunity.
    if status == "closed":
        return None, "closed", 0

    published = (
        _datetime_iso(detail.get("dataPublicacao"), default_year=reference_year)
        or _datetime_iso(record.get("dataConteudo"), default_year=reference_year)
        or _datetime_iso(detail.get("dataDivulgacao"), default_year=reference_year)
    )
    # DOPA exposes edition divulgation/publication dates, not an update time.
    updated = None
    attachments, attachment_rejections = _extract_attachments_with_stats(
        detail, record_id=record_id
    )
    principal_url = _export_pdf_url(record_id)
    principal = {
        "source_document_id": f"{record_id}:principal",
        "document_kind": "pdf",
        "url": principal_url,
        "filename": f"dopa-{record_id}.pdf",
        "mime_type": "application/pdf",
        "is_principal": True,
        "is_renderable": False,
    }
    documents = [principal, *attachments]

    detail_canonical = _detail_url(record_id)
    hierarchy = _clean_text(detail.get("hierarquiaPoderSecao"))
    kind = _clean_text(detail.get("hierarquiaTipoConteudo"))
    organization = _clean_text(detail.get("hierarquiaOrgao"))
    lines = [f"# {title}"]
    fields = (
        ("Fonte oficial", detail_canonical),
        ("Orgao", organization),
        ("Secao", hierarchy),
        ("Tipo", kind),
        ("Publicacao", published),
        ("Prazo", deadline),
        ("Situacao", status),
        ("Conteudo", normalized_content),
    )
    for label, value in fields:
        if value:
            lines.extend(("", f"## {label}", "", str(value)))
    if attachments:
        lines.extend(("", "## Anexos", ""))
        for document in attachments:
            lines.append(f"- {document['filename']}: {document['url']}")
    markdown = "\n".join(lines).strip()
    snapshot = _aware_datetime(snapshot_at or datetime.now(timezone.utc))
    opportunity = {
        "source_key": SOURCE_KEY,
        "source_record_id": record_id,
        "source_kind": "api",
        "opportunity_type": "public_call",
        "canonical_url": detail_canonical,
        "title": title,
        "description": normalized_content or None,
        "authoritative_status": status,
        "source_published_at": published,
        "source_updated_at": updated,
        "proposal_opens_at": None,
        "application_deadline": deadline,
        "source_snapshot_at": snapshot.astimezone(timezone.utc).isoformat(),
        "source_markdown": markdown,
        "source_content_hash": "",
        "documents": documents,
    }
    return opportunity, None, attachment_rejections


def parse_dopa_detail(
    record: dict[str, Any],
    detail: dict[str, Any],
    *,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return one normalized DOPA opportunity or ``None`` when out of scope."""
    opportunity, _, _ = _parse_dopa_detail(
        record, detail, snapshot_at=snapshot_at, now=now
    )
    return opportunity


def record_to_opportunity(
    record: dict[str, Any],
    detail: dict[str, Any],
    *,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    parsed, _, _ = _parse_dopa_detail(
        record, detail, snapshot_at=snapshot_at, now=now
    )
    return parsed


def _default_stats() -> dict[str, int]:
    return {
        "records": 0,
        "details_fetched": 0,
        "opportunities": 0,
        "policy_rejected": 0,
        "year_rejected": 0,
        "duplicate_records": 0,
        "search_failures": 0,
        "detail_failures": 0,
        "detail_parse_failures": 0,
        "errors": 0,
        "search_result_cap_reached": 0,
        "detail_cap_reached": 0,
        "candidate_cap_reached": 0,
        "attachment_rejected": 0,
    }


def discover_opportunities(
    *,
    fetch_json: Callable[[str], Any] | None = None,
    snapshot_at: datetime | None = None,
    now: datetime | None = None,
    min_year: int | None = None,
    start_date: date | datetime | str | None = None,
    end_date: date | datetime | str | None = None,
    window_days: int | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Discover current DOPA opportunities through a bounded rolling window."""
    current = _aware_datetime(
        now or snapshot_at or datetime.now(timezone.utc)
    )
    if start_date is None or end_date is None:
        default_start, default_end = _window_dates(
            now=current,
            window_days=(
                DOPA_INCREMENTAL_WINDOW_DAYS
                if window_days is None
                else window_days
            ),
        )
        start_date = start_date or default_start
        end_date = end_date or default_end

    stats = _default_stats()
    try:
        records = fetch_search_results(
            start_date, end_date, fetch_json=fetch_json
        )
    except Exception:
        stats["search_failures"] = 1
        stats["errors"] = 1
        # The orchestrator treats this marker as a source/parser failure and
        # will fail the run instead of silently accepting an empty discovery.
        stats["inventory_parse_failed"] = 1
        return stats, []

    stats["records"] = len(records)
    if len(records) > DOPA_MAX_SEARCH_RESULTS:
        stats["search_result_cap_reached"] = 1
        stats["inventory_parse_failed"] = 1
        records = records[: max(0, DOPA_MAX_SEARCH_RESULTS)]
    opportunities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    detail_fetches = 0
    fetch = fetch_json or _fetch_json_from_api

    for record in records:
        record_id = _record_id(record)
        title = _record_title(record)
        if not record_id or not title:
            stats["policy_rejected"] += 1
            continue
        if record_id in seen_ids:
            stats["duplicate_records"] += 1
            continue
        seen_ids.add(record_id)
        if min_year is not None:
            year = _record_year(record)
            if year is not None and year < min_year:
                stats["year_rejected"] += 1
                continue
        if not _is_executive(record):
            stats["policy_rejected"] += 1
            continue
        reason = _policy_reason(title)
        if reason:
            stats["policy_rejected"] += 1
            continue
        if detail_fetches >= DOPA_MAX_DETAILS_PER_RUN:
            stats["detail_cap_reached"] = 1
            stats["inventory_parse_failed"] = 1
            break
        # Derive the official endpoint from the stable id rather than trusting
        # a navigation URL returned as source data.
        detail_url = _detail_url(record_id)
        try:
            detail = _fetch_with_retry(detail_url, fetch)
            if not isinstance(detail, dict):
                raise ValueError("DOPA detail response must be an object")
            stats["details_fetched"] += 1
            detail_fetches += 1
            if min_year is not None:
                detail_year = _record_year(record, detail)
                if detail_year is not None and detail_year < min_year:
                    stats["year_rejected"] += 1
                    continue
            parsed, reject_reason, attachment_rejections = _parse_dopa_detail(
                record, detail, snapshot_at=snapshot_at or current, now=current
            )
            stats["attachment_rejected"] += attachment_rejections
            if parsed is None:
                if reject_reason in {"malformed", "empty_content", "content_limit"}:
                    stats["detail_parse_failures"] += 1
                    stats["errors"] += 1
                    stats["inventory_parse_failed"] = 1
                else:
                    stats["policy_rejected"] += 1
                continue
            opportunities.append(parsed)
        except Exception:
            detail_fetches += 1
            stats["detail_failures"] += 1
            stats["errors"] += 1
            stats["inventory_parse_failed"] = 1
            continue
        if len(opportunities) >= DOPA_MAX_OPPORTUNITIES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            stats["inventory_parse_failed"] = 1
            break

    stats["opportunities"] = len(opportunities)
    return stats, opportunities


__all__ = [
    "DOPA_API_BASE_URL",
    "DOPA_BASE_URL",
    "DOPA_SEARCH_URL",
    "DOPA_API_URL",
    "DOPA_DETAIL_BASE_URL",
    "DOPA_DETAIL_URL_TEMPLATE",
    "DOPA_EXPORT_PDF_URL_TEMPLATE",
    "DOPA_INCREMENTAL_WINDOW_DAYS",
    "DOPA_MAX_OPPORTUNITIES_PER_RUN",
    "SOURCE_KEY",
    "build_search_url",
    "discover_opportunities",
    "extract_attachments",
    "extract_application_deadline",
    "extract_deadline",
    "fetch_search_results",
    "html_to_text",
    "is_likely_opportunity",
    "normalize_html",
    "normalize_source_html",
    "parse_dopa_detail",
    "record_to_opportunity",
]
