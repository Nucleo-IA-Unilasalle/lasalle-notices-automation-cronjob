from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests

import pipeline_core
from pncp_filters import DROP_EXPIRED, FEDERAL_CNPJS, UF_FILTER
from pipeline_core import process_candidate


# Re-exports for callers (and existing tests) that still import these
# submit-side knobs from this module. They now live in pipeline_core so
# future per-source discoverers can use the same constants.
RENDER_SUBMIT_BATCH_SIZE = pipeline_core.RENDER_SUBMIT_BATCH_SIZE
RENDER_SUBMIT_TIMEOUT = pipeline_core.RENDER_SUBMIT_TIMEOUT
RENDER_SUBMIT_MAX_ATTEMPTS = pipeline_core.RENDER_SUBMIT_MAX_ATTEMPTS
RENDER_SUBMIT_BACKOFF_BASE = pipeline_core.RENDER_SUBMIT_BACKOFF_BASE
RENDER_SUBMIT_MAX_MARKDOWN_CHARS = pipeline_core.RENDER_SUBMIT_MAX_MARKDOWN_CHARS

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
PNCP_UPDATE_CHECKPOINT_PATH = os.environ.get(
    "PNCP_UPDATE_CHECKPOINT_PATH", ".cache/pncp_update_checkpoint.json"
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

PNCP_LOOKBACK_DAYS = int(os.environ.get("PNCP_LOOKBACK_DAYS", "30"))
PNCP_PROPOSTA_FORWARD_DAYS = int(os.environ.get("PNCP_PROPOSTA_FORWARD_DAYS", "60"))
PNCP_MAX_PAGES_PER_QUERY = int(os.environ.get("PNCP_MAX_PAGES_PER_QUERY", "20"))
PNCP_PAGE_SIZE = int(os.environ.get("PNCP_PAGE_SIZE", "50"))
PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN = int(os.environ.get("PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN", "100"))
PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES = int(os.environ.get("PNCP_MAX_CONSECUTIVE_DOCUMENT_FAILURES", "10"))
PNCP_MIN_NOTICE_YEAR = int(os.environ.get("PNCP_MIN_NOTICE_YEAR", "2026"))
PNCP_MAX_CANDIDATES_PER_RUN = int(os.environ.get("PNCP_MAX_CANDIDATES_PER_RUN", "10"))
PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN = int(os.environ.get("PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN", "20"))
PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN = int(os.environ.get("PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN", "5"))
PNCP_FETCH_MAX_ATTEMPTS = int(os.environ.get("PNCP_FETCH_MAX_ATTEMPTS", "3"))
PNCP_FETCH_BACKOFF_SECONDS = float(os.environ.get("PNCP_FETCH_BACKOFF_SECONDS", "2"))
PNCP_FETCH_TIMEOUT_SECONDS = int(os.environ.get("PNCP_FETCH_TIMEOUT_SECONDS", "8"))


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
                    time.sleep(sleep_seconds)
                    continue
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt >= PNCP_FETCH_MAX_ATTEMPTS:
                raise
            time.sleep(PNCP_FETCH_BACKOFF_SECONDS * attempt)

    raise RuntimeError("unreachable PNCP fetch retry state")


def fetch_pncp_search_pages(
    base_url: str,
    base_params: dict[str, str | int],
    *,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1

    while page <= PNCP_MAX_PAGES_PER_QUERY:
        params = {**base_params, "pagina": page, "tamanhoPagina": PNCP_PAGE_SIZE}
        url = f"{base_url}?{urlencode(params)}"
        try:
            payload = fetch_json(url)
        except Exception as exc:
            print(f"warning: skipping PNCP search page {page} from {base_url}: {exc}", file=sys.stderr)
            if stats is not None:
                stats["search_failures"] = stats.get("search_failures", 0) + 1
            break

        if not isinstance(payload, dict):
            print(f"warning: PNCP search page {page} returned non-object payload", file=sys.stderr)
            break

        page_records = payload.get("data", [])
        if isinstance(page_records, list):
            records.extend(record for record in page_records if isinstance(record, dict))

        total_pages = payload.get("totalPaginas") or page
        try:
            total_pages_int = int(total_pages)
        except (TypeError, ValueError):
            total_pages_int = page

        if page >= total_pages_int:
            break
        page += 1

    return records


BRASILIA_OFFSET = timezone(timedelta(hours=-3))
_UPDATE_FORMAT = "%Y%m%d%H%M%S"
_ATUALIZACAO_OVERLAP_DAYS = 1
_ATUALIZACAO_INITIAL_LOOKBACK_DAYS = 2


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
) -> list[dict[str, Any]]:
    """Hit /proposta, /publicacao (per modality), and /atualizacao (per modality) with the given params."""
    out: list[dict[str, Any]] = []
    out.extend(
        fetch_pncp_search_pages(
            PNCP_PROPOSTA_URL,
            {**base_params, "dataInicial": today_str, "dataFinal": proposal_end},
            stats=stats,
        )
    )
    for modality_code in PNCP_DEFAULT_MODALITY_CODES:
        out.extend(
            fetch_pncp_search_pages(
                PNCP_API_URL,
                {
                    **base_params,
                    "dataInicial": publication_start,
                    "dataFinal": today_str,
                    "codigoModalidadeContratacao": modality_code,
                },
                stats=stats,
            )
        )
        out.extend(
            fetch_pncp_search_pages(
                PNCP_ATUALIZACAO_URL,
                {
                    **base_params,
                    "dataInicial": overlap_start_str,
                    "dataFinal": today_str,
                    "codigoModalidadeContratacao": modality_code,
                },
                stats=stats,
            )
        )
    return out


def fetch_pncp_records(
    stats: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], datetime]:
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
            stats=stats,
        )
    )

    for cnpj in federal_cnpjs:
        raw_records.extend(
            _scrape_three_endpoints(
                {"cnpj": cnpj},
                today_str=today_str,
                proposal_end=proposal_end,
                publication_start=publication_start,
                overlap_start_str=overlap_start_str,
                stats=stats,
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


def discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]], datetime]:
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


def main() -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates, discovery_time = discover_candidates()
    print(f"PNCP discovery stats: {stats}")
    print(f"PNCP candidates discovered: {len(candidates)}")

    if not candidates and stats.get("search_failures", 0) > 0:
        print(
            "error: PNCP search failed and produced no candidates; "
            "treating as workflow failure instead of no eligible notices",
            file=sys.stderr,
        )
        return 1

    if not candidates:
        print("No new candidates to submit")
        return 0

    from ocr_worker.ocr_extraction_config import OCRExtractionConfig
    from ocr_worker.pdf_markdown_extractor import PDFMarkdownExtractor

    ocr_config = OCRExtractionConfig(
        language=os.getenv("KREUZBERG_PADDLE_LANGUAGE", "latin"),
        model_tier=os.getenv("KREUZBERG_PADDLE_MODEL_TIER", "tiny"),
        use_gpu=os.getenv("KREUZBERG_USE_GPU", "false").lower() == "true",
        force_ocr=os.getenv("KREUZBERG_FORCE_OCR_DEFAULT", "false").lower() == "true",
        extraction_timeout_seconds=int(os.getenv("KREUZBERG_EXTRACTION_TIMEOUT_SECONDS", "300")),
    )
    extractor = PDFMarkdownExtractor(ocr_config=ocr_config)
    max_pdf_bytes = pipeline_core.SCRAPE_MAX_PDF_BYTES

    processed: list[dict[str, Any]] = []
    submit_ready = 0
    for candidate in candidates:
        if len(processed) >= PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN:
            stats["processing_cap_reached"] = 1
            print(
                f"Stopping after processing cap {PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN}",
                file=sys.stderr,
            )
            break
        if submit_ready >= PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN:
            stats["submit_ready_cap_reached"] = 1
            print(
                f"Stopping after submit-ready cap {PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN}",
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
            submit_ready += 1

    stats["processed"] = len(processed)
    stats["ocr_successes"] = sum(1 for r in processed if r.get("worker_result"))
    stats["ocr_failures"] = sum(1 for r in processed if r.get("error"))
    print(f"PNCP processing stats: {stats}")

    if candidates and stats["ocr_successes"] == 0:
        print(
            "error: all discovered PNCP candidates failed download/OCR; "
            "nothing will be submitted and checkpoint will not advance",
            file=sys.stderr,
        )
        return 1

    result = submit_candidates(processed)
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


if __name__ == "__main__":
    raise SystemExit(main())
