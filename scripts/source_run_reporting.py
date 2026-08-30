from __future__ import annotations
import os
import time
import logging
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import requests

logger = logging.getLogger("source_run_reporting")

CONTRACT_VERSION = 1

# Códigos transitórios que merecem retry: rate limit e 5xx do servidor.
# 4xx definitivos (401/403/404/409/422) falham imediatamente — repetir
# divergência de contrato só agrava e consome o orçamento do workflow.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class _TelemetryCircuitBreaker:
    """Disjuntor compartilhado por processo (todas as fontes do workflow).

    Após 3 falhas transitórias consecutivas, desiste imediatamente pelo restante
    da execução: sem ele, 12 fontes × (POST ~51s + PATCH ~66s) ultrapassariam o
    timeout de 20 minutos do job sem contar a coleta. Uma resposta definitiva
    do backend antes da abertura (inclusive 4xx) comprova disponibilidade e
    zera a sequência. Depois de aberto, o disjuntor permanece aberto até o fim
    do processo; não existe probe/half-open durante este job curto.
    """

    FAILURE_THRESHOLD = 3

    def __init__(self) -> None:
        self.consecutive_failures = 0
        self.tripped = False

    def record_available(self) -> None:
        """Registra backend alcançável sem reabrir um breaker já disparado."""
        if self.tripped:
            return
        self.consecutive_failures = 0

    def record_transient_failure(self) -> None:
        """Conta somente rede, 429 ou 5xx após esgotar os retries."""
        if self.tripped:
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.FAILURE_THRESHOLD:
            self.tripped = True

    @property
    def open(self) -> bool:
        return self.tripped


_process_breaker = _TelemetryCircuitBreaker()

# Allowlist v1: somente estas chaves/tipos são aceitas em `stats`. Qualquer
# outra chave é descartada com warning (contrato compartilhado com o backend,
# que aplica a MESMA allowlist no DTO — ver Plano 04).
SAFE_STATS_SCHEMA = {
    "cap_reached": bool,
    "partial_inventory": bool,
    "parser_failures": int,
    "download_failures": int,
    "ocr_failures": int,
    "submission_failures": int,
}

def sanitize_stats(stats: dict[str, Any]) -> dict[str, int | bool]:
    """Mantém somente chaves e tipos escalares definidos no contrato v1."""
    sanitized: dict[str, int | bool] = {}
    for key, value in stats.items():
        expected_type = SAFE_STATS_SCHEMA.get(key)
        if expected_type is None:
            logger.warning("Chave fora da allowlist ignorada em stats: %s", key)
            continue
        if type(value) is not expected_type:
            continue
        sanitized[key] = max(0, value) if expected_type is int else value
    return sanitized

@dataclass
class SourceRunMetrics:
    inventory_seen: int = 0
    in_scope: int = 0
    policy_rejected: int = 0
    documents_downloaded: int = 0
    ocr_succeeded: int = 0
    submitted: int = 0
    inserted: int = 0
    updated: int = 0
    reactivated: int = 0
    duplicates: int = 0
    errors: int = 0
    fidelity_blockers: int = 0
    error_code: Optional[str] = None
    stats: dict[str, Any] = field(default_factory=dict)

def _enabled(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}

class SourceRunReporter:
    """Gerencia o ciclo de vida e relato de telemetria de uma execução por fonte."""

    def __init__(
        self,
        source_key: str,
        *,
        backend_url: Optional[str] = None,
        pipeline_secret: Optional[str] = None,
        workflow_name: Optional[str] = None,
        trigger_kind: Optional[str] = None,
    ) -> None:
        self.source_key = source_key
        # Flag default-false: telemetria desligada não altera a ingestão nem
        # exige callbacks — é o lever de rollback do Plano 07.
        self.enabled = _enabled(os.getenv("SOURCE_RUN_REPORTING_ENABLED", "false"))
        self.backend_url = (backend_url or os.getenv("RENDER_APP_URL", "")).rstrip("/")
        self.pipeline_secret = pipeline_secret or os.getenv("PIPELINE_SECRET", "")
        self.workflow_name = workflow_name or os.getenv("GITHUB_WORKFLOW", "manual-pipeline")
        # trigger_kind derivado do ambiente (overridable para audit/backfill)
        if trigger_kind is not None:
            self.trigger_kind = trigger_kind
        elif "GITHUB_RUN_ID" not in os.environ:
            self.trigger_kind = "local"
        elif os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
            self.trigger_kind = "manual"
        else:
            self.trigger_kind = "schedule"
        self.started_at = datetime.now(timezone.utc)

        # Identidade externa: repositório + run + tentativa + fonte (SHA-256 para
        # caber em 160 chars). Dois entrypoints preservam o mesmo source_key;
        # workflow_name é apenas diagnóstico.
        run_id = os.getenv("GITHUB_RUN_ID")
        attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
        server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
        repo = os.getenv("GITHUB_REPOSITORY", "Nucleo-IA-Unilasalle/lasalle-notices-automation-cronjob")
        if run_id:
            identity = f"{repo}:{run_id}:{attempt}:{source_key}"
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            self.external_run_id = f"github:{digest}"
            self.run_url = f"{server_url}/{repo}/actions/runs/{run_id}"
        else:
            # UUID estável durante a vida do processo local
            self.external_run_id = f"local:{uuid.uuid4()}"
            self.run_url = None

        self.run_uuid: Optional[str] = None
        self.metrics = SourceRunMetrics()
        self._terminal_status: Optional[str] = None  # Intenção de estado terminal
        self._is_completed: bool = False             # Confirmação de entrega do PATCH
        self._start_retried: bool = False            # complete() só repete start() 1x
        self._delivery_attempted: bool = False       # __exit__ não repete entrega falha
        self.telemetry_failed: bool = False

    def __enter__(self) -> "SourceRunReporter":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._is_completed:
            return
        if exc_type is not None:
            # Exceção não tratada => failed. A intenção fica registrada mesmo que
            # a entrega falhe; __exit__ nunca recria status divergente.
            if self.metrics.error_code is None:
                self.record_error(error_code="unhandled_exception")
            self.complete(status="failed")
        elif not self._delivery_attempted:
            # Nenhuma entrega foi tentada ainda (fluxo normal sem complete()
            # explícito): deriva o status das métricas. Se a entrega JÁ foi
            # tentada e falhou por rede, não repetimos aqui — o orçamento de
            # retries pertence a complete(); o workflow registra
            # telemetry_failed e encerra o run como não-reportado.
            target_status = self._terminal_status or (
                "warning" if (self.metrics.errors > 0 or self.metrics.fidelity_blockers > 0) else "success"
            )
            self.complete(status=target_status)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.pipeline_secret}",
            "Content-Type": "application/json",
            "X-Contract-Version": str(CONTRACT_VERSION),
        }

    def start(self) -> None:
        """Notifica o backend com a chave idempotente; retry apenas para falhas transitórias."""
        if not self.enabled:
            return
        if not self.pipeline_secret or not self.backend_url:
            self.telemetry_failed = True
            logger.error("Telemetria habilitada sem RENDER_APP_URL/PIPELINE_SECRET.")
            return
        if _process_breaker.open:
            # Disjuntor aberto: backend comprovadamente indisponível; não
            # gastamos timeout das fontes restantes do workflow.
            self.telemetry_failed = True
            logger.warning("Disjuntor de telemetria aberto; source run não reportado.")
            return
        endpoint = f"{self.backend_url}/api/pipeline/source-runs"
        payload = {
            "source_key": self.source_key,
            "external_run_id": self.external_run_id,
            "workflow_name": self.workflow_name,
            "run_url": self.run_url,
            "trigger_kind": self.trigger_kind,
            "started_at": self.started_at.isoformat(),
            "contract_version": CONTRACT_VERSION,
        }
        availability_failed = False
        for attempt in range(1, 4):
            retryable = False
            try:
                resp = requests.post(endpoint, json=payload, headers=self._headers(), timeout=15)
                if resp.status_code in (200, 201):
                    try:
                        body = resp.json()
                    except (ValueError, TypeError, AttributeError):
                        # O backend respondeu, mas violou o contrato: falha
                        # definitiva desta entrega, não indisponibilidade.
                        _process_breaker.record_available()
                        logger.warning("Resposta inválida ao iniciar source run.")
                        break
                    self.run_uuid = body.get("id") if isinstance(body, dict) else None
                    if self.run_uuid:
                        self.telemetry_failed = False
                        _process_breaker.record_available()
                        return
                    logger.warning("run id ausente na resposta do backend")
                if resp.status_code not in (200, 201):
                    logger.warning("Falha HTTP %s ao iniciar source run", resp.status_code)
                # 4xx definitivo (exceto 429): não repetir — divergência de
                # contrato persiste entre tentativas. Qualquer resposta HTTP
                # definitiva comprova disponibilidade e não alimenta o breaker.
                retryable = resp.status_code in RETRYABLE_STATUS
                availability_failed = retryable
                if not retryable:
                    _process_breaker.record_available()
            except requests.RequestException:
                retryable = True
                availability_failed = True
                logger.warning("Resposta inválida ou falha de rede ao iniciar source run (tentativa %s)", attempt)
            if not retryable:
                break
            if attempt < 3:
                time.sleep(2 ** attempt)
        self.telemetry_failed = True
        if availability_failed:
            # Uma entrega esgotada conta uma vez, não uma vez por tentativa.
            _process_breaker.record_transient_failure()

    def record_inventory(self, seen: int, in_scope: int, policy_rejected: int) -> None:
        self.metrics.inventory_seen = max(0, seen)
        self.metrics.in_scope = max(0, in_scope)
        self.metrics.policy_rejected = max(0, policy_rejected)

    def record_downloads(self, downloaded: int, ocr_ok: int) -> None:
        self.metrics.documents_downloaded += max(0, downloaded)
        self.metrics.ocr_succeeded += max(0, ocr_ok)

    def record_submission_outcomes(
        self, inserted: int = 0, updated: int = 0, reactivated: int = 0, duplicates: int = 0, errors: int = 0
    ) -> None:
        inserted = max(0, inserted)
        updated = max(0, updated)
        reactivated = max(0, reactivated)
        duplicates = max(0, duplicates)
        self.metrics.inserted += inserted
        self.metrics.updated += updated
        self.metrics.reactivated += reactivated
        self.metrics.duplicates += duplicates
        self.metrics.errors += max(0, errors)
        # submitted = outcomes persistidos/aceitos (never "tentados")
        self.metrics.submitted += (inserted + updated + reactivated + duplicates)

    def record_fidelity_blockers(self, count: int) -> None:
        self.metrics.fidelity_blockers += max(0, count)

    def record_error(self, error_code: str) -> None:
        """First-error-wins para o código; TODA chamada incrementa `errors`.
        Sem o incremento, __exit__ derivaria 'success' para runs com falha."""
        if self.metrics.error_code is None:
            self.metrics.error_code = error_code
        self.metrics.errors += 1

    def complete(self, status: str = "success") -> None:
        """Registra a intenção terminal e finaliza o run com retries/backoff.

        Orçamento pior caso com backend indisponível: a 3ª falha consecutiva
        de entrega abre o disjuntor compartilhado (_TelemetryCircuitBreaker) e
        as fontes restantes pulam telemetria imediatamente (sem timeout). Com
        12 fontes, o gasto total fica limitado a ~3 fontes × ~2 min ≈ 6 min —
        dentro do `timeout-minutes: 20` do job, contando a coleta. Retries
        acontecem apenas para rede, 429 e 5xx; 4xx definitivos abortam na
        primeira tentativa. `start()` só é reexecutado uma vez por processo
        (_start_retried) e `__exit__` não repete entrega já tentada
        (_delivery_attempted).
        """
        if status not in {"success", "warning", "failed", "cancelled"}:
            raise ValueError(f"Invalid terminal source-run status: {status}")
        if self._delivery_attempted and not self._is_completed:
            return
        self._terminal_status = status
        if self._is_completed or not self.enabled:
            return
        self._delivery_attempted = True
        if not self.run_uuid:
            # POST inicial falhou (rede); recuperação única — start() só é
            # reexecutado uma vez por processo, e apenas se nunca obteve uuid.
            if not self._start_retried:
                self._start_retried = True
                self.start()
        if not self.run_uuid:
            self.telemetry_failed = True
            return
        if _process_breaker.open:
            self.telemetry_failed = True
            logger.warning("Disjuntor de telemetria aberto; finalização não enviada.")
            return

        endpoint = f"{self.backend_url}/api/pipeline/source-runs/{self.run_uuid}"
        payload = {
            "status": status,
            "inventory_seen": self.metrics.inventory_seen,
            "in_scope": self.metrics.in_scope,
            "policy_rejected": self.metrics.policy_rejected,
            "documents_downloaded": self.metrics.documents_downloaded,
            "ocr_succeeded": self.metrics.ocr_succeeded,
            "submitted": self.metrics.submitted,
            "inserted": self.metrics.inserted,
            "updated": self.metrics.updated,
            "reactivated": self.metrics.reactivated,
            "duplicates": self.metrics.duplicates,
            "errors": self.metrics.errors,
            "fidelity_blockers": self.metrics.fidelity_blockers,
            "error_code": self.metrics.error_code,
            "stats": sanitize_stats(self.metrics.stats),
            "contract_version": CONTRACT_VERSION,
        }
        availability_failed = False
        for attempt in range(1, 4):
            retryable = False
            try:
                resp = requests.patch(endpoint, json=payload, headers=self._headers(), timeout=20)
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except (ValueError, TypeError, AttributeError):
                        _process_breaker.record_available()
                        logger.warning("Resposta inválida ao finalizar source run.")
                        break
                    if isinstance(body, dict) and body.get("status") == status:
                        self._is_completed = True
                        self.telemetry_failed = False
                        _process_breaker.record_available()
                        logger.info(f"Source run {self.run_uuid} finalizado com sucesso ({status})")
                        return
                logger.warning("Tentativa %s de finalizar run divergente ou falhou: HTTP %s", attempt, resp.status_code)
                # 4xx definitivo (exceto 429): divergência de contrato — repetir
                # retorna o mesmo erro; aborta imediatamente. Resposta 2xx com
                # status canônico divergente também é definitiva e não abre o
                # breaker de disponibilidade.
                retryable = resp.status_code in RETRYABLE_STATUS
                availability_failed = retryable
                if not retryable:
                    _process_breaker.record_available()
            except requests.RequestException:
                retryable = True
                availability_failed = True
                logger.warning("Tentativa %s de finalizar run recebeu resposta inválida ou erro de rede", attempt)
            if not retryable:
                break
            if attempt < 3:
                time.sleep(2 ** attempt)
        self.telemetry_failed = True
        if availability_failed:
            _process_breaker.record_transient_failure()
