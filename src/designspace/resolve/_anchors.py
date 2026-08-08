"""`.anchor()` and `Space.meta()`: space-level anchors and metadata (API.md,
"Constraints and Feasibility").

An anchor is a named whole reference configuration, in the same nested
phenotype shape `.validate()` and `.sample_dicts()` use. Both methods act on
an already-resolved `Space` and so validate immediately: there is no later
pass to defer to, which is how `add_constraints` in
`resolve/_constraints.py` treats a `.forbid()` or `.require()` condition. A
param's own `.meta()` is checked later, at resolution, by
`_validate_tags_meta` in `resolve/_pipeline.py`.

An anchor invalid against the space is error row 22, and the message names
the anchor key. Row 22 also covers an anchor conflicting with a frozen or
sliced value, which `ops/_structural.py` raises from its `freeze`/`slice`
re-validation rather than here.

Anchor values are domain-typed configurations rather than free-form JSON.
`space.validate(config)` already requires every value to be a domain member,
and therefore JSON-representable, so anchors need no separate
`check_meta_json_serializable` pass of the kind constraint and param
metadata need.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

from designspace.builder._names import check_meta_json_serializable
from designspace.builder._space import Space
from designspace.errors import ResolutionError


def add_anchors(space: Space, configs: dict[str, dict[str, Any]]) -> Space:
    merged = dict(space.anchors)
    for name, config in configs.items():
        result = space.validate(config)
        if not result.valid:
            reasons = "; ".join(f"{e.param!r}: {e.reason}" for e in result.param_errors)
            if not reasons:
                reasons = "a declared constraint is violated"
            raise ResolutionError(f"anchor {name!r} is invalid against the space ({reasons})")
        merged[name] = config
    return replace(space, anchors=MappingProxyType(merged))


def add_meta(space: Space, mapping: dict[str, Any] | None, kwargs: dict[str, Any]) -> Space:
    merged = dict(space.meta_map)
    if mapping:
        merged.update(mapping)
    merged.update(kwargs)
    check_meta_json_serializable(merged, what="space.meta()")
    return replace(space, meta_map=MappingProxyType(merged))
