"""Bounded trusted-worker client. Never print tokens or arbitrary API bodies."""
import os

import requests


# Adapter collection scopes (must match each discoverer's checkpoint scope
# exactly: the server pins claim_scope at claim time and rejects register/
# checkpoint writes whose scope differs). Central mapping so the supervisor
# and every drain/collection call site share one truth.
SOURCE_SCOPES = {
    "pncp": "pncp-updates-v1",
    "finep": "finep-pages-v1",
}
DEFAULT_SCOPE = "default"


def scope_for(source):
    return SOURCE_SCOPES.get(source, DEFAULT_SCOPE)


class AdmissionConflict(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# 409 reasons that mean the source lease no longer fences this worker: the
# schedule claim expired/was lost (claim_expired/claim_missing on the spool
# take/finish calls) or the X-Source-Claim submission header was rejected
# (claim_invalid). Every other conflict reason (not_due, claim_active,
# capacity_full, work_conflict, queue_full, cursor_*, ...) is admission or
# state policy and must keep its existing propagation behavior.
LEASE_EXPIRED_REASONS = frozenset({"claim_expired", "claim_missing", "claim_invalid"})


def lease_expired(exc):
    """True when an AdmissionConflict means the source lease is gone."""
    return isinstance(exc, AdmissionConflict) and exc.reason in LEASE_EXPIRED_REASONS


class SourceControl:
    def __init__(self, source, token=None):
        self.source = source
        self.token = token or os.environ.get("SOURCE_CLAIM_TOKEN")
        self.url = os.environ["RENDER_APP_URL"].rstrip("/")
        self.headers = {"Authorization": "Bearer " + os.environ["PIPELINE_SECRET"]}

    def post(self, path, payload):
        response = requests.post(self.url + "/api/pipeline/" + path, json=payload,
                                 headers=self.headers, timeout=(5, 15), allow_redirects=False)
        if response.status_code == 409:
            detail = response.json().get("detail", {})
            reason = detail.get("reason", "conflict") if isinstance(detail, dict) else "conflict"
            raise AdmissionConflict(reason)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Source control failed: HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Source control returned an invalid object")
        return body

    def claim(self, force=False, purpose="collection"):
        # Claim with the adapter's checkpoint scope so the server pins
        # claim_scope to the scope register/checkpoint calls will actually
        # use (a "default"-scoped claim cannot advance "pncp-updates-v1").
        result = self.post("source-schedule/claims", {
            "source_key": self.source, "owner": os.environ.get("GITHUB_RUN_ID", "local"),
            "lease_seconds": 300, "force": force,
            "scope": scope_for(self.source), "purpose": purpose,
        })
        self.token = result["claim_token"]
        if not isinstance(self.token, str) or len(self.token) < 16:
            raise RuntimeError("Invalid source claim response")
        return result

    def renew(self):
        return self.post("source-schedule/claims/renew", {
            "source_key": self.source, "claim_token": self.token, "lease_seconds": 300,
        })

    def release(self, outcome):
        return self.post("source-schedule/claims/release", {
            "source_key": self.source, "claim_token": self.token, "outcome": outcome,
        })

    def work(self, action, **kwargs):
        return self.post("source-work", {
            "source_key": self.source, "claim_token": self.token, "action": action, **kwargs,
        })
