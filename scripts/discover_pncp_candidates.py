from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests


RENDER_SUBMIT_BATCH_SIZE = int(os.environ.get("RENDER_SUBMIT_BATCH_SIZE", "30"))
RENDER_SUBMIT_TIMEOUT = int(os.environ.get("RENDER_SUBMIT_TIMEOUT", "90"))
RENDER_SUBMIT_MAX_ATTEMPTS = int(os.environ.get("RENDER_SUBMIT_MAX_ATTEMPTS", "4"))
RENDER_SUBMIT_BACKOFF_BASE = float(os.environ.get("RENDER_SUBMIT_BACKOFF_BASE", "5"))

PNCP_DEDUP_CACHE_PATH = os.environ.get(
    "PNCP_DEDUP_CACHE_PATH", ".cache/pncp_submitted_urls.json"
)
PNCP_DEDUP_CACHE_TTL_DAYS = int(os.environ.get("PNCP_DEDUP_CACHE_TTL_DAYS", "7"))


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
PNCP_DOCS_BASE_URL = "https://pncp.gov.br/api/pncp/v1"
PNCP_DEFAULT_MODALITY_CODES = ("5", "6", "10")
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


def fetch_json(url: str, *, timeout: int = 30) -> Any:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_pncp_search_pages(base_url: str, base_params: dict[str, str | int]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1

    while page <= PNCP_MAX_PAGES_PER_QUERY:
        params = {**base_params, "pagina": page, "tamanhoPagina": PNCP_PAGE_SIZE}
        url = f"{base_url}?{urlencode(params)}"
        try:
            payload = fetch_json(url)
        except Exception as exc:
            print(f"warning: skipping PNCP search page {page} from {base_url}: {exc}", file=sys.stderr)
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


def fetch_pncp_records() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    publication_start = (today - timedelta(days=PNCP_LOOKBACK_DAYS)).strftime("%Y%m%d")
    today_str = today.strftime("%Y%m%d")
    proposal_end = (today + timedelta(days=PNCP_PROPOSTA_FORWARD_DAYS)).strftime("%Y%m%d")

    raw_records: list[dict[str, Any]] = []
    raw_records.extend(
        fetch_pncp_search_pages(
            PNCP_PROPOSTA_URL,
            {"dataInicial": today_str, "dataFinal": proposal_end},
        )
    )
    for modality_code in PNCP_DEFAULT_MODALITY_CODES:
        raw_records.extend(
            fetch_pncp_search_pages(
                PNCP_API_URL,
                {
                    "dataInicial": publication_start,
                    "dataFinal": today_str,
                    "codigoModalidadeContratacao": modality_code,
                },
            )
        )

    records: list[dict[str, Any]] = []
    seen_control_numbers: set[str] = set()
    for record in raw_records:
        control_number = str(record.get("numeroControlePNCP") or "")
        if control_number and control_number in seen_control_numbers:
            continue
        if control_number:
            seen_control_numbers.add(control_number)
        records.append(record)
    return records


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


def load_dedup_cache() -> dict[str, str]:
    try:
        with open(PNCP_DEDUP_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        if not isinstance(exc, FileNotFoundError):
            print(f"warning: discarding corrupt PNCP dedup cache: {exc}", file=sys.stderr)
        return {}
    if not isinstance(payload, dict):
        print("warning: PNCP dedup cache root was not an object; discarding", file=sys.stderr)
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def save_dedup_cache(cache: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(PNCP_DEDUP_CACHE_PATH) or ".", exist_ok=True)
    tmp_path = f"{PNCP_DEDUP_CACHE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, PNCP_DEDUP_CACHE_PATH)


def filter_cached_candidates(
    candidates: list[dict[str, Any]], cache: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    now = datetime.now(timezone.utc)
    ttl = timedelta(days=PNCP_DEDUP_CACHE_TTL_DAYS)
    kept: list[dict[str, Any]] = []
    skipped = 0
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        cached_at_raw = cache.get(url)
        if cached_at_raw:
            try:
                cached_at = datetime.fromisoformat(cached_at_raw)
            except ValueError:
                cached_at = None
            if cached_at is None or (now - cached_at) <= ttl:
                skipped += 1
                continue
        kept.append(candidate)
    return kept, skipped


def record_submitted_urls(
    cache: dict[str, str], candidates: list[dict[str, Any]]
) -> dict[str, str]:
    now_iso = datetime.now(timezone.utc).isoformat()
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        if url:
            cache[url] = now_iso
    return cache


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
        "cnpj": orgao.get("cnpj") if isinstance(orgao, dict) else None,
        "tipoDocumentoNome": document.get("tipoDocumentoNome"),
        "titulo": document.get("titulo") or "",
        "sequencialDocumento": document.get("sequencialDocumento"),
        "priority": pncp_document_priority(document),
        "objetoCompra": record.get("objetoCompra") or "",
        "modalidadeNome": record.get("modalidadeNome") or "",
        "dataEncerramentoProposta": record.get("dataEncerramentoProposta"),
        "dataPublicacaoPncp": record.get("dataPublicacaoPncp"),
        "municipioNome": unidade.get("municipioNome") if isinstance(unidade, dict) else None,
        "ufSigla": unidade.get("ufSigla") if isinstance(unidade, dict) else None,
    }
    return {"url": url.strip(), "kind": "pdf", "metadata": metadata}


def discover_candidates() -> tuple[dict[str, int], list[dict[str, Any]]]:
    stats = {
        "records": 0,
        "document_lookups": 0,
        "candidates": 0,
        "document_failures": 0,
    }
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    consecutive_failures = 0

    records = fetch_pncp_records()
    stats["records"] = len(records)

    for record in records:
        if stats["document_lookups"] >= PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN:
            print(f"warning: stopping after document lookup cap {PNCP_MAX_DOCUMENT_LOOKUPS_PER_RUN}", file=sys.stderr)
            break

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
                continue
            seen_urls.add(url)
            candidates.append(candidate)

    stats["candidates"] = len(candidates)
    return stats, candidates


def _is_retryable_response(response: requests.Response) -> bool:
    return response.status_code in (408, 425, 429, 500, 502, 503, 504)


def _post_batch(
    render_url: str,
    token: str,
    batch: list[dict[str, Any]],
    batch_index: int,
    total_batches: int,
) -> tuple[dict[str, Any] | None, str | None]:
    url = f"{render_url}/api/pipeline/candidates"
    last_error: str | None = None

    for attempt in range(1, RENDER_SUBMIT_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"source": "pncp", "candidates": batch},
                timeout=RENDER_SUBMIT_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"warning: Render submit batch {batch_index}/{total_batches} "
                f"attempt {attempt}/{RENDER_SUBMIT_MAX_ATTEMPTS} failed: {last_error}",
                file=sys.stderr,
            )
            if attempt < RENDER_SUBMIT_MAX_ATTEMPTS:
                time.sleep(RENDER_SUBMIT_BACKOFF_BASE ** attempt)
            continue

        if response.status_code >= 500 or _is_retryable_response(response):
            last_error = f"HTTP {response.status_code}"
            print(
                f"warning: Render submit batch {batch_index}/{total_batches} "
                f"attempt {attempt}/{RENDER_SUBMIT_MAX_ATTEMPTS} returned {last_error}",
                file=sys.stderr,
            )
            if attempt < RENDER_SUBMIT_MAX_ATTEMPTS:
                time.sleep(RENDER_SUBMIT_BACKOFF_BASE ** attempt)
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            last_error = f"HTTP {exc.response.status_code if exc.response is not None else '?'}"
            print(
                f"error: Render submit batch {batch_index}/{total_batches} "
                f"non-retryable failure: {last_error}",
                file=sys.stderr,
            )
            return None, last_error

        try:
            return response.json(), None
        except ValueError:
            return {"status": "accepted"}, None

    return None, last_error


def submit_candidates(
    candidates: list[dict[str, Any]], cache: dict[str, str] | None = None
) -> dict[str, Any]:
    render_url = os.environ["RENDER_APP_URL"].rstrip("/")
    token = os.environ["PIPELINE_SECRET"]

    batches = [
        candidates[i : i + RENDER_SUBMIT_BATCH_SIZE]
        for i in range(0, len(candidates), RENDER_SUBMIT_BATCH_SIZE)
    ]
    total_batches = len(batches)

    submitted = 0
    failed_batches: list[str] = []
    last_result: dict[str, Any] | None = None

    for index, batch in enumerate(batches, start=1):
        result, error = _post_batch(render_url, token, batch, index, total_batches)
        if error is None:
            submitted += len(batch)
            last_result = result
            if cache is not None:
                record_submitted_urls(cache, batch)
            print(
                f"Render submit batch {index}/{total_batches}: "
                f"{len(batch)} candidates accepted"
            )
        else:
            failed_batches.append(f"batch {index}/{total_batches} ({len(batch)}): {error}")

    summary = {
        "total": len(candidates),
        "submitted": submitted,
        "failed_batches": len(failed_batches),
        "errors": failed_batches,
        "last_result": last_result,
    }

    if submitted == 0 and failed_batches:
        raise RuntimeError(
            f"All {len(failed_batches)} Render submit batches failed: "
            + "; ".join(failed_batches)
        )
    if failed_batches:
        print(
            f"warning: {len(failed_batches)}/{total_batches} Render submit batches failed",
            file=sys.stderr,
        )

    return summary


def main() -> int:
    if not os.environ.get("RENDER_APP_URL"):
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not os.environ.get("PIPELINE_SECRET"):
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2

    stats, candidates = discover_candidates()
    print(f"PNCP discovery stats: {stats}")
    print(f"PNCP candidates discovered: {len(candidates)}")

    cache = load_dedup_cache()
    print(f"PNCP dedup cache loaded: {len(cache)} entries")

    candidates, cached_skipped = filter_cached_candidates(candidates, cache)
    if cached_skipped:
        print(f"PNCP candidates skipped (already submitted within TTL): {cached_skipped}")
    print(f"PNCP candidates to submit: {len(candidates)}")

    stats["cached_skipped"] = cached_skipped
    stats["to_submit"] = len(candidates)

    if not candidates:
        print("No new candidates to submit")
        return 0

    result = submit_candidates(candidates, cache)
    save_dedup_cache(cache)
    print(f"PNCP dedup cache saved: {len(cache)} entries at {PNCP_DEDUP_CACHE_PATH}")
    print(f"Render candidate submission: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
