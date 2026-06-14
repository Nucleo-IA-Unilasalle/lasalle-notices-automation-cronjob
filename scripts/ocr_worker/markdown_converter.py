"""Convert PDF documents into Markdown format for AI consumption."""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Optional

from ocr_extraction_config import OCRExtractionConfig

logger = logging.getLogger(__name__)

_PAGE_PATTERN = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")


class MarkdownConversionError(RuntimeError):
    """Raised when a document fails to convert to Markdown."""


class MarkdownConverter:
    """Convert PDF byte streams into Markdown using PaddleOCR."""

    def __init__(
        self,
        ocr_config: Optional[OCRExtractionConfig] = None,
        ocr_extractor: Optional[Callable[..., str]] = None,
    ) -> None:
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

        self._markdown_document = self._ocr_extractor(
            file_path,
            force_ocr=self.ocr_config.force_ocr,
            language=self.ocr_config.language,
            model_tier=self.ocr_config.model_tier,
            use_gpu=self.ocr_config.use_gpu,
        )

    def add_page_counters(self) -> None:
        """Annotate the markdown with page markers compatible with the extraction prompt."""

        if not self._markdown_document:
            return

        if _PAGE_PATTERN.search(self._markdown_document):
            pages = _PAGE_PATTERN.split(self._markdown_document)
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
