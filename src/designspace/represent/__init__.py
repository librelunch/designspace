"""represent/: the Representation Layer (API.md, "The Representation
Layer"; "Protocols" — `Encoding`; "IR" — `Representation`; M11).

A genotype **is** a `Space`; a `Representation` is the `Space → Space`
morphism between one and its phenotype, carrying a value-level `decode`/
`encode` pair. `_protocol.py` defines the per-param `Encoding` arrow;
`_representation.py` the whole-space morphism, `then`, and `check()`;
`_charts.py` the one representation core ships (the induced chart
representation); `_transport.py` the expression rewriting that keeps
conditions/constraints meaningful in the target; `_build.py` the
`space.represent(*rules)` dispatcher these all feed. `Space.represent()`
(`build/_space.py`) is the only builder-facing entry point — everything
here is otherwise reached through the `Representation`/`Encoding` objects
`designspace/__init__.py` re-exports.
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
from designspace.represent._representation import Representation

__all__ = [
    "Encoding",
    "EncodingRule",
    "Representation",
    "can_encode",
    "has_decode_expr",
    "has_prop_expr",
    "has_rewrite",
    "is_measure_preserving",
]
