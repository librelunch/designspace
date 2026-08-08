"""A small `require`-using space, for a known-answer digest vector.

Deliberately not a corpus fixture, having no design-history provenance, and
not collected by pytest, its name leading with an underscore and carrying no
`test_` or `Test` names. It exists so that
`tests/conformance/vectors/require_demo.json` has a stable builder, kept
apart from `tests/corpus/` so that the check that every corpus vector stays
byte-identical stays clean.

It exercises the `require` fingerprint canonicalization on both a bare
`Compare`, the whole-expression negation of `x <= y`, and a composite
`BoolOp`, `~(a & b)`. Those are the two shapes the `Not` wrap must handle.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


def build_space() -> Space:
    return (
        ds.space(
            ds.param("x").real(0.0, 1.0),
            ds.param("y").real(0.0, 1.0),
            ds.param("k").integer(0, 10),
        )
        .require(ds.param("x") <= ds.param("y"))
        .require((ds.param("k") >= 2) & (ds.param("k") <= 8))
    )
