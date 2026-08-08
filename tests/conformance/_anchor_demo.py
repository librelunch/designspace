"""A small `.anchor()` and `.meta()` space, for a known-answer digest vector.

Not a corpus fixture, and not collected by pytest, its name leading with an
underscore. It parallels `_require_demo.py` and `_discourage_demo.py`, and
is kept apart from `tests/corpus/sat_solver.py` deliberately: adding anchors
to that already-frozen fixture would change its committed vector, which the
add-never-replace discipline forbids.

It exercises two named anchors, sorted by key in the preimage, and one
space-level `.meta()` call carrying both a scalar and a nested-dict value,
which locks the recursive type-tagging codec anchors and metadata share with
`default` and `ParamDef.meta`.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


def build_space() -> Space:
    return (
        ds.space(
            ds.param("x").real(0.0, 1.0),
            ds.param("mode").categorical("fast", "accurate"),
        )
        .anchor(
            {
                "baseline": {"x": 0.5, "mode": "fast"},
                "best_known": {"x": 0.9, "mode": "accurate"},
            }
        )
        .meta(objective="minimize_latency", cost_model={"fast": 1, "accurate": 4})
    )
