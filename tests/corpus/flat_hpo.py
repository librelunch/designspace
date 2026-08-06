"""`flat_hpo` corpus fixture (PLAN.md corpus table, added M2).

Exercises: reals/ints/categorical, log_scale, quantized, `when`, forbid
margins. Reused end-to-end by every milestone from here on (round-trip
joins once serialization exists, M7).
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


def build_space() -> Space:
    return (
        ds.space(
            ds.param("lr").real(1e-5, 1.0).log_scale(),
            ds.param("momentum").real(0.0, 0.99),
            ds.param("weight_decay").real(1e-6, 1e-2).log_scale().quantized(factor=2.0),
            ds.param("n_layers").integer(1, 8),
            ds.param("batch_size").integer(16, 512).quantized(step=16),
            ds.param("optimizer").categorical("sgd", "adam", "rmsprop"),
            ds.param("nesterov").bool().when(ds.param("optimizer") == "sgd"),
        )
        .forbid(
            ds.param("lr") > 0.5,
        )
        .encourage(
            ds.param("momentum") < 0.95,
            tags=("stability",),
        )
    )
