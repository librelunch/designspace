"""`flow_chemistry` corpus fixture (PLAN.md corpus table,
added M3).

Exercises: subset inclusion priors, `contains`, `sum_over`, implications.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

REAGENTS = ("acid", "base", "catalyst", "solvent", "oxidizer")
COSTS = {"acid": 2.0, "base": 1.5, "catalyst": 10.0, "solvent": 0.5, "oxidizer": 3.0}


def build_space() -> Space:
    # A `.forbid()` predicate names the *forbidden* (bad) state (D-4), so
    # "oxidizer implies acid" is enforced by forbidding its negation
    # (oxidizer present, acid absent) -- not by forbidding the implication
    # itself, which would forbid the *desired* state instead.
    return (
        ds.space(
            ds.param("reagents")
            .subset(REAGENTS, min_size=1, max_size=4)
            .prior(weights=[0.8, 0.8, 0.3, 0.9, 0.4]),
            ds.param("temperature_c").real(0.0, 200.0),
        )
        .forbid(
            ds.param("reagents").contains("oxidizer") & ~ds.param("reagents").contains("acid"),
        )
        .forbid(
            ds.param("reagents").contains("catalyst") & (ds.param("temperature_c") <= 50.0),
        )
        .encourage(
            ds.param("reagents").sum_over(COSTS) <= 15.0,
            tags=("budget",),
        )
    )
