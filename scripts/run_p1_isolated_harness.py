"""Run the production-only P1 checks against disposable local PostgreSQL.

The harness deliberately uses two real processes instead of test doubles:

* Repo A is started with Uvicorn and a private PostgreSQL schema.
* Repo B worker subprocesses use ``SourceControl`` and HTTP submissions.

The database guard only permits loopback hosts.  A random schema is created
inside the supplied database and dropped in ``finally``; the supplied
database itself is never dropped.  The generated report contains no secrets
or claim tokens and is suitable for review as a candidate evidence artifact.

This is an isolated release-gate tool, not a production smoke test.  It does
not contact a non-loopback endpoint, mutate production, or enable a source.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable
from urllib.parse import urlsplit

import requests


SCRIPT_PATH = Path(__file__).resolve()
B_REPO = SCRIPT_PATH.parents[1]
DEFAULT_A_REPO = B_REPO.parent / "lasalle-notices-automation"
DEFAULT_OUTPUT_ROOT = B_REPO / "docs" / "evidence" / "production-only-2026-09-12"

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DATABASE_NAME_BLOCKLIST = frozenset({
    "prod", "production", "staging", "supabase", "render",
})
SCHEMA_RE = re.compile(r"^p1_harness_[0-9a-f]{12}$")
SOURCE_KEYS = ("bndes", "brde", "fao", "fapergs")
CAPACITY_SOURCES = SOURCE_KEYS[:3]
MAX_CONCURRENT_SOURCE_RUNS = 3


class HarnessConfigurationError(ValueError):
    """The harness cannot safely start with the supplied configuration."""


class HarnessExecutionError(RuntimeError):
    """An isolated check failed or could not complete."""


@dataclass(frozen=True)
class DatabaseTarget:
    """Sanitized identity for the disposable PostgreSQL target."""

    host: str
    port: int | None
    database: str

    @property
    def label(self) -> str:
        host = f"{self.host}:{self.port}" if self.port else self.host
        return f"{host}/{self.database}"


@dataclass
class WorkerHandle:
    process: subprocess.Popen[str]
    control_path: Path
    ready_path: Path
    items_path: Path
    source: str
    mode: str

    def control(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.control_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HarnessExecutionError(
                f"worker {self.source}/{self.mode} did not write valid control state"
            ) from exc
        if not isinstance(payload, dict):
            raise HarnessExecutionError(
                f"worker {self.source}/{self.mode} control state is not an object"
            )
        return payload


@dataclass
class ApiHandle:
    process: subprocess.Popen[str]
    base_url: str
    stdout: Any
    stderr: Any


@dataclass
class RequestStats:
    total: int = 0
    failures: int = 0
    timeouts: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    latencies_ms: list[float] = field(default_factory=list)

    def observe(self, status: int | None, elapsed_ms: float, *, timeout: bool = False) -> None:
        self.total += 1
        self.latencies_ms.append(elapsed_ms)
        if timeout:
            self.timeouts += 1
            self.failures += 1
            self.statuses["timeout"] += 1
        elif status is None:
            self.failures += 1
            self.statuses["transport_error"] += 1
        else:
            self.statuses[str(status)] += 1
            if status >= 500:
                self.failures += 1

    def merge(self, other: "RequestStats") -> None:
        self.total += other.total
        self.failures += other.failures
        self.timeouts += other.timeouts
        self.statuses.update(other.statuses)
        self.latencies_ms.extend(other.latencies_ms)


# The helper snippets execute in Repo A's selected interpreter, so the B
# harness itself does not need SQLAlchemy or psycopg installed.
_PING_SQL = r'''
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
with engine.connect() as connection:
    connection.execute(text("SELECT 1"))
engine.dispose()
print("ok")
'''

_SNAPSHOT_SQL = r'''
import json
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
result = {}
with engine.connect() as connection:
    for table in ("scraping_sources", "source_schedule_state", "source_work_items",
                  "source_collection_checkpoints", "scrape_candidates", "editais",
                  "edital_documents"):
        result[table] = int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
    result["work_status"] = {
        str(row.status): int(row.count)
        for row in connection.execute(text(
            "SELECT status, count(*) AS count FROM source_work_items GROUP BY status"
        ))
    }
    result["active_claims"] = int(connection.execute(text(
        "SELECT count(*) FROM source_schedule_state "
        "WHERE claim_token_hash IS NOT NULL AND claim_expires_at > now()"
    )).scalar() or 0)
    result["db_connections"] = int(connection.execute(text(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    )).scalar() or 0)
    result["max_connections"] = int(connection.execute(text(
        "SELECT setting::int FROM pg_settings WHERE name = 'max_connections'"
    )).scalar() or 0)
    result["superuser_reserved_connections"] = int(connection.execute(text(
        "SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections'"
    )).scalar() or 0)
    result["database_size_bytes"] = int(connection.execute(text(
        "SELECT pg_database_size(current_database())"
    )).scalar() or 0)
    result["tablespace_size_bytes"] = int(connection.execute(text(
        "SELECT pg_tablespace_size('pg_default')"
    )).scalar() or 0)
print(json.dumps(result, sort_keys=True))
engine.dispose()
'''

_IDENTITY_SQL = r'''
import json
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
source = os.environ["P1_SOURCE"]
record_id = os.environ["P1_RECORD_ID"]
result = {"editais": [], "documents": [], "candidates": [], "work_items": []}
with engine.connect() as connection:
    result["editais"] = [
        dict(row._mapping)
        for row in connection.execute(text(
            "SELECT id, source_url, worker_content_hash, source_snapshot_at::text "
            "FROM editais WHERE source_key = :source AND source_record_id = :record_id "
            "ORDER BY id"
        ), {"source": source, "record_id": record_id})
    ]
    result["documents"] = [
        dict(row._mapping)
        for row in connection.execute(text(
            "SELECT d.id, d.edital_id, d.url, d.content_hash "
            "FROM edital_documents AS d JOIN editais AS e ON e.id = d.edital_id "
            "WHERE e.source_key = :source AND e.source_record_id = :record_id "
            "ORDER BY d.id"
        ), {"source": source, "record_id": record_id})
    ]
    result["candidates"] = [
        dict(row._mapping)
        for row in connection.execute(text(
            "SELECT id, url, status FROM scrape_candidates "
            "WHERE source = :source "
            "AND candidate_metadata ->> 'source_record_id' = :record_id ORDER BY id"
        ), {"source": source, "record_id": record_id})
    ]
    result["work_items"] = [
        dict(row._mapping)
        for row in connection.execute(text(
            "SELECT id, revision, status, attempts, error_code, "
            "retry_after_at::text "
            "FROM source_work_items "
            "WHERE source_id = (SELECT id FROM scraping_sources WHERE source_key = :source) "
            "AND payload -> 'metadata' ->> 'source_record_id' = :record_id ORDER BY id"
        ), {"source": source, "record_id": record_id})
    ]
print(json.dumps(result, sort_keys=True))
engine.dispose()
'''

_EXPIRE_SQL = r'''
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
with engine.begin() as connection:
    connection.execute(text(
        "UPDATE source_schedule_state AS state SET "
        "claim_expires_at = now() - interval '1 second', "
        "retry_after_at = now() - interval '1 second' "
        "FROM scraping_sources AS source "
        "WHERE state.source_id = source.id AND source.source_key = :source"
    ), {"source": os.environ["P1_SOURCE"]})
    connection.execute(text(
        "UPDATE source_work_items AS item SET "
        "retry_after_at = now() - interval '1 second' "
        "FROM scraping_sources AS source "
        "WHERE item.source_id = source.id AND source.source_key = :source"
    ), {"source": os.environ["P1_SOURCE"]})
engine.dispose()
print("ok")
'''

_EXPIRE_WORK_SQL = r'''
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
with engine.begin() as connection:
    connection.execute(text(
        "UPDATE source_work_items AS item SET "
        "retry_after_at = now() - interval '1 second' "
        "FROM scraping_sources AS source "
        "WHERE item.source_id = source.id AND source.source_key = :source "
        "AND item.status = 'pending'"
    ), {"source": os.environ["P1_SOURCE"]})
engine.dispose()
print("ok")
'''

_DROP_SCHEMA_SQL = r'''
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
with engine.begin() as connection:
    connection.execute(text('DROP SCHEMA IF EXISTS "' + os.environ["P1_SCHEMA"] + '" CASCADE'))
engine.dispose()
print("ok")
'''


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_disposable_database_url(value: str) -> DatabaseTarget:
    """Reject production-looking or non-loopback PostgreSQL targets."""
    if not value or not value.strip():
        raise HarnessConfigurationError(
            "Provide --database-url or P1_DATABASE_URL for a disposable PostgreSQL target"
        )
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise HarnessConfigurationError("Database URL is malformed") from exc
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
        raise HarnessConfigurationError("Database URL must use a PostgreSQL scheme")
    host = (parsed.hostname or "").casefold()
    if host not in LOOPBACK_HOSTS:
        raise HarnessConfigurationError(
            "P1 harness only permits loopback PostgreSQL hosts; production and hosted staging are forbidden"
        )
    database = (parsed.path or "").rstrip("/").rsplit("/", 1)[-1]
    if not database:
        raise HarnessConfigurationError("Database URL must include a database name")
    normalized_name = re.sub(r"[^a-z0-9]+", "_", database.casefold())
    if any(token in normalized_name.split("_") for token in DATABASE_NAME_BLOCKLIST):
        raise HarnessConfigurationError(
            "Database name looks like production/staging infrastructure; use a disposable database"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise HarnessConfigurationError("Database URL port is malformed") from exc
    return DatabaseTarget(host=host, port=port, database=database)


def make_schema_name() -> str:
    return f"p1_harness_{secrets.token_hex(6)}"


def redact(value: Any, secret_values: Iterable[str] = ()) -> Any:
    """Redact credentials/tokens before values enter reports or diagnostics."""
    if isinstance(value, dict):
        return {str(key): redact(item, secret_values) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secret_values) for item in value]
    if not isinstance(value, str):
        return value
    result = value
    for secret in secret_values:
        if secret:
            result = result.replace(secret, "<redacted>")
    result = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1<redacted>", result)
    result = re.sub(r"(?i)(postgres(?:ql)?(?:\+[^:]+)?://)[^\s]+", r"\1<redacted>", result)
    result = re.sub(r"(?i)(password|token|secret)(\s*[=:]\s*)[^\s,;]+", r"\1\2<redacted>", result)
    return result


def percentile(values: Iterable[float], percent: float) -> float | None:
    values = sorted(values)
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * percent / 100
    lower = int(position)
    upper = min(len(values) - 1, lower + 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def safe_latency_summary(stats: RequestStats) -> dict[str, Any]:
    return {
        "requests": stats.total,
        "failures_5xx_or_transport": stats.failures,
        "timeouts": stats.timeouts,
        "status_counts": dict(sorted(stats.statuses.items())),
        "p50_ms": percentile(stats.latencies_ms, 50),
        "p95_ms": percentile(stats.latencies_ms, 95),
        "max_ms": max(stats.latencies_ms) if stats.latencies_ms else None,
    }


def evaluate_thresholds(
    *,
    request_stats: RequestStats,
    claim_p95_ms: float | None,
    peak_connections: int | None,
    usable_connections: int | None,
    storage_headroom_ratio: float | None,
    service_rate_per_hour: float | None,
    arrival_rate_per_hour: float,
) -> dict[str, Any]:
    """Evaluate only measured values; unknown denominators remain blocked."""
    error_rate = (
        request_stats.failures / request_stats.total
        if request_stats.total
        else None
    )
    capacity_ratio = (
        service_rate_per_hour / arrival_rate_per_hour
        if service_rate_per_hour is not None and arrival_rate_per_hour > 0
        else None
    )
    checks = {
        "api_5xx_and_timeout_rate_lt_1pct": (
            error_rate is not None and error_rate < 0.01
        ),
        "warm_claim_p95_le_1000ms": (
            claim_p95_ms is not None and claim_p95_ms <= 1000
        ),
        "db_connections_le_70pct_usable": (
            peak_connections is not None
            and usable_connections is not None
            and usable_connections > 0
            and peak_connections / usable_connections <= 0.70
        ),
        "storage_headroom_ge_20pct": (
            storage_headroom_ratio is not None and storage_headroom_ratio >= 0.20
        ),
        "service_capacity_ge_1_25x_declared_arrival": (
            capacity_ratio is not None and capacity_ratio >= 1.25
        ),
    }
    return {
        "error_rate": error_rate,
        "claim_p95_ms": claim_p95_ms,
        "peak_connections": peak_connections,
        "usable_connections": usable_connections,
        "storage_headroom_ratio": storage_headroom_ratio,
        "service_rate_per_hour": service_rate_per_hour,
        "declared_arrival_rate_per_hour": arrival_rate_per_hour,
        "capacity_ratio": capacity_ratio,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "blocked_or_failed",
    }


def _choose_python(api_repo: Path, configured: str | None) -> str:
    if configured:
        path = Path(configured).expanduser()
        if not path.exists():
            raise HarnessConfigurationError(f"Configured API Python does not exist: {path}")
        return str(path)
    candidates = (
        api_repo / ".venv" / "Scripts" / "python.exe",
        api_repo / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _helper_env(database_url: str, schema: str, *, source: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": database_url,
        "PGOPTIONS": f"-c search_path={schema}",
        "P1_SCHEMA": schema,
    })
    if source is not None:
        env["P1_SOURCE"] = source
    return env


def _run_a_python(
    api_python: str,
    api_repo: Path,
    code: str,
    env: dict[str, str],
    *,
    label: str,
    timeout: float = 120,
) -> str:
    result = subprocess.run(
        [api_python, "-c", code],
        cwd=str(api_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise HarnessExecutionError(f"Repo A helper {label} failed (exit {result.returncode})")
    return result.stdout.strip()


def _run_a_module(
    api_python: str,
    api_repo: Path,
    module_args: list[str],
    env: dict[str, str],
    *,
    label: str,
    timeout: float = 180,
) -> None:
    result = subprocess.run(
        [api_python, *module_args],
        cwd=str(api_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise HarnessExecutionError(f"Repo A helper {label} failed (exit {result.returncode})")


def _snapshot(
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
) -> dict[str, Any]:
    raw = _run_a_python(
        api_python, api_repo, _SNAPSHOT_SQL, _helper_env(database_url, schema),
        label="snapshot",
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessExecutionError("Repo A snapshot helper returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise HarnessExecutionError("Repo A snapshot helper returned a non-object")
    return value


def _identity_snapshot(
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    source: str,
    record_id: str,
) -> dict[str, Any]:
    env = _helper_env(database_url, schema, source=source)
    env["P1_RECORD_ID"] = record_id
    raw = _run_a_python(
        api_python, api_repo, _IDENTITY_SQL, env,
        label=f"identity-{source}-{record_id}",
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessExecutionError("Repo A identity helper returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise HarnessExecutionError("Repo A identity helper returned a non-object")
    return value


def _expire_source(
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    source: str,
) -> None:
    _run_a_python(
        api_python, api_repo, _EXPIRE_SQL,
        _helper_env(database_url, schema, source=source),
        label=f"expire-{source}",
    )


def _expire_work_items(
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    source: str,
) -> None:
    """Make pending fixture work immediately eligible without losing its lease."""
    _run_a_python(
        api_python, api_repo, _EXPIRE_WORK_SQL,
        _helper_env(database_url, schema, source=source),
        label=f"expire-work-{source}",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _process_rss_bytes(pid: int) -> int | None:
    """Return one process's resident set size without adding a dependency."""
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("page_fault_count", wintypes.DWORD),
                    ("peak_working_set_size", ctypes.c_size_t),
                    ("working_set_size", ctypes.c_size_t),
                    ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                    ("quota_paged_pool_usage", ctypes.c_size_t),
                    ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                    ("quota_non_paged_pool_usage", ctypes.c_size_t),
                    ("pagefile_usage", ctypes.c_size_t),
                    ("peak_pagefile_usage", ctypes.c_size_t),
                ]

            process_query = 0x1000 | 0x0010
            handle = ctypes.windll.kernel32.OpenProcess(process_query, False, pid)
            if not handle:
                return None
            try:
                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                getter = ctypes.windll.psapi.GetProcessMemoryInfo
                if not getter(handle, ctypes.byref(counters), counters.cb):
                    return None
                return int(counters.working_set_size)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
    status_path = Path(f"/proc/{pid}/status")
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                match = re.search(r"(\d+)", line)
                return int(match.group(1)) * 1024 if match else None
    except (OSError, ValueError):
        pass
    return None


def _sample_peak_rss(processes: Iterable[subprocess.Popen[Any]]) -> int | None:
    values = [
        value
        for process in processes
        if (value := _process_rss_bytes(process.pid)) is not None
    ]
    return max(values) if values else None


def _api_env(
    database_url: str,
    schema: str,
    *,
    mode: str,
    admitted_source: str,
    pipeline_secret: str,
    api_repo: Path,
) -> dict[str, str]:
    """Construct a fully explicit local A environment, overriding .env."""
    # A's Settings intentionally requires these values even for pipeline-only
    # tests.  They are random/local placeholders and never leave this process.
    env = _helper_env(database_url, schema)
    env.update({
        "SECRET_KEY": secrets.token_urlsafe(32),
        "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
        "GOOGLE_CLIENT_ID": "p1-isolated-client",
        "GOOGLE_CLIENT_SECRET": "p1-isolated-secret",
        "GOOGLE_REDIRECT_URI": "http://127.0.0.1/auth/google/callback",
        "ENCRYPTION_KEY": "4rJ0GhiYPWXNhEQba4V5Q5EV8qHrt6XdmV8vzVSQj2M=",
        "FRONTEND_URL": "http://127.0.0.1",
        "APP_NAME": "P1 Isolated API",
        "APP_VERSION": "p1-isolated",
        "DEBUG": "false",
        "SESSION_COOKIE_NAME": "p1_isolated_session",
        "SESSION_COOKIE_SAMESITE": "lax",
        "RATE_LIMIT_DEFAULT": "10000/minute",
        "RATE_LIMIT_SYNC": "10000/minute",
        "RATE_LIMIT_AI": "10000/minute",
        "MAX_UPLOAD_SIZE_BYTES": "50000000",
        "AI_PROVIDER": "google",
        "OPENAI_MODEL": "isolated-unused",
        "GOOGLE_GENAI_MODEL": "isolated-unused",
        "AI_SYSTEM_PROMPT_PATH": str(api_repo / "prompts" / "data_extraction.md"),
        "PIPELINE_SECRET": pipeline_secret,
        "ENABLE_SCHEDULER": "false",
        "SOURCE_RUN_MAINTENANCE_ENABLED": "false",
        "SOURCE_ADMISSION_MODE": mode,
        "SOURCE_ADMISSION_SOURCE": admitted_source,
        "SOURCE_ADMISSION_CONTRACT": "candidate",
        "SOURCE_CLAIM_ENFORCEMENT": "strict",
        "ENABLE_DOCUMENTLESS_OPPORTUNITIES": "false",
        "DB_CONNECT_TIMEOUT_SECONDS": "5",
        "DB_INIT_MAX_ATTEMPTS": "1",
        "DB_INIT_RETRY_DELAY_SECONDS": "0",
        "DB_POOL_SIZE": "5",
        "DB_MAX_OVERFLOW": "0",
        "SCRAPE_MAX_SOURCES_PER_RUN": "2",
        "SCRAPE_MAX_PDFS_PER_RUN": "5",
        "SCRAPE_MAX_CANDIDATES_PER_INGEST_RUN": "25",
        "SCRAPE_DEFAULT_BS4_SOURCES": "bndes,brde",
        "SCRAPE_ENABLE_PLAYWRIGHT_ON_RENDER": "false",
        "SCRAPE_MAX_PDF_BYTES": "15000000",
        "SCRAPE_DISCOVERY_ONLY_DEFAULT": "true",
    })
    return env


def _stop_process(process: subprocess.Popen[str] | None, *, timeout: float = 15) -> int | None:
    if process is None:
        return None
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    return process.returncode


def _start_api(
    api_python: str,
    api_repo: Path,
    env: dict[str, str],
    *,
    timeout: float = 90,
) -> ApiHandle:
    port = _free_port()
    stdout = tempfile.TemporaryFile(mode="w+b")
    stderr = tempfile.TemporaryFile(mode="w+b")
    process = subprocess.Popen(
        [api_python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(api_repo),
        env=env,
        stdout=stdout,
        stderr=stderr,
        text=False,
        start_new_session=os.name != "nt",
    )
    handle = ApiHandle(process=process, base_url=f"http://127.0.0.1:{port}", stdout=stdout, stderr=stderr)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _stop_process(process)
            raise HarnessExecutionError("Repo A Uvicorn process exited before readiness")
        try:
            response = requests.get(handle.base_url + "/health", timeout=(1, 2))
            if response.status_code == 200 and response.json().get("status") == "healthy":
                return handle
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.25)
    _stop_process(process)
    raise HarnessExecutionError("Repo A Uvicorn process did not become ready")


def _stop_api(handle: ApiHandle | None) -> None:
    if handle is None:
        return
    _stop_process(handle.process)
    handle.stdout.close()
    handle.stderr.close()


def _post(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    secret: str,
    claim_token: str | None = None,
    stream: bool = False,
    stats: RequestStats | None = None,
) -> tuple[int | None, dict[str, Any], float, bool]:
    headers = {"Authorization": f"Bearer {secret}"}
    if claim_token is not None:
        headers["X-Source-Claim"] = claim_token
    started = time.perf_counter()
    status: int | None = None
    timed_out = False
    body: dict[str, Any] = {}
    try:
        response = requests.post(
            base_url + path,
            headers=headers,
            json=payload,
            timeout=(3, 20),
            allow_redirects=False,
            stream=stream,
        )
        status = response.status_code
        if not stream:
            try:
                decoded = response.json()
                if isinstance(decoded, dict):
                    body = decoded
            except ValueError:
                body = {}
        response.close()
    except requests.Timeout:
        timed_out = True
    except requests.RequestException:
        pass
    elapsed_ms = (time.perf_counter() - started) * 1000
    if stats is not None:
        stats.observe(status, elapsed_ms, timeout=timed_out)
    return status, body, elapsed_ms, timed_out


def _get(
    base_url: str,
    path: str,
    *,
    secret: str,
    stats: RequestStats | None = None,
) -> tuple[int | None, dict[str, Any], float, bool]:
    """Authenticated read helper used for capabilities and catalog probes."""
    started = time.perf_counter()
    status: int | None = None
    timed_out = False
    body: dict[str, Any] = {}
    try:
        response = requests.get(
            base_url + path,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=(3, 20),
            allow_redirects=False,
        )
        status = response.status_code
        try:
            decoded = response.json()
            if isinstance(decoded, dict):
                body = decoded
        except ValueError:
            body = {}
        response.close()
    except requests.Timeout:
        timed_out = True
    except requests.RequestException:
        pass
    elapsed_ms = (time.perf_counter() - started) * 1000
    if stats is not None:
        stats.observe(status, elapsed_ms, timeout=timed_out)
    return status, body, elapsed_ms, timed_out


def _claim(
    base_url: str,
    source: str,
    *,
    secret: str,
    owner: str,
    stats: RequestStats | None = None,
) -> tuple[str, dict[str, Any], float]:
    status, body, elapsed, timed_out = _post(
        base_url,
        "/api/pipeline/source-schedule/claims",
        {"source_key": source, "owner": owner, "force": True, "scope": "default"},
        secret=secret,
        stats=stats,
    )
    if status != 201 or timed_out or not isinstance(body.get("claim_token"), str):
        reason = body.get("detail", {}).get("reason") if isinstance(body.get("detail"), dict) else None
        raise HarnessExecutionError(f"claim for {source} failed: {reason or status}")
    return body["claim_token"], body, elapsed


def _work(
    base_url: str,
    source: str,
    token: str,
    action: str,
    *,
    secret: str,
    stats: RequestStats | None = None,
    **kwargs: Any,
) -> tuple[int | None, dict[str, Any], float]:
    payload = {"source_key": source, "claim_token": token, "action": action, **kwargs}
    status, body, elapsed, _ = _post(
        base_url, "/api/pipeline/source-work", payload,
        secret=secret, stats=stats,
    )
    return status, body, elapsed


def _release(
    base_url: str,
    source: str,
    token: str,
    *,
    secret: str,
    outcome: str,
    stats: RequestStats | None = None,
) -> None:
    status, body, _, _ = _post(
        base_url,
        "/api/pipeline/source-schedule/claims/release",
        {"source_key": source, "claim_token": token, "outcome": outcome},
        secret=secret,
        stats=stats,
    )
    if status != 200:
        reason = body.get("detail", {}).get("reason") if isinstance(body.get("detail"), dict) else None
        raise HarnessExecutionError(f"release for {source} failed: {reason or status}")


def _descriptor(source: str, index: int) -> dict[str, Any]:
    return {
        "url": f"https://{source}.example.gov.br/p1/{index}.pdf",
        "metadata": {
            "source_record_id": f"p1-{source}-{index}",
            "title": f"P1 isolated descriptor {source} {index}",
        },
    }


def _worker_env(api_url: str, secret: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "RENDER_APP_URL": api_url,
        "PIPELINE_SECRET": secret,
        "SOURCE_RUN_REPORTING_ENABLED": "false",
    })
    return env


def _spawn_worker(
    *,
    api_url: str,
    secret: str,
    source: str,
    mode: str,
    items: list[dict[str, Any]],
    work_dir: Path,
) -> WorkerHandle:
    token = secrets.token_hex(6)
    items_path = work_dir / f"items-{source}-{mode}-{token}.json"
    control_path = work_dir / f"control-{source}-{mode}-{token}.json"
    ready_path = work_dir / f"ready-{source}-{mode}-{token}"
    items_path.write_text(json.dumps(items, sort_keys=True), encoding="utf-8")
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--worker-mode", mode,
        "--worker-source", source,
        "--worker-items", str(items_path),
        "--worker-control", str(control_path),
        "--worker-ready", str(ready_path),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(B_REPO),
        env=_worker_env(api_url, secret),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=os.name != "nt",
    )
    return WorkerHandle(
        process=process,
        control_path=control_path,
        ready_path=ready_path,
        items_path=items_path,
        source=source,
        mode=mode,
    )


def _wait_worker_ready(handle: WorkerHandle, timeout: float = 45) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.ready_path.exists():
            return handle.control()
        if handle.process.poll() is not None:
            # The control file, when present, contains only status/reason and
            # never a raw response or secret.
            state = handle.control() if handle.control_path.exists() else {}
            raise HarnessExecutionError(
                f"worker {handle.source}/{handle.mode} exited before ready: "
                f"{state.get('reason') or handle.process.returncode}"
            )
        time.sleep(0.05)
    raise HarnessExecutionError(f"worker {handle.source}/{handle.mode} readiness timed out")


def _terminate_worker(handle: WorkerHandle) -> int | None:
    return _stop_process(handle.process)


def _cleanup_worker_files(handle: WorkerHandle) -> None:
    for path in (handle.control_path, handle.ready_path, handle.items_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _dispose_workers(handles: Iterable[WorkerHandle]) -> None:
    """Kill any live fixture workers and remove their private control files."""
    for handle in handles:
        try:
            _terminate_worker(handle)
        except Exception:
            # The scenario result already fails if cleanup cannot terminate a
            # worker; continue so other workers do not leak into later checks.
            pass
        _cleanup_worker_files(handle)


def _make_candidate_payload(
    source: str,
    index: int,
    *,
    variant: str = "base",
) -> tuple[dict[str, Any], dict[str, Any]]:
    suffix = "" if variant == "base" else f" {variant}"
    content = f"%PDF-1.7\nP1 isolated fixture {source}-{index}{suffix}\n%%EOF\n".encode()
    markdown = f"# P1 isolated fixture {source}-{index}{suffix}"
    candidate = _descriptor(source, index)
    candidate["worker_result"] = {
        "ocr_markdown": markdown,
        "content_hash": hashlib.sha256(content).hexdigest(),
        "content_length": len(content),
        "validated_at": utc_now().isoformat(),
        "validation_outcome": "valid_pdf",
    }
    return candidate, content


def _candidate_for_item(source: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Add the worker result only after a descriptor has been taken."""
    metadata = payload.get("metadata") or {}
    record_id = str(metadata.get("source_record_id") or "")
    try:
        index = int(record_id.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        index = 0
    variant = metadata.get("p1_fixture_variant", "base")
    if not isinstance(variant, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", variant):
        variant = "base"
    candidate, _ = _make_candidate_payload(source, index, variant=variant)
    candidate["url"] = payload.get("url", candidate["url"])
    candidate["metadata"] = metadata
    return candidate


def _candidate_submit(
    base_url: str,
    source: str,
    token: str,
    candidate: dict[str, Any],
    *,
    secret: str,
    stats: RequestStats | None = None,
    stream: bool = False,
) -> tuple[int | None, dict[str, Any], float]:
    status, body, elapsed, _ = _post(
        base_url,
        "/api/pipeline/candidates",
        {"source": source, "candidates": [candidate]},
        secret=secret,
        claim_token=token,
        stream=stream,
        stats=stats,
    )
    return status, body, elapsed


def _run_worker_mode(argv: argparse.Namespace) -> int:
    """Child process implementation used by the parent harness."""
    from source_control import AdmissionConflict, SourceControl

    source = argv.worker_source
    items = json.loads(Path(argv.worker_items).read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise HarnessExecutionError("worker items file must contain a list")
    stats = RequestStats()
    api_url = os.environ["RENDER_APP_URL"]
    secret = os.environ["PIPELINE_SECRET"]

    class MeasuredSourceControl(SourceControl):
        """Record every worker API call without exposing response bodies."""

        def post(self, path, payload):
            started = time.perf_counter()
            status = None
            timed_out = False
            try:
                result = super().post(path, payload)
                # SourceControl deliberately returns only validated JSON, so a
                # successful call is known to be either HTTP 200 or 201. The
                # exact status is not needed for the aggregate release gate.
                status = 200
                return result
            except AdmissionConflict:
                # Capacity and lease conflicts are expected measurements, not
                # API failures for the error-rate gate.
                status = 409
                raise
            except requests.Timeout:
                timed_out = True
                stats.observe(
                    None,
                    (time.perf_counter() - started) * 1000,
                    timeout=True,
                )
                raise
            except Exception:
                # SourceControl turns non-2xx responses into RuntimeError and
                # intentionally does not retain arbitrary response bodies.
                stats.observe(None, (time.perf_counter() - started) * 1000)
                raise
            finally:
                if status is not None:
                    stats.observe(
                        status,
                        (time.perf_counter() - started) * 1000,
                        timeout=timed_out,
                    )

    client = MeasuredSourceControl(source)
    control: dict[str, Any] = {"source": source, "mode": argv.worker_mode}
    try:
        started = time.perf_counter()
        try:
            claim = client.claim(force=True)
        except AdmissionConflict as exc:
            control.update(
                status="rejected", reason=exc.reason,
                requests=safe_latency_summary(stats),
            )
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            return 0
        claim_elapsed = (time.perf_counter() - started) * 1000
        token = client.token
        if not token:
            raise HarnessExecutionError("worker claim did not return a token")
        control.update(status="claimed", claim_ms=round(claim_elapsed, 3))

        if argv.worker_mode == "register_hold":
            client.work("register", contract="candidate", items=items)
            control.update(
                registered=len(items), requests=safe_latency_summary(stats),
            )
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            while True:
                time.sleep(1)

        if argv.worker_mode == "submit_hold":
            descriptors = [
                {key: value for key, value in item.items() if key != "worker_result"}
                for item in items
            ]
            client.work("register", contract="candidate", items=descriptors)
            taken = client.work("take", limit=1)
            if not taken.get("items"):
                raise HarnessExecutionError("submit worker could not take its registered item")
            item = taken["items"][0]
            candidate = _candidate_for_item(source, item["payload"])
            status, _, elapsed, _ = _post(
                api_url,
                "/api/pipeline/candidates",
                {"source": source, "candidates": [candidate]},
                secret=secret,
                claim_token=token,
                stream=True,
                stats=stats,
            )
            if status != 200:
                raise HarnessExecutionError(f"submit lost-ACK fixture returned {status}")
            # The response headers were received and then intentionally
            # discarded. The worker does not learn the logical outcome.
            control.update(
                item_id=item["id"], revision=item["revision"],
                submitted_status=status, submit_ms=round(elapsed, 3),
                requests=safe_latency_summary(stats),
            )
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            while True:
                time.sleep(1)

        if argv.worker_mode == "finish_hold":
            descriptors = [
                {key: value for key, value in item.items() if key != "worker_result"}
                for item in items
            ]
            client.work("register", contract="candidate", items=descriptors)
            taken = client.work("take", limit=1)
            if not taken.get("items"):
                raise HarnessExecutionError("finish worker could not take its registered item")
            item = taken["items"][0]
            candidate = _candidate_for_item(source, item["payload"])
            status, _, _, _ = _post(
                api_url,
                "/api/pipeline/candidates",
                {"source": source, "candidates": [candidate]},
                secret=secret,
                claim_token=token,
                stats=stats,
            )
            if status != 200:
                raise HarnessExecutionError(f"finish fixture submit returned {status}")
            status, _, elapsed, _ = _post(
                api_url,
                "/api/pipeline/source-work",
                {"source_key": source, "claim_token": token, "action": "finish",
                 "item_id": item["id"], "revision": item["revision"], "outcome": "accepted"},
                secret=secret,
                stream=True,
                stats=stats,
            )
            if status != 200:
                raise HarnessExecutionError(f"finish lost-ACK fixture returned {status}")
            control.update(
                item_id=item["id"], revision=item["revision"],
                finished_status=status, finish_ms=round(elapsed, 3),
                requests=safe_latency_summary(stats),
                # This control file is private and deleted during cleanup. It
                # lets the parent retry the same request while the lease is
                # still live without placing the token in evidence.
                claim_token=token,
            )
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            while True:
                time.sleep(1)

        if argv.worker_mode == "changed_replay":
            if len(items) != 2:
                raise HarnessExecutionError("changed replay worker needs exactly two descriptors")
            descriptors = [
                {key: value for key, value in item.items() if key != "worker_result"}
                for item in items
            ]

            client.work("register", contract="candidate", items=[descriptors[0]])
            initial_taken = client.work("take", limit=1)
            initial_rows = initial_taken.get("items") or []
            if not initial_rows:
                raise HarnessExecutionError("changed replay worker could not take initial item")
            initial_item = initial_rows[0]
            initial_candidate = _candidate_for_item(source, initial_item["payload"])
            initial_status, initial_body, _ = _candidate_submit(
                api_url, source, token, initial_candidate,
                secret=secret, stats=stats,
            )
            if initial_status != 200:
                raise HarnessExecutionError(
                    f"changed replay initial submit returned {initial_status}"
                )
            client.work(
                "finish", item_id=initial_item["id"],
                revision=initial_item["revision"], outcome="accepted",
            )

            client.work("register", contract="candidate", items=[descriptors[1]])
            changed_taken = client.work("take", limit=1)
            changed_rows = changed_taken.get("items") or []
            if not changed_rows:
                raise HarnessExecutionError("changed replay worker could not take updated item")
            changed_item = changed_rows[0]
            changed_candidate = _candidate_for_item(source, changed_item["payload"])
            changed_status, changed_body, _ = _candidate_submit(
                api_url, source, token, changed_candidate,
                secret=secret, stats=stats,
            )
            if changed_status != 200:
                raise HarnessExecutionError(
                    f"changed replay updated submit returned {changed_status}"
                )
            client.work(
                "finish", item_id=changed_item["id"],
                revision=changed_item["revision"], outcome="accepted",
            )
            client.release("complete")

            def submit_outcome(body: dict[str, Any]) -> str | None:
                rows = body.get("items") or []
                return rows[0].get("outcome") if rows and isinstance(rows[0], dict) else None

            control.update(
                status="completed",
                initial_item_id=initial_item["id"],
                initial_revision=initial_item["revision"],
                initial_submit_status=initial_status,
                initial_submit_outcome=submit_outcome(initial_body),
                changed_item_id=changed_item["id"],
                changed_revision=changed_item["revision"],
                changed_submit_status=changed_status,
                changed_submit_outcome=submit_outcome(changed_body),
                same_item_id=initial_item["id"] == changed_item["id"],
                requests=safe_latency_summary(stats),
            )
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            return 0

        if argv.worker_mode == "claim_hold":
            control["requests"] = safe_latency_summary(stats)
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            while True:
                time.sleep(1)

        if argv.worker_mode == "drain":
            client.work("register", contract="candidate", items=items)
            completed = 0
            while True:
                taken = client.work("take", limit=25)
                rows = taken.get("items") or []
                if not rows:
                    break
                for item in rows:
                    client.work(
                        "finish", item_id=item["id"], revision=item["revision"],
                        outcome="accepted",
                    )
                    completed += 1
            client.release("complete")
            duration = max(0.001, time.perf_counter() - started)
            control.update(
                status="completed", completed=completed,
                duration_seconds=duration,
                requests=safe_latency_summary(stats),
            )
            Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
            Path(argv.worker_ready).touch()
            return 0
        raise HarnessExecutionError(f"unknown worker mode {argv.worker_mode}")
    except Exception as exc:
        detail = str(exc).strip()
        control.update(
            status="failed", reason=type(exc).__name__,
            detail=redact(detail, (secret,))[:160] if detail else None,
            requests=safe_latency_summary(stats),
        )
        Path(argv.worker_control).write_text(json.dumps(control, sort_keys=True), encoding="utf-8")
        Path(argv.worker_ready).touch()
        return 1


def _run_termination_scenario(
    *,
    api: ApiHandle,
    secret: str,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    temp_dir: Path,
    source: str = "bndes",
) -> dict[str, Any]:
    items = [_descriptor(source, index) for index in range(1, 13)]
    before = _snapshot(api_python, api_repo, database_url, schema)
    worker = _spawn_worker(
        api_url=api.base_url, secret=secret, source=source,
        mode="register_hold", items=items, work_dir=temp_dir,
    )
    try:
        state = _wait_worker_ready(worker)
        exit_code = _terminate_worker(worker)
        _expire_source(api_python, api_repo, database_url, schema, source)
        after_kill = _snapshot(api_python, api_repo, database_url, schema)
        token, _, _ = _claim(api.base_url, source, secret=secret, owner="p1-successor")
        status, taken, _, = _work(
            api.base_url, source, token, "take", secret=secret, limit=25,
        )
        rows = taken.get("items") or []
        for item in rows:
            finish_status, _, _ = _work(
                api.base_url, source, token, "finish", secret=secret,
                item_id=item["id"], revision=item["revision"], outcome="accepted",
            )
            if finish_status != 200:
                raise HarnessExecutionError("successor could not finish post-termination work")
        _release(api.base_url, source, token, secret=secret, outcome="noop")
        after_recovery = _snapshot(api_python, api_repo, database_url, schema)
    finally:
        _dispose_workers((worker,))
    passed = (
        state.get("status") == "claimed"
        and state.get("registered") == len(items)
        and exit_code not in (None, 0)
        and after_kill.get("source_work_items", 0) - before.get("source_work_items", 0) == len(items)
        and status == 200
        and len(rows) == len(items)
        and after_recovery.get("work_status", {}).get("accepted", 0)
        >= before.get("work_status", {}).get("accepted", 0) + len(items)
    )
    return {
        "status": "pass" if passed else "failed",
        "worker_exit_code": exit_code,
        "registered": len(items),
        "taken_after_successor_claim": len(rows),
        "before": before,
        "after_kill": after_kill,
        "after_recovery": after_recovery,
    }


def _run_replay_scenario(
    *,
    api: ApiHandle,
    secret: str,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    temp_dir: Path,
    source: str = "bndes",
) -> dict[str, Any]:
    candidate, _ = _make_candidate_payload(source, 100)
    before = _snapshot(api_python, api_repo, database_url, schema)
    worker = _spawn_worker(
        api_url=api.base_url, secret=secret, source=source,
        mode="submit_hold", items=[candidate], work_dir=temp_dir,
    )
    try:
        state = _wait_worker_ready(worker)
        exit_code = _terminate_worker(worker)
        # Ensure the accepted response had committed before the parent starts
        # the replay. The query is local and read-only.
        deadline = time.monotonic() + 10
        submitted = None
        while time.monotonic() < deadline:
            submitted = _snapshot(api_python, api_repo, database_url, schema)
            if submitted.get("editais", 0) >= before.get("editais", 0) + 1:
                break
            time.sleep(0.1)
        _expire_source(api_python, api_repo, database_url, schema, source)
        successor, _, _ = _claim(api.base_url, source, secret=secret, owner="p1-replay-successor")
        status, taken, _, = _work(
            api.base_url, source, successor, "take", secret=secret, limit=1,
        )
        rows = taken.get("items") or []
        replay_status, replay_body, _, = _candidate_submit(
            api.base_url, source, successor, candidate, secret=secret,
        )
        if rows:
            finish_status, _, _ = _work(
                api.base_url, source, successor, "finish", secret=secret,
                item_id=rows[0]["id"], revision=rows[0]["revision"], outcome="accepted",
            )
            if finish_status != 200:
                raise HarnessExecutionError("replay successor could not finish work")
        _release(api.base_url, source, successor, secret=secret, outcome="noop")
        after = _snapshot(api_python, api_repo, database_url, schema)
    finally:
        _dispose_workers((worker,))
    outcomes = [item.get("outcome") for item in replay_body.get("items", [])]
    passed = (
        state.get("status") == "claimed"
        and state.get("submitted_status") == 200
        and exit_code not in (None, 0)
        and submitted is not None
        and submitted.get("editais", 0) == before.get("editais", 0) + 1
        and status == 200
        and len(rows) == 1
        and replay_status == 200
        and "duplicate" in outcomes
        and after.get("editais", 0) == before.get("editais", 0) + 1
        and after.get("edital_documents", 0) == before.get("edital_documents", 0) + 1
    )
    return {
        "status": "pass" if passed else "failed",
        "worker_exit_code": exit_code,
        "lost_submit_ack_status": state.get("submitted_status"),
        "replay_status": replay_status,
        "replay_outcomes": outcomes,
        "before": before,
        "after": after,
    }


def _run_finish_replay_scenario(
    *,
    api: ApiHandle,
    secret: str,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    temp_dir: Path,
    source: str = "bndes",
) -> dict[str, Any]:
    candidate, _ = _make_candidate_payload(source, 101)
    worker = _spawn_worker(
        api_url=api.base_url, secret=secret, source=source,
        mode="finish_hold", items=[candidate], work_dir=temp_dir,
    )
    try:
        state = _wait_worker_ready(worker)
        token = state.get("claim_token")
        item_id = state.get("item_id")
        revision = state.get("revision")
        if not isinstance(token, str) or not isinstance(item_id, int) or not isinstance(revision, int):
            raise HarnessExecutionError("finish worker did not expose private retry state")
        retry_status, retry_body, retry_elapsed = _work(
            api.base_url, source, token, "finish", secret=secret,
            item_id=item_id, revision=revision, outcome="accepted",
        )
        exit_code = _terminate_worker(worker)
        _expire_source(api_python, api_repo, database_url, schema, source)
        successor, _, _ = _claim(api.base_url, source, secret=secret, owner="p1-finish-successor")
        after_takeover = _snapshot(api_python, api_repo, database_url, schema)
        _release(api.base_url, source, successor, secret=secret, outcome="noop")
        after = _snapshot(api_python, api_repo, database_url, schema)
    finally:
        _dispose_workers((worker,))
    # ``finish_hold`` receives HTTP 200 before dropping the ACK. The server
    # state must already be accepted, and a successor must not duplicate it.
    passed = (
        state.get("status") == "claimed"
        and state.get("finished_status") == 200
        and retry_status == 200
        and exit_code not in (None, 0)
        and after_takeover.get("work_status", {}).get("accepted", 0) >= 1
        and after.get("source_work_items", 0) == after_takeover.get("source_work_items", 0)
    )
    return {
        "status": "pass" if passed else "failed",
        "worker_exit_code": exit_code,
        "lost_finish_ack_status": state.get("finished_status"),
        "finish_replay_status": retry_status,
        "finish_replay_reason": (
            retry_body.get("detail", {}).get("reason")
            if isinstance(retry_body.get("detail"), dict)
            else None
        ),
        "finish_replay_ms": retry_elapsed,
        "after_takeover": after_takeover,
        "after": after,
        "note": "The worker drops the committed finish response; the parent retries the exact finish while the original lease remains live.",
    }


def _run_changed_content_replay_scenario(
    *,
    api: ApiHandle,
    secret: str,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    temp_dir: Path,
    source: str = "bndes",
) -> dict[str, Any]:
    """Prove same-identity content changes requeue one durable row only."""
    initial, _ = _make_candidate_payload(source, 200, variant="v1")
    changed, _ = _make_candidate_payload(source, 200, variant="v2")
    initial["metadata"].update({
        "p1_fixture_variant": "v1",
        "source_snapshot_at": "2026-09-12T00:00:00+00:00",
        "source_content_hash": initial["worker_result"]["content_hash"],
        "title": "P1 changed-content fixture v1",
    })
    changed["metadata"].update({
        "p1_fixture_variant": "v2",
        "source_snapshot_at": "2026-09-12T00:01:00+00:00",
        "source_content_hash": changed["worker_result"]["content_hash"],
        "title": "P1 changed-content fixture v2",
    })
    record_id = str(initial["metadata"]["source_record_id"])
    before = _snapshot(api_python, api_repo, database_url, schema)
    worker = _spawn_worker(
        api_url=api.base_url, secret=secret, source=source,
        mode="changed_replay", items=[initial, changed], work_dir=temp_dir,
    )
    try:
        state = _wait_worker_ready(worker)
        exit_code = _terminate_worker(worker)
        if state.get("status") != "completed":
            # Do not let a failed fixture worker hold the source claim and
            # mask the later poison/backoff scenario's own result.
            _expire_source(api_python, api_repo, database_url, schema, source)
        after = _snapshot(api_python, api_repo, database_url, schema)
        identity = _identity_snapshot(
            api_python, api_repo, database_url, schema, source, record_id,
        )
    finally:
        _dispose_workers((worker,))

    edital_rows = identity.get("editais") or []
    document_rows = identity.get("documents") or []
    candidate_rows = identity.get("candidates") or []
    work_rows = identity.get("work_items") or []
    work_row = work_rows[0] if len(work_rows) == 1 else {}
    edital_row = edital_rows[0] if len(edital_rows) == 1 else {}
    document_row = document_rows[0] if len(document_rows) == 1 else {}
    initial_hash = initial["worker_result"]["content_hash"]
    changed_hash = changed["worker_result"]["content_hash"]
    passed = (
        state.get("status") == "completed"
        and exit_code == 0
        and state.get("initial_submit_status") == 200
        and state.get("initial_submit_outcome") == "inserted"
        and state.get("changed_submit_status") == 200
        and state.get("changed_submit_outcome") == "updated"
        and state.get("same_item_id") is True
        and state.get("initial_revision") == 1
        and state.get("changed_revision") == 2
        and after.get("source_work_items", 0) == before.get("source_work_items", 0) + 1
        and after.get("editais", 0) == before.get("editais", 0) + 1
        and after.get("edital_documents", 0) == before.get("edital_documents", 0) + 1
        and after.get("scrape_candidates", 0) == before.get("scrape_candidates", 0) + 1
        and work_row.get("status") == "accepted"
        and work_row.get("revision") == 2
        and len(edital_rows) == len(document_rows) == len(candidate_rows) == 1
        and edital_row.get("worker_content_hash") == changed_hash
        and document_row.get("content_hash") == changed_hash
        and initial_hash != changed_hash
    )
    return {
        "status": "pass" if passed else "failed",
        "worker_exit_code": exit_code,
        "source_record_id": record_id,
        "initial_revision": state.get("initial_revision"),
        "changed_revision": state.get("changed_revision"),
        "same_item_id": state.get("same_item_id"),
        "initial_submit_outcome": state.get("initial_submit_outcome"),
        "changed_submit_outcome": state.get("changed_submit_outcome"),
        "worker_failure_detail": state.get("detail"),
        "initial_content_hash": initial_hash,
        "changed_content_hash": changed_hash,
        "after": after,
        "identity": identity,
        "note": "The worker registers, accepts, updates, and re-accepts one stable source identity with changed content; the URL remains stable so the principal document is updated in place.",
    }


def _run_poison_backoff_scenario(
    *,
    api: ApiHandle,
    secret: str,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    source: str = "bndes",
) -> dict[str, Any]:
    """Prove retry backoff lets eligible work proceed before quarantine."""
    poison = _descriptor(source, 300)
    healthy = _descriptor(source, 301)
    poison_record_id = poison["metadata"]["source_record_id"]
    healthy_record_id = healthy["metadata"]["source_record_id"]
    before = _snapshot(api_python, api_repo, database_url, schema)
    token, _, _ = _claim(api.base_url, source, secret=secret, owner="p1-poison")
    status, _, _ = _work(
        api.base_url, source, token, "register", secret=secret,
        contract="candidate", items=[poison, healthy],
    )
    first_status, first_taken, _, = _work(
        api.base_url, source, token, "take", secret=secret, limit=1,
    )
    first_rows = first_taken.get("items") or []
    first_record = (
        (first_rows[0].get("payload") or {}).get("metadata", {}).get("source_record_id")
        if first_rows else None
    )
    if first_record != poison_record_id:
        _release(api.base_url, source, token, secret=secret, outcome="noop")
        return {
            "status": "failed",
            "registered_status": status,
            "first_take_status": first_status,
            "first_take_record_id": first_record,
            "expected_first_take_record_id": poison_record_id,
            "note": "The poison fixture was not the oldest pending row; the scenario stopped without finishing an unrelated row.",
        }
    poison_finish_status, _, _ = _work(
        api.base_url, source, token, "finish", secret=secret,
        item_id=first_rows[0]["id"],
        revision=first_rows[0]["revision"],
        outcome="failed", error_code="processing_failed",
    )
    after_first_failure = _identity_snapshot(
        api_python, api_repo, database_url, schema, source, poison_record_id,
    )
    after_first_rows = after_first_failure.get("work_items") or []
    after_first_row = after_first_rows[0] if len(after_first_rows) == 1 else {}
    eligible_status, eligible_taken, _, = _work(
        api.base_url, source, token, "take", secret=secret, limit=1,
    )
    eligible_rows = eligible_taken.get("items") or []
    eligible_record = (
        (eligible_rows[0].get("payload") or {}).get("metadata", {}).get("source_record_id")
        if eligible_rows else None
    )
    healthy_finish_status, _, _ = _work(
        api.base_url, source, token, "finish", secret=secret,
        item_id=eligible_rows[0]["id"] if eligible_rows else None,
        revision=eligible_rows[0]["revision"] if eligible_rows else None,
        outcome="accepted",
    )
    poison_attempts: list[int | None] = []
    poison_take_statuses: list[int | None] = []
    poison_finish_statuses: list[int | None] = []
    for _ in range(2):
        _expire_work_items(api_python, api_repo, database_url, schema, source)
        take_status, taken, _, = _work(
            api.base_url, source, token, "take", secret=secret, limit=1,
        )
        rows = taken.get("items") or []
        poison_take_statuses.append(take_status)
        if not rows:
            poison_attempts.append(None)
            poison_finish_statuses.append(None)
            continue
        row_record = (rows[0].get("payload") or {}).get("metadata", {}).get("source_record_id")
        if row_record != poison_record_id:
            poison_attempts.append(None)
            poison_finish_statuses.append(None)
            continue
        detail = _identity_snapshot(
            api_python, api_repo, database_url, schema, source, poison_record_id,
        )
        details = detail.get("work_items") or []
        poison_attempts.append(details[0].get("attempts") if len(details) == 1 else None)
        finish_status, _, _ = _work(
            api.base_url, source, token, "finish", secret=secret,
            item_id=rows[0]["id"], revision=rows[0]["revision"],
            outcome="failed", error_code="processing_failed",
        )
        poison_finish_statuses.append(finish_status)
    _release(api.base_url, source, token, secret=secret, outcome="noop")
    after = _snapshot(api_python, api_repo, database_url, schema)
    poison_identity = _identity_snapshot(
        api_python, api_repo, database_url, schema, source, poison_record_id,
    )
    healthy_identity = _identity_snapshot(
        api_python, api_repo, database_url, schema, source, healthy_record_id,
    )
    poison_rows = poison_identity.get("work_items") or []
    healthy_rows = healthy_identity.get("work_items") or []
    poison_row = poison_rows[0] if len(poison_rows) == 1 else {}
    healthy_row = healthy_rows[0] if len(healthy_rows) == 1 else {}
    passed = (
        status == 200
        and first_status == 200
        and first_record == poison_record_id
        and poison_finish_status == 200
        and after_first_row.get("status") == "pending"
        and after_first_row.get("attempts") == 1
        and after_first_row.get("error_code") == "processing_failed"
        and after_first_row.get("retry_after_at")
        and eligible_status == 200
        and eligible_record == healthy_record_id
        and healthy_finish_status == 200
        and poison_attempts == [2, 3]
        and poison_take_statuses == [200, 200]
        and poison_finish_statuses == [200, 200]
        and poison_row.get("status") == "quarantined"
        and poison_row.get("attempts") == 3
        and poison_row.get("error_code") == "processing_failed"
        and healthy_row.get("status") == "accepted"
        and after.get("source_work_items", 0) == before.get("source_work_items", 0) + 2
    )
    return {
        "status": "pass" if passed else "failed",
        "registered_status": status,
        "first_take_status": first_status,
        "first_take_record_id": first_record,
        "first_failure_finish_status": poison_finish_status,
        "eligible_take_status": eligible_status,
        "eligible_record_id": eligible_record,
        "healthy_finish_status": healthy_finish_status,
        "poison_attempts_before_finishes": poison_attempts,
        "poison_take_statuses": poison_take_statuses,
        "poison_finish_statuses": poison_finish_statuses,
        "poison": poison_row,
        "healthy": healthy_row,
        "after_first_failure": after_first_failure,
        "after": after,
        "note": "The oldest pending fixture is deliberately poisoned first; its retry backoff lets the next eligible descriptor finish, then three bounded attempts quarantine the poison row.",
    }


def _run_capacity_scenario(
    *,
    api: ApiHandle,
    secret: str,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    temp_dir: Path,
    arrival_rate_per_hour: float,
    storage_budget_bytes: int | None,
    warm_samples: int,
) -> dict[str, Any]:
    warm = RequestStats()
    for _ in range(warm_samples):
        _get(
            api.base_url,
            "/api/pipeline/source-schedule/catalog",
            secret=secret,
            stats=warm,
        )
    claim_workers = [
        _spawn_worker(
            api_url=api.base_url, secret=secret, source=source,
            mode="claim_hold", items=[], work_dir=temp_dir,
        )
        for source in SOURCE_KEYS
    ]
    states: list[dict[str, Any]] = []
    peak_memory_bytes: int | None = None
    memory_samples = 0
    try:
        for worker in claim_workers:
            states.append(_wait_worker_ready(worker))
        peak_connections = 0
        peak_claims = 0
        observation_deadline = time.monotonic() + 2
        while time.monotonic() < observation_deadline:
            current = _snapshot(api_python, api_repo, database_url, schema)
            peak_connections = max(peak_connections, int(current.get("db_connections", 0)))
            peak_claims = max(peak_claims, int(current.get("active_claims", 0)))
            sample = _sample_peak_rss(
                [api.process, *(worker.process for worker in claim_workers)]
            )
            if sample is not None:
                peak_memory_bytes = max(peak_memory_bytes or 0, sample)
                memory_samples += 1
            time.sleep(0.05)
    finally:
        _dispose_workers(claim_workers)
    for source in SOURCE_KEYS:
        _expire_source(api_python, api_repo, database_url, schema, source)

    drain_started = time.perf_counter()
    drain_workers = [
        _spawn_worker(
            api_url=api.base_url, secret=secret, source=source,
            mode="drain",
            # Use a disjoint range because the earlier crash/replay scenarios
            # intentionally leave accepted descriptors in the same schema.
            items=[_descriptor(source, index) for index in range(1001, 1005)],
            work_dir=temp_dir,
        )
        for source in CAPACITY_SOURCES
    ]
    try:
        drain_states = [_wait_worker_ready(worker, timeout=90) for worker in drain_workers]
        wall_seconds = max(0.001, time.perf_counter() - drain_started)
    finally:
        _dispose_workers(drain_workers)
    completed = sum(int(state.get("completed", 0)) for state in drain_states)
    service_rate = completed / wall_seconds * 3600 if completed else 0.0
    final = _snapshot(api_python, api_repo, database_url, schema)
    max_connections = int(final.get("max_connections", 0) or 0)
    reserved = int(final.get("superuser_reserved_connections", 0) or 0)
    usable = max_connections - reserved if max_connections else None
    storage_headroom = None
    if storage_budget_bytes is not None and storage_budget_bytes > 0:
        storage_headroom = max(
            0.0,
            1 - int(final.get("database_size_bytes", 0) or 0) / storage_budget_bytes,
        )
    capacity_stats = RequestStats()
    capacity_stats.merge(warm)
    for state in states + drain_states:
        request_summary = state.get("requests")
        if not isinstance(request_summary, dict):
            continue
        # Child summaries are intentionally aggregate-only; retain statuses
        # and counts without trying to reconstruct individual latencies.
        capacity_stats.total += int(request_summary.get("requests", 0) or 0)
        capacity_stats.failures += int(request_summary.get("failures_5xx_or_transport", 0) or 0)
        capacity_stats.timeouts += int(request_summary.get("timeouts", 0) or 0)
        for status, count in (request_summary.get("status_counts") or {}).items():
            capacity_stats.statuses[str(status)] += int(count or 0)
    checks = evaluate_thresholds(
        request_stats=capacity_stats,
        claim_p95_ms=percentile(warm.latencies_ms, 95),
        peak_connections=peak_connections,
        usable_connections=usable,
        storage_headroom_ratio=storage_headroom,
        service_rate_per_hour=service_rate,
        arrival_rate_per_hour=arrival_rate_per_hour,
    )
    accepted_claims = sum(state.get("status") == "claimed" for state in states)
    rejected_reasons = Counter(
        state.get("reason") for state in states if state.get("status") == "rejected"
    )
    aggregate_requests = {
        "requests": capacity_stats.total,
        "failures_5xx_or_transport": capacity_stats.failures,
        "timeouts": capacity_stats.timeouts,
        "status_counts": dict(sorted(capacity_stats.statuses.items())),
    }
    drain_failures = sum(state.get("status") != "completed" for state in drain_states)
    return {
        "status": (
            "pass"
            if accepted_claims == MAX_CONCURRENT_SOURCE_RUNS
            and drain_failures == 0
            and checks["status"] == "pass"
            else "blocked_or_failed"
        ),
        "claim_limit": MAX_CONCURRENT_SOURCE_RUNS,
        "accepted_claims": accepted_claims,
        "rejected_claims": sum(state.get("status") == "rejected" for state in states),
        "rejected_reasons": dict(rejected_reasons),
        "peak_active_claims": peak_claims,
        "worker_claim_states": [
            {key: value for key, value in state.items() if key not in {"claim_token"}}
            for state in states
        ],
        "drain_workers": drain_states,
        "drain_failures": drain_failures,
        "completed_descriptors": completed,
        "drain_wall_seconds": wall_seconds,
        "memory": {
            "peak_rss_bytes": peak_memory_bytes,
            "samples": memory_samples,
            "scope": "Repo A API plus four claim workers during the two-second capacity observation",
        },
        "final_snapshot": final,
        "latency": safe_latency_summary(warm),
        "latency_scope": "warm authenticated catalog GETs; worker-call counts are aggregate below",
        "request_aggregate": aggregate_requests,
        "quantitative_gates": checks,
    }


def _seed_catalog(
    *,
    api_python: str,
    api_repo: Path,
    database_url: str,
    schema: str,
    active_sources: Iterable[str],
    temp_dir: Path,
) -> Path:
    active_set = set(active_sources)
    manifest = [
        {
            "source_key": source,
            "catalog_status": "active" if source in active_set else "paused",
            "expected_interval_minutes": 60,
            "max_run_minutes": 20,
            "zero_inventory_is_warning": True,
            "operational_verified_at": "2026-09-12T00:00:00Z",
            "operational_evidence": "P1 isolated disposable PostgreSQL fixture",
        }
        for source in SOURCE_KEYS
    ]
    path = temp_dir / "operational-manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    _run_a_module(
        api_python,
        api_repo,
        ["scripts/seed_source_catalog.py", "--operational-manifest", str(path)],
        _helper_env(database_url, schema),
        label="seed-catalog",
    )
    return path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("P1_DATABASE_URL"),
        help="Disposable loopback PostgreSQL URL (or P1_DATABASE_URL); never production/staging",
    )
    parser.add_argument(
        "--api-repo", type=Path, default=DEFAULT_A_REPO,
        help="Repo A checkout containing app.main and scripts/migrate_schema.py",
    )
    parser.add_argument(
        "--api-python", default=None,
        help="Python executable for Repo A (defaults to A/.venv or current interpreter)",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=None,
        help="Sanitized evidence directory (default: production-only/.../p1-harness-<UTC>)",
    )
    parser.add_argument(
        "--arrival-rate-per-hour", type=float, default=22.0,
        help="Declared descriptor arrival rate used only for the capacity ratio",
    )
    parser.add_argument(
        "--storage-budget-bytes", type=int, default=None,
        help="Confirmed disposable storage allowance; omission blocks storage gate",
    )
    parser.add_argument(
        "--warm-samples", type=int, default=20,
        help="Authenticated compact catalog reads for the warm p95 measurement",
    )
    parser.add_argument(
        "--admitted-source", choices=SOURCE_KEYS, default="bndes",
        help="Closed-beta source exercised by correctness scenarios (default: bndes)",
    )
    # Private child-process switches. They are intentionally hidden from the
    # normal help so operators invoke the parent command only.
    parser.add_argument("--worker-mode", choices=("register_hold", "submit_hold", "finish_hold", "changed_replay", "claim_hold", "drain"), help=argparse.SUPPRESS)
    parser.add_argument("--worker-source", help=argparse.SUPPRESS)
    parser.add_argument("--worker-items", help=argparse.SUPPRESS)
    parser.add_argument("--worker-control", help=argparse.SUPPRESS)
    parser.add_argument("--worker-ready", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_mode:
        for name in ("worker_source", "worker_items", "worker_control", "worker_ready"):
            if not getattr(args, name):
                parser.error(f"--{name.replace('_', '-')} is required with --worker-mode")
        return args
    if args.arrival_rate_per_hour <= 0:
        parser.error("--arrival-rate-per-hour must be positive")
    if args.warm_samples < 5:
        parser.error("--warm-samples must be at least 5")
    if args.storage_budget_bytes is not None and args.storage_budget_bytes <= 0:
        parser.error("--storage-budget-bytes must be positive")
    return args


def run_harness(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    target = validate_disposable_database_url(args.database_url)
    api_repo = args.api_repo.resolve()
    if not api_repo.is_dir():
        raise HarnessConfigurationError(f"Repo A checkout does not exist: {api_repo}")
    api_python = _choose_python(api_repo, args.api_python)
    output_dir = (
        args.output_dir
        or DEFAULT_OUTPUT_ROOT / f"p1-harness-{utc_now().strftime('%Y%m%dT%H%M%SZ')}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    schema = make_schema_name()
    if not SCHEMA_RE.fullmatch(schema):
        raise HarnessExecutionError("Generated schema name failed its safety check")
    pipeline_secret = secrets.token_urlsafe(32)
    started_at = utc_now()
    report: dict[str, Any] = {
        "gate": "P1",
        "status": "running",
        "started_at": started_at.isoformat(),
        "target": {
            "kind": "disposable_local_postgresql",
            "identity": target.label,
            "schema": schema,
        },
        "candidate": {
            "repo_a": str(api_repo),
            "repo_b": str(B_REPO),
            "api_python": Path(api_python).name,
            "worker_python": Path(sys.executable).name,
        },
        "declared_workload": {
            "admitted_source": args.admitted_source,
            "capacity_sources": list(CAPACITY_SOURCES),
            "descriptor_items_per_drain_worker": 4,
            "warm_samples": args.warm_samples,
            "arrival_rate_per_hour": args.arrival_rate_per_hour,
            "storage_budget_bytes": args.storage_budget_bytes,
        },
        "scenarios": {},
        "skipped": [],
    }
    api: ApiHandle | None = None
    capacity_api: ApiHandle | None = None
    temp_dir = Path(tempfile.mkdtemp(prefix="p1-harness-"))
    try:
        base_env = _helper_env(args.database_url, schema)
        _run_a_python(api_python, api_repo, _PING_SQL, base_env, label="database-ping")
        # Create the isolated schema without relying on psql being installed.
        create_sql = (
            "import os\nfrom sqlalchemy import create_engine, text\n"
            "engine=create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)\n"
            "with engine.begin() as c: c.execute(text('CREATE SCHEMA IF NOT EXISTS \"' + os.environ['P1_SCHEMA'] + '\"'))\n"
            "engine.dispose()\nprint('ok')\n"
        )
        _run_a_python(api_python, api_repo, create_sql, base_env, label="create-schema")
        _run_a_module(
            api_python, api_repo, ["-m", "scripts.migrate_schema"],
            base_env, label="migrate-schema", timeout=240,
        )
        _seed_catalog(
            api_python=api_python, api_repo=api_repo, database_url=args.database_url,
            schema=schema, active_sources=SOURCE_KEYS, temp_dir=temp_dir,
        )

        closed_env = _api_env(
            args.database_url, schema, mode="closed_beta", admitted_source=args.admitted_source,
            pipeline_secret=pipeline_secret, api_repo=api_repo,
        )
        api = _start_api(api_python, api_repo, closed_env)
        capabilities_status, capabilities, _, _ = _get(
            api.base_url, "/api/pipeline/capabilities", secret=pipeline_secret,
        )
        if capabilities_status != 200 or capabilities.get("source_admission_mode") != "closed_beta":
            reason = capabilities.get("source_admission_reason") or capabilities.get("detail")
            raise HarnessExecutionError(
                "Repo A closed-beta capabilities preflight failed "
                f"(status={capabilities_status}, reason={reason or 'unknown'})"
            )
        report["api_closed_beta_capabilities"] = {
            key: capabilities.get(key)
            for key in (
                "source_admission_mode", "source_admission_ready", "admitted_source",
                "admitted_contract", "source_claim_enforcement",
            )
        }
        report["scenarios"]["worker_termination_and_recovery"] = _run_termination_scenario(
            api=api, secret=pipeline_secret, api_python=api_python, api_repo=api_repo,
            database_url=args.database_url, schema=schema, temp_dir=temp_dir,
            source=args.admitted_source,
        )
        report["scenarios"]["lost_submit_ack_replay_idempotency"] = _run_replay_scenario(
            api=api, secret=pipeline_secret, api_python=api_python, api_repo=api_repo,
            database_url=args.database_url, schema=schema, temp_dir=temp_dir,
            source=args.admitted_source,
        )
        report["scenarios"]["lost_finish_ack_replay"] = _run_finish_replay_scenario(
            api=api, secret=pipeline_secret, api_python=api_python, api_repo=api_repo,
            database_url=args.database_url, schema=schema, temp_dir=temp_dir,
            source=args.admitted_source,
        )
        report["scenarios"]["changed_content_replay"] = _run_changed_content_replay_scenario(
            api=api, secret=pipeline_secret, api_python=api_python, api_repo=api_repo,
            database_url=args.database_url, schema=schema, temp_dir=temp_dir,
            source=args.admitted_source,
        )
        report["scenarios"]["poison_backoff_and_quarantine"] = _run_poison_backoff_scenario(
            api=api, secret=pipeline_secret, api_python=api_python, api_repo=api_repo,
            database_url=args.database_url, schema=schema,
            source=args.admitted_source,
        )
        _stop_api(api)
        api = None

        # Capacity uses legacy admission solely to exercise the shared global
        # lease pool across four active isolated fixture sources. It does not
        # relax or represent the closed-beta production configuration.
        legacy_env = _api_env(
            args.database_url, schema, mode="legacy", admitted_source="",
            pipeline_secret=pipeline_secret, api_repo=api_repo,
        )
        capacity_api = _start_api(api_python, api_repo, legacy_env)
        report["capacity"] = _run_capacity_scenario(
            api=capacity_api, secret=pipeline_secret, api_python=api_python,
            api_repo=api_repo, database_url=args.database_url, schema=schema,
            temp_dir=temp_dir, arrival_rate_per_hour=args.arrival_rate_per_hour,
            storage_budget_bytes=args.storage_budget_bytes, warm_samples=args.warm_samples,
        )
        _stop_api(capacity_api)
        capacity_api = None
        scenario_statuses = [
            result.get("status") for result in report["scenarios"].values()
        ]
        capacity_status = report.get("capacity", {}).get("status")
        report["status"] = (
            "pass"
            if all(status == "pass" for status in scenario_statuses)
            and capacity_status == "pass"
            else "blocked_or_failed"
        )
    except (HarnessConfigurationError, HarnessExecutionError) as exc:
        report["status"] = "blocked_or_failed"
        report["error"] = str(exc)
    finally:
        _stop_api(api)
        _stop_api(capacity_api)
        try:
            _run_a_python(
                api_python, api_repo, _DROP_SCHEMA_SQL,
                _helper_env(args.database_url, schema), label="drop-schema",
            )
        except Exception as exc:
            report["cleanup_error"] = type(exc).__name__
        try:
            for path in temp_dir.iterdir():
                path.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError:
            report["temp_cleanup"] = "incomplete"
    report["finished_at"] = utc_now().isoformat()
    report["target"]["schema_dropped"] = "cleanup_error" not in report
    sanitized = redact(report, (pipeline_secret,))
    report_path = output_dir / "p1-isolated-harness.json"
    report_path.write_text(json.dumps(sanitized, indent=2, sort_keys=True), encoding="utf-8")
    # A small human-readable companion makes review practical without opening
    # JSON, while keeping the JSON as the machine-readable source of truth.
    summary = [
        f"P1 isolated harness: {sanitized['status']}",
        f"Target: {target.label}/{schema} (dropped={sanitized['target']['schema_dropped']})",
        f"Evidence: {report_path}",
    ]
    (output_dir / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return (0 if sanitized["status"] == "pass" else 1), sanitized


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.worker_mode:
        return _run_worker_mode(args)
    try:
        code, report = run_harness(args)
    except HarnessConfigurationError as exc:
        print(f"P1 harness configuration blocked: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"P1 harness failed before evidence could be written: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "evidence": report.get("target", {})}, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
