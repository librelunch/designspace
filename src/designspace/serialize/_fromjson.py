"""`Space.from_json()` (API_v3.md, "to_json / from_json"): reconstructs the
resolved IR directly (no builder replay) and rebuilds every chart via
`resolve.rebuild_charts` (which calls `charts.build_chart`) — charts are
derived, never stored, so the round-trip law
(`from_json(to_json(s)).fingerprint() == s.fingerprint()`) holds simply
because both sides compute the same charts from the same domain/prior/
quantized facts. `rebuild_charts` is shared with `meta/_meta.py::
space_from_ir` (M8), another route that assembles a `Space` from raw
`ParamDef`s with no chart of their own to trust.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from designspace.build._space import Space
from designspace.errors import SerializationError
from designspace.identity._ir_codec import (
    decode_anchors,
    decode_condition,
    decode_constraint,
    decode_param,
    decode_space_meta,
)
from designspace.ir import ParamDef
from designspace.resolve import check_fully_resolved, rebuild_charts
from designspace.serialize._version import FORMAT_VERSION


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
        pd = rebuild_charts(decode_param(entry))
        params[pd.path] = pd
    conditions = tuple(decode_condition(c) for c in data.get("conditions", ()))
    constraints = tuple(decode_constraint(c) for c in data.get("constraints", ()))
    anchors = decode_anchors(data.get("anchors"))
    meta = decode_space_meta(data.get("meta"))
    space = Space(
        params=MappingProxyType(params),
        conditions=conditions,
        constraints=constraints,
        anchors=anchors,
        meta_map=meta,
    )
    check_fully_resolved(space)
    return space
