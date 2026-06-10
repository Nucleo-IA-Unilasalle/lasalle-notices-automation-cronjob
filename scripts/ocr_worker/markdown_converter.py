"""Convert PDF documents into Markdown format for AI consumption."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pdfminer.high_level import extract_text

from ocr_extraction_config import OCRExtractionConfig

logger = logging.getLogger(__name__)

_KREUZBERG_PAGE_PATTERN = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")


class MarkdownConversionError(RuntimeError):
    """Raised when a document fails to convert to Markdown."""


@dataclass
class MarkdownConverterConfig:
    """Configuration for the Markdown conversion pipeline."""

    pdfminer_codec: str = "utf-8"
    pdfminer_fallback_encodings: tuple[str, ...] = ("windows-1252", "iso-8859-1")


class MarkdownConverter:
    """Convert PDF byte streams into Markdown using Kreuzberg as primary extractor."""

    def __init__(
        self,
        config: Optional[MarkdownConverterConfig] = None,
        ocr_config: Optional[OCRExtractionConfig] = None,
        ocr_extractor: Optional[Callable[..., str]] = None,
    ) -> None:
        self.config = config or MarkdownConverterConfig()
        self._markdown_document: Optional[str] = None
        self.ocr_config = ocr_config or OCRExtractionConfig()

        if ocr_extractor is not None:
            self._ocr_extractor = ocr_extractor
        else:
            from kreuzberg_extractor import extract_file_sync

            self._ocr_extractor = lambda path, **kw: extract_file_sync(path, **kw)

    def convert_document(self, file_path: str) -> None:
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)

        if self._ocr_extractor is not None:
            try:
                self._markdown_document = self._ocr_extractor(
                    file_path,
                    force_ocr=self.ocr_config.force_ocr,
                    language=self.ocr_config.language,
                    model_tier=self.ocr_config.model_tier,
                    use_gpu=self.ocr_config.use_gpu,
                )
                return
            except Exception as exc:
                logger.warning("Kreuzberg extraction failed: %s", exc)

        try:
            self._markdown_document = self._convert_with_pdfminer(file_path)
        except Exception as exc:
            raise MarkdownConversionError("Both Kreuzberg and pdfminer failed") from exc

    def _convert_with_pdfminer(self, file_path: str) -> str:
        primary_codec = self.config.pdfminer_codec
        fallback_codecs = list(self.config.pdfminer_fallback_encodings or ())
        encodings_to_try = [primary_codec] + [c for c in fallback_codecs if c != primary_codec]

        last_error: Optional[Exception] = None
        last_text: Optional[str] = None

        for codec in encodings_to_try:
            try:
                text = extract_text(file_path, codec=codec)
            except Exception as exc:
                logger.warning("pdfminer extraction with codec '%s' failed: %s", codec, exc)
                last_error = exc
                last_text = None
                continue

            if not text:
                logger.warning("pdfminer extraction with codec '%s' returned empty text", codec)
                continue

            replacement_count = text.count('\ufffd')
            if replacement_count <= 5:
                logger.info("Successfully extracted text with codec '%s'", codec)
                return text

            logger.info(
                "Codec '%s' produced %d replacement chars; trying next encoding",
                codec, replacement_count
            )
            last_text = text

        if last_text:
            logger.warning("All encodings produced replacement chars; returning best effort result")
            return last_text

        if last_error:
            raise MarkdownConversionError(
                f"Failed to extract text from PDF with encodings {encodings_to_try}"
            ) from last_error

        raise MarkdownConversionError("PDF text extraction returned empty content")

    def add_page_counters(self) -> None:
        """Annotate the markdown with page markers compatible with the extraction prompt."""

        if not self._markdown_document:
            return

        if _KREUZBERG_PAGE_PATTERN.search(self._markdown_document):
            pages = _KREUZBERG_PAGE_PATTERN.split(self._markdown_document)
            assembled: list[str] = []
            last_emitted_page: Optional[int] = None
            if pages[0].strip():
                assembled.append(pages[0].strip())
            for i in range(1, len(pages), 2):
                page_num = int(pages[i])
                content = pages[i + 1].strip() if i + 1 < len(pages) else ""
                if page_num == 1:
                    if content:
                        assembled.append(content)
                        last_emitted_page = 1
                else:
                    if content:
                        if page_num != last_emitted_page:
                            assembled.append(f"<!-- Página {page_num} -->\n\n{content}")
                            last_emitted_page = page_num
                        else:
                            assembled.append(content)
            self._markdown_document = "\n\n".join(assembled)
            return

        pages = [segment.strip() for segment in self._markdown_document.split("\f")]
        pages = [segment for segment in pages if segment]

        if not pages:
            pages = [self._markdown_document.strip()]

        assembled: list[str] = []
        for index, section in enumerate(pages, start=1):
            if index == 1:
                assembled.append(section)
            else:
                assembled.append(f"<!-- Página {index} -->\n\n{section}")

        self._markdown_document = "\n\n".join(assembled)

    def get_markdown_document(self) -> str:
        if not self._markdown_document:
            raise MarkdownConversionError("Document has not been converted yet")
        return self._markdown_document

    def clear(self) -> None:
        self._markdown_document = None
