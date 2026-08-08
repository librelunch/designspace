"""`sat_solver` corpus fixture.

Exercises choice with ordinal, and ordinal comparisons.

`build_space()` stays byte-identical to its committed known-answer vector.
`.freeze()`-ablation tests live in `test_sat_solver.py`; adding `.anchor()`
calls here would change this fixture's already-frozen `fingerprint_full` and
`to_json`, which the add-never-replace discipline forbids. Anchors are
exercised instead by `tests/conformance/_anchor_demo.py` and its own
committed vector.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


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
