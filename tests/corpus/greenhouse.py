"""`greenhouse` corpus fixture.

Exercises choice, nested values and the defaults cascade.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


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
