"""Read-only source freshness monitor (Plan 06, free-only).

Compares the approved registry (config/source_schedule.json) against Repo A
public catalog + source-run health without triggering ingestion. Fails closed
on auth/schema/network errors (monitoring incident, never zero-source success).

Outputs a JSON report with per-source staleness, missing telemetry, and queue
depth signals. Notification dedup + heartbeat live in the operator channel;
this script only produces the report artifact. GitHub-only scheduling shares
the platform failure domain -- a platform-wide outage has no guaranteed
real-time alert; daily human review covers retrospective gaps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # type: ignore

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "source_schedule.json"
STALE_MINUTES_DEFAULT = 120


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"error: {name} is required (read-only monitor access)", file=sys.stderr)
        raise SystemExit(2)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stale-minutes", type=int, default=STALE_MINUTES_DEFAULT)
    parser.add_argument("--output", default="freshness-report.json")
    args = parser.parse_args()

    backend = os.environ.get("RENDER_APP_URL", "").rstrip("/")
    secret = os.environ.get("PIPELINE_SECRET", "")
    if not backend or not secret:
        print("error: RENDER_APP_URL/PIPELINE_SECRET required", file=sys.stderr)
        return 2

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    expected = [s["source_key"] for s in registry["sources"] if s.get("rollout_mode") != "paused"]

    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(f"{backend}/api/sources/summary", headers=headers, timeout=20)
        resp.raise_for_status()
        summary = resp.json()
    except Exception as exc:
        print(f"monitoring incident: cannot read catalog summary: {exc}", file=sys.stderr)
        report = {
            "checked_at": checked_at,
            "stale_threshold_minutes": args.stale_minutes,
            "expected_sources": expected,
            "incident": "monitor_read_failed",
            "missing_telemetry": expected,
            "stale": [],
            "healthy": [],
        }
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 1

    # Summary is aggregate-only; per-source detail requires the public list.
    # Missing samples are unknown, never compliant by default.
    try:
        detail = requests.get(f"{backend}/api/sources?limit=100", headers=headers, timeout=20)
        detail.raise_for_status()
        items = detail.json().get("items", [])
    except Exception as exc:
        print(f"monitoring incident: cannot read source list: {exc}", file=sys.stderr)
        return 1

    by_key = {i.get("source_key"): i for i in items if isinstance(i, dict)}
    missing = [k for k in expected if k not in by_key or not by_key[k].get("last_checked_at")]
    stale: list[str] = []
    healthy: list[str] = []
    unhealthy: list[str] = []
    now = datetime.now(timezone.utc)
    for key in expected:
        row = by_key.get(key)
        if not row or not row.get("last_checked_at"):
            continue
        try:
            last = datetime.fromisoformat(str(row["last_checked_at"]).replace("Z", "+00:00"))
            if last.tzinfo is None:
                raise ValueError("Timestamp must include a timezone")
        except ValueError:
            stale.append(key)
            continue
        age_min = (now - last).total_seconds() / 60.0
        if age_min < 0 or age_min > args.stale_minutes:
            stale.append(key)
        elif row.get("health_status") != "healthy":
            # A recent failed/warning run is fresh telemetry, not proof of
            # successful collection. Unknown states must also fail closed.
            unhealthy.append(key)
        else:
            healthy.append(key)

    report = {
        "checked_at": checked_at,
        "stale_threshold_minutes": args.stale_minutes,
        "expected_sources": expected,
        "missing_telemetry": missing,
        "stale": stale,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "summary": summary,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"freshness: {len(healthy)} healthy, {len(unhealthy)} unhealthy, {len(stale)} stale, {len(missing)} missing of {len(expected)} expected")
    if stale or missing or unhealthy:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
