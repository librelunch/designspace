"""A small induced-representation target for the M11 known-answer digest
vector (PLAN.md M11 gate) — freezes `identity/_tags.py`'s `ChartApply`
codec (Stage 1) the same way `_anchor_demo.py`/`_require_demo.py`/
`_discourage_demo.py` freeze their own M8/M7.5/M7.6 additions.

Not a corpus fixture, not collected by pytest (leading underscore). The
source space mirrors `flat_hpo`'s own shape deliberately (a log-scaled real
plus a plain real, one `.forbid()` and one `.encourage()` each referencing
a chart-bearing param) without importing it, so this file stays a
self-contained fixture like its demo siblings: `build_space()` returns the
*induced representation's target* — an ordinary `Space` whose `.forbid()`/
`.encourage()` expressions carry `ChartApply` nodes wrapping both a plain
and a log-scaled chart, wrapped in `+`/`Compare` (structural transport,
never opaque) — exactly the additive, ChartApply-bearing shape the codec
needs a frozen byte-identical digest for.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space


def _source_space() -> Space:
    return (
        ds.space(
            ds.param("lr").real(1e-5, 1.0).log_scale(),
            ds.param("momentum").real(0.0, 0.99),
        )
        .forbid(ds.param("lr") + ds.param("momentum") > 1.0)
        .encourage(ds.param("momentum") < 0.95, tags=("stability",))
    )


def build_space() -> Space:
    return _source_space().represent().target
