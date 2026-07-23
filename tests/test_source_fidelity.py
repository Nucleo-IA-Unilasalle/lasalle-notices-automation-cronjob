"""Tests for the deterministic source-fidelity audit (Plan 01)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from source_fidelity import (
    BLOCKING_REASON_CODES,
    normalize_timestamp,
    normalize_url,
    render_summary,
    run_audit,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "audit"
INVENTORY = FIXTURE_DIR / "source_inventory.json"
DISCOVERY = FIXTURE_DIR / "discovery.json"
DASHBOARD = FIXTURE_DIR / "dashboard.json"

AUDIT_CLI = Path(__file__).resolve().parent.parent / "scripts" / "audit_source_fidelity.py"


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_normalize_url_preserves_query_params():
    url = "https://www.gov.br/mma/oportunidades/001?utm_source=newsletter"
    assert normalize_url(url) == url
    with_fragment = "https://x.com/p?a=1&b=2#section"
    assert normalize_url(with_fragment) == "https://x.com/p?a=1&b=2"
    assert normalize_url("https://X.com/P/?z=1") == "https://x.com/P/?z=1"


def test_normalize_url_preserves_repeated_parameter_value_order():
    normalized = normalize_url(
        "https://example.test/path?step=2&other=x&step=1"
    )
    assert normalized == "https://example.test/path?other=x&step=2&step=1"


def test_normalize_timestamp_to_utc_preserves_original():
    norm, original = normalize_timestamp("2026-07-16T00:00:00Z")
    assert norm == "2026-07-16T00:00:00Z"
    assert original == "2026-07-16T00:00:00Z"
    norm2, orig2 = normalize_timestamp("2026-07-16T12:00:00+02:00")
    assert norm2 == "2026-07-16T10:00:00Z"
    assert orig2 == "2026-07-16T12:00:00+02:00"
    norm3, orig3 = normalize_timestamp("not-a-date")
    assert norm3 is None
    assert orig3 == "not-a-date"
    assert normalize_timestamp(None) == (None, None)


def test_stable_id_match_with_different_urls():
    inventory = [
        {
            "source_key": "wwf",
            "source_record_id": "005705",
            "canonical_url": "https://www.wwf.org.br/oportunidades/005705",
            "status": "open",
            "deadline": "2026-08-01T23:59:59Z",
            "document_urls": ["https://cdn.wwf.org.br/edital/005705.pdf"],
            "document_hashes": ["a" * 64],
        }
    ]
    discovery = [
        {
            "source_key": "wwf",
            "source_record_id": "005705",
            "canonical_url": "https://www.wwf.org.br/oportunidades/005705?ref=email",
            "status": "open",
            "deadline": "2026-08-01T23:59:59Z",
            "document_urls": ["https://cdn.wwf.org.br/edital/005705.pdf"],
            "document_hashes": ["a" * 64],
        }
    ]
    result = run_audit(inventory, discovery)
    assert len(result.matches) == 1
    assert result.matches[0].match_method == "stable_id"
    assert result.blocking_exceptions() == []
    assert result.matches[0].field_comparison["status"]["match"] is True


def test_canonical_url_match_without_source_id():
    inventory = [
        {
            "canonical_url": "https://www.wwf.org.br/oportunidades/005706",
            "status": "open",
            "deadline": "2026-08-02T23:59:59Z",
            "document_urls": ["https://cdn.wwf.org.br/edital/005706.pdf"],
            "document_hashes": ["b" * 64],
        }
    ]
    discovery = [
        {
            "canonical_url": "https://www.wwf.org.br/oportunidades/005706",
            "status": "open",
            "deadline": "2026-08-02T23:59:59Z",
            "document_urls": ["https://cdn.wwf.org.br/edital/005706.pdf"],
            "document_hashes": ["b" * 64],
        }
    ]
    result = run_audit(inventory, discovery)
    assert len(result.matches) == 1
    assert result.matches[0].match_method == "canonical_url"
    assert result.blocking_exceptions() == []


def test_hash_match_after_cdn_url_rotates():
    inventory = [
        {
            "source_key": "tnc",
            "source_record_id": "TNC-77",
            "canonical_url": "https://tnc.org.br/licitacoes/77",
            "status": "open",
            "deadline": "2026-08-20T23:59:59Z",
            "document_urls": ["https://tnc.org.br/docs/77.pdf"],
            "document_hashes": ["e" * 64],
        }
    ]
    discovery = [
        {
            "source_key": "tnc",
            "source_record_id": "TNC-77",
            "canonical_url": "https://cdn1.tnc.org.br/licitacoes/77/arquivo.pdf",
            "status": "open",
            "deadline": "2026-08-20T23:59:59Z",
            "document_urls": ["https://cdn1.tnc.org.br/licitacoes/77/arquivo.pdf"],
            "document_hashes": ["e" * 64],
        }
    ]
    result = run_audit(inventory, discovery)
    assert any(m.match_method == "stable_id" for m in result.matches)
    assert result.blocking_exceptions() == []


def test_missing_source_opportunity_is_blocking():
    inventory = [
        {
            "source_key": "wwf",
            "source_record_id": "005710",
            "canonical_url": "https://www.wwf.org.br/oportunidades/005710",
            "status": "open",
        }
    ]
    discovery: list[dict] = []
    result = run_audit(inventory, discovery)
    codes = {e.reason_code for e in result.blocking_exceptions()}
    assert "missing_open" in codes
    assert any(
        e.reason_code == "missing_open" and e.evidence.get("stable_id") == ("wwf", "005710")
        for e in result.exceptions
    )


def test_closed_inventory_record_is_not_required_for_open_accounting():
    inventory = [
        {
            "source_key": "wwf",
            "source_record_id": "005094",
            "canonical_url": "https://www.wwf.org.br/oportunidades/005094",
            "status": "closed",
        }
    ]

    result = run_audit(inventory, [])
    summary = render_summary(result)

    assert result.blocking_exceptions() == []
    assert summary["inventory_accounting_pct"] == 100.0
    assert summary["inventory_accounted_numerator"] == 0
    assert summary["inventory_accounted_denominator"] == 0
    assert summary["inventory_open_in_scope_total"] == 0


def test_extra_scraper_and_dashboard_record_is_blocking():
    inventory: list[dict] = []
    discovery = [
        {
            "source_key": "wwf",
            "source_record_id": "005708",
            "canonical_url": "https://www.wwf.org.br/oportunidades/005708",
            "status": "open",
        }
    ]
    dashboard = [
        {
            "source_key": "wwf",
            "source_record_id": "005720",
            "canonical_url": "https://www.wwf.org.br/oportunidades/005720",
            "status": "open",
        }
    ]
    result = run_audit(inventory, discovery, dashboard)
    extra = [e for e in result.exceptions if e.reason_code == "extra_submission"]
    assert len(extra) == 2
    assert {e.evidence["origin"] for e in extra} == {"discovery", "dashboard"}


def test_duplicate_candidate_is_blocking():
    inventory = [
        {
            "source_key": "funbio",
            "source_record_id": "FB-100",
            "canonical_url": "https://funbio.org.br/oportunidades/100",
            "status": "open",
        },
        {
            "source_key": "funbio",
            "source_record_id": "FB-100",
            "canonical_url": "https://funbio.org.br/oportunidades/100",
            "status": "open",
        },
    ]
    discovery: list[dict] = []
    result = run_audit(inventory, discovery)
    dupes = [e for e in result.exceptions if e.reason_code == "duplicate_identity"]
    assert dupes
    assert all(e.severity == "blocking" for e in dupes)


def test_deadline_and_status_mismatch_is_blocking():
    inventory = [
        {
            "source_key": "mma",
            "source_record_id": "MMA-2026-001",
            "canonical_url": "https://www.gov.br/mma/oportunidades/001",
            "status": "open",
            "deadline": "2026-09-01T23:59:59Z",
        }
    ]
    discovery = [
        {
            "source_key": "mma",
            "source_record_id": "MMA-2026-001",
            "canonical_url": "https://www.gov.br/mma/oportunidades/001",
            "status": "closed",
            "deadline": "2026-09-01T23:59:59Z",
        }
    ]
    result = run_audit(inventory, discovery)
    codes = {e.reason_code for e in result.blocking_exceptions()}
    assert "authoritative_status_mismatch" in codes
    assert "authoritative_deadline_mismatch" not in codes


def test_query_params_not_stripped():
    inv_url = "https://www.gov.br/mma/oportunidades/001?utm_source=newsletter"
    inv = [{"source_key": "mma", "source_record_id": "MMA-2026-001", "canonical_url": inv_url, "status": "open"}]
    disc = [{"source_key": "mma", "source_record_id": "MMA-2026-001", "canonical_url": inv_url, "status": "open"}]
    result = run_audit(inv, disc)
    assert result.matches[0].inventory["canonical_url"] == inv_url
    assert "utm_source=newsletter" in result.matches[0].inventory["canonical_url"]


def test_absent_optional_field_is_not_auto_mismatch():
    inventory = [{"source_key": "x", "source_record_id": "1", "status": "open"}]
    discovery = [{"source_key": "x", "source_record_id": "1"}]
    result = run_audit(inventory, discovery)
    assert result.blocking_exceptions() == []
    assert any(e.reason_code == "missing_optional_metadata" for e in result.non_blocking_exceptions())


def test_renderability_mismatch_is_blocking():
    inventory = [
        {
            "source_key": "funbio",
            "source_record_id": "FB-100",
            "canonical_url": "https://funbio.org.br/oportunidades/100",
            "status": "open",
            "document_urls": ["https://funbio.org.br/docs/edital100.pdf"],
            "renderable": True,
        }
    ]
    dashboard = [
        {
            "source_key": "funbio",
            "source_record_id": "FB-100",
            "canonical_url": "https://funbio.org.br/oportunidades/100",
            "status": "open",
            "document_urls": ["https://funbio.org.br/docs/edital100.pdf"],
            "renderable": False,
        }
    ]
    result = run_audit(inventory, dashboard)
    assert any(e.reason_code == "renderability_mismatch" for e in result.blocking_exceptions())


def test_fixtures_cover_identity_and_deadline_mismatch():
    inventory = _load(INVENTORY)
    discovery = _load(DISCOVERY)
    result = run_audit(inventory, discovery)
    codes = {e.reason_code for e in result.blocking_exceptions()}
    assert "identity_mismatch" in codes
    assert "authoritative_deadline_mismatch" in codes
    assert any(
        e.reason_code == "identity_mismatch"
        and e.evidence.get("stable_id") == ("bndes", "BN-5")
        for e in result.exceptions
    )


def test_parser_failure_on_invalid_timestamp_is_blocking():
    inventory = [
        {
            "source_key": "iis_rio",
            "source_record_id": "IIS-9",
            "canonical_url": "https://iisrio.org.br/oportunidades/9",
            "status": "open",
            "deadline": "not-a-date",
        }
    ]
    discovery: list[dict] = []
    result = run_audit(inventory, discovery)
    parser_fails = [e for e in result.exceptions if e.reason_code == "parser_failure"]
    assert parser_fails
    assert parser_fails[0].evidence["field"] == "deadline"


def test_title_similarity_does_not_establish_identity():
    inventory = [{"source_key": "a", "source_record_id": "1", "title": "Edital consultoria", "status": "open"}]
    discovery = [{"source_key": "b", "source_record_id": "2", "title": "Edital consultoria", "status": "open"}]
    result = run_audit(inventory, discovery)
    assert result.blocking_exceptions()
    assert any(e.reason_code == "extra_submission" for e in result.blocking_exceptions())
    assert not any(m.match_method for m in result.matches)


def test_title_only_match_is_not_an_identity():
    inventory = [
        {
            "source_key": "a",
            "source_record_id": "1",
            "canonical_url": "https://a.com/1",
            "title": "Edital consultoria",
            "status": "open",
        }
    ]
    discovery = [
        {
            "source_key": "a",
            "source_record_id": "2",
            "canonical_url": "https://a.com/2",
            "title": "Edital consultoria",
            "status": "open",
        }
    ]
    result = run_audit(inventory, discovery)
    assert not result.matches
    codes = {e.reason_code for e in result.blocking_exceptions()}
    assert "missing_open" in codes
    assert "extra_submission" in codes


def test_deterministic_report_ordering():
    inventory = _load(INVENTORY)
    discovery = _load(DISCOVERY)
    dashboard = _load(DASHBOARD)
    result = run_audit(inventory, discovery, dashboard)
    md1 = sorted(m.match_key for m in result.matches)
    md2 = sorted(m.match_key for m in result.matches)
    assert md1 == md2
    keys = [m.match_key for m in sorted(result.matches, key=lambda x: x.match_key)]
    assert keys == sorted(keys)


def test_report_is_byte_stable_across_runs(tmp_path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    cmd = [
        sys.executable,
        str(AUDIT_CLI),
        "--source-inventory", str(INVENTORY),
        "--discovery", str(DISCOVERY),
        "--dashboard", str(DASHBOARD),
        "--out", str(out1),
    ]
    subprocess.run(cmd, check=False)
    subprocess.run([sys.executable, str(AUDIT_CLI),
                    "--source-inventory", str(INVENTORY),
                    "--discovery", str(DISCOVERY),
                    "--dashboard", str(DASHBOARD),
                    "--out", str(out2)], check=False)
    for name in ("summary.json", "matches.json", "exceptions.json", "report.md"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_known_unrelated_pdf_causes_exit_1_with_url_and_evidence(tmp_path):
    out = tmp_path / "report"
    proc = subprocess.run(
        [sys.executable, str(AUDIT_CLI),
         "--source-inventory", str(INVENTORY),
         "--discovery", str(DISCOVERY),
         "--dashboard", str(DASHBOARD),
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    exceptions = json.loads((out / "exceptions.json").read_text(encoding="utf-8"))
    unrelated = [e for e in exceptions if "relatorio-anual-2025.pdf" in json.dumps(e)]
    assert unrelated
    assert unrelated[0]["evidence"]["canonical_url"] == "https://example.com/relatorio-anual-2025.pdf"
    assert "document_urls" in unrelated[0]["evidence"]


def test_invalid_json_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text("[]", encoding="utf-8")
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, str(AUDIT_CLI),
         "--source-inventory", str(bad),
         "--discovery", str(good),
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2


def test_missing_required_argument_exits_2():
    proc = subprocess.run([sys.executable, str(AUDIT_CLI)], capture_output=True, text=True)
    assert proc.returncode == 2


def test_every_blocking_reason_code_is_fixture_tested(tmp_path):
    out = tmp_path / "report"
    proc = subprocess.run(
        [sys.executable, str(AUDIT_CLI),
         "--source-inventory", str(INVENTORY),
         "--discovery", str(DISCOVERY),
         "--dashboard", str(DASHBOARD),
         "--out", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    counts = summary["blocking_reason_counts"]
    tested = {code for code, n in counts.items() if n > 0}
    assert tested == set(BLOCKING_REASON_CODES)


def test_cli_help_exits_0():
    proc = subprocess.run([sys.executable, str(AUDIT_CLI), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "--source-inventory" in proc.stdout
    assert "--discovery" in proc.stdout
    assert "--dashboard" in proc.stdout


def test_reports_redact_credentials(tmp_path):
    out = tmp_path / "report"
    inventory = [
        {
            "source_key": "x",
            "source_record_id": "1",
            "canonical_url": "https://x.com/1",
            "status": "open",
            "Authorization": "Bearer secret-token",
            "token": "abc123",
        }
    ]
    disc = [_load(DISCOVERY)[0]]
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(json.dumps(inventory), encoding="utf-8")
    subprocess.run([sys.executable, str(AUDIT_CLI),
                    "--source-inventory", str(inv_path),
                    "--discovery", str(DISCOVERY),
                    "--out", str(out)], check=False)
    blob = (out / "matches.json").read_text(encoding="utf-8") + (out / "exceptions.json").read_text(encoding="utf-8")
    assert "secret-token" not in blob
    assert "abc123" not in blob
    assert "[REDACTED]" in blob


def test_perfect_three_way_match_passes_with_full_traceability():
    record = {
        "source_key": "wwf",
        "source_record_id": "005705",
        "canonical_url": "https://example.test/005705",
        "status": "open",
    }
    result = run_audit([record], [record], [record])
    summary = render_summary(result)

    assert summary["pass"] is True
    assert summary["candidate_traceability_pct"] == 100.0
    assert summary["candidates_traced_numerator"] == 2
    assert summary["candidates_traced_denominator"] == 2
    assert result.matches[0].discovery is not None
    assert result.matches[0].dashboard is not None


@pytest.mark.parametrize(
    ("field", "inventory_values", "discovery_values", "expected_method"),
    [
        (
            "document_hashes",
            ["a" * 64, "b" * 64],
            ["c" * 64, "b" * 64],
            "document_hash",
        ),
        (
            "document_urls",
            ["https://cdn.test/a.pdf", "https://cdn.test/shared.pdf"],
            ["https://cdn.test/c.pdf", "https://cdn.test/shared.pdf"],
            "document_url",
        ),
    ],
)
def test_any_document_identity_can_match(
    field, inventory_values, discovery_values, expected_method
):
    inventory = [{"source_key": "x", "status": "open", field: inventory_values}]
    discovery = [{"source_key": "x", "status": "open", field: discovery_values}]

    result = run_audit(inventory, discovery)

    assert result.blocking_exceptions() == []
    assert result.matches[0].match_method == expected_method


def test_renderable_requires_successful_type_and_hash_validation():
    base = {
        "source_key": "x",
        "source_record_id": "1",
        "status": "open",
        "document_urls": ["https://example.test/not-validated.pdf"],
        "renderable": True,
    }
    failed = run_audit([base], [base])
    assert any(
        exc.reason_code == "renderability_mismatch"
        for exc in failed.blocking_exceptions()
    )

    validated = {
        **base,
        "content_type_validated": True,
        "hash_validated": True,
    }
    passed = run_audit([validated], [validated])
    assert passed.blocking_exceptions() == []


def test_reports_recursively_redact_credentials_and_auth_query_values(tmp_path):
    record = {
        "source_key": "x",
        "source_record_id": "1",
        "canonical_url": "https://example.test/1?access_token=query-secret",
        "status": "open",
        "headers": {
            "Authorization": "Bearer nested-secret",
            "X-Api-Key": "nested-api-key",
        },
        "metadata": {"password": "nested-password"},
    }
    inventory = tmp_path / "inventory.json"
    discovery = tmp_path / "discovery.json"
    inventory.write_text(json.dumps([record]), encoding="utf-8")
    unrelated = {
        **record,
        "source_record_id": "2",
        "canonical_url": "https://user:exception-secret@example.test/2?api_key=exception-query-secret",
    }
    discovery.write_text(json.dumps([record, unrelated]), encoding="utf-8")
    out = tmp_path / "report"

    proc = subprocess.run(
        [
            sys.executable,
            str(AUDIT_CLI),
            "--source-inventory",
            str(inventory),
            "--discovery",
            str(discovery),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    blob = "".join(
        (out / name).read_text(encoding="utf-8")
        for name in ("matches.json", "exceptions.json", "report.md")
    )
    assert "query-secret" not in blob
    assert "nested-secret" not in blob
    assert "nested-password" not in blob
    assert "nested-api-key" not in blob
    assert "exception-secret" not in blob
    assert "exception-query-secret" not in blob


def test_canonical_url_match_key_redacts_credentials_from_every_report(tmp_path):
    record = {
        "canonical_url": "https://example.test/call?access_token=match-key-secret",
        "status": "open",
    }
    inventory = tmp_path / "inventory.json"
    discovery = tmp_path / "discovery.json"
    inventory.write_text(json.dumps([record]), encoding="utf-8")
    discovery.write_text(json.dumps([record]), encoding="utf-8")
    out = tmp_path / "report"

    proc = subprocess.run(
        [
            sys.executable,
            str(AUDIT_CLI),
            "--source-inventory",
            str(inventory),
            "--discovery",
            str(discovery),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    blob = "".join(
        (out / name).read_text(encoding="utf-8")
        for name in ("summary.json", "matches.json", "exceptions.json", "report.md")
    )
    assert "match-key-secret" not in blob
    assert "%5BREDACTED%5D" in blob or "[REDACTED]" in blob


def test_conflicting_stable_ids_do_not_match_through_shared_url():
    inventory = [
        {
            "source_key": "wwf",
            "source_record_id": "expected",
            "canonical_url": "https://example.test/shared",
            "status": "open",
        }
    ]
    discovery = [
        {
            "source_key": "wwf",
            "source_record_id": "different",
            "canonical_url": "https://example.test/shared",
            "status": "open",
        }
    ]

    result = run_audit(inventory, discovery)

    assert result.matches == []
    reason_codes = [exc.reason_code for exc in result.blocking_exceptions()]
    assert "identity_mismatch" in reason_codes
    assert "missing_open" in reason_codes
    assert "extra_submission" in reason_codes


def test_invalid_record_shape_exits_2_without_traceback(tmp_path):
    inventory = tmp_path / "inventory.json"
    discovery = tmp_path / "discovery.json"
    inventory.write_text("[42]", encoding="utf-8")
    discovery.write_text("[]", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(AUDIT_CLI),
            "--source-inventory",
            str(inventory),
            "--discovery",
            str(discovery),
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "must be a JSON object" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_explicit_policy_outcomes_are_non_blocking_and_accounted():
    inventory = [
        {
            "source_key": "x",
            "source_record_id": "1",
            "status": "open",
            "reason_code": "out_of_scope",
            "evidence": {"policy": "not an edital"},
        }
    ]
    discovery = [
        {
            "title": "Unresolved announcement",
            "reason_code": "unresolved_news_lead",
            "evidence": {"resolution": "no canonical call found"},
        }
    ]

    result = run_audit(inventory, discovery)
    summary = render_summary(result)

    assert result.blocking_exceptions() == []
    assert {exc.reason_code for exc in result.non_blocking_exceptions()} == {
        "out_of_scope",
        "unresolved_news_lead",
    }
    assert summary["inventory_accounting_pct"] == 100.0
    assert summary["inventory_accounted_denominator"] == 0
    assert summary["candidate_traceability_pct"] == 100.0
