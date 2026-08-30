from unittest.mock import patch

def test_stats_allowlist_and_clamping(caplog):
    from source_run_reporting import sanitize_stats
    with caplog.at_level("WARNING"):
        assert sanitize_stats({"ocr_failures": -2, "cap_reached": True, "bad": 1, "errors": "x"}) == {"ocr_failures": 0, "cap_reached": True}
    assert "allowlist" in caplog.text

def test_record_error_counts_every_call():
    from source_run_reporting import SourceRunReporter
    r = SourceRunReporter("x"); r.record_error("first"); r.record_error("second")
    assert r.metrics.errors == 2 and r.metrics.error_code == "first"

def test_wrong_types_are_dropped():
    from source_run_reporting import sanitize_stats
    assert sanitize_stats({"ocr_failures": "3", "cap_reached": 1, "parser_failures": True, "download_failures": 2, "partial_inventory": False}) == {"download_failures": 2, "partial_inventory": False}
