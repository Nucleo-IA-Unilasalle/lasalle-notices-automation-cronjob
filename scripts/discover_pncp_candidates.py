from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

import pipeline_core
from source_run_reporting import SourceRunReporter
from source_control import AdmissionConflict
from pncp_filters import DROP_EXPIRED, FEDERAL_CNPJS, UF_FILTER
from pipeline_core import process_candidate


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

PNCP_API_URL = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
PNCP_PROPOSTA_URL = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
PNCP_ATUALIZACAO_URL = "https://pncp.gov.br/api/consulta/v1/contratacoes/atualizacao"
PNCP_DOCS_BASE_URL = "https://pncp.gov.br/api/pncp/v1"
PNCP_DEFAULT_MODALITY_CODES = ("6", "8", "4")
PNCP_MODALITY_NAMES = {
    "6": "Pregão Eletrônico",
    "8": "Dispensa de Licitação",
    "4": "Concorrência Eletrônica",
}
def _positive_env_int(name: str, default: int) -> int:
    """Keep safety-related PNCP caps positive when env input is missing/bad."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


PNCP_UPDATE_CHECKPOINT_PATH = (
    os.environ.get("PNCP_UPDATE_CHECKPOINT_PATH", ".cache/pncp_update_checkpoint.json").strip()
    or ".cache/pncp_update_checkpoint.json"
)
PNCP_PREFERRED_DOCUMENT_TYPES = (
    "edital",
    "aviso de contratação direta",
    "aviso de contratacao direta",
    "termo de referência",
    "termo de referencia",
)
PNCP_DOCUMENT_TYPE_PRIORITIES = {
    "edital": 10,
    "aviso de contratação direta": 20,
    "aviso de contratacao direta": 20,
    "termo de referência": 30,
    "termo de referencia": 30,
}

PNCP_LOOKBACK_DAYS = _positive_env_int("PNCP_LOOKBACK_DAYS", 30)
PNCP_PROPOSTA_FORWARD_DAYS = _positive_env_int("PNCP_PROPOSTA_FORWARD_DAYS", 60)
PNCP_MAX_PAGES_PER_QUERY = _positive_env_int("PNCP_MAX_PAGES_PER_QUERY", 20)
PNCP_PAGE_SIZE = _positive_env_int("PNCP_PAGE_SIZE", 50)
PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN = _positive_env_int("PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN", 100)
PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES = _positive_env_int(
    "PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES", 10
)
PNCP_MIN_NOTICE_YEAR = _positive_env_int("PNCP_MIN_NOTICE_YEAR", 2026)
PNCP_MAX_CANDIDATES_PER_RUN = _positive_env_int("PNCP_MAX_CANDIDATES_PER_RUN", 10)
PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN = _positive_env_int(
    "PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN", 20
)
PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN = _positive_env_int(
    "PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN", 5
)
PNCP_FETCH_MAX_ATTEMPTS = _positive_env_int("PNCP_FETCH_MAX_ATTEMPTS", 3)
try:
    PNCP_FETCH_BACKOFF_SECONDS = max(
        0.0, float(os.environ.get("PNCP_FETCH_BACKOFF_SECONDS", "2"))
    )
except (TypeError, ValueError):
    PNCP_FETCH_BACKOFF_SECONDS = 2.0
PNCP_FETCH_TIMEOUT_SECONDS = _positive_env_int("PNCP_FETCH_TIMEOUT_SECONDS", 20)
PNCP_SEARCH_BUDGET_SECONDS = _positive_env_int("PNCP_SEARCH_BUDGET_SECONDS", 480)
# Durable sweep only: pages fetched per run (the legacy per-query cap does not
# truncate a sweep) and the pause between consecutive page requests.
PNCP_MAX_PAGES_PER_RUN = _positive_env_int("PNCP_MAX_PAGES_PER_RUN", 40)
try:
    PNCP_PAGE_DELAY_SECONDS = max(
        0.0, float(os.environ.get("PNCP_PAGE_DELAY_SECONDS", "0.3"))
    )
except (TypeError, ValueError):
    PNCP_PAGE_DELAY_SECONDS = 0.3
PNCP_RETRY_AFTER_CAP_SECONDS = 60
PNCP_SWEEP_VERSION = 1
PNCP_SWEEP_MAX_AGE = timedelta(days=7)
PNCP_SWEEP_PAGE_FAILURE_LIMIT = 3
# A 5xx or timeout may be a PNCP outage, and a skip forfeits the whole sweep:
# hold about 6 h (two runs per hour) before treating it as a bad page.
PNCP_SWEEP_OUTAGE_FAILURE_LIMIT = 12
PNCP_SWEEP_OVERLAP = timedelta(hours=1)
PNCP_OPPORTUNITY_V2_ENABLED = (
    os.environ.get("PNCP_OPPORTUNITY_V2_ENABLED", "false").lower() == "true"
)
PNCP_OPPORTUNITY_V2_SHADOW = (
    os.environ.get("PNCP_OPPORTUNITY_V2_SHADOW", "true").lower() == "true"
)


def fetch_json(url: str, *, timeout: int | None = None) -> Any:
    for attempt in range(1, PNCP_FETCH_MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=PNCP_FETCH_TIMEOUT_SECONDS if timeout is None else timeout,
            )
            if response.status_code in (408, 425, 429, 500, 502, 503, 504):
                if attempt < PNCP_FETCH_MAX_ATTEMPTS:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        sleep_seconds = float(retry_after) if retry_after else PNCP_FETCH_BACKOFF_SECONDS * attempt
                    except (TypeError, ValueError):
                        sleep_seconds = PNCP_FETCH_BACKOFF_SECONDS * attempt
                    # A server-provided delay must not outlast the search budget.
                    time.sleep(min(sleep_seconds, PNCP_RETRY_AFTER_CAP_SECONDS))
                    continue
            response.raise_for_status()
            if response.status_code == 204:
                # PNCP answers an empty window with 204 and no body: that is
                # "no records", not an unparseable payload to retry and fail.
                return {"data": [], "totalRegistros": 0, "totalPaginas": 0}
            return response.json()
        except (requests.Timeout, requests.ConnectionError, ValueError):
            if attempt >= PNCP_FETCH_MAX_ATTEMPTS:
                raise
            time.sleep(PNCP_FETCH_BACKOFF_SECONDS * attempt)

    raise RuntimeError("unreachable PNCP fetch retry state")


def fetch_pncp_search_pages(
    base_url: str,
    base_params: dict[str, str | int],
    *,
    stats: dict[str, int] | None = None,
    search_deadline: float | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    last_total_pages = 1

    while page <= PNCP_MAX_PAGES_PER_QUERY:
        if search_deadline is not None and time.monotonic() >= search_deadline:
            _mark_search_budget_exhausted(stats)
            break
        if page > 1 and PNCP_PAGE_DELAY_SECONDS > 0:
            time.sleep(PNCP_PAGE_DELAY_SECONDS)
        params = {**base_params, "pagina": page, "tamanhoPagina": PNCP_PAGE_SIZE}
        url = f"{base_url}?{urlencode(params)}"
        if stats is not None:
            stats["pncp_pages_attempted"] = int(stats.get("pncp_pages_attempted", 0) or 0) + 1
        try:
            payload = fetch_json(url)
        except Exception as exc:
            print(f"warning: skipping PNCP search page {page} from {base_url}: {exc}", file=sys.stderr)
            if stats is not None:
                stats["search_failures"] = stats.get("search_failures", 0) + 1
                if (isinstance(exc, requests.HTTPError)
                        and exc.response is not None
                        and exc.response.status_code == 429):
                    stats["rate_limited"] = 1
            break

        if not isinstance(payload, dict):
            print(f"warning: PNCP search page {page} returned non-object payload", file=sys.stderr)
            if stats is not None:
                stats["search_failures"] = stats.get("search_failures", 0) + 1
            break

        page_records = payload.get("data", [])
        if not isinstance(page_records, list):
            print(f"warning: PNCP search page {page} returned invalid data", file=sys.stderr)
            if stats is not None:
                stats["search_failures"] = stats.get("search_failures", 0) + 1
            break
        records.extend(record for record in page_records if isinstance(record, dict))
        if stats is not None:
            stats["pncp_pages_completed"] = int(stats.get("pncp_pages_completed", 0) or 0) + 1

        total_pages = payload.get("totalPaginas") or page
        try:
            total_pages_int = int(total_pages)
        except (TypeError, ValueError):
            total_pages_int = page
        last_total_pages = total_pages_int

        if page >= total_pages_int:
            break
        page += 1

    if stats is not None and page >= PNCP_MAX_PAGES_PER_QUERY and last_total_pages > PNCP_MAX_PAGES_PER_QUERY:
        # The listing was truncated by the per-query page cap: the tail was
        # never enumerated, so the collection cursor must stay incomplete.
        stats["page_cap_reached"] = 1
        stats["pncp_page_cap_reached"] = 1

    return records


BRASILIA_OFFSET = timezone(timedelta(hours=-3))
_UPDATE_FORMAT = "%Y%m%d%H%M%S"
_ATUALIZACAO_OVERLAP_DAYS = 1
_ATUALIZACAO_INITIAL_LOOKBACK_DAYS = 2


def _mark_search_budget_exhausted(stats: dict[str, int] | None) -> None:
    if stats is not None and not stats.get("search_budget_exhausted"):
        stats["search_budget_exhausted"] = 1
        stats["search_failures"] = stats.get("search_failures", 0) + 1
        print("warning: PNCP search budget exhausted; inventory is incomplete", file=sys.stderr)


def parse_pncp_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRASILIA_OFFSET)
        return dt
    except (ValueError, TypeError):
        pass
    if len(value) == 14 and value.isdigit():
        try:
            naive = datetime.strptime(value, _UPDATE_FORMAT)
            return naive.replace(tzinfo=BRASILIA_OFFSET)
        except ValueError:
            pass
    if len(value) == 8 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d").replace(
                tzinfo=BRASILIA_OFFSET
            )
        except ValueError:
            pass
    return None


def _normalize_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BRASILIA_OFFSET)
    return dt.astimezone(timezone.utc)


def is_pncp_record_actionable(record: dict[str, Any], *, drop_expired: bool = True) -> bool:
    try:
        ano_compra = int(record.get("anoCompra"))
    except (TypeError, ValueError):
        ano_compra = None
    if ano_compra is None or ano_compra < PNCP_MIN_NOTICE_YEAR:
        print(
            "Skipping PNCP record before "
            f"{PNCP_MIN_NOTICE_YEAR}: {record.get('numeroControlePNCP')}",
            file=sys.stderr,
        )
        return False

    status = record.get("situacaoCompraId")
    try:
        status_int = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_int = None
    if status_int is not None and status_int != 1:
        return False
    if not drop_expired:
        return True
    encerramento_raw = record.get("dataEncerramentoProposta")
    encerramento = parse_pncp_datetime(encerramento_raw)
    if encerramento is None:
        return False
    now_utc = datetime.now(timezone.utc)
    if _normalize_to_utc(encerramento) <= now_utc:
        return False
    abertura_raw = record.get("dataAberturaProposta")
    if abertura_raw:
        abertura = parse_pncp_datetime(abertura_raw)
        if abertura is not None and _normalize_to_utc(abertura) > now_utc:
            return False
    return True


def validate_pncp_record_for_download(record: dict[str, Any]) -> bool:
    control = str(record.get("numeroControlePNCP") or "").strip()
    if not control:
        return False
    if record.get("sequencialCompra") is None:
        return False
    if record.get("anoCompra") is None:
        return False
    return True


def _load_update_checkpoint() -> datetime | None:
    import durable_source_work
    if durable_source_work.enabled():
        from source_control import SourceControl
        cursor = SourceControl("pncp").work("checkpoint", scope="pncp-updates-v1").get("cursor") or {}
        versioned, adapter, scope = durable_source_work.parse_collection_cursor(cursor)
        if versioned and adapter == "pncp" and scope == durable_source_work.PNCP_SCOPE:
            # Older workers wrote the scan start even for uncollected tails.
            # Such rows are not safe update watermarks; rescan the lookback.
            if cursor.get("complete") is not True:
                return None
            return parse_pncp_datetime(cursor.get("last_successful_update")) if cursor.get("last_successful_update") else None
        # Legacy watermark rows predate versioned cursors: honor the time
        # watermark for overlap, but never treat it as pagination position.
        if isinstance(cursor.get("last_successful_update"), str):
            return parse_pncp_datetime(cursor.get("last_successful_update"))
        return None
    try:
        with open(PNCP_UPDATE_CHECKPOINT_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("last_successful_update")
    if not isinstance(raw, str):
        return None
    return parse_pncp_datetime(raw)


def _save_update_checkpoint(checkpoint_dt: datetime) -> None:
    os.makedirs(os.path.dirname(PNCP_UPDATE_CHECKPOINT_PATH) or ".", exist_ok=True)
    normalized = _normalize_to_utc(checkpoint_dt)
    payload = {
        "last_successful_update": normalized.isoformat(),
    }
    tmp_path = f"{PNCP_UPDATE_CHECKPOINT_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp_path, PNCP_UPDATE_CHECKPOINT_PATH)


_PNCP_COUNTER_FIELDS = (
    "records_enumerated", "records_registered", "document_lookups_completed",
    "documents_selected", "search_pages_completed",
)


def _load_stored_cursor() -> dict[str, Any]:
    """Raw stored PNCP collection cursor (durable mode); {} when absent."""
    import durable_source_work
    from source_control import SourceControl
    cursor = SourceControl("pncp").work(
        "checkpoint", scope=durable_source_work.PNCP_SCOPE
    ).get("cursor") or {}
    return cursor if isinstance(cursor, dict) else {}


def _stored_complete_watermark(cursor: dict[str, Any]) -> str | None:
    """Raw last complete watermark in a stored cursor, or None.

    Same rule as ``_load_update_checkpoint``: a versioned PNCP cursor only
    vouches for ``last_successful_update`` when ``complete`` is true (a sweep in
    progress keeps the prior complete watermark in ``last_complete_update``);
    a legacy bare watermark is honoured as a time watermark.
    """
    import durable_source_work
    versioned, adapter, scope = durable_source_work.parse_collection_cursor(cursor)
    if versioned and adapter == "pncp" and scope == durable_source_work.PNCP_SCOPE:
        raw = (
            cursor.get("last_successful_update")
            if cursor.get("complete") is True
            else cursor.get("last_complete_update")
        )
    else:
        raw = cursor.get("last_successful_update")
    if isinstance(raw, str) and parse_pncp_datetime(raw) is not None:
        return raw
    return None


def _is_plain_int(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _load_sweep_state(cursor: dict[str, Any], *, now: datetime) -> dict[str, Any] | None:
    """Sweep position stored in an incomplete cursor, or None to start afresh.

    A cursor without a well-formed ``sweep`` (legacy, complete, or written by a
    worker that predates sweeps) and a sweep older than ``PNCP_SWEEP_MAX_AGE``
    are both ignored.
    """
    import durable_source_work
    versioned, adapter, scope = durable_source_work.parse_collection_cursor(cursor)
    if not (versioned and adapter == "pncp" and scope == durable_source_work.PNCP_SCOPE):
        return None
    if cursor.get("complete") is not False:
        return None
    sweep = cursor.get("sweep")
    if not isinstance(sweep, dict) or sweep.get("version") != PNCP_SWEEP_VERSION:
        return None
    started = parse_pncp_datetime(sweep.get("started_at"))
    if started is None or now - _normalize_to_utc(started) > PNCP_SWEEP_MAX_AGE:
        return None
    for key in ("window_start", "window_end"):
        value = sweep.get(key)
        if not (isinstance(value, str) and len(value) == 8 and value.isdigit()):
            return None
    if not (
        _is_plain_int(sweep.get("stream_index"), 0)
        and _is_plain_int(sweep.get("next_page"), 1)
        and _is_plain_int(sweep.get("page_failures"), 0)
        and _is_plain_int(sweep.get("streams"), 1)
        and isinstance(sweep.get("skipped_records"), bool)
    ):
        return None
    return dict(sweep)


def _watermark_key(value: Any) -> tuple[int, str]:
    """Ordering REPO_A applies to cursor watermarks (ISO strings, else raw)."""
    try:
        return (0, datetime.fromisoformat(value).isoformat())
    except (TypeError, ValueError):
        return (1, str(value))


def _deduplicate_records(raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_control: dict[str, dict[str, Any]] = {}
    for record in raw_records:
        control = str(record.get("numeroControlePNCP") or "")
        if not control:
            continue
        existing = best_by_control.get(control)
        if existing is None:
            best_by_control[control] = record
            continue
        new_global = str(record.get("dataAtualizacaoGlobal") or "")
        old_global = str(existing.get("dataAtualizacaoGlobal") or "")
        if new_global > old_global:
            best_by_control[control] = record
            continue
        if new_global == old_global:
            new_upd = str(record.get("dataAtualizacao") or "")
            old_upd = str(existing.get("dataAtualizacao") or "")
            if new_upd > old_upd:
                best_by_control[control] = record
    return list(best_by_control.values())


def _scrape_three_endpoints(
    base_params: dict[str, str | int],
    *,
    today_str: str,
    proposal_end: str,
    publication_start: str,
    overlap_start_str: str,
    stats: dict[str, int] | None,
    search_deadline: float | None = None,
) -> list[dict[str, Any]]:
    """Hit /proposta, /publicacao (per modality), and /atualizacao (per modality) with the given params."""
    out: list[dict[str, Any]] = []
    queries = [
        (PNCP_PROPOSTA_URL, {**base_params, "dataInicial": today_str, "dataFinal": proposal_end})
    ]
    for modality_code in PNCP_DEFAULT_MODALITY_CODES:
        queries.append(
            (PNCP_API_URL, {
                **base_params,
                "dataInicial": publication_start,
                "dataFinal": today_str,
                "codigoModalidadeContratacao": modality_code,
            })
        )
        queries.append(
            (PNCP_ATUALIZACAO_URL, {
                **base_params,
                "dataInicial": overlap_start_str,
                "dataFinal": today_str,
                "codigoModalidadeContratacao": modality_code,
            })
        )
    for url, params in queries:
        if search_deadline is not None and time.monotonic() >= search_deadline:
            _mark_search_budget_exhausted(stats)
            break
        out.extend(fetch_pncp_search_pages(
            url, params, stats=stats, search_deadline=search_deadline,
        ))
        if stats is not None and (stats.get("search_budget_exhausted") or stats.get("rate_limited")):
            break
    return out


def fetch_pncp_records(
    stats: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], datetime]:
    run_stats = stats if stats is not None else {}
    uf_filter = UF_FILTER
    federal_cnpjs: list[str] = list(FEDERAL_CNPJS)
    drop_expired = DROP_EXPIRED

    now_utc = datetime.now(timezone.utc)
    now_brasilia = now_utc.astimezone(BRASILIA_OFFSET)
    today = now_brasilia.date()
    publication_start = (today - timedelta(days=PNCP_LOOKBACK_DAYS)).strftime("%Y%m%d")
    today_str = today.strftime("%Y%m%d")
    proposal_end = (today + timedelta(days=PNCP_PROPOSTA_FORWARD_DAYS)).strftime("%Y%m%d")

    base_params: dict[str, str | int] = {}
    if uf_filter:
        base_params["uf"] = uf_filter

    raw_records: list[dict[str, Any]] = []
    search_deadline = time.monotonic() + PNCP_SEARCH_BUDGET_SECONDS

    checkpoint = _load_update_checkpoint()
    if checkpoint is not None:
        checkpoint_brasilia = _normalize_to_utc(checkpoint).astimezone(BRASILIA_OFFSET)
        overlap_start_date = checkpoint_brasilia.date() - timedelta(days=_ATUALIZACAO_OVERLAP_DAYS)
    else:
        overlap_start_date = today - timedelta(days=_ATUALIZACAO_INITIAL_LOOKBACK_DAYS)
    overlap_start_str = overlap_start_date.strftime("%Y%m%d")

    raw_records.extend(
        _scrape_three_endpoints(
            base_params,
            today_str=today_str,
            proposal_end=proposal_end,
            publication_start=publication_start,
            overlap_start_str=overlap_start_str,
            stats=run_stats,
            search_deadline=search_deadline,
        )
    )

    for cnpj in federal_cnpjs:
        if run_stats.get("search_budget_exhausted") or run_stats.get("rate_limited"):
            break
        raw_records.extend(
            _scrape_three_endpoints(
                {"cnpj": cnpj},
                today_str=today_str,
                proposal_end=proposal_end,
                publication_start=publication_start,
                overlap_start_str=overlap_start_str,
                stats=run_stats,
                search_deadline=search_deadline,
            )
        )

    proposta_modalities = {int(c) for c in PNCP_DEFAULT_MODALITY_CODES}
    proposta_records = [
        r for r in raw_records
        if r.get("modalidadeId") in proposta_modalities
    ]
    deduplicated = _deduplicate_records(proposta_records)

    records = [
        r for r in deduplicated
        if is_pncp_record_actionable(r, drop_expired=drop_expired)
    ]
    if stats is not None:
        stats["pncp_raw_records"] = len(raw_records)
        stats["pncp_records_enumerated"] = len(records)

    return records, now_utc


def fetch_pncp_documents(record: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    orgao = record.get("orgaoEntidade")
    cnpj = orgao.get("cnpj") if isinstance(orgao, dict) else None
    ano = record.get("anoCompra")
    sequencial = record.get("sequencialCompra")

    if not cnpj or not ano or not sequencial:
        return [], False

    url = f"{PNCP_DOCS_BASE_URL}/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos"
    try:
        payload = fetch_json(url)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 404:
            return [], False
        print(f"warning: failed fetching PNCP documents from {url}: {exc}", file=sys.stderr)
        return [], True
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"warning: PNCP document list unparseable from {url}: {exc}", file=sys.stderr)
        return [], True
    except Exception as exc:
        print(f"warning: failed fetching PNCP documents from {url}: {exc}", file=sys.stderr)
        return [], True

    if not isinstance(payload, list):
        print(f"warning: PNCP document list from {url} was not a list", file=sys.stderr)
        return [], True

    return [document for document in payload if isinstance(document, dict)], False


def pncp_document_priority(document: dict[str, Any]) -> int:
    type_name = str(document.get("tipoDocumentoNome") or "").lower()
    title = str(document.get("titulo") or "").lower()
    searchable = f"{type_name} {title}"
    for token, priority in PNCP_DOCUMENT_TYPE_PRIORITIES.items():
        if token in searchable:
            return priority
    return 100


def select_pncp_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for document in documents:
        url = document.get("url")
        if not isinstance(url, str) or not url or url in seen_urls:
            continue
        type_name = str(document.get("tipoDocumentoNome") or "").lower()
        title = str(document.get("titulo") or "").lower()
        searchable = f"{type_name} {title}"
        if any(document_type in searchable for document_type in PNCP_PREFERRED_DOCUMENT_TYPES):
            selected.append(document)
            seen_urls.add(url)
    selected.sort(key=pncp_document_priority)
    return selected


def build_candidate(record: dict[str, Any], document: dict[str, Any]) -> dict[str, Any] | None:
    url = document.get("url")
    if not isinstance(url, str) or not url.strip():
        return None

    orgao = record.get("orgaoEntidade")
    unidade = record.get("unidadeOrgao")
    metadata = {
        "numeroControlePNCP": record.get("numeroControlePNCP"),
        "anoCompra": record.get("anoCompra"),
        "sequencialCompra": record.get("sequencialCompra"),
        "numeroCompra": record.get("numeroCompra"),
        "sequencialDocumento": document.get("sequencialDocumento"),
        "tipoDocumentoNome": document.get("tipoDocumentoNome"),
        "titulo": document.get("titulo") or "",
        "priority": pncp_document_priority(document),
        "dataPublicacaoPncp": record.get("dataPublicacaoPncp"),
        "dataAberturaProposta": record.get("dataAberturaProposta"),
        "dataEncerramentoProposta": record.get("dataEncerramentoProposta"),
        "situacaoCompraId": record.get("situacaoCompraId"),
        "situacaoCompraNome": record.get("situacaoCompraNome"),
        "dataAtualizacaoGlobal": record.get("dataAtualizacaoGlobal"),
        "dataAtualizacao": record.get("dataAtualizacao"),
        "modalidadeId": record.get("modalidadeId"),
        "modalidadeNome": record.get("modalidadeNome"),
        "srp": record.get("srp"),
        "objetoCompra": record.get("objetoCompra") or "",
        "processo": record.get("processo") or "",
        "informacaoComplementar": record.get("informacaoComplementar") or "",
        "linkSistemaOrigem": record.get("linkSistemaOrigem"),
        "linkProcessoEletronico": record.get("linkProcessoEletronico"),
        "cnpj": orgao.get("cnpj") if isinstance(orgao, dict) else None,
        "municipioNome": unidade.get("municipioNome") if isinstance(unidade, dict) else None,
        "ufSigla": unidade.get("ufSigla") if isinstance(unidade, dict) else None,
    }
    return {"url": url.strip(), "kind": "pdf", "metadata": metadata}


def _pncp_iso(value: Any) -> str | None:
    parsed = parse_pncp_datetime(str(value)) if value else None
    return _normalize_to_utc(parsed).isoformat() if parsed else None


def build_opportunity(
    record: dict[str, Any],
    documents: list[dict[str, Any]],
    *,
    snapshot_at: datetime,
) -> dict[str, Any] | None:
    """Represent one PNCP control number as one parent with child documents."""
    control_number = str(record.get("numeroControlePNCP") or "").strip()
    if not control_number:
        return None
    orgao = record.get("orgaoEntidade")
    cnpj = str(orgao.get("cnpj") or "") if isinstance(orgao, dict) else ""
    year = record.get("anoCompra")
    sequence = record.get("sequencialCompra")
    canonical_url = (
        f"https://pncp.gov.br/app/editais/{cnpj}/{year}/{sequence}"
        if cnpj and year is not None and sequence is not None
        else None
    )
    title = str(
        record.get("objetoCompra")
        or record.get("informacaoComplementar")
        or f"Contratacao PNCP {control_number}"
    ).strip()
    field_values = [
        ("Numero de controle PNCP", control_number),
        ("Objeto", str(record.get("objetoCompra") or "").strip()),
        ("Processo", str(record.get("processo") or "").strip()),
        ("Modalidade", str(record.get("modalidadeNome") or "").strip()),
        ("Situacao", str(record.get("situacaoCompraNome") or "").strip()),
        ("Abertura", _pncp_iso(record.get("dataAberturaProposta")) or ""),
        ("Encerramento", _pncp_iso(record.get("dataEncerramentoProposta")) or ""),
        (
            "Informacao complementar",
            str(record.get("informacaoComplementar") or "").strip(),
        ),
    ]
    lines = [f"# {title}"]
    for label, value in field_values:
        if value:
            lines.extend(("", f"## {label}", "", value))
    selected = select_pncp_documents(documents)
    descriptors = []
    seen_sequence: set[str] = set()
    for document in selected:
        url = document.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        document_sequence = document.get("sequencialDocumento")
        if document_sequence is None:
            continue
        source_document_id = str(document_sequence)
        if source_document_id in seen_sequence:
            continue
        seen_sequence.add(source_document_id)
        descriptors.append(
            {
                "source_document_id": source_document_id,
                "document_kind": "pdf",
                "url": url.strip(),
                "filename": url.split("?", 1)[0].rsplit("/", 1)[-1],
                "mime_type": "application/pdf",
                "is_principal": False,
                "is_renderable": False,
            }
        )
    return {
        "source_key": "pncp",
        "source_record_id": control_number,
        "source_kind": "api",
        "opportunity_type": "procurement",
        "canonical_url": canonical_url,
        "title": title,
        "description": str(record.get("informacaoComplementar") or "").strip() or None,
        "authoritative_status": str(record.get("situacaoCompraNome") or "").strip() or None,
        "source_published_at": _pncp_iso(record.get("dataPublicacaoPncp")),
        "source_updated_at": _pncp_iso(
            record.get("dataAtualizacaoGlobal") or record.get("dataAtualizacao")
        ),
        "proposal_opens_at": _pncp_iso(record.get("dataAberturaProposta")),
        "application_deadline": _pncp_iso(record.get("dataEncerramentoProposta")),
        "source_snapshot_at": snapshot_at.astimezone(timezone.utc).isoformat(),
        "source_markdown": "\n".join(lines),
        "source_content_hash": "",
        "documents": descriptors,
    }


def discover_opportunities() -> tuple[dict[str, int], list[dict[str, Any]], datetime]:
    """Discover PNCP parents even when their API document list is empty."""
    stats = {
        "records": 0,
        "document_lookups": 0,
        "opportunities": 0,
        "document_failures": 0,
        "search_failures": 0,
    }
    records, discovery_time = fetch_pncp_records(stats=stats)
    stats["records"] = len(records)
    opportunities: list[dict[str, Any]] = []
    for record in records:
        if stats["document_lookups"] >= PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN:
            stats["detail_cap_reached"] = 1
            break
        documents, failed = fetch_pncp_documents(record)
        stats["document_lookups"] += 1
        if failed:
            stats["document_failures"] += 1
            documents = []
        opportunity = build_opportunity(
            record, documents, snapshot_at=discovery_time
        )
        if opportunity is not None:
            opportunities.append(opportunity)
        if len(opportunities) >= PNCP_MAX_CANDIDATES_PER_RUN:
            break
    stats["opportunities"] = len(opportunities)
    return stats, opportunities, discovery_time


def _main_opportunities() -> int:
    stats, opportunities, discovery_time = discover_opportunities()
    print(f"PNCP v2 opportunity discovery stats: {stats}")
    if not opportunities and stats.get("search_failures", 0):
        return 1
    if not opportunities:
        return 0
    if PNCP_OPPORTUNITY_V2_SHADOW:
        artifact = Path(
            os.environ.get(
                "PNCP_OPPORTUNITY_V2_ARTIFACT",
                "artifacts/pncp-v2/opportunities.json",
            )
        )
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(
                {"stats": stats, "opportunities": opportunities},
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"PNCP v2 shadow artifact written to {artifact}")
        return 0
    _config, extractor = pipeline_core.make_default_ocr_extractor()
    processed = [
        pipeline_core.process_opportunity(
            opportunity, extractor=extractor, stats=stats
        )
        for opportunity in opportunities
    ]
    result = pipeline_core.submit_opportunities(processed)
    print(f"PNCP v2 opportunity submission: {result}")
    if result.get("submitted") != len(processed):
        return 1
    _save_update_checkpoint(discovery_time)
    return 0


PNCP_MODALITY_IDS = frozenset(int(code) for code in PNCP_DEFAULT_MODALITY_CODES)
_SWEEP_STAMP_FIELDS = ("dataAtualizacaoGlobal", "dataAtualizacao", "dataPublicacaoPncp")


def _brasilia_date(value: datetime):
    return _normalize_to_utc(value).astimezone(BRASILIA_OFFSET).date()


def _sweep_date(value: str):
    return datetime.strptime(value, "%Y%m%d").date()


def _new_sweep(now_utc: datetime, prior_complete: str | None) -> dict[str, Any]:
    """Freeze the window of a new sweep.

    Backfill (no complete watermark) reads the whole lookback; an incremental
    sweep reads from one day before the prior complete watermark.
    """
    today = _brasilia_date(now_utc)
    if prior_complete is not None:
        start = _brasilia_date(parse_pncp_datetime(prior_complete)) - timedelta(
            days=_ATUALIZACAO_OVERLAP_DAYS
        )
        start = min(start, today)
    else:
        start = today - timedelta(days=PNCP_LOOKBACK_DAYS)
    return {
        "version": PNCP_SWEEP_VERSION,
        "started_at": now_utc.isoformat(),
        "window_start": start.strftime("%Y%m%d"),
        "window_end": today.strftime("%Y%m%d"),
        "stream_index": 0,
        "next_page": 1,
        "skipped_records": False,
        "page_failures": 0,
    }


def _sweep_streams(
    sweep: dict[str, Any], *, incremental: bool
) -> list[tuple[str, dict[str, str | int]]]:
    """Deterministic (url, params) list for a frozen window.

    ``stream_index`` only means something between runs because this list is a
    pure function of the window, the mode and the scope constants.
    """
    start, end = sweep["window_start"], sweep["window_end"]
    scopes: list[dict[str, str | int]] = [{"uf": UF_FILTER} if UF_FILTER else {}]
    scopes.extend({"cnpj": cnpj} for cnpj in FEDERAL_CNPJS)
    if incremental:
        update_start = start
    else:
        update_start = (
            _sweep_date(end) - timedelta(days=_ATUALIZACAO_INITIAL_LOOKBACK_DAYS)
        ).strftime("%Y%m%d")
    proposal_end = (
        _sweep_date(end) + timedelta(days=PNCP_PROPOSTA_FORWARD_DAYS)
    ).strftime("%Y%m%d")
    streams: list[tuple[str, dict[str, str | int]]] = []
    for scope in scopes:
        if not incremental:
            streams.append(
                (PNCP_PROPOSTA_URL, {**scope, "dataInicial": end, "dataFinal": proposal_end})
            )
        for modality_code in PNCP_DEFAULT_MODALITY_CODES:
            streams.append((PNCP_API_URL, {
                **scope,
                "dataInicial": start,
                "dataFinal": end,
                "codigoModalidadeContratacao": modality_code,
            }))
            streams.append((PNCP_ATUALIZACAO_URL, {
                **scope,
                "dataInicial": update_start,
                "dataFinal": end,
                "codigoModalidadeContratacao": modality_code,
            }))
    return streams


def _record_is_stale(record: dict[str, Any], cutoff: datetime) -> bool:
    """True when every timestamp the record carries predates ``cutoff``."""
    stamps = [
        parse_pncp_datetime(str(record[field]))
        for field in _SWEEP_STAMP_FIELDS
        if record.get(field)
    ]
    stamps = [stamp for stamp in stamps if stamp is not None]
    if not stamps:
        return False
    return max(_normalize_to_utc(stamp) for stamp in stamps) < cutoff


def _sweep_collect_page(
    page_records: list[Any],
    *,
    stats: dict[str, Any],
    candidates: list[dict[str, Any]],
    seen_urls: set[str],
    seen_controls: set[str],
    cutoff: datetime | None,
) -> bool:
    """Look up the attachments of one page; True when any lookup failed."""
    page_failed = False
    consecutive_failures = 0
    for record in page_records:
        if not isinstance(record, dict) or record.get("modalidadeId") not in PNCP_MODALITY_IDS:
            continue
        control = str(record.get("numeroControlePNCP") or "")
        if not control or control in seen_controls:
            continue
        if cutoff is not None and _record_is_stale(record, cutoff):
            stats["pncp_overlap_skipped"] += 1
            continue
        if not is_pncp_record_actionable(record, drop_expired=DROP_EXPIRED):
            continue
        seen_controls.add(control)
        stats["records"] += 1
        if not validate_pncp_record_for_download(record):
            stats["pre_download_rejected"] += 1
            continue

        documents, failed = fetch_pncp_documents(record)
        stats["document_lookups"] += 1
        if failed:
            stats["document_failures"] += 1
            page_failed = True
            consecutive_failures += 1
            if consecutive_failures >= PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES:
                print("warning: stopping page after consecutive PNCP document failures", file=sys.stderr)
                break
        else:
            consecutive_failures = 0

        for document in select_pncp_documents(documents):
            candidate = build_candidate(record, document)
            if candidate is None:
                continue
            url = str(candidate["url"])
            if url in seen_urls:
                print(f"Skipping duplicate PNCP PDF URL: {url}", file=sys.stderr)
                continue
            seen_urls.add(url)
            candidates.append(candidate)
    return page_failed


def _pncp_page_count(payload: Any) -> int | None:
    """``totalPaginas`` of a search envelope, or None when it is not usable."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("totalPaginas")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if _is_plain_int(value, 0) else None


def _sweep_search_page_failed(
    sweep: dict[str, Any], stats: dict[str, Any], *, index: int, page: int, limit: int
) -> int:
    """Count a failed search page; the page to resume at (next one once skipped)."""
    failures = sweep["page_failures"] + 1
    if failures < limit:
        sweep["page_failures"] = failures
        return page
    print(
        f"warning: skipping PNCP search page {page} of stream {index} after {failures} failed runs",
        file=sys.stderr,
    )
    sweep["page_failures"] = 0
    sweep["skipped_records"] = True
    stats["pncp_pages_skipped"] += 1
    return page + 1


def _discover_candidates_sweep() -> tuple[dict[str, Any], list[dict[str, Any]], datetime]:
    """One bounded run of the windowed, resumable PNCP sweep (durable mode).

    The position (``stream_index``, ``next_page``) only moves past a page whose
    records were all looked up, and is handed to the caller in
    ``stats["pncp_sweep"]``; the caller persists it after registering the
    descriptors. Caps are soft at page granularity: the current page is
    finished, then the run stops if work remains.
    """
    stats: dict[str, Any] = {
        "records": 0,
        "pre_download_rejected": 0,
        "document_lookups": 0,
        "candidates": 0,
        "document_failures": 0,
        "search_failures": 0,
        "candidate_cap_reached": 0,
        "pncp_pages_attempted": 0,
        "pncp_pages_completed": 0,
        "pncp_pages_skipped": 0,
        "pncp_overlap_skipped": 0,
        "pncp_page_rewinds": 0,
    }
    now_utc = datetime.now(timezone.utc)
    stored = _load_stored_cursor()
    prior = _stored_complete_watermark(stored)
    incremental = prior is not None

    sweep = _load_sweep_state(stored, now=now_utc)
    streams = _sweep_streams(sweep, incremental=incremental) if sweep else []
    if (
        sweep is None
        or sweep["streams"] != len(streams)
        or sweep["stream_index"] >= len(streams)
    ):
        sweep = _new_sweep(now_utc, prior)
        streams = _sweep_streams(sweep, incremental=incremental)
        sweep["streams"] = len(streams)
    resumed = (
        sweep["stream_index"], sweep["next_page"],
        sweep["page_failures"], sweep["skipped_records"],
    )
    cutoff = (
        _normalize_to_utc(parse_pncp_datetime(prior)) - PNCP_SWEEP_OVERLAP
        if prior is not None
        else None
    )

    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_controls: set[str] = set()
    search_deadline = time.monotonic() + PNCP_SEARCH_BUDGET_SECONDS
    index, page = sweep["stream_index"], sweep["next_page"]
    pages_run = 0
    done = False

    while True:
        if index >= len(streams):
            done = True
            break
        if time.monotonic() >= search_deadline:
            # A run bound, not a failure: the position is kept and work remains.
            stats["search_budget_exhausted"] = 1
            stats["page_cap_reached"] = stats["pncp_page_cap_reached"] = 1
            print("warning: PNCP search budget exhausted; sweep resumes next run", file=sys.stderr)
            break
        if stats["pncp_pages_attempted"] and PNCP_PAGE_DELAY_SECONDS > 0:
            time.sleep(PNCP_PAGE_DELAY_SECONDS)

        base_url, base_params = streams[index]
        params = {**base_params, "pagina": page, "tamanhoPagina": PNCP_PAGE_SIZE}
        stats["pncp_pages_attempted"] += 1
        try:
            payload = fetch_json(f"{base_url}?{urlencode(params)}")
        except Exception as exc:
            print(f"warning: PNCP sweep page {page} of stream {index} failed: {exc}", file=sys.stderr)
            stats["search_failures"] += 1
            status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
            if status == 429:
                # Rate limiting says nothing about the page: never skip it.
                stats["rate_limited"] = 1
            else:
                rejected = status is not None and 400 <= status < 500
                page = _sweep_search_page_failed(
                    sweep, stats, index=index, page=page,
                    limit=PNCP_SWEEP_PAGE_FAILURE_LIMIT if rejected else PNCP_SWEEP_OUTAGE_FAILURE_LIMIT,
                )
            break
        # Fail closed: an error body or a truncated envelope served with HTTP 200
        # must not read as an empty page, or the sweep would claim coverage. A
        # real empty window is the explicit envelope fetch_json builds for 204.
        page_records = payload.get("data") if isinstance(payload, dict) else None
        total_pages = _pncp_page_count(payload)
        if not isinstance(page_records, list) or total_pages is None:
            print(f"warning: PNCP sweep page {page} of stream {index} returned an invalid payload", file=sys.stderr)
            stats["search_failures"] += 1
            page = _sweep_search_page_failed(
                sweep, stats, index=index, page=page, limit=PNCP_SWEEP_PAGE_FAILURE_LIMIT,
            )
            break

        # A window that shrank moved later rows onto pages already visited, so
        # step back far enough to read them. Growth only repeats known rows.
        stream_total = payload.get("totalRegistros")
        known_total = sweep.get("stream_total")
        if _is_plain_int(stream_total, 0):
            sweep["stream_total"] = stream_total
            if page > 1 and _is_plain_int(known_total, 0) and stream_total < known_total:
                stats["pncp_page_rewinds"] += 1
                page = max(1, page - -(-(known_total - stream_total) // PNCP_PAGE_SIZE))
                # Failures were counted against the page we are leaving.
                sweep["page_failures"] = 0
                continue

        page_failed = _sweep_collect_page(
            page_records, stats=stats, candidates=candidates, seen_urls=seen_urls,
            seen_controls=seen_controls, cutoff=cutoff,
        )
        if page_failed:
            failures = sweep["page_failures"] + 1
            if failures < PNCP_SWEEP_PAGE_FAILURE_LIMIT:
                # Hold the position: this page is retried next run.
                sweep["page_failures"] = failures
                break
            print(
                f"warning: skipping PNCP page {page} of stream {index} after {failures} failed runs",
                file=sys.stderr,
            )
            sweep["skipped_records"] = True
            stats["pncp_pages_skipped"] += 1
        sweep["page_failures"] = 0
        stats["pncp_pages_completed"] += 1
        pages_run += 1

        if page >= total_pages:
            index, page = index + 1, 1
            sweep.pop("stream_total", None)
        else:
            page += 1
        if index >= len(streams):
            done = True
            break

        # Work remains: report the cap that stopped this run.
        if len(candidates) >= PNCP_MAX_CANDIDATES_PER_RUN:
            stats["candidate_cap_reached"] = 1
            print(f"Stopping after candidate cap {PNCP_MAX_CANDIDATES_PER_RUN}", file=sys.stderr)
        if stats["document_lookups"] >= PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN:
            stats["detail_cap_reached"] = 1
            print(f"warning: stopping after document lookup cap {PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN}", file=sys.stderr)
        if pages_run >= PNCP_MAX_PAGES_PER_RUN:
            stats["page_cap_reached"] = stats["pncp_page_cap_reached"] = 1
            print(f"Stopping after page cap {PNCP_MAX_PAGES_PER_RUN}", file=sys.stderr)
        if (stats["candidate_cap_reached"] or stats.get("detail_cap_reached")
                or stats.get("page_cap_reached")):
            break

    sweep["stream_index"], sweep["next_page"] = index, page
    if sweep["skipped_records"]:
        # A sweep that skipped records can never be recorded as complete.
        stats["partial_inventory"] = 1
    stats["candidates"] = len(candidates)
    stats["pncp_records_enumerated"] = stats["records"]
    versioned_stored = _stored_is_pncp_cursor(stored)
    stats["pncp_sweep"] = {
        "started_at": sweep["started_at"],
        "state": None if done else sweep,
        "done": done,
        "skipped_records": sweep["skipped_records"],
        "last_complete_update": prior,
        "stored_last_successful_update": (
            stored.get("last_successful_update")
            if isinstance(stored.get("last_successful_update"), str) else None
        ),
        "stored_counters": {
            field: stored[field] for field in _PNCP_COUNTER_FIELDS
            if versioned_stored and _is_plain_int(stored.get(field), 0)
        },
        "dirty": (index, page, sweep["page_failures"], sweep["skipped_records"]) != resumed,
    }
    return stats, candidates, now_utc


def _stored_is_pncp_cursor(cursor: dict[str, Any]) -> bool:
    import durable_source_work
    versioned, adapter, scope = durable_source_work.parse_collection_cursor(cursor)
    return versioned and adapter == "pncp" and scope == durable_source_work.PNCP_SCOPE


def _sweep_cursor(
    stats: dict[str, Any], sweep: dict[str, Any], registered: int, *, complete: bool
) -> dict[str, Any]:
    """PNCP cursor for one sweep run: progress while incomplete, else final.

    ``last_successful_update`` is the sweep start and never regresses, for
    progress and complete cursors alike. An incomplete cursor vouches for nothing
    (the prior watermark lives in ``last_complete_update``), and the complete one
    carrying the start means changes made during the sweep are re-read by the
    next incremental sweep. Counters are floored at the stored ones whenever the
    watermark is unchanged, which REPO_A requires; since each sweep moves the
    watermark, that floor lasts at most ``PNCP_SWEEP_MAX_AGE``, well inside the
    30 days after which REPO_A prunes the rows ``records_registered`` is
    checked against.
    """
    import durable_source_work
    started = sweep["started_at"]
    stored = sweep.get("stored_last_successful_update")
    watermark = stored if stored and _watermark_key(stored) > _watermark_key(started) else started
    values = {
        "records_enumerated": int(stats.get("records", 0) or 0),
        "records_registered": registered,
        "document_lookups_completed": int(stats.get("document_lookups", 0) or 0),
        "documents_selected": registered,
        "search_pages_completed": int(stats.get("pncp_pages_completed", 0) or 0),
    }
    if stored and _watermark_key(watermark) == _watermark_key(stored):
        for field, floor in (sweep.get("stored_counters") or {}).items():
            values[field] = max(values[field], floor)
    extra: dict[str, Any] = {}
    if not complete:
        extra = {"sweep": sweep["state"], "last_complete_update": sweep["last_complete_update"]}
    return durable_source_work.build_pncp_cursor(
        last_successful_update=watermark,
        search_truncated=not complete,
        complete=complete,
        **values,
        **extra,
    )


def discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]], datetime]:
    import durable_source_work
    if durable_source_work.enabled():
        return _discover_candidates_sweep()
    stats = {
        "records": 0,
        "pre_download_rejected": 0,
        "document_lookups": 0,
        "candidates": 0,
        "document_failures": 0,
        "search_failures": 0,
        "candidate_cap_reached": 0,
    }
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    consecutive_failures = 0

    records, discovery_time = fetch_pncp_records(stats=stats)
    stats["records"] = len(records)

    for record in records:
        if stats["document_lookups"] >= PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN:
            print(f"warning: stopping after document lookup cap {PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN}", file=sys.stderr)
            stats["detail_cap_reached"] = 1
            break

        if not validate_pncp_record_for_download(record):
            stats["pre_download_rejected"] += 1
            continue

        documents, failed = fetch_pncp_documents(record)
        stats["document_lookups"] += 1

        if failed:
            stats["document_failures"] += 1
            consecutive_failures += 1
            if consecutive_failures >= PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES:
                print("warning: stopping after consecutive PNCP document failures", file=sys.stderr)
                break
        else:
            consecutive_failures = 0

        for document in select_pncp_documents(documents):
            candidate = build_candidate(record, document)
            if candidate is None:
                continue
            url = str(candidate["url"])
            if url in seen_urls:
                print(f"Skipping duplicate PNCP PDF URL: {url}", file=sys.stderr)
                continue
            seen_urls.add(url)
            candidates.append(candidate)
            if len(candidates) >= PNCP_MAX_CANDIDATES_PER_RUN:
                stats["candidate_cap_reached"] = 1
                print(
                    f"Stopping after candidate cap {PNCP_MAX_CANDIDATES_PER_RUN}",
                    file=sys.stderr,
                )
                break

        if len(candidates) >= PNCP_MAX_CANDIDATES_PER_RUN:
            break

    stats["candidates"] = len(candidates)
    return stats, candidates, discovery_time


def submit_candidates(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """PNCP-flavoured wrapper around :func:`pipeline_core.submit_candidates`.

    Preserves the original ``submit_candidates(candidates)`` signature for
    backward compatibility with the existing test suite. New per-source
    discoverers should call ``pipeline_core.submit_candidates`` directly
    with their own ``source`` name.
    """
    return pipeline_core.submit_candidates(candidates, source="pncp")


def _main_impl(reporter: SourceRunReporter | None = None) -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2
    if PNCP_OPPORTUNITY_V2_ENABLED:
        if os.environ.get("SOURCE_WORK_ENABLED") == "true" and not PNCP_OPPORTUNITY_V2_SHADOW:
            print("Managed PNCP v2 ingestion is not enabled; use the validated candidate contract", file=sys.stderr)
            return 2
        return _main_opportunities()

    if os.environ.get("SOURCE_DRAIN_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:
        import durable_source_work
        if os.environ.get("SOURCE_WORK_ENABLED") != "true" or reporter is None:
            print("error: SOURCE_DRAIN_ONLY requires SOURCE_WORK_ENABLED=true and managed reporting", file=sys.stderr)
            return 2
        # Recovery drain: the spool is oldest-first, so pending work resumes
        # in registration order. No search-pagination position is restored
        # here; the stored versioned cursor keeps the last committed prefix
        # for the next collection cycle.
        try:
            failures = durable_source_work.drain("pncp", reporter, {})
        except AdmissionConflict as exc:
            if durable_source_work.abort_drain_on_lease_conflict(exc):
                return 1
            raise
        if failures or reporter.metrics.stats.get("cap_reached"):
            reporter.complete("warning")
        return 1 if failures else 0

    stats, candidates, discovery_time = discover_candidates()
    if reporter is not None:
        reporter.record_inventory(
            seen=int(stats.get("records", stats.get("candidates", 0)) or 0),
            in_scope=int(stats.get("candidates", 0) or 0),
            policy_rejected=int(stats.get("pre_download_rejected", 0) or 0) + int(stats.get("year_rejected", 0) or 0) + int(stats.get("prefilter_rejected", 0) or 0),
        )
        # Populate partial-inventory telemetry before any early return so a
        # failed search stream is never reported without its coverage flag.
        reporter.metrics.stats.update({
            "partial_inventory": bool(stats.get("search_failures")),
            "download_failures": int(stats.get("document_failures", 0) or 0),
        })
    print(f"PNCP discovery stats: {stats}")
    print(f"PNCP candidates discovered: {len(candidates)}")

    if not candidates and stats.get("search_failures", 0) > 0:
        print(
            "error: PNCP search failed and produced no candidates; "
            "treating as workflow failure instead of no eligible notices",
            file=sys.stderr,
        )
        if reporter is not None:
            reporter.metrics.stats["partial_inventory"] = True
            # Pages advanced before the failure stay advanced.
            sweep = stats.get("pncp_sweep")
            if sweep and sweep["dirty"]:
                import durable_source_work
                durable_source_work.register_collection(
                    "pncp", "candidate", [], stats, scope=durable_source_work.PNCP_SCOPE,
                    progress_cursor=_sweep_cursor(stats, sweep, 0, complete=False),
                )
        return 1

    import durable_source_work
    if durable_source_work.enabled() and reporter is not None:
        # Keep the previous completed watermark until this entire scan is
        # registered. Partial descriptor progress remains in the spool.
        watermark = discovery_time.isoformat()
        enumerated = int(stats.get("records", 0) or 0)
        lookups = int(stats.get("document_lookups", 0) or 0)
        pages_completed = int(stats.get("pncp_pages_completed", 0) or 0)
        truncated = bool(stats.get("page_cap_reached") or stats.get("search_failures"))
        sweep = stats.get("pncp_sweep")
        progress = (
            _sweep_cursor(stats, sweep, len(candidates), complete=False)
            if sweep and (sweep["dirty"] or sweep["skipped_records"])
            else None
        )

        def _pncp_cursor(prefix, complete):
            # Descriptors are durable independently. Only a fully registered,
            # uncapped scan may replace the last successful update watermark.
            if not complete:
                return None
            if sweep:
                return _sweep_cursor(stats, sweep, prefix, complete=True)
            return durable_source_work.build_pncp_cursor(
                last_successful_update=watermark,
                records_enumerated=enumerated,
                records_registered=prefix,
                document_lookups_completed=lookups,
                documents_selected=prefix,
                search_pages_completed=pages_completed,
                search_truncated=truncated,
                complete=complete,
            )

        complete = durable_source_work.register_collection(
            "pncp", "candidate", candidates, stats, scope=durable_source_work.PNCP_SCOPE,
            cursor_builder=_pncp_cursor, progress_cursor=progress,
        )
        if not complete:
            reporter.metrics.stats["partial_inventory"] = True
        try:
            failures = durable_source_work.drain("pncp", reporter, stats)
        except AdmissionConflict as exc:
            if durable_source_work.abort_drain_on_lease_conflict(exc):
                return 1
            raise
        if not complete or failures or reporter.metrics.stats.get("cap_reached"):
            reporter.complete("warning")
        return 1 if failures else 0

    if not candidates:
        print("No new candidates to submit")
        return 0

    _ocr_config, extractor = pipeline_core.make_default_ocr_extractor()
    max_pdf_bytes = pipeline_core.SCRAPE_MAX_PDF_BYTES

    processed: list[dict[str, Any]] = []
    successful_results = 0
    for candidate in candidates:
        if len(processed) >= PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN:
            stats["processing_cap_reached"] = 1
            print(
                f"Stopping after processing cap {PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN}",
                file=sys.stderr,
            )
            break
        if pipeline_core.pdf_download_limit_reached(stats):
            stats["pdf_download_cap_reached"] = 1
            print(
                f"Stopping after PDF download cap {pipeline_core.SCRAPE_MAX_PDFS_PER_RUN}",
                file=sys.stderr,
            )
            break

        result = process_candidate(
            candidate,
            extractor=extractor,
            max_bytes=max_pdf_bytes,
        )
        processed.append(result)
        if result.get("worker_result"):
            pipeline_core.record_pdf_download(stats)
            successful_results += 1
            if successful_results >= PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN:
                stats["submittable_cap_reached"] = 1
                print(
                    "Stopping after submittable candidate cap "
                    f"{PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN}",
                    file=sys.stderr,
                )
                break

    stats["processed"] = len(processed)
    stats["ocr_successes"] = sum(1 for r in processed if r.get("worker_result"))
    # Downloads and OCR are distinct facts: a "download:" error consumed no
    # bytes, an "ocr:" error downloaded but failed extraction.
    stats["download_failures"] = sum(
        1 for r in processed
        if not r.get("worker_result") and not str(r.get("error", "")).startswith("ocr:")
    )
    stats["ocr_failures"] = sum(
        1 for r in processed if str(r.get("error", "")).startswith("ocr:")
    )
    if reporter is not None:
        reporter.record_downloads(
            stats["ocr_successes"] + stats["ocr_failures"], stats.get("ocr_successes", 0)
        )
        reporter.metrics.stats.update({
            "cap_reached": bool(
                stats.get("processing_cap_reached")
                or stats.get("pdf_download_cap_reached")
                or stats.get("submittable_cap_reached")
            ),
            # A failed search stream leaves the declared scope uncovered.
            "partial_inventory": bool(stats.get("search_failures")),
            "download_failures": stats["download_failures"],
            "ocr_failures": stats["ocr_failures"],
        })
    print(f"PNCP processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered PNCP candidates failed download/OCR; "
            "nothing will be submitted and checkpoint will not advance",
            file=sys.stderr,
        )
        return 1

    result = submit_candidates(processed)
    if reporter is not None:
        counts = result.get("outcome_counts", {})
        reporter.record_submission_outcomes(
            inserted=counts.get("inserted", 0), updated=counts.get("updated", 0),
            reactivated=counts.get("reactivated", 0), duplicates=counts.get("duplicates", 0),
            errors=counts.get("invalid", 0) + result.get("failed_batches", 0),
        )
        reporter.metrics.stats["submission_failures"] = counts.get("invalid", 0) + result.get("failed_batches", 0)
    print(f"Render candidate submission: {result}")

    if candidates and result.get("submitted", 0) == 0:
        print(
            "error: discovered PNCP candidates produced no Render submissions; "
            "checkpoint will not advance",
            file=sys.stderr,
        )
        return 1

    if result.get("failed_batches", 0) == 0:
        _save_update_checkpoint(discovery_time)

    return 0


def main() -> int:
    reporter = SourceRunReporter(source_key="pncp")
    result = 1
    try:
        with reporter:
            result = _main_impl(reporter)
            if result != 0:
                reporter.record_error("scraping_failed")
                reporter.complete("failed")
    except Exception:
        reporter.record_error("scraping_failed")
        reporter.complete("failed")
        raise
    finally:
        if reporter.telemetry_failed:
            # Preserve the primary ingestion result, but make telemetry failure
            # observable to Actions.
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
