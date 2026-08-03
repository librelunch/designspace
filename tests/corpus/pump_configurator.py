"""`pump_configurator` corpus fixture (PLAN.md corpus table, M6).

Exercises: the driver loop — `next_assignable` + `remaining_domain`. A
bound-origin coupling (`impeller_diameter_mm` <= `flow_rate_lpm`, `max_pressure_bar`
<= `num_stages * 10`), a single-forbid value exclusion (`seal_type != "packing"`),
and a subset with a `contains`-forbid (reducible) alongside a compound
seal/cert forbid (deliberately *not* one-unset-operand reducible — the
descriptor stays sound, not complete, for that coupling).
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space

CERTIFICATIONS = ("CE", "UL", "ATEX")


def build_space() -> Space:
    return (
        ds.space(
            ds.param("flow_rate_lpm").real(100.0, 500.0),
            ds.param("impeller_diameter_mm").real(20.0, ds.param("flow_rate_lpm")),
            ds.param("num_stages").integer(1, 5),
            ds.param("max_pressure_bar").real(1.0, ds.param("num_stages") * 10.0),
            ds.param("seal_type").categorical("mechanical", "packing", "magnetic"),
            ds.param("certifications").subset(CERTIFICATIONS, min_size=0, max_size=3),
        )
        .forbid(
            # Packing seals are discontinued in this catalog -- a single
            # unset-bare-operand exclusion, reducible by remaining_domain.
            ds.param("seal_type") == "packing",
        )
        .forbid(
            # Magnetic seals aren't ATEX-rated -- a *compound* coupling
            # across two params, deliberately left unreduced (the
            # one-unset-operand guarantee doesn't cover it).
            (ds.param("seal_type") == "magnetic") & ds.param("certifications").contains("ATEX"),
        )
    )
