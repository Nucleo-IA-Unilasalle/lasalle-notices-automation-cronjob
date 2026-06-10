"""Lightweight PDF optimization helpers used prior to OCR extraction."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf._page import PageObject

logger = logging.getLogger(__name__)


class PDFCompressionError(RuntimeError):
    """Raised when a PDF cannot be optimized safely."""


@dataclass
class PDFOptimizerConfig:
    """Configuration flags for the PDF optimizer."""

    max_pages: Optional[int] = None
    drop_blank_pages: bool = True
    compress_streams: bool = True
    min_text_length: int = 0


class PDFOptimizer:
    """Best-effort optimizer that trims obvious waste before OCR."""

    def __init__(self, config: Optional[PDFOptimizerConfig] = None) -> None:
        self.config = config or PDFOptimizerConfig()

    def optimize(self, pdf_bytes: bytes) -> bytes:
        if not pdf_bytes:
            raise PDFCompressionError("PDF payload is empty")

        try:
            reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        except PdfReadError as exc:
            raise PDFCompressionError("PDF payload is invalid") from exc

        total_pages = len(reader.pages)
        if total_pages == 0:
            raise PDFCompressionError("PDF does not contain any pages")

        writer = PdfWriter()
        pages_added = 0
        blank_pages_skipped = 0

        for index, page in enumerate(reader.pages):
            if self.config.max_pages and self.config.max_pages > 0 and pages_added >= self.config.max_pages:
                logger.info(
                    "Truncated PDF from %s to %s pages to limit OCR workload",
                    total_pages,
                    self.config.max_pages,
                )
                break

            if self.config.drop_blank_pages and self._is_blank_page(page):
                blank_pages_skipped += 1
                continue

            if self.config.compress_streams:
                try:
                    page.compress_content_streams()
                except Exception as exc:
                    logger.debug("Failed to compress page %s: %s", index, exc)

            writer.add_page(page)
            pages_added += 1

        if pages_added == 0:
            if blank_pages_skipped:
                raise PDFCompressionError("All PDF pages appeared blank after optimization")
            raise PDFCompressionError("Unable to retain any pages during optimization")

        buffer = io.BytesIO()

        try:
            writer.write(buffer)
        except Exception as exc:
            raise PDFCompressionError("Failed to serialize optimized PDF") from exc

        return buffer.getvalue()

    def _is_blank_page(self, page: PageObject) -> bool:
        try:
            contents = page.get_contents()
        except Exception:
            contents = True

        if contents is None:
            return True

        if not self.config.min_text_length or self.config.min_text_length <= 0:
            return False

        try:
            extracted = page.extract_text() or ""
        except Exception:
            return False
        return len(extracted.strip()) < self.config.min_text_length
