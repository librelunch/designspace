"""A small `discourage` and `encourage` space, for a known-answer digest vector.

The frozen format carries `origin="discourage"`, and this fixture is what
locks it. Not a corpus fixture, and not collected by pytest, parallel to
`_require_demo.py`.
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
