"""Utilities for validating downloaded PDF files."""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_ENABLE_PYTHON_MAGIC = (
    os.getenv("ENABLE_PYTHON_MAGIC", "1") == "1"
    and not sys.platform.startswith("win")
)

if _ENABLE_PYTHON_MAGIC:
    try:
        import magic  # type: ignore
    except ImportError:
        magic = None  # type: ignore
else:
    magic = None  # type: ignore

logger = logging.getLogger(__name__)


class FileValidationError(ValueError):
    """Raised when a file fails validation checks."""


def _detect_mime_type(content: bytes) -> Optional[str]:
    if magic is None:
        if content.startswith(b"%PDF"):
            return "application/pdf"
        return None

    try:
        return magic.from_buffer(content, mime=True)
    except Exception as exc:
        logger.warning("Failed to detect mime type via python-magic: %s", exc)
        return None


def validate_pdf(content: bytes, *, max_size: Optional[int] = None) -> None:
    """Ensure the provided bytes represent a valid PDF within size limits."""

    if not content:
        raise FileValidationError("File is empty")

    if max_size is None:
        raise FileValidationError("max_size is required in the cronjob worker context")
    if len(content) > max_size:
        raise FileValidationError("File exceeds maximum allowed size")

    mime_type = _detect_mime_type(content)
    if mime_type != "application/pdf":
        raise FileValidationError("File is not a valid PDF document")

    if not content.startswith(b"%PDF"):
        raise FileValidationError("PDF header missing or corrupted")
