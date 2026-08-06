"""A small `discourage`/`encourage`-using space for the M7.6 known-answer
digest vector (PLAN.md M7.6: the new `origin="discourage"` frozen-format value
gets a committed KA vector).

Not a corpus fixture, not collected by pytest (leading underscore) — parallels
`_require_demo`. It locks the soft polarity pair: `encourage` (origin `"user"`,
byte-identical to the old `constrain`) and `discourage` (the new
`origin="discourage"`, canonicalized to `Not(e)` in the preimage).
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


def build_space() -> Space:
    return (
        ds.space(
            ds.param("x").real(0.0, 1.0),
            ds.param("k").integer(0, 10),
        )
        .encourage(ds.param("x") >= 0.5)
        .discourage(ds.param("k") > 8)
    )
