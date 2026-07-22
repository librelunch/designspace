"""A small `.anchor()`/`.meta()`-using space for the M8 known-answer digest
vector (PLAN.md M8 gate; DECISIONS.md D-40).

Not a corpus fixture, not collected by pytest (leading underscore) —
parallels `_require_demo.py`/`_discourage_demo.py`. Kept apart from
`tests/corpus/sat_solver.py` deliberately: adding anchors to that
already-frozen fixture would change its committed KA vector, which the
"add — never replace" discipline forbids (D-40). Exercises two named
anchors (sorted by key in the preimage) and a space-level `.meta()` call
with both a scalar and a nested-dict value, to lock the recursive
type-tagging codec anchors/meta share with `default`/`ParamDef.meta`.
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space


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
