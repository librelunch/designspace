"""`sat_solver` corpus fixture (PLAN.md.md corpus table, added
M3).

Exercises: choice+ordinal, ordinal comparisons. Anchors are out of M3's
scope (see DECISIONS.md) — this fixture gains `.anchor()` calls whenever
that milestone lands; "freeze asserts at M8" in the plan's corpus table
refers to `.freeze()`-ablation tests added then, not anchors.
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
        .constrain(
            ds.param("verbosity") > "silent",
            tags=("observability",),
        )
    )
