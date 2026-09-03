"""Lightweight OCR extraction configuration for worker context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DEFAULT_OCR_EXTRACTION_TIMEOUT_SECONDS = 300


def parse_ocr_timeout(value: object) -> int:
    """Return a positive OCR timeout, falling back to the shared default."""
    try:
        timeout = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_OCR_EXTRACTION_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_OCR_EXTRACTION_TIMEOUT_SECONDS


@dataclass(frozen=True)
class OCRExtractionConfig:
    """Configuration required by OCR extraction without loading full app state."""

    language: Literal["latin", "en", "es", "fr", "pt", "de", "it"] = "latin"
    model_tier: Literal["tiny", "small", "medium"] = "tiny"
    use_gpu: bool = False
    force_ocr: bool = False
    extraction_timeout_seconds: int = DEFAULT_OCR_EXTRACTION_TIMEOUT_SECONDS
    max_pages: int = 50
