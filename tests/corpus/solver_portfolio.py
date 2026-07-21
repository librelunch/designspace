"""`solver_portfolio` corpus fixture (PLAN.md.md corpus table, M4).

Exercises: bool + `ds.count()`, `if_inactive`, inactive-vs-empty (the
spec's own worked example pattern, API.md "Three-valued semantics"
lines 295-298).
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space

SOLVERS = ("cplex", "gurobi", "glpk", "heuristic")
MAX_WORKERS = 8
TOTAL_TIMEOUT_BUDGET_S = 7200


def build_space() -> Space:
    solver_flags = tuple(ds.param(f"use_{name}").bool() for name in SOLVERS)
    worker = ds.space(ds.param("timeout_s").integer(1, 3600))
    return (
        ds.space(
            *solver_flags,
            ds.param("use_ensemble").bool(),
            ds.param("n_workers").integer(0, MAX_WORKERS),
            ds.param("workers").space(worker).repeat(ds.param("n_workers")).when(
                ds.param("use_ensemble")
            ),
        )
        .forbid(
            # At least one solver must be enabled — a forbid (feasibility),
            # so the reference sampler actually respects it.
            ds.count(*solver_flags) < 1,
        )
        .forbid(
            # `use_ensemble` inactive -> `workers` inactive -> `.sum()` is
            # Unknown -> `.if_inactive(0)` coalesces it -> forbid never
            # fires from the "no ensemble" branch. `use_ensemble` active
            # with `n_workers == 0` -> `workers` is an *active empty*
            # list -> `.sum() == 0` -> `.if_inactive` is a no-op -> still
            # never fires. Only an active, non-empty, over-budget worker
            # pool trips it.
            ds.param("workers").field("timeout_s").sum().if_inactive(0) > TOTAL_TIMEOUT_BUDGET_S,
        )
    )
