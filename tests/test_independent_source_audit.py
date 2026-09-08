"""Offline tests for the diagnostic source comparison helper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

import discover_brde_candidates
import run_independent_source_audit as diagnostic


def _record(
    source: str = "brde", *, suffix: str = "notice", status: str | None = "open"
) -> dict[str, object]:
    url = f"https://official.example/{source}/{suffix}.pdf"
    return {
        "source_key": source,
        "source_record_id": url,
        "canonical_url": url,
        "title": "Official notice",
        "status": status,
        "published_at": None,
        "deadline": None,
        "document_urls": [url],
        "document_hashes": [],
    }


def test_blocker_free_diagnostic_never_returns_release_acceptance(tmp_path, monkeypatch):
    record = _record()
    monkeypatch.setattr(
        diagnostic,
        "capture_brde_ground_truth",
        lambda: ([record], {"evidence_classification": "diagnostic_only"}),
    )
    monkeypatch.setattr(diagnostic, "run_pipeline_discovery", lambda _source: [record])

    out_dir = tmp_path / "comparison"
    code = diagnostic.main(
        ["--source", "brde", "--slot", "1", "--out-dir", str(out_dir)]
    )

    assert code == 2
    summary = json.loads((out_dir / "fidelity" / "summary.json").read_text(encoding="utf-8"))
    assert summary["pass"] is True
    assert summary["evidence_classification"] == "diagnostic_only"
    assert summary["rr05_accepted"] is False
    assert summary["selected_scope_complete"] is True
    assert summary["diagnostic_pass"] is True
    report = (out_dir / "fidelity" / "report.md").read_text(encoding="utf-8")
    assert "does not satisfy RR-05" in report
    metadata = json.loads((out_dir / "capture_metadata.json").read_text(encoding="utf-8"))
    assert metadata["evidence_classification"] == "diagnostic_only"


def test_missing_unknown_status_selected_record_blocks_diagnostic(tmp_path, monkeypatch):
    matched = _record(status=None)
    missing = _record(suffix="selected-but-missing", status=None)
    monkeypatch.setattr(
        diagnostic,
        "capture_brde_ground_truth",
        lambda: ([matched, missing], {"evidence_classification": "diagnostic_only"}),
    )
    monkeypatch.setattr(diagnostic, "run_pipeline_discovery", lambda _source: [matched])

    out_dir = tmp_path / "incomplete-comparison"
    code = diagnostic.main(
        ["--source", "brde", "--slot", "1", "--out-dir", str(out_dir)]
    )

    assert code == 1
    summary = json.loads((out_dir / "fidelity" / "summary.json").read_text(encoding="utf-8"))
    # Status remains unknown, so this verifies the diagnostic's separate
    # selected-scope check rather than changing source-fidelity semantics.
    assert summary["pass"] is True
    assert summary["selected_scope_records"] == 2
    assert summary["selected_scope_matched_records"] == 1
    assert summary["selected_scope_missing_records"] == 1
    assert summary["selected_scope_complete"] is False
    assert summary["diagnostic_pass"] is False


def test_relative_document_anchor_is_resolved_to_page_url():
    assert diagnostic._canonical_document_url(
        "https://www.brde.com.br/palacete/editais/",
        "/wp-content/uploads/2026/edital.pdf#download",
    ) == "https://www.brde.com.br/wp-content/uploads/2026/edital.pdf"


def test_brde_capture_resolves_relative_selected_pdf_anchor(monkeypatch):
    class Response:
        def __init__(self, status_code, content, url):
            self.status_code = status_code
            self.content = content
            self.url = url

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}")

    class Session:
        headers = {}

        def get(self, url, timeout):
            if url == "https://www.brde.com.br/editais/":
                return Response(404, b"not found", url)
            if url == "https://www.brde.com.br/fsa/chamadas-de-investimento/":
                return Response(200, b"<html></html>", url)
            if url == "https://www.brde.com.br/palacete/editais/":
                return Response(
                    200,
                    (
                        b'<a href="/wp-content/uploads/2026/Patrocinio-2026.pdf#download">'
                        b"Selected notice</a>"
                    ),
                    url,
                )
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(diagnostic.requests, "Session", Session)

    records, _metadata = diagnostic.capture_brde_ground_truth()

    assert records[0]["source_record_id"] == (
        "https://www.brde.com.br/wp-content/uploads/2026/Patrocinio-2026.pdf"
    )
    assert records[0]["document_urls"] == [records[0]["source_record_id"]]


def test_existing_output_directory_is_rejected_before_capture(tmp_path, monkeypatch):
    out_dir = tmp_path / "existing"
    out_dir.mkdir()
    capture = MagicMock(side_effect=AssertionError("capture must not run"))
    monkeypatch.setattr(diagnostic, "capture_brde_ground_truth", capture)

    code = diagnostic.main(
        ["--source", "brde", "--slot", "1", "--out-dir", str(out_dir)]
    )

    assert code == 2
    capture.assert_not_called()


def test_required_official_page_http_error_fails_closed():
    response = MagicMock(spec=requests.Response)
    response.status_code = 503
    response.raise_for_status.side_effect = requests.HTTPError("HTTP 503")

    with pytest.raises(RuntimeError, match="request failed"):
        diagnostic._require_response(response, "https://official.example/notices")


def test_expected_status_mismatch_fails_closed():
    response = MagicMock(spec=requests.Response)
    response.status_code = 200

    with pytest.raises(RuntimeError, match=r"expected \[404\]"):
        diagnostic._require_response(
            response,
            "https://official.example/not-found-check",
            expected={404},
        )


@pytest.mark.parametrize(
    ("stats", "candidates", "message"),
    [
        ({"errors": 1, "candidate_cap_reached": 0, "candidates": 0}, [], "reported 1 error"),
        ({"errors": 0, "candidate_cap_reached": 1, "candidates": 1}, [_record()], "candidate cap"),
        ({"errors": 0, "candidate_cap_reached": 0, "candidates": 2}, [_record()], "mismatch"),
        ({"errors": 0, "candidate_cap_reached": 0, "candidates": 0}, [], "no candidates"),
    ],
)
def test_discovery_rejects_partial_or_inconsistent_results(
    monkeypatch,
    stats,
    candidates,
    message,
):
    monkeypatch.setattr(
        discover_brde_candidates,
        "discover_candidates",
        lambda: (stats, candidates),
    )

    with pytest.raises(RuntimeError, match=message):
        diagnostic.run_pipeline_discovery("brde")
