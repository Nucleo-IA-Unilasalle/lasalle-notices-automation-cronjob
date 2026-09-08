"""Diagnostic official-page comparison for BRDE and BNDES.

This repository-owned helper fetches a selected set of official pages, runs the
repository's adapter, and compares their URL identities. It is useful for parser
diagnostics, but it is not an independent ground-truth audit and cannot satisfy
Gate RR-05. Even a blocker-free comparison exits with code 2 so automation cannot
mistake the diagnostic for release acceptance.

Usage:
    py -3.13 scripts/run_independent_source_audit.py --source brde --slot 1 --out-dir artifacts/diagnostics/brde-1
    py -3.13 scripts/run_independent_source_audit.py --source bndes --slot 1 --out-dir artifacts/diagnostics/bndes-1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_fidelity import render_markdown, render_summary, run_audit, validate_records

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "(Repository diagnostic; not an independent audit)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _require_response(response: requests.Response, url: str, *, expected: set[int] | None = None) -> None:
    """Fail closed when a required official-page request is unsuccessful."""
    if expected is not None:
        if response.status_code not in expected:
            raise RuntimeError(
                f"official page {url} returned HTTP {response.status_code}; expected {sorted(expected)}"
            )
        return
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"official page {url} request failed: {exc}") from exc


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_document_url(page_url: str, href: str) -> str:
    """Resolve a document anchor and remove its non-identity fragment."""
    parsed = urlsplit(urljoin(page_url, href))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# BRDE Official Ground Truth Capture
# ---------------------------------------------------------------------------

def capture_brde_ground_truth() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Capture the BRDE links selected by this diagnostic's fixed rules."""
    captured_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    palacete_url = "https://www.brde.com.br/palacete/editais/"
    fsa_url = "https://www.brde.com.br/fsa/chamadas-de-investimento/"
    editais_root_url = "https://www.brde.com.br/editais/"

    metadata: dict[str, Any] = {
        "source": "brde",
        "captured_at_utc": captured_at,
        "operator": "Repository diagnostic runner (not an independent reviewer)",
        "method": "Selected-link HTTP/DOM diagnostic; completeness not established",
        "evidence_classification": "diagnostic_only",
        "inspected_urls": {},
    }

    # 1. Check editais root (WordPress listing check)
    r_root = session.get(editais_root_url, timeout=20)
    _require_response(r_root, editais_root_url, expected={404})
    metadata["inspected_urls"][editais_root_url] = {
        "status_code": r_root.status_code,
        "bytes": len(r_root.content),
        "sha256": _sha256(r_root.content),
        "final_url": r_root.url,
        "note": "Expected diagnostic observation: HTTP 404",
    }

    # 2. Check FSA investment calls listing
    r_fsa = session.get(fsa_url, timeout=25)
    _require_response(r_fsa, fsa_url)
    metadata["inspected_urls"][fsa_url] = {
        "status_code": r_fsa.status_code,
        "bytes": len(r_fsa.content),
        "sha256": _sha256(r_fsa.content),
        "final_url": r_fsa.url,
        "note": "Fetched for diagnostic context; contents were not inventoried exhaustively",
    }

    # 3. Fetch official Palacete editais page (active open calls)
    r_pal = session.get(palacete_url, timeout=25)
    _require_response(r_pal, palacete_url)
    metadata["inspected_urls"][palacete_url] = {
        "status_code": r_pal.status_code,
        "bytes": len(r_pal.content),
        "sha256": _sha256(r_pal.content),
        "final_url": r_pal.url,
    }

    soup = BeautifulSoup(r_pal.content, "html.parser")
    inventory_records: list[dict[str, Any]] = []

    # Find the 2026 public call: "Edital de Patrocínio BRDE Cultural – Palacete dos Leões 2026"
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if not href or not urlsplit(href).path.lower().endswith(".pdf"):
            continue
        text = a.get_text(" ", strip=True)
        # Match the 2026 edital
        if "Patrocinio" in href and "2026" in href:
            canonical = _canonical_document_url(r_pal.url, href)
            title = text or "Edital de Patrocínio BRDE Cultural – Palacete dos Leões 2026"
            inventory_records.append({
                "source_key": "brde",
                "source_record_id": canonical,
                "canonical_url": canonical,
                "title": title,
                # The fixed URL selector does not establish lifecycle state.
                "status": None,
                "published_at": None,
                "deadline": None,
                "document_urls": [canonical],
                "document_hashes": [],
            })
            break

    if not inventory_records:
        raise RuntimeError("BRDE diagnostic selector found no matching link")

    return inventory_records, metadata


# ---------------------------------------------------------------------------
# BNDES Official Ground Truth Capture
# ---------------------------------------------------------------------------

def capture_bndes_ground_truth() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Capture the BNDES links selected by this diagnostic's fixed rules."""
    captured_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    root_fsa = "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental"
    vanity_inovacao = "https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao"

    metadata: dict[str, Any] = {
        "source": "bndes",
        "captured_at_utc": captured_at,
        "operator": "Repository diagnostic runner (not an independent reviewer)",
        "method": "Selected-link HTTP/DOM diagnostic; completeness not established",
        "evidence_classification": "diagnostic_only",
        "inspected_urls": {},
    }

    # 1. Root FSA
    r_root = session.get(root_fsa, timeout=30)
    _require_response(r_root, root_fsa)
    metadata["inspected_urls"][root_fsa] = {
        "status_code": r_root.status_code,
        "bytes": len(r_root.content),
        "sha256": _sha256(r_root.content),
        "final_url": r_root.url,
    }

    # 2. Inovacao vanity
    r_inov = session.get(vanity_inovacao, timeout=30)
    _require_response(r_inov, vanity_inovacao)
    metadata["inspected_urls"][vanity_inovacao] = {
        "status_code": r_inov.status_code,
        "bytes": len(r_inov.content),
        "sha256": _sha256(r_inov.content),
        "final_url": r_inov.url,
        "note": "Fetched for diagnostic context; redirect meaning requires reviewer assessment",
    }

    # Official subpages with open/active calls
    subpages = [
        ("bndes-corais", "?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fmeio-ambiente%2Fbndes-azul%2Fbndes-corais"),
        ("bndes-periferias", "?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fsocial%2Fbndes-periferias"),
        ("sertao-mais-produtivo", "?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fsocial%2Fsertao-mais-produtivo"),
        ("bndes-bioinsumos", "?1dmy&urile=wcm%3apath%3a%2Fbndes_institucional%2Fhome%2Fonde-atuamos%2Fsocial%2Fbndes-bioinsumos"),
    ]

    inventory_records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for slug, query in subpages:
        page_url = urljoin(root_fsa, query)
        r_page = session.get(page_url, timeout=30)
        _require_response(r_page, page_url)
        metadata["inspected_urls"][page_url] = {
            "slug": slug,
            "status_code": r_page.status_code,
            "bytes": len(r_page.content),
            "sha256": _sha256(r_page.content),
            "final_url": r_page.url,
        }
        soup = BeautifulSoup(r_page.content, "html.parser")

        for a in soup.find_all("a"):
            href = a.get("href", "")
            if not href or ".pdf" not in href.lower():
                continue
            text = a.get_text(" ", strip=True)
            resolved = urljoin(page_url, href)

            # Filter non-edital informational brochures and FAQs (e.g. Perguntas e Respostas, Folheto)
            fn = unquote(urlsplit(resolved).path).lower()
            if any(p in fn for p in ["perguntas", "faq", "apresentacao", "folheto", "projetos+em+andamento"]):
                continue

            # Year guard for prior-cycle historical documents (e.g. 2024 results)
            if "2024" in fn and "sertao" not in fn and "edital" not in fn:
                continue

            # Identify the 5 authoritative call documents:
            # 1. Corais: Modelo Roteiro MA_Corais_Web
            # 2. Periferias: Roteiro BNDES Periferias 6º ciclo
            # 3. Sertao: Edital Sertão Produtivo capa
            # 4. Sertao: Anexo IV Roteiro Projetos Sertão Produtivo
            # 5. Bioinsumos: Roteiro Projetos Bioinsumos 2º ciclo
            is_target = False
            if slug == "bndes-corais" and "corais" in fn:
                is_target = True
            elif slug == "bndes-periferias" and "periferias" in fn and "6" in fn:
                is_target = True
            elif slug == "sertao-mais-produtivo" and ("sertao" in fn and ("edital_capa" in fn or "anexo+iv" in fn)):
                is_target = True
            elif slug == "bndes-bioinsumos" and "bioinsumos" in fn:
                is_target = True

            if is_target:
                # Retain exact canonical query params from href
                parsed = urlsplit(resolved)
                canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
                if canonical not in seen_urls:
                    seen_urls.add(canonical)
                    inventory_records.append({
                        "source_key": "bndes",
                        "source_record_id": canonical,
                        "canonical_url": canonical,
                        "title": text or fn,
                        # Link presence alone does not establish lifecycle state.
                        "status": None,
                        "published_at": None,
                        "deadline": None,
                        "document_urls": [canonical],
                        "document_hashes": [],
                    })

    if not inventory_records:
        raise RuntimeError("BNDES diagnostic selectors found no matching links")

    return inventory_records, metadata


# ---------------------------------------------------------------------------
# Pipeline Discovery Execution
# ---------------------------------------------------------------------------

def run_pipeline_discovery(source_key: str) -> list[dict[str, Any]]:
    """Run adapter discovery, rejecting partial or internally inconsistent output."""
    if source_key == "brde":
        import discover_brde_candidates
        stats, candidates = discover_brde_candidates.discover_candidates()
    elif source_key == "bndes":
        import discover_bndes_candidates
        stats, candidates = discover_bndes_candidates.discover_candidates()
    else:
        raise ValueError(f"Unsupported source_key: {source_key}")

    if not isinstance(stats, dict):
        raise RuntimeError(f"{source_key} discovery returned invalid stats")
    if stats.get("errors", 0):
        raise RuntimeError(f"{source_key} discovery reported {stats['errors']} error(s)")
    if stats.get("candidate_cap_reached", 0):
        raise RuntimeError(f"{source_key} discovery reached its candidate cap")
    if stats.get("candidates") != len(candidates):
        raise RuntimeError(
            f"{source_key} discovery stats/candidate mismatch: "
            f"{stats.get('candidates')!r} != {len(candidates)}"
        )
    if not candidates:
        raise RuntimeError(f"{source_key} discovery returned no candidates")

    records: list[dict[str, Any]] = []
    for c in candidates:
        url = c["url"]
        meta = c.get("metadata") or {}
        records.append({
            "source_key": source_key,
            "source_record_id": meta.get("source_record_id") or url,
            "canonical_url": meta.get("canonical_url") or url,
            "title": meta.get("title") or c.get("title"),
            "status": meta.get("status") or meta.get("authoritative_status"),
            "published_at": meta.get("published_at"),
            "deadline": meta.get("deadline") or meta.get("application_deadline"),
            "document_urls": [url] if url else [],
            "document_hashes": [],
        })
    return records


# ---------------------------------------------------------------------------
# Main Audit Orchestration
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=["brde", "bndes"])
    parser.add_argument("--slot", required=True, type=int, choices=[1, 2])
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    out_dir: Path = args.out_dir
    if out_dir.exists():
        print(f"error: diagnostic output directory already exists: {out_dir}", file=sys.stderr)
        return 2
    try:
        out_dir.mkdir(parents=True)
    except OSError as exc:
        print(f"error: cannot create diagnostic output directory {out_dir}: {exc}", file=sys.stderr)
        return 2
    fidelity_dir = out_dir / "fidelity"
    fidelity_dir.mkdir()

    print(f"[{args.source.upper()}] Starting diagnostic selected-page comparison (slot {args.slot})...")

    # Step 1: Selected official-page capture for this diagnostic
    try:
        if args.source == "brde":
            inventory, capture_meta = capture_brde_ground_truth()
        else:
            inventory, capture_meta = capture_bndes_ground_truth()

        capture_meta["audit_slot"] = args.slot
        _save_json(out_dir / "ground_truth_inventory.json", inventory)
        _save_json(out_dir / "capture_metadata.json", capture_meta)
        print(f"[{args.source.upper()}] Selected diagnostic inventory: {len(inventory)} record(s).")

        # Step 2: Adapter Discovery
        print(f"[{args.source.upper()}] Running adapter candidate discovery...")
        discovery = run_pipeline_discovery(args.source)
        _save_json(out_dir / "discovery.json", discovery)
        print(f"[{args.source.upper()}] Adapter Discovery: {len(discovery)} candidate(s) discovered.")

        # Step 3: Offline Source-Fidelity Audit
        print(f"[{args.source.upper()}] Executing diagnostic source-fidelity comparison...")
        validated_inv = validate_records(inventory, "inventory")
        validated_disc = validate_records(discovery, "discovery")
        result = run_audit(validated_inv, validated_disc)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"error: diagnostic comparison incomplete: {exc}", file=sys.stderr)
        return 1

    summary = render_summary(result)
    summary["evidence_classification"] = "diagnostic_only"
    summary["rr05_accepted"] = False
    matches = [m.to_dict() for m in result.matches]
    exceptions = [e.to_dict() for e in result.exceptions]
    selected_records_matched = sum(
        1 for match in result.matches if match.discovery is not None
    )
    selected_records_missing = len(inventory) - selected_records_matched
    selected_scope_complete = selected_records_missing == 0
    summary["selected_scope_records"] = len(inventory)
    summary["selected_scope_matched_records"] = selected_records_matched
    summary["selected_scope_missing_records"] = selected_records_missing
    summary["selected_scope_complete"] = selected_scope_complete
    summary["diagnostic_pass"] = summary["pass"] and selected_scope_complete

    _save_json(fidelity_dir / "summary.json", summary)
    _save_json(fidelity_dir / "matches.json", matches)
    _save_json(fidelity_dir / "exceptions.json", exceptions)
    report = (
        "# Diagnostic Classification\n\n"
        "This selected-page, repository-owned comparison is diagnostic only. "
        "It is not an independent audit and does not satisfy RR-05.\n\n"
        "# Selected Scope Coverage\n\n"
        f"- Selected records: {len(inventory)}\n"
        f"- Selected records matched by discovery: {selected_records_matched}\n"
        f"- Selected records missing from discovery: {selected_records_missing}\n"
        f"- Selected scope complete: {selected_scope_complete}\n\n"
        + render_markdown(result)
    )
    (fidelity_dir / "report.md").write_text(report, encoding="utf-8")

    blockers = summary["total_blocking_exceptions"]
    accounted_pct = summary["inventory_accounting_pct"]
    traced_pct = summary["candidate_traceability_pct"]

    print(f"[{args.source.upper()}] Diagnostic slot {args.slot} result:")
    print(f"  - Total Blocking Exceptions: {blockers}")
    print(f"  - Inventory Accounting: {accounted_pct}%")
    print(f"  - Candidate Traceability: {traced_pct}%")
    print(f"  - Selected records missing from discovery: {selected_records_missing}")
    print(
        "  - Comparison Status: "
        f"{'NO BLOCKERS' if summary['diagnostic_pass'] else 'BLOCKED'}"
    )
    print("  - RR-05 Status: NOT ACCEPTED (independent inventory and reviewer sign-off required)")

    if not summary["diagnostic_pass"]:
        print(
            "error: diagnostic comparison has "
            f"{blockers} source-fidelity blocker(s) and "
            f"{selected_records_missing} missing selected record(s)",
            file=sys.stderr,
        )
        return 1

    # This repository-owned selected-scope comparison is diagnostic evidence.
    # A distinct non-zero code prevents CI or operators from treating it as a
    # release-gate pass even when the URL comparison has no blockers.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
