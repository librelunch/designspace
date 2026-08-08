"""`memetic_pipeline` corpus fixture.

Exercises a lifted choice, `count_of`, and list element forms, with bare
variant strings alongside parameterized ones in one list.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

MIN_OPS = 2
MAX_OPS = 6


def build_space() -> Space:
    pipeline = (
        ds.param("pipeline")
        .choice(
            "shuffle",
            "crossover",
            mutation=ds.space(ds.param("rate").real(0.01, 0.5)),
            local_search=ds.space(ds.param("iters").integer(1, 100)),
        )
        .repeat(ds.param("n_ops"))
    )
    return ds.space(
        ds.param("n_ops").integer(MIN_OPS, MAX_OPS),
        pipeline,
    ).forbid(
        # Every pipeline needs at least one local-search step.
        ds.param("pipeline").count_of("local_search") < 1,
    )
