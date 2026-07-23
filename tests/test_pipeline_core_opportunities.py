from __future__ import annotations

import hashlib
from typing import Any

import pipeline_core


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
