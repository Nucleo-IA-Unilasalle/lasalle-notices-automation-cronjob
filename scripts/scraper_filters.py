"""Edital filename/URL prefilter and diagnostic message builder.

Ports the EDITAL inclusion/exclusion patterns, ``is_likely_edital``
URL/filename filter, and ``build_diagnostic_message`` helper from
``lasalle-notices-automation/app/services/scraper/types.py`` (lines
74-95) and ``app/services/scraper/ingestion.py`` (lines 38-50) into
the cronjob. The cronjob only needs the URL/filename filter; the
DB-coupled ``is_known_pdf_url`` / ``_save_edital_metadata`` paths are
intentionally omitted.
"""

from __future__ import annotations

import re
from typing import Literal, NotRequired, TypedDict


FilterPolicy = Literal["default", "include_tdr", "no_prefilter"]

VALID_FILTER_POLICIES = frozenset({"default", "include_tdr", "no_prefilter"})

EDITAL_INCLUSION_PATTERNS = [
    r"edital", r"chamada", r"convocatoria", r"selecao", r"processo.?seletivo",
    r"financiamento", r"fomento", r"bolsas?", r"auxilio", r"proposta",
]
EDITAL_EXCLUSION_PATTERNS = [
    r"relatorio", r"resultado", r"lista.?de", r"manual", r"instrucao",
    r"modelo.?de", r"formulario", r"termo.?de.?referencia", r"ata.?de",
    r"retificacao", r"errata",
    r"credenciamento.?(de.?(fornecedor|jornalista|banco))",
]
TDR_PATTERN = r"termo.?de.?referencia"


class DiagnosticMessage(TypedDict):
    source: str
    url: str
    kind: str
    reason: str
    status_code: NotRequired[int]


def resolve_filter_policy(filter_policy: FilterPolicy) -> tuple[bool, list[str]]:
    if filter_policy not in VALID_FILTER_POLICIES:
        raise ValueError(f"Unknown filter_policy: {filter_policy}")
    if filter_policy == "no_prefilter":
        return False, EDITAL_EXCLUSION_PATTERNS
    if filter_policy == "include_tdr":
        return True, [pattern for pattern in EDITAL_EXCLUSION_PATTERNS if pattern != TDR_PATTERN]
    return True, EDITAL_EXCLUSION_PATTERNS


def is_likely_edital(filename: str, url: str, filter_policy: FilterPolicy = "default") -> bool:
    text = f"{filename} {url}".lower()
    text = text.replace("á", "a").replace("é", "e").replace("í", "i")
    text = text.replace("ó", "o").replace("ú", "u").replace("ã", "a")
    text = text.replace("õ", "o").replace("ç", "c")
    should_prefilter, exclusion_patterns = resolve_filter_policy(filter_policy)
    if not should_prefilter:
        return True
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in exclusion_patterns):
        return False
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in EDITAL_INCLUSION_PATTERNS):
        return True
    return True


def build_diagnostic_message(
    *,
    source_name: str,
    listing_url: str,
    reason: str,
    status_code: int | None = None,
) -> DiagnosticMessage:
    message: DiagnosticMessage = {
        "source": source_name,
        "url": listing_url,
        "kind": "diagnostic",
        "reason": reason,
    }
    if status_code is not None:
        message["status_code"] = status_code
    return message
