"""A small induced-representation target, for a known-answer digest vector.

It freezes the `ChartApply` codec in `identity/_tags.py`, as
`_anchor_demo.py`, `_require_demo.py` and `_discourage_demo.py` freeze their
own additions. Not a corpus fixture, and not collected by pytest.

The source space mirrors `flat_hpo`'s shape deliberately, carrying a
log-scaled real, a plain real, and one `.forbid()` and one `.encourage()`
each referencing a chart-bearing param, without importing it, so that this
file stays self-contained like its demo siblings.

`build_space()` returns the induced representation's target: an ordinary
`Space` whose `.forbid()` and `.encourage()` expressions carry `ChartApply`
nodes wrapping both a plain and a log-scaled chart, inside `+` and `Compare`
so transport is structural rather than opaque.
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
