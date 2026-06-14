"""Direct PaddleOCR extraction wrapper using configurable PP-OCRv6 tiers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_TIERS = {"tiny", "small", "medium"}
_paddleocr_instances: dict[tuple[str, bool], Any] = {}


def _get_ocr_instance(model_tier: str = "tiny", use_gpu: bool = False) -> Any:
    if model_tier not in _MODEL_TIERS:
        raise ValueError(f"Unsupported PP-OCRv6 model tier: {model_tier}")

    cache_key = (model_tier, use_gpu)
    if cache_key in _paddleocr_instances:
        return _paddleocr_instances[cache_key]

    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError("paddleocr is not installed") from exc

    device = "gpu" if use_gpu else "cpu"
    instance = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_detection_model_name=f"PP-OCRv6_{model_tier}_det",
        text_recognition_model_name=f"PP-OCRv6_{model_tier}_rec",
        device=device,
    )
    _paddleocr_instances[cache_key] = instance
    logger.info("PaddleOCR initialized with PP-OCRv6_%s on %s", model_tier, device)
    return instance


def extract_file_sync(
    file_path: str,
    *,
    force_ocr: bool = False,
    language: str = "latin",
    model_tier: str = "tiny",
    use_gpu: bool = False,
) -> str:
    """Extract text from a file using PaddleOCR directly with PP-OCRv6."""
    ocr = _get_ocr_instance(model_tier=model_tier, use_gpu=use_gpu)

    logger.debug(
        "Extracting with paddleocr: force_ocr=%s, language=%s, file=%s",
        force_ocr, language, file_path,
    )

    result = ocr.predict(file_path)

    pages: list[str] = []
    for page_result in result:
        rec_texts = page_result.get("rec_texts", [])
        page_text = "\n".join(rec_texts)
        page_index = page_result.get("page_index")
        if page_index is not None:
            pages.append(f"<!-- PAGE {page_index + 1} -->\n{page_text}")
        elif page_text:
            pages.append(page_text)

    text = "\n\n".join(pages)

    logger.info(
        "PaddleOCR extraction complete: %d chars, %d words",
        len(text), len(text.split()),
    )

    return text
