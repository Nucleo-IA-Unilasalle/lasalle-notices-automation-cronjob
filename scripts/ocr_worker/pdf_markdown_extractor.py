"""Worker-friendly PDF to markdown extraction boundary."""

from __future__ import annotations

import asyncio
import os
import tempfile

from ocr_extraction_config import OCRExtractionConfig
from markdown_converter import MarkdownConversionError, MarkdownConverter
from pdf_optimizer import PDFCompressionError, PDFOptimizer


class PDFMarkdownExtractor:
    """Convert PDF bytes to markdown without depending on FastAPI or pipeline state."""

    def __init__(
        self,
        *,
        ocr_config: OCRExtractionConfig | None = None,
        markdown_converter: MarkdownConverter | None = None,
        pdf_optimizer: PDFOptimizer | None = None,
    ) -> None:
        self.ocr_config = ocr_config or OCRExtractionConfig()
        self.markdown_converter = markdown_converter or MarkdownConverter(ocr_config=self.ocr_config)
        self.pdf_optimizer = pdf_optimizer or PDFOptimizer()

    async def extract(self, pdf_content: bytes) -> str:
        optimized = await self._optimize_pdf(pdf_content)
        markdown = await asyncio.wait_for(
            self._convert_to_markdown(optimized),
            timeout=self.ocr_config.extraction_timeout_seconds,
        )
        return markdown

    async def _convert_to_markdown(self, pdf_content: bytes) -> str:
        if not pdf_content:
            raise MarkdownConversionError("PDF content is empty")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            tmp_file.write(pdf_content)
            tmp_path = tmp_file.name
        try:
            await asyncio.to_thread(self.markdown_converter.convert_document, tmp_path)
            await asyncio.to_thread(self.markdown_converter.add_page_counters)
            markdown = await asyncio.to_thread(self.markdown_converter.get_markdown_document)
            if not markdown or not markdown.strip():
                raise MarkdownConversionError("Markdown conversion produced empty content")
            return markdown
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            self.markdown_converter.clear()

    async def _optimize_pdf(self, pdf_content: bytes) -> bytes:
        if not pdf_content:
            return pdf_content
        try:
            return await asyncio.to_thread(self.pdf_optimizer.optimize, pdf_content)
        except PDFCompressionError:
            return pdf_content
