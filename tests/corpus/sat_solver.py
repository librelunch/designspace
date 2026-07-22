"""`sat_solver` corpus fixture (PLAN.md.md corpus table, added
M3).

Exercises: choice+ordinal, ordinal comparisons. `build_space()` stays
byte-identical to its M7 committed known-answer vector (DECISIONS.md D-40):
"freeze asserts at M8" in the plan's corpus table means `.freeze()`-ablation
tests added to `test_sat_solver.py` at M8, not anchors added here — adding
`.anchor()` calls to this fixture would change its already-frozen
`fingerprint_full`/`to_json`, which the "add — never replace — known-answer
vectors" discipline forbids. Anchors are exercised instead by
`tests/conformance/_anchor_demo.py`'s own, separately committed vector.
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space


def build_space() -> Space:
    return (
        ds.space(
            ds.param("solver").choice(
                "dpll",
                cdcl=ds.space(
                    ds.param("restart_strategy").categorical("luby", "geometric"),
                ),
            ),
            ds.param("verbosity").ordinal("silent", "normal", "verbose", "debug"),
            ds.param("timeout_s").integer(1, 3600),
        )
        .forbid(
            (ds.param("verbosity") >= "debug") & (ds.param("timeout_s") < 60),
        )
        .encourage(
            ds.param("verbosity") > "silent",
            tags=("observability",),
        )
    )
