"""`Space.from_json()` (API_v3.md, "to_json / from_json"): reconstructs the
resolved IR directly (no builder replay) and rebuilds every chart via
`charts.build_chart` — charts are derived, never stored, so the round-trip
law (`from_json(to_json(s)).fingerprint() == s.fingerprint()`) holds simply
because both sides compute the same charts from the same domain/prior/
quantized facts.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

from designspace.build._space import Space
from designspace.charts import build_chart
from designspace.errors import SerializationError
from designspace.identity._ir_codec import decode_condition, decode_constraint, decode_param
from designspace.ir import ListDomain, ParamDef
from designspace.resolve._pipeline import check_fully_resolved
from designspace.serialize._version import FORMAT_VERSION


def _rebuild_list_domain_charts(path: str, domain: ListDomain) -> ListDomain:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return replace(
            domain, element_domain=_rebuild_list_domain_charts(path, domain.element_domain)
        )
    element_chart = (
        build_chart(
            path, domain.element_kind, domain.element_domain, domain.element_prior,
            domain.element_quantized,
        )
        if domain.element_kind in ("real", "integer")
        else None
    )
    return replace(domain, element_chart=element_chart)


def _rebuild_charts(pd: ParamDef) -> ParamDef:
    if pd.type_kind == "list":
        assert isinstance(pd.domain, ListDomain)
        return replace(pd, domain=_rebuild_list_domain_charts(pd.path, pd.domain))
    chart = build_chart(pd.path, pd.type_kind, pd.domain, pd.prior, pd.quantized)
    return replace(pd, chart=chart)


def from_json(data: dict[str, Any], custom_types: dict[str, Any] | None = None) -> Space:
    # `custom_types` is part of the spec's `from_json` signature (registry
    # mapping `type_key -> factory` for custom params) but no document can
    # currently contain a custom-type entry — no builder surface for
    # `.custom()` exists before M9. Accepted now for signature fidelity;
    # consulted starting M9.
    version = data.get("version")
    if version != FORMAT_VERSION:
        raise SerializationError(
            f"unknown format version {version!r}; this designspace build supports "
            f"version {FORMAT_VERSION}"
        )
    params: dict[str, ParamDef] = {}
    for entry in data["params"]:
        pd = _rebuild_charts(decode_param(entry))
        params[pd.path] = pd
    conditions = tuple(decode_condition(c) for c in data.get("conditions", ()))
    constraints = tuple(decode_constraint(c) for c in data.get("constraints", ()))
    space = Space(params=MappingProxyType(params), conditions=conditions, constraints=constraints)
    check_fully_resolved(space)
    return space
