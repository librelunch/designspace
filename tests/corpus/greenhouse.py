"""`greenhouse` corpus fixture (IMPLEMENTATION_PLAN.md corpus table, added M3).

Exercises: choice, nested values, defaults cascade (`.default()` accepted
and resolution-validated since M1; `apply_defaults()` itself is M6 — see
PROGRESS.md/DECISIONS.md for the same pattern this fixture's forbears use).
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space


def build_space() -> Space:
    return ds.space(
        ds.param("heating").choice(
            "electric",
            gas=ds.space(
                ds.param("burner_power_kw").real(5.0, 50.0),
                ds.param("pilot_light").bool().default(True),
            ),
        ),
        ds.param("target_temp_c").real(10.0, 35.0).default(21.0),
        ds.param("humidity_control").choice(
            "off",
            active=ds.space(
                ds.param("target_humidity_pct").real(30.0, 90.0),
            ),
        ),
        ds.param("zone").space(
            ds.param("area_m2").real(1.0, 1000.0),
            ds.param("shade_cloth").bool(),
        ),
    )
