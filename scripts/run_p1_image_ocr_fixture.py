"""Run a bounded genuine image-only PDF OCR fixture for the P1 gate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

from ocr_worker.ocr_extraction_config import OCRExtractionConfig
from ocr_worker.pdf_markdown_extractor import PDFMarkdownExtractor


EXPECTED_TOKENS = ("EDITAL", "2026")


def _image_only_pdf() -> bytes:
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=70)
    draw.text((120, 280), "EDITAL TESTE OCR 2026", font=font, fill="black")
    draw.text((120, 430), "INSCRICOES ATE 30 SETEMBRO", font=font, fill="black")
    with tempfile.TemporaryDirectory(prefix="lasalle-p1-image-ocr-") as folder:
        path = Path(folder) / "image-only.pdf"
        image.save(path, "PDF", resolution=150.0)
        return path.read_bytes()


async def run_fixture() -> dict[str, object]:
    pdf = _image_only_pdf()
    embedded = "".join(
        (page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages
    )
    if embedded.strip():
        raise RuntimeError("Fixture unexpectedly contains an embedded text layer")

    config = OCRExtractionConfig(
        force_ocr=True,
        model_tier="tiny",
        max_pages=1,
        extraction_timeout_seconds=600,
    )
    started = time.perf_counter()
    markdown = await PDFMarkdownExtractor(ocr_config=config).extract(pdf)
    elapsed = time.perf_counter() - started
    normalized = " ".join(markdown.upper().split())
    missing = [token for token in EXPECTED_TOKENS if token not in normalized]
    if missing:
        raise RuntimeError(f"OCR output omitted expected tokens: {missing}")

    return {
        "status": "pass",
        "image_only": True,
        "pages": 1,
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "markdown_chars": len(markdown),
        "elapsed_seconds": round(elapsed, 3),
        "contains_expected_tokens": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the sanitized JSON result; stdout is always emitted.",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(run_fixture())
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
