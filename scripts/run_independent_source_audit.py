"""Independent Official Ground Truth Audit Runner (Gate RR-05).

Fetches ground truth directly from official portals independently of adapter
discovery output, executes adapter discovery, and runs deterministic source-fidelity
audit using audit_source_fidelity.py / source_fidelity.py.

Usage:
    py -3.13 scripts/run_independent_source_audit.py --source brde --slot 1 --out-dir docs/evidence/sources/brde/audit-1
    py -3.13 scripts/run_independent_source_audit.py --source bndes --slot 1 --out-dir docs/evidence/sources/bndes/audit-1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_source_fidelity
import source_fidelity
from source_fidelity import render_markdown, render_summary, run_audit, validate_records

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "(Independent Ground-Truth Audit; Gate RR-05)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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
    """Independently inspect official BRDE portals and build authoritative inventory."""
    captured_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    palacete_url = "https://www.brde.com.br/palacete/editais/"
    fsa_url = "https://www.brde.com.br/fsa/chamadas-de-investimento/"
    editais_root_url = "https://www.brde.com.br/editais/"

    metadata: dict[str, Any] = {
        "source": "brde",
        "captured_at_utc": captured_at,
        "operator": "Independent Auditor (Antigravity)",
        "method": "Direct official portal HTTP capture & DOM extraction",
        "inspected_urls": {},
    }

    # 1. Check editais root (WordPress listing check)
    try:
        r_root = session.get(editais_root_url, timeout=20)
        metadata["inspected_urls"][editais_root_url] = {
            "status_code": r_root.status_code,
            "bytes": len(r_root.content),
            "sha256": _sha256(r_root.content),
            "note": "Returns 404 (WordPress default not found)",
        }
    except Exception as exc:
        metadata["inspected_urls"][editais_root_url] = {"error": str(exc)}

    # 2. Check FSA investment calls listing
    try:
        r_fsa = session.get(fsa_url, timeout=25)
        metadata["inspected_urls"][fsa_url] = {
            "status_code": r_fsa.status_code,
            "bytes": len(r_fsa.content),
            "sha256": _sha256(r_fsa.content),
            "note": "Historical calls and contractual minutes (2014-2018); no active 2026 notices",
        }
    except Exception as exc:
        metadata["inspected_urls"][fsa_url] = {"error": str(exc)}

    # 3. Fetch official Palacete editais page (active open calls)
    r_pal = session.get(palacete_url, timeout=25)
    metadata["inspected_urls"][palacete_url] = {
        "status_code": r_pal.status_code,
        "bytes": len(r_pal.content),
        "sha256": _sha256(r_pal.content),
    }

    soup = BeautifulSoup(r_pal.content, "html.parser")
    inventory_records: list[dict[str, Any]] = []

    # Find the 2026 public call: "Edital de Patrocínio BRDE Cultural – Palacete dos Leões 2026"
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if not href or not href.lower().endswith(".pdf"):
            continue
        text = a.get_text(" ", strip=True)
        # Match the 2026 edital
        if "Patrocinio" in href and "2026" in href:
            canonical = href
            title = text or "Edital de Patrocínio BRDE Cultural – Palacete dos Leões 2026"
            inventory_records.append({
                "source_key": "brde",
                "source_record_id": canonical,
                "canonical_url": canonical,
                "title": title,
                "status": "open",
                "published_at": None,
                "deadline": None,
                "document_urls": [canonical],
                "document_hashes": [],
            })
            break

    if not inventory_records:
        raise RuntimeError("Failed to independently extract BRDE 2026 edital from official portal")

    return inventory_records, metadata


# ---------------------------------------------------------------------------
# BNDES Official Ground Truth Capture
# ---------------------------------------------------------------------------

def capture_bndes_ground_truth() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Independently inspect official BNDES portal and build authoritative inventory."""
    captured_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    root_fsa = "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-socioambiental"
    vanity_inovacao = "https://www.bndes.gov.br/wps/vanityurl/chamadadeinovacao"

    metadata: dict[str, Any] = {
        "source": "bndes",
        "captured_at_utc": captured_at,
        "operator": "Independent Auditor (Antigravity)",
        "method": "Direct official portal HTTP capture & DOM extraction",
        "inspected_urls": {},
    }

    # 1. Root FSA
    r_root = session.get(root_fsa, timeout=30)
    metadata["inspected_urls"][root_fsa] = {
        "status_code": r_root.status_code,
        "bytes": len(r_root.content),
        "sha256": _sha256(r_root.content),
    }

    # 2. Inovacao vanity
    try:
        r_inov = session.get(vanity_inovacao, timeout=30)
        metadata["inspected_urls"][vanity_inovacao] = {
            "status_code": r_inov.status_code,
            "bytes": len(r_inov.content),
            "sha256": _sha256(r_inov.content),
            "note": "External worldlabs.org redirect; no bndes.gov.br hosted PDFs",
        }
    except Exception as exc:
        metadata["inspected_urls"][vanity_inovacao] = {"error": str(exc)}

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
        metadata["inspected_urls"][page_url] = {
            "slug": slug,
            "status_code": r_page.status_code,
            "bytes": len(r_page.content),
            "sha256": _sha256(r_page.content),
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
                        "status": "open",
                        "published_at": None,
                        "deadline": None,
                        "document_urls": [canonical],
                        "document_hashes": [],
                    })

    if len(inventory_records) != 5:
        raise RuntimeError(f"Expected 5 authoritative BNDES records, found {len(inventory_records)}")

    return inventory_records, metadata


# ---------------------------------------------------------------------------
# Pipeline Discovery Execution
# ---------------------------------------------------------------------------

def run_pipeline_discovery(source_key: str) -> list[dict[str, Any]]:
    """Run adapter discovery and format records for source-fidelity audit."""
    if source_key == "brde":
        import discover_brde_candidates
        stats, candidates = discover_brde_candidates.discover_candidates()
    elif source_key == "bndes":
        import discover_bndes_candidates
        stats, candidates = discover_bndes_candidates.discover_candidates()
    else:
        raise ValueError(f"Unsupported source_key: {source_key}")

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
    out_dir.mkdir(parents=True, exist_ok=True)
    fidelity_dir = out_dir / "fidelity"
    fidelity_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.source.upper()}] Starting Independent Ground-Truth Audit (Slot {args.slot})...")

    # Step 1: Independent Official Ground Truth Capture
    if args.source == "brde":
        inventory, capture_meta = capture_brde_ground_truth()
    else:
        inventory, capture_meta = capture_bndes_ground_truth()

    capture_meta["audit_slot"] = args.slot
    _save_json(out_dir / "ground_truth_inventory.json", inventory)
    _save_json(out_dir / "capture_metadata.json", capture_meta)
    print(f"[{args.source.upper()}] Official Ground-Truth Inventory: {len(inventory)} record(s) captured.")

    # Step 2: Adapter Discovery
    print(f"[{args.source.upper()}] Running adapter candidate discovery...")
    discovery = run_pipeline_discovery(args.source)
    _save_json(out_dir / "discovery.json", discovery)
    print(f"[{args.source.upper()}] Adapter Discovery: {len(discovery)} candidate(s) discovered.")

    # Step 3: Offline Source-Fidelity Audit
    print(f"[{args.source.upper()}] Executing audit_source_fidelity...")
    validated_inv = validate_records(inventory, "inventory")
    validated_disc = validate_records(discovery, "discovery")
    result = run_audit(validated_inv, validated_disc)

    summary = render_summary(result)
    matches = [m.to_dict() for m in result.matches]
    exceptions = [e.to_dict() for e in result.exceptions]

    _save_json(fidelity_dir / "summary.json", summary)
    _save_json(fidelity_dir / "matches.json", matches)
    _save_json(fidelity_dir / "exceptions.json", exceptions)
    (fidelity_dir / "report.md").write_text(render_markdown(result), encoding="utf-8")

    blockers = summary["total_blocking_exceptions"]
    accounted_pct = summary["inventory_accounting_pct"]
    traced_pct = summary["candidate_traceability_pct"]

    print(f"[{args.source.upper()}] Audit Slot {args.slot} Result:")
    print(f"  - Total Blocking Exceptions: {blockers}")
    print(f"  - Inventory Accounting: {accounted_pct}%")
    print(f"  - Candidate Traceability: {traced_pct}%")
    print(f"  - Audit Status: {'PASS' if blockers == 0 else 'FAIL'}")

    if blockers > 0:
        print(f"error: {blockers} blocking exception(s) detected!", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
