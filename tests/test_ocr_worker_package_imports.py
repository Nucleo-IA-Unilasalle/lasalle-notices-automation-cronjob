from __future__ import annotations

import importlib
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_ocr_worker_modules_support_package_imports() -> None:
    importlib.import_module("ocr_worker.pdf_markdown_extractor")
    importlib.import_module("ocr_worker.run_ocr_worker")
