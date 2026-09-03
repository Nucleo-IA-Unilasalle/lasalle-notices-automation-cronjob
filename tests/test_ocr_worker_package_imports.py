from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_ocr_worker_modules_support_package_imports() -> None:
    importlib.import_module("ocr_worker.pdf_markdown_extractor")
    importlib.import_module("ocr_worker.run_ocr_worker")


def test_ocr_worker_cli_smoke_matches_pipeline_invocation() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/ocr_worker/run_ocr_worker.py", "--help"],
        cwd=repo_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Run the GitHub Actions OCR worker" in result.stdout
