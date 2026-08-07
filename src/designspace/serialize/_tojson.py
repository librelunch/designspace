"""`.to_json()` (API.md, "to_json / from_json"): the full-IR document."""

from __future__ import annotations

from typing import Any

from designspace.builder._space import Space
from designspace.identity._ir_codec import (
    EncodeContext,
    OnUnserializable,
    encode_anchors,
    encode_condition,
    encode_constraint,
    encode_param,
    encode_space_meta,
)
from designspace.resolve._pipeline import check_fully_resolved
from designspace.serialize._version import FORMAT_VERSION

_VALID_MODES = ("raise", "mark", "drop")


def to_json(space: Space, on_unserializable: OnUnserializable = "raise") -> dict[str, Any]:
    if on_unserializable not in _VALID_MODES:
        raise TypeError(
            f"to_json(): on_unserializable must be 'raise', 'mark', or 'drop', "
            f"got {on_unserializable!r}"
        )
    check_fully_resolved(space)
    ctx = EncodeContext(mode=on_unserializable)
    doc: dict[str, Any] = {
        "version": FORMAT_VERSION,
        "params": [encode_param(pd, "document", ctx) for pd in space.params.values()],
        "conditions": [encode_condition(c, ctx) for c in space.conditions],
        "constraints": [
            encode_constraint(c, "document", ctx, site=f"constraint {i}")
            for i, c in enumerate(space.constraints)
        ],
    }
    anchors_tree = encode_anchors(space.anchors)
    if anchors_tree is not None:
        doc["anchors"] = anchors_tree
    meta_tree = encode_space_meta(space.meta_map)
    if meta_tree is not None:
        doc["meta"] = meta_tree
    if ctx.dropped:
        # "the reconstructed space is a *different* space by design", so
        # the manifest names exactly which sites were omitted.
        doc["dropped"] = list(ctx.dropped)
    return doc
