"""`.fingerprint()`: a stable identifier of the resolved space.

See API.md, "fingerprint()". The identifier is computed over the
post-resolution IR and never over builder expressions.

The output is `"{version}:{scope}:{64 hex chars}"`. Both the format version
and the scope string belong to the hashed preimage rather than to the
human-readable prefix alone. The scope table lists "Format version" as a
preimage row in both scopes, and folding `scope` in as well costs nothing
and disambiguates `full` from `sampling` digests that would otherwise differ
only by coincidence of content.

`on_unserializable` accepts `"raise"` and `"mark"` here, not `"drop"`.
`to_json`'s drop mode returns a document plus a manifest the caller can
inspect, whereas `fingerprint` returns a hash alone, so a silently dropped
site would vanish from the digest with no visible trace. The spec's
"Callables" paragraph under `fingerprint()` mentions raise and mark only.
"""

from __future__ import annotations

from typing import Any, Literal

from designspace.builder._space import Space
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
