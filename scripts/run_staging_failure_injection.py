"""Staging Failure Injection & Fencing Test Runner.

Executes tests against https://lasalle-notices-api-staging.onrender.com
DOX compliant: Retrieves PIPELINE_SECRET via Render REST API in-memory.
Never prints or logs secrets or raw tokens.
"""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import requests

STAGING_BASE_URL = "https://lasalle-notices-api-staging.onrender.com"
BASE_URL = STAGING_BASE_URL
RENDER_SERVICE_ID = "srv-d9i41fl8nd3s7397hcig"
LIVE_MUTATION_ARGUMENT = "--allow-live-staging-mutation"
LIVE_MUTATION_ACKNOWLEDGEMENT = "staging-only"
SENSITIVE_KEY_PARTS = ("token", "secret", "authorization", "password", "cookie", "api_key")


def require_live_mutation_consent(argv: list[str]) -> None:
    """Fail closed: this probe changes staging lease state and is never a production tool."""
    if BASE_URL != STAGING_BASE_URL:
        raise RuntimeError("Failure injection is restricted to the fixed staging API URL")
    if LIVE_MUTATION_ARGUMENT not in argv:
        raise RuntimeError(
            f"Refusing live staging mutation; pass {LIVE_MUTATION_ARGUMENT} explicitly"
        )
    if os.environ.get("STAGING_FAILURE_INJECTION_ACK") != LIVE_MUTATION_ACKNOWLEDGEMENT:
        raise RuntimeError(
            "Refusing live staging mutation; set STAGING_FAILURE_INJECTION_ACK=staging-only"
        )


def get_pipeline_secret() -> str:
    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key:
        raise RuntimeError("RENDER_API_KEY environment variable not set")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    resp = requests.get(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars?limit=100",
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch Render env-vars: HTTP {resp.status_code}")
    for item in resp.json():
        ev = item.get("envVar", item)
        if ev.get("key") == "PIPELINE_SECRET":
            val = ev.get("value")
            if val:
                return val
    raise RuntimeError("PIPELINE_SECRET not found in service environment")


def mask_token(token: str) -> str:
    if not token:
        return "[REDACTED]"
    # Do not preserve token prefixes or suffixes in durable evidence.
    return f"[REDACTED sha256:{hashlib.sha256(token.encode()).hexdigest()}]"


def sanitize_dict(d: Any) -> Any:
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            normalized_key = k.lower().replace("-", "_")
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                out[k] = mask_token(str(v))
            else:
                out[k] = sanitize_dict(v)
        return out
    elif isinstance(d, list):
        return [sanitize_dict(x) for x in d]
    return d


class StagingTestRunner:
    def __init__(self, secret: str):
        self.secret = secret
        self.headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }
        self.results: Dict[str, Any] = {}
        self._active_claims: dict[tuple[str, str], None] = {}

    def post(self, path: str, payload: Dict[str, Any]) -> requests.Response:
        url = f"{BASE_URL}/api/pipeline/{path}"
        response = requests.post(url, json=payload, headers=self.headers, timeout=20)
        if path == "source-schedule/claims" and response.status_code == 201:
            body = response.json()
            token = body.get("claim_token") if isinstance(body, dict) else None
            source_key = payload.get("source_key")
            if isinstance(token, str) and isinstance(source_key, str):
                # Register before returning so cleanup still runs if a later check crashes.
                # A new 201 for this source necessarily fences any older tracked token.
                for claim_key in list(self._active_claims):
                    if claim_key[0] == source_key:
                        self._active_claims.pop(claim_key, None)
                self._active_claims[(source_key, token)] = None
        elif path == "source-schedule/claims/release" and response.status_code == 200:
            body = response.json()
            source_key = payload.get("source_key")
            token = payload.get("claim_token")
            if isinstance(body, dict) and body.get("accepted") is True:
                self._active_claims.pop((source_key, token), None)
        elif path in {"source-schedule/claims/renew", "source-schedule/claims/release"}:
            body = response.json()
            detail = body.get("detail") if isinstance(body, dict) else None
            reason = detail.get("reason") if isinstance(detail, dict) else None
            if reason in {"claim_expired", "claim_missing", "claim_invalid"}:
                # The server has already fenced this token, so retrying cleanup would
                # turn a successful expiry test into a false cleanup failure.
                self._active_claims.pop((payload.get("source_key"), payload.get("claim_token")), None)
        return response

    def cleanup_active_claims(self) -> list[Dict[str, Any]]:
        """Best-effort `noop` release for every tracked lease, including error paths."""
        cleanup_results: list[Dict[str, Any]] = []
        for source_key, token in list(self._active_claims):
            try:
                response = self.post(
                    "source-schedule/claims/release",
                    {"source_key": source_key, "claim_token": token, "outcome": "noop"},
                )
                body = response.json()
                cleanup_results.append(
                    {
                        "source_key": source_key,
                        "status_code": response.status_code,
                        "accepted": isinstance(body, dict) and body.get("accepted") is True,
                    }
                )
            except Exception as exc:  # Cleanup must not hide the original test failure.
                cleanup_results.append(
                    {"source_key": source_key, "error_type": type(exc).__name__, "accepted": False}
                )
        return cleanup_results

    def run_task_1_concurrency_limit(self) -> Dict[str, Any]:
        """Task 1: Boundary Test - 4 concurrent claims for 3 slots."""
        sources = ["brde", "fapergs", "iis_rio", "worldbank"]
        owner = "failure-injection-test"
        lease_seconds = 120

        print(f"[{datetime.now(timezone.utc).isoformat()}] Task 1: Concurrently claiming 4 sources: {sources}")

        def _claim(src: str):
            payload = {
                "source_key": src,
                "owner": owner,
                "lease_seconds": lease_seconds,
                "force": True,
                "scope": "default",
                "purpose": "collection",
            }
            start = time.perf_counter()
            r = self.post("source-schedule/claims", payload)
            duration = time.perf_counter() - start
            return {
                "source": src,
                "status_code": r.status_code,
                "duration_ms": round(duration * 1000, 2),
                "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text,
            }

        claim_responses = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_claim, source): source for source in sources}
            for future in concurrent.futures.as_completed(futures):
                source = futures[future]
                try:
                    # `post` tracks a 201 lease before this result is recorded.
                    claim_responses.append(future.result())
                except Exception as exc:
                    claim_responses.append(
                        {"source": source, "status_code": None, "error_type": type(exc).__name__}
                    )

        admitted = [res for res in claim_responses if res["status_code"] == 201]
        rejected = [res for res in claim_responses if res["status_code"] == 409]

        capacity_full_rejected = [
            res for res in rejected
            if isinstance(res["body"], dict)
            and res["body"].get("detail", {}).get("reason") == "capacity_full"
        ]

        print(f"Admitted claims count: {len(admitted)} (expected 3)")
        print(f"Rejected claims count: {len(rejected)} (expected 1)")
        print(f"Capacity full rejected count: {len(capacity_full_rejected)} (expected 1)")

        # Release all admitted claims
        release_results = []
        for res in admitted:
            token = res["body"].get("claim_token") if isinstance(res["body"], dict) else None
            src = res["source"]
            if not isinstance(token, str):
                release_results.append({"source": src, "status_code": None, "accepted": False})
                continue
            rel_payload = {
                "source_key": src,
                "claim_token": token,
                "outcome": "noop",
            }
            start = time.perf_counter()
            try:
                r_rel = self.post("source-schedule/claims/release", rel_payload)
                duration = time.perf_counter() - start
                release_results.append({
                    "source": src,
                    "status_code": r_rel.status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "body": r_rel.json() if r_rel.headers.get("content-type", "").startswith("application/json") else r_rel.text,
                })
            except Exception as exc:
                release_results.append({"source": src, "status_code": None, "error_type": type(exc).__name__})

        all_released_cleanly = all(
            r["status_code"] == 200
            and isinstance(r.get("body"), dict)
            and r["body"].get("accepted") is True
            for r in release_results
        )
        print(f"All admitted claims released cleanly (outcome=noop): {all_released_cleanly}")

        gate_passed = (
            len(admitted) == 3
            and len(rejected) == 1
            and len(capacity_full_rejected) == 1
            and all_released_cleanly
        )

        return {
            "gate_passed": gate_passed,
            "admitted_count": len(admitted),
            "rejected_count": len(rejected),
            "capacity_full_count": len(capacity_full_rejected),
            "claim_responses": [sanitize_dict(r) for r in claim_responses],
            "release_responses": [sanitize_dict(r) for r in release_results],
        }

    def run_task_2_stale_owner_fencing(self) -> Dict[str, Any]:
        """Task 2: Stale-Owner Fencing."""
        print(f"[{datetime.now(timezone.utc).isoformat()}] Task 2: Stale-Owner Fencing")

        # 2A: Test 'empraba' as requested
        empraba_payload = {
            "source_key": "empraba",
            "owner": "owner-alpha",
            "lease_seconds": 120,
            "force": False,
        }
        r_empraba = self.post("source-schedule/claims", empraba_payload)
        empraba_result = {
            "source_key": "empraba",
            "status_code": r_empraba.status_code,
            "body": r_empraba.json() if r_empraba.headers.get("content-type", "").startswith("application/json") else r_empraba.text,
        }
        print(
            f"Empraba claim status: {r_empraba.status_code}, "
            f"body: {sanitize_dict(empraba_result['body'])}"
        )
        empraba_detail = (
            empraba_result["body"].get("detail")
            if isinstance(empraba_result["body"], dict)
            else None
        )

        # 2B: Full fencing protocol on valid active source 'fao'
        source = "fao"

        # Step 1: Owner Alpha claims
        payload_alpha = {
            "source_key": source,
            "owner": "owner-alpha",
            "lease_seconds": 120,
            "force": True,
            "scope": "default",
            "purpose": "collection",
        }
        r_alpha = self.post("source-schedule/claims", payload_alpha)
        alpha_status = r_alpha.status_code
        alpha_body = r_alpha.json()
        token_alpha = alpha_body.get("claim_token")
        print(f"Owner Alpha claim status: {alpha_status}, token acquired: {bool(token_alpha)}")

        # Step 2: Owner Beta attempts claim without force
        payload_beta_noforce = {
            "source_key": source,
            "owner": "owner-beta",
            "lease_seconds": 120,
            "force": False,
            "scope": "default",
            "purpose": "collection",
        }
        r_beta_noforce = self.post("source-schedule/claims", payload_beta_noforce)
        beta_noforce_status = r_beta_noforce.status_code
        beta_noforce_body = r_beta_noforce.json()
        beta_noforce_reason = beta_noforce_body.get("detail", {}).get("reason")
        print(f"Owner Beta (force=False) status: {beta_noforce_status}, reason: {beta_noforce_reason}")

        # Step 3: Owner Beta attempts claim WITH force
        payload_beta_force = {
            "source_key": source,
            "owner": "owner-beta",
            "lease_seconds": 120,
            "force": True,
            "scope": "default",
            "purpose": "collection",
        }
        r_beta_force = self.post("source-schedule/claims", payload_beta_force)
        beta_force_status = r_beta_force.status_code
        beta_force_body = r_beta_force.json()
        beta_force_reason = beta_force_body.get("detail", {}).get("reason")
        print(f"Owner Beta (force=True) status: {beta_force_status}, reason: {beta_force_reason}")

        # Step 4: Owner Beta attempts renew with mismatched/invalid token
        mismatched_token = "invalid-mismatched-fencing-token-beta-12345"
        renew_payload_invalid = {
            "source_key": source,
            "claim_token": mismatched_token,
            "lease_seconds": 120,
        }
        r_renew_invalid = self.post("source-schedule/claims/renew", renew_payload_invalid)
        renew_invalid_status = r_renew_invalid.status_code
        renew_invalid_body = r_renew_invalid.json()
        renew_invalid_reason = renew_invalid_body.get("detail", {}).get("reason")
        print(f"Owner Beta invalid renew status: {renew_invalid_status}, reason: {renew_invalid_reason}")

        # Step 5: Owner Alpha releases cleanly
        release_payload_alpha = {
            "source_key": source,
            "claim_token": token_alpha,
            "outcome": "noop",
        }
        r_release_alpha = self.post("source-schedule/claims/release", release_payload_alpha)
        release_alpha_status = r_release_alpha.status_code
        release_alpha_body = r_release_alpha.json()
        print(
            f"Owner Alpha clean release status: {release_alpha_status}, "
            f"body: {sanitize_dict(release_alpha_body)}"
        )

        gate_passed = (
            r_empraba.status_code == 404
            and empraba_detail == "Unknown source_key: empraba"
            and alpha_status == 201
            and beta_noforce_status == 409 and beta_noforce_reason == "claim_active"
            and beta_force_status == 409 and beta_force_reason == "claim_active"
            and renew_invalid_status == 409 and renew_invalid_reason == "claim_missing"
            and release_alpha_status == 200 and release_alpha_body.get("accepted") is True
        )

        return {
            "gate_passed": gate_passed,
            "empraba_check": sanitize_dict(empraba_result),
            "fencing_steps": {
                "step1_alpha_claim": {
                    "status_code": alpha_status,
                    "body": sanitize_dict(alpha_body),
                },
                "step2_beta_claim_noforce": {
                    "status_code": beta_noforce_status,
                    "body": sanitize_dict(beta_noforce_body),
                    "reason": beta_noforce_reason,
                },
                "step3_beta_claim_force": {
                    "status_code": beta_force_status,
                    "body": sanitize_dict(beta_force_body),
                    "reason": beta_force_reason,
                },
                "step4_beta_renew_invalid_token": {
                    "status_code": renew_invalid_status,
                    "body": sanitize_dict(renew_invalid_body),
                    "reason": renew_invalid_reason,
                },
                "step5_alpha_clean_release": {
                    "status_code": release_alpha_status,
                    "body": sanitize_dict(release_alpha_body),
                },
            },
        }

    def run_task_3_lease_expiry_and_renewal(self) -> Dict[str, Any]:
        """Task 3: Lease Expiry / Renewal Verification."""
        print(f"[{datetime.now(timezone.utc).isoformat()}] Task 3: Lease Expiry / Renewal Verification")
        source = "bndes"
        owner = "renewal-test-owner"

        # Step 1: Claim with short lease (30 seconds)
        claim_payload = {
            "source_key": source,
            "owner": owner,
            "lease_seconds": 30,
            "force": True,
            "scope": "default",
            "purpose": "collection",
        }
        r_claim = self.post("source-schedule/claims", claim_payload)
        claim_status = r_claim.status_code
        claim_body = r_claim.json()
        token = claim_body.get("claim_token")
        expires_at_1 = claim_body.get("expires_at")
        print(f"Step 1: Short lease claim status: {claim_status}, expires_at_1: {expires_at_1}")

        # Step 2: Renew claim to extend lease (120 seconds)
        renew_payload = {
            "source_key": source,
            "claim_token": token,
            "lease_seconds": 120,
        }
        r_renew = self.post("source-schedule/claims/renew", renew_payload)
        renew_status = r_renew.status_code
        renew_body = r_renew.json()
        expires_at_2 = renew_body.get("expires_at")
        print(f"Step 2: Renewal status: {renew_status}, expires_at_2: {expires_at_2}")

        lease_extended = False
        if expires_at_1 and expires_at_2:
            dt1 = datetime.fromisoformat(expires_at_1.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(expires_at_2.replace("Z", "+00:00"))
            lease_extended = dt2 > dt1
        print(f"Lease extended: {lease_extended}")

        # Step 3: Clean release with outcome='noop'
        release_payload = {
            "source_key": source,
            "claim_token": token,
            "outcome": "noop",
        }
        r_release = self.post("source-schedule/claims/release", release_payload)
        release_status = r_release.status_code
        release_body = r_release.json()
        print(f"Step 3: Release status: {release_status}, accepted: {release_body.get('accepted')}")

        # Step 4 (Deep verification): Test actual lease expiration and post-expiry renewal rejection
        print(f"Step 4: Testing lease expiration fencing (30s lease + 31s wait)...")
        r_claim_exp = self.post("source-schedule/claims", {
            "source_key": source,
            "owner": "expiry-fencer-alpha",
            "lease_seconds": 30,
            "force": True,
        })
        token_exp = r_claim_exp.json().get("claim_token")
        print(f"Acquired 30s claim on {source}, sleeping 31s...")
        time.sleep(31)

        # Attempt renewal on expired claim
        r_renew_expired = self.post("source-schedule/claims/renew", {
            "source_key": source,
            "claim_token": token_exp,
            "lease_seconds": 60,
        })
        renew_exp_status = r_renew_expired.status_code
        renew_exp_body = r_renew_expired.json()
        renew_exp_reason = renew_exp_body.get("detail", {}).get("reason")
        print(f"Expired renewal status: {renew_exp_status}, reason: {renew_exp_reason}")

        # Attempt reclaim by new owner after expiry
        r_reclaim = self.post("source-schedule/claims", {
            "source_key": source,
            "owner": "expiry-fencer-beta",
            "lease_seconds": 60,
            "force": True,
        })
        reclaim_status = r_reclaim.status_code
        reclaim_body = r_reclaim.json()
        reclaim_token = reclaim_body.get("claim_token")
        print(f"Post-expiry reclaim status: {reclaim_status}, new token: {bool(reclaim_token)}")

        # Release reclaimed lease cleanly and include cleanup in the verdict.
        reclaim_release_status = None
        reclaim_release_body: Any = None
        if reclaim_token:
            r_reclaim_release = self.post("source-schedule/claims/release", {
                "source_key": source,
                "claim_token": reclaim_token,
                "outcome": "noop",
            })
            reclaim_release_status = r_reclaim_release.status_code
            reclaim_release_body = r_reclaim_release.json()
        print(
            "Post-expiry reclaim release status: "
            f"{reclaim_release_status}, accepted: "
            f"{reclaim_release_body.get('accepted') if isinstance(reclaim_release_body, dict) else None}"
        )

        gate_passed = (
            claim_status == 201
            and renew_status == 200
            and lease_extended
            and release_status == 200 and release_body.get("accepted") is True
            and renew_exp_status == 409 and renew_exp_reason == "claim_expired"
            and reclaim_status == 201
            and reclaim_release_status == 200
            and isinstance(reclaim_release_body, dict)
            and reclaim_release_body.get("accepted") is True
        )

        return {
            "gate_passed": gate_passed,
            "step1_claim": {
                "status_code": claim_status,
                "expires_at": expires_at_1,
                "body": sanitize_dict(claim_body),
            },
            "step2_renew": {
                "status_code": renew_status,
                "expires_at": expires_at_2,
                "lease_extended": lease_extended,
                "body": sanitize_dict(renew_body),
            },
            "step3_release": {
                "status_code": release_status,
                "body": sanitize_dict(release_body),
            },
            "step4_expired_lease_fencing": {
                "renew_after_expiry_status": renew_exp_status,
                "renew_after_expiry_reason": renew_exp_reason,
                "renew_after_expiry_body": sanitize_dict(renew_exp_body),
                "reclaim_post_expiry_status": reclaim_status,
                "reclaim_post_expiry_body": sanitize_dict(reclaim_body),
                "reclaim_release_status": reclaim_release_status,
                "reclaim_release_body": sanitize_dict(reclaim_release_body),
            },
        }


def main() -> int:
    require_live_mutation_consent(sys.argv[1:])
    secret = get_pipeline_secret()
    runner = StagingTestRunner(secret)

    try:
        print("=== STARTING STAGING FAILURE INJECTION & FENCING TEST SUITE ===")
        t1 = runner.run_task_1_concurrency_limit()
        t2 = runner.run_task_2_stale_owner_fencing()
        t3 = runner.run_task_3_lease_expiry_and_renewal()
    finally:
        cleanup_results = runner.cleanup_active_claims()

    cleanup_succeeded = all(
        result.get("status_code") == 200 and result.get("accepted") is True
        for result in cleanup_results
    )
    probe_gates_passed = t1["gate_passed"] and t2["gate_passed"] and t3["gate_passed"]

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "target_url": BASE_URL,
        "task_1_concurrency_limit": t1,
        "task_2_stale_owner_fencing": t2,
        "task_3_lease_expiry_and_renewal": t3,
        "all_probe_gates_passed": probe_gates_passed,
        "all_gates_passed": probe_gates_passed and cleanup_succeeded,
        "exception_cleanup": cleanup_results,
        "cleanup_succeeded": cleanup_succeeded,
    }

    print("\n=== SUMMARY OF TEST RESULTS ===")
    print(f"Task 1 Concurrency Limit Gate Passed: {t1['gate_passed']}")
    print(f"Task 2 Stale-Owner Fencing Gate Passed: {t2['gate_passed']}")
    print(f"Task 3 Lease Expiry / Renewal Gate Passed: {t3['gate_passed']}")
    print(f"All Probe Gates Passed: {summary['all_probe_gates_passed']}")
    print(f"Overall Gates Passed: {summary['all_gates_passed']}")
    print(f"Exception Cleanup Succeeded: {cleanup_succeeded}")

    # Save sanitized summary to a local json for easy report generation
    out_file = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "failure_injection_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Sanitized test evidence saved to {out_file}")
    return 0 if summary["all_gates_passed"] and cleanup_succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
