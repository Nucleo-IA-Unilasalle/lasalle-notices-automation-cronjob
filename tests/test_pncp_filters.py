from __future__ import annotations

import pncp_filters


def test_pncp_filter_scope_defaults_are_explicit_and_safe() -> None:
    assert pncp_filters.UF_FILTER == "RS"
    assert pncp_filters.FEDERAL_CNPJS
    assert all(len(cnpj) == 14 and cnpj.isdigit() for cnpj in pncp_filters.FEDERAL_CNPJS)
    assert pncp_filters.DROP_EXPIRED is True
