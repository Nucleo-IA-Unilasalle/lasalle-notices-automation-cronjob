"""Lightweight OCR extraction configuration for worker context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OCRExtractionConfig:
    """Configuration required by OCR extraction without loading full app state."""

    language: Literal["latin", "en", "es", "fr", "pt", "de", "it"] = "latin"
    model_tier: Literal["mobile", "server"] = "mobile"
    use_gpu: bool = False
    force_ocr: bool = False
    extraction_timeout_seconds: int = 300
