"""A small `require`-using space for the M7.5 known-answer digest vector
(PLAN.md M7.5 gate: "new `require` KA vectors committed").

Deliberately **not** a corpus fixture (no design-history provenance) and
**not collected by pytest** (leading underscore, no `test_`/`Test` names):
it exists only so `tests/conformance/vectors/require_demo.json` has a stable
builder, kept apart from `tests/corpus/` so the "all corpus vectors stay
byte-identical" check stays clean. It exercises the `require` fingerprint
canonicalization on both a bare `Compare` (whole-expression negation of
`x <= y`) and a composite `BoolOp` (`~(a & b)`), the two shapes the
`Not`-wrap must handle.
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space


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
