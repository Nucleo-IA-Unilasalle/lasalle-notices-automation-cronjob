"""Enforce global admission and a wall-clock deadline outside OCR threads."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from source_control import SourceControl, AdmissionConflict
from build_source_matrix import load_registry, validate_registry


def remaining_budget(now, job_started, job_minutes=20, application_seconds=1080):
    if job_minutes <= 0 or application_seconds <= 0 or job_started > now:
        raise ValueError("Invalid job budget")
    # Leave two minutes for process cleanup, lease release, telemetry/artifacts.
    return max(0, min(application_seconds, job_minutes * 60 - (now - job_started) - 120))


def stop_process_tree(process):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       check=False, capture_output=True, timeout=15)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("script", choices=("scripts/discover_all_candidates.py", "scripts/discover_pncp_candidates.py"))
    args = parser.parse_args(argv)
    registry = load_registry()
    entries = {entry["source_key"]: entry for entry in validate_registry(registry)}
    entry = entries.get(args.source)
    if entry is None:
        parser.error("Source is not in the execution registry")
    audit = os.environ.get("DISCOVERY_AUDIT_ONLY", "false").lower() == "true"
    if entry["rollout_mode"] in {"paused", "audit"} and not audit:
        parser.error("Registry holds this source outside ingestion; use audit mode")
    defaults = registry["defaults"]
    start = time.time()
    budget = remaining_budget(start, float(os.environ.get("SOURCE_JOB_STARTED_AT", start)),
                              int(os.environ.get("SOURCE_JOB_TIMEOUT_MINUTES", defaults["run_timeout_minutes"])),
                              defaults["application_budget_seconds"])
    if budget < 60:
        print("No application budget remains after setup", file=sys.stderr)
        return 1
    deadline = time.monotonic() + budget
    client = SourceControl(args.source)
    force = audit or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    while True:
        try:
            client.claim(force=force)
            break
        except AdmissionConflict as exc:
            if exc.reason in {"not_due", "claim_active"}:
                print(f"Source skipped: {exc.reason}; no collection success recorded")
                return 0
            if exc.reason == "capacity_full" and deadline - time.monotonic() > 450:
                time.sleep(15)
                continue
            print(f"Source admission denied: {exc.reason}", file=sys.stderr)
            return 1
    process = None
    result = 1
    outcome = "failed"
    try:
        with tempfile.TemporaryDirectory(prefix="source-run-") as folder:
            completion = Path(folder) / "collection-complete"
            env = dict(os.environ, SOURCE_CLAIM_TOKEN=client.token,
                       SOURCE_DEADLINE_EPOCH=str(time.time() + max(0, deadline - time.monotonic())),
                       SOURCE_COLLECTION_COMPLETE_FILE=str(completion), SOURCE_WORK_ENABLED="true")
            env.update(SOURCES=args.source, SUBMISSION_CONTRACT=entry["submission_contract"],
                       SCRAPE_MAX_PDFS_PER_RUN=str(defaults["pdf_limit"]), FILTER_POLICY=entry["filter_policy"])
            process = subprocess.Popen([sys.executable, args.script], env=env,
                                       start_new_session=os.name != "nt")
            next_renew = time.monotonic() + 60
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Source application budget exhausted")
                if time.monotonic() >= next_renew:
                    client.renew()  # Any uncertainty stops the worker before lease expiry.
                    next_renew = time.monotonic() + 60
                time.sleep(0.5)
            result = process.returncode
            outcome = "noop" if audit else "complete" if completion.exists() else "failed"
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Managed source stopped: {type(exc).__name__}", file=sys.stderr)
        result = 1
    finally:
        stop_process_tree(process)
        try:
            client.release(outcome)
        except Exception:
            print("Source release unconfirmed; lease expiry will recover ownership", file=sys.stderr)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
