"""`.fingerprint()` (API.md, "fingerprint()"): a stable identifier of the
resolved space — post-resolution IR, never builder expressions.

Output: `"{version}:{scope}:{64 hex chars}"`. The format version and the
scope string are both part of the hashed preimage (not just the human-
readable prefix) — the scope table lists "Format version" as a preimage row
in both scopes, and folding `scope` in too is free, extra-safe hygiene (it
already disambiguates `full` vs `sampling` digests that would otherwise only
differ by coincidence of content).

Only `"raise"`/`"mark"` are offered for `on_unserializable` here — unlike
`to_json`, whose "drop" mode returns a document plus a manifest the caller
can inspect, `fingerprint` returns nothing but a hash: a silently-dropped
site would vanish from the digest with no visible trace, which is strictly
worse than "mark"'s explicit, distinguishing sentinel. The spec's own
"Callables" paragraph under `fingerprint()` only ever mentions raise/mark.
"""

from __future__ import annotations

from typing import Any, Literal

from designspace.build._space import Space
from designspace.identity._ir_codec import (
    EncodeContext,
    encode_anchors,
    encode_condition,
    encode_constraint,
    encode_param,
    encode_space_meta,
)
from designspace.identity._jcs import canonical_digest
from designspace.resolve._pipeline import check_fully_resolved
from designspace.serialize._version import FORMAT_VERSION

FingerprintScope = Literal["full", "sampling"]
"""Which facts a fingerprint covers.

`"full"` is document identity: params, conditions, hard constraints,
declared constraints, defaults, tags, meta, and anchors. `"sampling"`
narrows to what fixes the feasible set, the sampling measure, and chart
geometry. It is the scope to compare when transferring a warm start or a
surrogate, so two spaces differing only in tags, meta, defaults, anchors, or
declared constraints agree at `"sampling"` and differ at `"full"`.
"""

FingerprintUnserializable = Literal["raise", "mark"]
"""What `Space.fingerprint` does with a callable it cannot serialize.

The same meanings as `OnUnserializable`, minus `"drop"`: dropping a site
would silently change what is being identified, which is the one thing a
fingerprint may not do.
"""

_VALID_SCOPES = ("full", "sampling")
_VALID_MODES = ("raise", "mark")


def fingerprint(
    space: Space,
    scope: FingerprintScope = "full",
    on_unserializable: FingerprintUnserializable = "raise",
) -> str:
    if scope not in _VALID_SCOPES:
        raise TypeError(f"fingerprint(): scope must be 'full' or 'sampling', got {scope!r}")
    if on_unserializable not in _VALID_MODES:
        raise TypeError(
            f"fingerprint(): on_unserializable must be 'raise' or 'mark', got {on_unserializable!r}"
        )
    check_fully_resolved(space)
    ctx = EncodeContext(mode=on_unserializable)
    tree: dict[str, Any] = {
        "version": FORMAT_VERSION,
        "scope": scope,
        "params": [encode_param(pd, scope, ctx) for pd in space.params.values()],
        "conditions": [encode_condition(c, ctx) for c in space.conditions],
        "constraints": [
            encoded
            for i, c in enumerate(space.constraints)
            if (encoded := encode_constraint(c, scope, ctx, site=f"constraint {i}")) is not None
        ],
    }
    # Anchors/meta are `full`-scope only (API.md's scope table) and omitted
    # entirely when empty, so an anchor/meta-free space's preimage is
    # byte-identical whether or not this branch exists.
    if scope != "sampling":
        anchors_tree = encode_anchors(space.anchors)
        if anchors_tree is not None:
            tree["anchors"] = anchors_tree
        meta_tree = encode_space_meta(space.meta_map)
        if meta_tree is not None:
            tree["meta"] = meta_tree
    digest = canonical_digest(tree)
    return f"{FORMAT_VERSION}:{scope}:{digest}"
