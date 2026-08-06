"""`.anchor()` / `.meta()`: space-level anchors and metadata (API.md,
"Constraints and Feasibility"; deferred past M2 to M8 — see
builder/_space.py, DECISIONS.md D-40).

Anchors are named whole reference configs — the same nested-phenotype
shape `.validate()`/`.sample_dicts()` use — validated against the space
immediately: unlike a param's own `.meta()` (checked later, at resolution,
by `resolve/_pipeline.py::_validate_tags_meta`), `.anchor()`/`Space.meta()`
are post-hoc methods on an *already-resolved* `Space` with no later pass to
defer to, exactly like `.forbid()`/`.require()` validate their conditions
immediately in `resolve/_constraints.py::add_constraints`. An anchor invalid
against the space is error row 22; its message names the anchor key. Row 22
also covers "anchor conflicting with a frozen/sliced value" — raised by
`ops/_structural.py`'s `freeze`/`slice` re-validation, not here.

Anchor *values* are domain-typed configs, not free-form JSON like `.meta()`
values: `space.validate(config)` already enforces every value is a
legitimate (and therefore JSON-representable) domain member, so no separate
`check_meta_json_serializable` pass is needed the way constraint/param meta
needs one.
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
            raise ResolutionError(
                f"anchor {name!r} is invalid against the space ({reasons}) (row 22)"
            )
        merged[name] = config
    return replace(space, anchors=MappingProxyType(merged))


def add_meta(space: Space, mapping: dict[str, Any] | None, kwargs: dict[str, Any]) -> Space:
    merged = dict(space.meta_map)
    if mapping:
        merged.update(mapping)
    merged.update(kwargs)
    check_meta_json_serializable(merged, what="space.meta()")
    return replace(space, meta_map=MappingProxyType(merged))
