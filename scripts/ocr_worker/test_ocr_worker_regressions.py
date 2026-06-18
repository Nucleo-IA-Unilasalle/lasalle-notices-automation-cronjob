from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

WORKER_DIR = Path(__file__).parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

import kreuzberg_extractor
from markdown_converter import MarkdownConverter
from run_ocr_worker import WorkerSettings


class FakeOCR:
    def __init__(self, results):
        self.results = results

    def predict(self, file_path: str):
        return self.results


class KreuzbergExtractorTests(unittest.TestCase):
    def tearDown(self) -> None:
        kreuzberg_extractor._paddleocr_instances.clear()

    def test_extract_file_sync_preserves_pdf_page_boundaries(self) -> None:
        ocr = FakeOCR(
            [
                {"page_index": 0, "rec_texts": ["first page"]},
                {"page_index": 1, "rec_texts": ["second page"]},
            ]
        )

        with patch.object(kreuzberg_extractor, "_get_ocr_instance", return_value=ocr):
            text = kreuzberg_extractor.extract_file_sync("document.pdf")

        self.assertEqual(
            text,
            "<!-- PAGE 1 -->\nfirst page\n\n<!-- PAGE 2 -->\nsecond page",
        )

    def test_page_markers_are_converted_to_markdown_page_counters(self) -> None:
        converter = MarkdownConverter(
            ocr_extractor=lambda path, **kwargs: (
                "<!-- PAGE 1 -->\nfirst page\n\n<!-- PAGE 2 -->\nsecond page"
            )
        )

        with patch("markdown_converter.os.path.exists", return_value=True):
            converter.convert_document("document.pdf")
        converter.add_page_counters()

        self.assertEqual(
            converter.get_markdown_document(),
            "first page\n\n<!-- Página 2 -->\n\nsecond page",
        )

    def test_get_ocr_instance_uses_requested_tier_and_device(self) -> None:
        created: list[dict[str, object]] = []

        class PaddleOCR:
            def __init__(self, **kwargs):
                created.append(kwargs)

        fake_module = SimpleNamespace(PaddleOCR=PaddleOCR)
        with patch.dict(sys.modules, {"paddleocr": fake_module}):
            first = kreuzberg_extractor._get_ocr_instance(
                model_tier="small", use_gpu=True
            )
            second = kreuzberg_extractor._get_ocr_instance(
                model_tier="small", use_gpu=True
            )

        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["text_detection_model_name"], "PP-OCRv6_small_det")
        self.assertEqual(created[0]["text_recognition_model_name"], "PP-OCRv6_small_rec")
        self.assertEqual(created[0]["device"], "gpu")

    def test_get_ocr_instance_disables_onednn_before_importing_paddle(self) -> None:
        captured_flag: list[str | None] = []

        class PaddleOCR:
            def __init__(self, **kwargs):
                captured_flag.append(os.environ.get("FLAGS_use_mkldnn"))

        fake_module = SimpleNamespace(PaddleOCR=PaddleOCR)
        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(sys.modules, {"paddleocr": fake_module}):
                kreuzberg_extractor._get_ocr_instance(model_tier="tiny", use_gpu=False)

        self.assertEqual(captured_flag, ["0"])


class WorkerSettingsTests(unittest.TestCase):
    def test_from_env_defaults_to_tiny_model_tier(self) -> None:
        with patch.dict(
            os.environ,
            {"RENDER_APP_URL": "https://example.com", "PIPELINE_SECRET": "secret"},
            clear=True,
        ):
            settings = WorkerSettings.from_env()

        self.assertEqual(settings.ocr_config.model_tier, "tiny")


if __name__ == "__main__":
    unittest.main()
