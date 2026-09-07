from __future__ import annotations

import hashlib
from typing import Any

import pipeline_core
from unittest.mock import MagicMock, patch


def test_process_opportunity_normalizes_markdown_before_hashing() -> None:
    opportunity = {
        "source_key": "finep",
        "source_record_id": "42",
        "source_markdown": " \r# Official call\r\n\r\nFunding opportunity\r\n ",
        "documents": [],
    }

    processed = pipeline_core.process_opportunity(
        opportunity,
        extractor=object(),
        stats={},
    )

    normalized = "# Official call\n\nFunding opportunity"
    assert processed["source_markdown"] == normalized
    assert processed["source_content_hash"] == hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
    assert processed["documents"] == []


def test_submit_opportunities_aggregates_outcomes_and_no_reactivation(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_APP_URL", "https://r.example.com"); monkeypatch.setenv("PIPELINE_SECRET", "tok")
    responses = []
    for outcome in ("inserted", "duplicate"):
        r = MagicMock(status_code=200); r.json.return_value = {"outcome": outcome}; responses.append(r)
    opportunities = [{"documents": [{"document_kind": "pdf", "is_renderable": True}]} for _ in responses]
    with patch("pipeline_core.requests.post", side_effect=responses):
        result = pipeline_core.submit_opportunities(opportunities)
    assert result["outcome_counts"] == {"inserted": 1, "updated": 0, "reactivated": 0, "duplicates": 1, "invalid": 0}


def _zip_inspection(*filenames):
    from archive_validation import ArchiveInspection, ExtractedPdf

    return ArchiveInspection(
        outcome="accepted",
        rejection_reason=None,
        members=(),
        pdf_members=tuple(
            ExtractedPdf(name, b"%PDF-1.4 " + name.encode(), f"hash-{name}")
            for name in filenames
        ),
    )


def test_zip_pdf_members_consume_the_shared_pdf_cap(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_core, "SCRAPE_MAX_PDFS_PER_RUN", 10)
    monkeypatch.setattr(pipeline_core, "_download_attachment", lambda url, **kwargs: b"zip-bytes")

    async def _extract(content):
        return "# extracted"

    extractor = MagicMock()
    extractor.extract = _extract
    monkeypatch.setattr(pipeline_core, "inspect_zip_archive",
                        lambda data, **kwargs: _zip_inspection("a.pdf", "b.pdf"))
    stats: dict[str, int] = {}
    processed = pipeline_core.process_opportunity(
        {
            "source_key": "demo",
            "source_record_id": "zip-1",
            "source_markdown": "# Call",
            "documents": [{"document_kind": "zip", "url": "https://example.com/a.zip"}],
        },
        extractor=extractor,
        stats=stats,
    )
    assert stats["pdfs_downloaded"] == 2, "every ZIP member OCR must consume the PDF cap"
    markdown = processed["documents"][0]["extracted_markdown"]
    assert "## Arquivo: a.pdf" in markdown
    assert "## Arquivo: b.pdf" in markdown
    assert processed["documents"][0]["validation_outcome"] == "accepted"


def test_zip_members_are_skipped_once_the_pdf_cap_is_reached(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_core, "SCRAPE_MAX_PDFS_PER_RUN", 1)
    monkeypatch.setattr(pipeline_core, "_download_attachment", lambda url, **kwargs: b"zip-bytes")
    extractor = MagicMock()
    monkeypatch.setattr(pipeline_core, "inspect_zip_archive",
                        lambda data, **kwargs: _zip_inspection("a.pdf"))
    stats: dict[str, int] = {"pdfs_downloaded": 1}
    processed = pipeline_core.process_opportunity(
        {
            "source_key": "demo",
            "source_record_id": "zip-capped",
            "source_markdown": "# Call",
            "documents": [{"document_kind": "zip", "url": "https://example.com/a.zip"}],
        },
        extractor=extractor,
        stats=stats,
    )
    document = processed["documents"][0]
    assert document["validation_outcome"] == "zip_validation_failed"
    assert document["is_renderable"] is False
    assert stats["pdf_download_cap_reached"] == 1
    extractor.extract.assert_not_called()


def test_process_opportunity_promotes_first_validated_pdf_to_principal(
    monkeypatch,
) -> None:
    worker_result: dict[str, Any] = {
        "content_hash": "a" * 64,
        "content_length": 1_024,
        "validated_at": "2026-07-23T12:00:00+00:00",
        "ocr_markdown": "# Extracted PDF",
    }
    monkeypatch.setattr(
        pipeline_core,
        "process_candidate",
        lambda *_args, **_kwargs: {"worker_result": worker_result},
    )
    stats: dict[str, int] = {}

    processed = pipeline_core.process_opportunity(
        {
            "source_key": "finep",
            "source_record_id": "42",
            "source_markdown": "# Official call",
            "documents": [
                {
                    "source_document_id": "notice",
                    "document_kind": "pdf",
                    "url": "https://example.org/notice.pdf",
                    "is_principal": False,
                    "is_renderable": False,
                }
            ],
        },
        extractor=object(),
        stats=stats,
    )

    assert stats["pdfs_downloaded"] == 1
    assert processed["documents"] == [
        {
            "source_document_id": "notice",
            "document_kind": "pdf",
            "url": "https://example.org/notice.pdf",
            "is_principal": True,
            "is_renderable": True,
            "content_hash": "a" * 64,
            "content_length": 1_024,
            "validation_outcome": "valid_pdf",
            "validated_at": "2026-07-23T12:00:00+00:00",
            "extracted_markdown": "# Extracted PDF",
        }
    ]
