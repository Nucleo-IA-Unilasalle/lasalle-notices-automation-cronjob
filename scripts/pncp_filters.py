"""Module-level configuration for PNCP candidate discovery.

This file is the single source of truth for the PNCP filter behavior used by
``scripts/discover_pncp_candidates.py``. Editing the values below requires a
code change; there is no environment variable override.

The values are public configuration (UF sigla and public federal agency CNPJs)
and are not sensitive.
"""

from __future__ import annotations

UF_FILTER = "RS"

FEDERAL_CNPJS: tuple[str, ...] = (
    "33654831000136",
    "00889834000165",
    "00394494000136",
    "37115375000107",
)

DROP_EXPIRED = True
