"""Kreuzberg + PaddleOCR extraction wrapper."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kreuzberg import ExtractionConfig, ExtractionResult, OcrConfig, PageConfig

_kreuzberg_modules: Optional[dict[str, Any]] = None


def _import_kreuzberg() -> dict[str, Any]:
    global _kreuzberg_modules
    if _kreuzberg_modules is not None:
        if _kreuzberg_modules.get("available"):
            return _kreuzberg_modules
        return {}

    try:
        from kreuzberg import (
            ExtractionConfig,
            ExtractionResult,
            OcrConfig,
            extract_file_sync,
        )
        try:
            from kreuzberg import PageConfig
        except ImportError:
            PageConfig = None

        _kreuzberg_modules = {
            "available": True,
            "ExtractionConfig": ExtractionConfig,
            "ExtractionResult": ExtractionResult,
            "OcrConfig": OcrConfig,
            "PageConfig": PageConfig,
            "extract_file_sync": extract_file_sync,
        }
        logger.info("Kreuzberg modules loaded successfully")
        return _kreuzberg_modules
    except Exception as exc:
        logger.warning("Failed to load kreuzberg: %s", exc)
        _kreuzberg_modules = {"available": False}
        return {}


def _is_available(modules) -> bool:
    if hasattr(modules, "get"):
        return modules.get("available", False)
    if hasattr(modules, "available"):
        return modules.available
    return True


def _get_module(modules, name: str):
    if hasattr(modules, "get"):
        return modules.get(name)
    return getattr(modules, name, None)


def extract_file_sync(
    file_path: str,
    *,
    force_ocr: bool = False,
    language: str = "latin",
    model_tier: str = "mobile",
    use_gpu: bool = False,
) -> str:
    """Extract text from a file using Kreuzberg with PaddleOCR backend."""
    modules = _import_kreuzberg()
    if not _is_available(modules):
        raise RuntimeError("Kreuzberg is not available")

    ExtractionConfig = _get_module(modules, "ExtractionConfig")
    OcrConfig = _get_module(modules, "OcrConfig")
    PageConfig = _get_module(modules, "PageConfig")
    extract_file_sync_func = _get_module(modules, "extract_file_sync")

    config = ExtractionConfig(
        force_ocr=force_ocr,
        ocr=OcrConfig(
            backend="paddle-ocr",
            language=language,
        ),
        pages=PageConfig(insert_page_markers=True) if PageConfig else None,
    )

    logger.debug(
        "Extracting with kreuzberg: force_ocr=%s, language=%s",
        force_ocr, language,
    )

    result = extract_file_sync_func(file_path, config=config)

    ExtractionResult = _get_module(modules, "ExtractionResult")
    if ExtractionResult and not isinstance(result, ExtractionResult):
        raise RuntimeError(f"Unexpected result type: {type(result)}")

    content = result.content
    logger.info(
        "Kreuzberg extraction complete: %d chars, %d words",
        len(content or ""), len((content or "").split())
    )

    return content or ""
