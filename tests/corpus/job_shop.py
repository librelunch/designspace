"""`job_shop` corpus fixture.

Exercises permutation and `position_of`.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

JOBS = ("job_a", "job_b", "job_c", "job_d", "job_e")


def build_space() -> Space:
    return ds.space(
        ds.param("schedule").permutation(JOBS),
    ).forbid(
        # job_a (high priority) must not be scheduled after job_e (soft deadline).
        ds.param("schedule").position_of("job_a") > ds.param("schedule").position_of("job_e"),
    )
