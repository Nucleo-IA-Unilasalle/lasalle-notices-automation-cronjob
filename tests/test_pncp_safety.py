from __future__ import annotations

import importlib


def test_invalid_pncp_safety_env_values_fall_back_to_safe_defaults(monkeypatch) -> None:
    import discover_pncp_candidates as dpc

    monkeypatch.setenv("PNCP_UPDATE_CHECKPOINT_PATH", "   ")
    monkeypatch.setenv("PNCP_MAX_PAGES_PER_QUERY", "0")
    monkeypatch.setenv("PNCP_PAGE_SIZE", "invalid")
    monkeypatch.setenv("PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN", "-1")
    monkeypatch.setenv("PNCP_FETCH_MAX_ATTEMPTS", "0")
    monkeypatch.setenv("PNCP_FETCH_TIMEOUT_SECONDS", "bad")
    monkeypatch.setenv("PNCP_FETCH_BACKOFF_SECONDS", "-1")

    module = importlib.reload(dpc)

    assert module.PNCP_UPDATE_CHECKPOINT_PATH == ".cache/pncp_update_checkpoint.json"
    assert module.PNCP_MAX_PAGES_PER_QUERY == 20
    assert module.PNCP_PAGE_SIZE == 50
    assert module.PNCP_MAX_SUBMITTABLE_CANDIDATES_PER_RUN == 5
    assert module.PNCP_FETCH_MAX_ATTEMPTS == 3
    assert module.PNCP_FETCH_TIMEOUT_SECONDS == 8
    assert module.PNCP_FETCH_BACKOFF_SECONDS == 0.0

