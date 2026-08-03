"""`firmware_buffers` corpus fixture (PLAN.md corpus table, M5).

Exercises: expression bounds, envelopes, bound-origin margins. Three ring
buffers are carved out of a fixed RAM budget in sequence — each buffer's
capacity is bounded above by whatever the previous ones left behind, a
chained dependency along the resolution's bound-envelope DAG (`total_ram`,
then `buf_a`, then `buf_b`, then `buf_c`).
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space

TOTAL_LO = 4096
TOTAL_HI = 65536


def build_space() -> Space:
    return ds.space(
        ds.param("total_ram").integer(TOTAL_LO, TOTAL_HI),
        ds.param("buf_a").integer(1, ds.param("total_ram")),
        ds.param("buf_b").integer(1, ds.param("total_ram") - ds.param("buf_a")),
        ds.param("buf_c").integer(0, ds.param("buf_b") - 1),
    ).encourage(
        # Declared, not feasibility-affecting: flags configs that leave no
        # headroom at all for a 4th, not-yet-modeled buffer.
        ds.param("total_ram") - ds.param("buf_a") - ds.param("buf_b") - ds.param("buf_c") >= 1,
        tags=("headroom",),
    )
