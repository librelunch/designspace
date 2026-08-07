"""represent: the Representation Layer.

See API.md, "The Representation Layer", "Protocols" for `Encoding` and "IR"
for `Representation`.

A genotype is a `Space`, and a `Representation` is the `Space -> Space`
morphism between one and its phenotype, carrying a value-level `decode` and
`encode` pair. The modules divide as follows:

- `_protocol.py` defines the per-param `Encoding` arrow.
- `_representation.py` defines the whole-space morphism, `then` and
  `check()`.
- `_charts.py` holds the one representation core ships, the induced chart
  representation.
- `_transport.py` holds the expression rewriting that keeps conditions and
  constraints meaningful in the target.
- `_build.py` holds the `space.represent(*rules)` dispatcher the rest feed.

`Space.represent()` in `builder/_space.py` is the only builder-facing entry
point. Everything else here is reached through the `Representation` and
`Encoding` objects `designspace/__init__.py` re-exports.
"""

from designspace.represent._protocol import (
    Encoding,
    EncodingRule,
    can_encode,
    has_decode_expr,
    has_prop_expr,
    has_rewrite,
    is_measure_preserving,
)
from designspace.represent._representation import Config, Representation

__all__ = [
    "Config",
    "Encoding",
    "EncodingRule",
    "Representation",
    "can_encode",
    "has_decode_expr",
    "has_prop_expr",
    "has_rewrite",
    "is_measure_preserving",
]
