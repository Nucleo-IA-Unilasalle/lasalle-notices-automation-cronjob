# P1 Image-Only OCR Fixture - 2026-09-13T00:30Z

Status: **PASS (isolated dependency/runtime evidence only)**

Command, from a temporary Python 3.13 environment containing
`requirements-ocr-worker.txt`:

```text
python scripts/run_p1_image_ocr_fixture.py
```

A one-page PDF was generated in a temporary directory from a raster image
containing two large text lines. `pypdf` returned no embedded text, proving the
fixture was image-only. The repository's real `PDFMarkdownExtractor` and
PaddleOCR `PP-OCRv6_tiny` detector/recognizer then extracted non-empty markdown
containing the expected `EDITAL` and `2026` tokens. The fixture and temporary
PDF were removed automatically; only hashes and measurements are recorded.

| Measure | Result |
|---|---|
| Pages | 1 |
| Embedded text before OCR | Empty |
| Extracted markdown | 48 characters |
| Expected tokens | Present |
| OCR elapsed time | 6.363 seconds |
| PDF SHA-256 | `801a0a10495252011114760f17a45bd6a7f66e0eb9d736d7e0d80eb0cc989f6e` |
| Markdown SHA-256 | `31a487e52bffe8f878dd247b8a83ed0a949da48fabcd0840b2d9eff2a5578705` |

The first run used the repository's former `paddlepaddle==3.0.0` pin and failed
while creating the PP-OCRv6 predictor with Paddle `InvalidArgument: Type of
attribute: strides is not right`. Repeating the same fixture with
`paddlepaddle==3.3.1` passed, so `requirements-ocr-worker.txt` now pins 3.3.1.
No mock OCR result is counted as evidence.

This run used an isolated temporary Python 3.13 environment and downloaded the
official tiny model artifacts. It did not access any production endpoint or
data and is not a frozen-head or production approval record.

The sanitized machine result is
[`p1-image-only-ocr-2026-09-13T0030Z.json`](p1-image-only-ocr-2026-09-13T0030Z.json).
