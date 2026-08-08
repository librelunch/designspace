"""`delivery_routes` corpus fixture.

Exercises struct lifts, instance paths, per-instance constraints and
aggregates.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

N_LOCATIONS = 10
MAX_STOPS = 5
TOTAL_DWELL_BUDGET_MIN = 90


def build_space() -> Space:
    stop = ds.space(
        ds.param("location").integer(0, N_LOCATIONS - 1),
        ds.param("dwell_min").integer(5, 30),
    ).forbid(
        # The depot, location 0, is a quick stop only. This is a per-instance
        # constraint, instantiated once per stop.
        (ds.param("location") == 0) & (ds.param("dwell_min") > 10),
    )
    return (
        ds.space(
            ds.param("n_stops").integer(1, MAX_STOPS),
            ds.param("stops").space(stop).repeat(ds.param("n_stops")),
        )
        .encourage(
            # Aggregate over the lift.
            ds.param("stops").field("dwell_min").sum() <= TOTAL_DWELL_BUDGET_MIN,
        )
        .forbid(
            # Root-level forbid addressing a fixed instance path: every
            # route starts at the depot (n_stops >= 1, so stops[0] is
            # always in range).
            ds.param("stops[0].location") != 0,
        )
    )
