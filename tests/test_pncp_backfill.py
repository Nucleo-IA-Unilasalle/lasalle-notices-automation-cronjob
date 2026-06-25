from __future__ import annotations

import pytest


def test_fetch_claimed_candidates_calls_render(monkeypatch):
    import scripts.backfill_pncp_pending_candidates as backfill

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "source": "pncp",
                "limit": 2,
                "active_only": True,
                "candidates": [
                    {
                        "id": 1,
                        "url": "https://pncp.gov.br/doc.pdf",
                        "kind": "pdf",
                        "metadata": {"numeroControlePNCP": "control", "sequencialDocumento": 1},
                    }
                ],
            }

    def fake_post(url, headers, params, timeout):
        captured.update({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr(backfill.requests, "post", fake_post)

    candidates = backfill.fetch_claimed_candidates(
        render_url="https://render.example",
        token="secret",
        limit=2,
    )

    assert captured["url"] == "https://render.example/api/pipeline/candidates/backfill/claim"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["params"] == {"source": "pncp", "limit": 2, "active_only": "true"}
    assert candidates == [
        {
            "url": "https://pncp.gov.br/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "control", "sequencialDocumento": 1},
        }
    ]


def test_run_backfill_processes_and_submits_successes(monkeypatch):
    import scripts.backfill_pncp_pending_candidates as backfill

    monkeypatch.setattr(
        backfill,
        "fetch_claimed_candidates",
        lambda **_kwargs: [{"url": "https://pncp.gov.br/doc.pdf", "kind": "pdf", "metadata": {}}],
    )
    monkeypatch.setattr(backfill.pipeline_core, "SCRAPE_MAX_PDF_BYTES", 123)
    monkeypatch.setattr(backfill.pipeline_core, "pdf_download_limit_reached", lambda stats: False)
    monkeypatch.setattr(backfill.pipeline_core, "record_pdf_download", lambda stats: stats.__setitem__("pdfs_downloaded", 1))
    monkeypatch.setattr(
        backfill.pipeline_core,
        "process_candidate",
        lambda candidate, extractor, max_bytes: {**candidate, "worker_result": {"ocr_markdown": "# ok"}},
    )
    monkeypatch.setattr(backfill.pipeline_core, "make_default_ocr_extractor", lambda: (object(), object()))
    monkeypatch.setattr(
        backfill.pipeline_core,
        "submit_candidates",
        lambda processed, source: {"submitted": len(processed), "failed_batches": 0},
    )

    exit_code = backfill.run_backfill(
        render_url="https://render.example",
        token="secret",
        claim_limit=1,
        process_limit=1,
    )

    assert exit_code == 0


def test_run_backfill_fails_when_claimed_but_submitted_none(monkeypatch):
    import scripts.backfill_pncp_pending_candidates as backfill

    monkeypatch.setattr(
        backfill,
        "fetch_claimed_candidates",
        lambda **_kwargs: [{"url": "https://pncp.gov.br/doc.pdf", "kind": "pdf", "metadata": {}}],
    )
    monkeypatch.setattr(backfill.pipeline_core, "SCRAPE_MAX_PDF_BYTES", 123)
    monkeypatch.setattr(backfill.pipeline_core, "pdf_download_limit_reached", lambda stats: False)
    monkeypatch.setattr(
        backfill.pipeline_core,
        "process_candidate",
        lambda candidate, extractor, max_bytes: {**candidate, "error": "ocr: boom"},
    )
    monkeypatch.setattr(backfill.pipeline_core, "make_default_ocr_extractor", lambda: (object(), object()))
    monkeypatch.setattr(
        backfill.pipeline_core,
        "submit_candidates",
        lambda processed, source: {"submitted": 0, "failed_batches": 0},
    )

    assert backfill.run_backfill(
        render_url="https://render.example",
        token="secret",
        claim_limit=1,
        process_limit=1,
    ) == 1
