"""Quantization grid math (API.md, "Charts" > "Quantization").

Shared by chart construction (charts/_quantized.py builds the continuous
chart over the grid's extension) and by validate/ (grid membership and
canonicalization use the same `k = round((v - lo) / step)` recovery).

Grid points are `g_k = lo + k*step` (linear) or `g_k = lo * factor**k`
(geometric), `k = 0..K`. `K` is the greatest index with `g_K <= hi`, except
the degenerate case `step >= hi - lo` (or its geometric analogue
`factor >= hi/lo`), which collapses to the single point `{lo}` (K=0) even
though a literal g_1 might coincide with `hi`. API.md's Degeneracy Table
states this as a `{lo}`-only outcome rather than a coincidental two-point
grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_DEFAULT_RTOL = 1e-9
_K_EPS = 1e-9


def _isclose(a: float, b: float, rtol: float) -> bool:
    return abs(a - b) <= rtol * max(1.0, abs(a), abs(b))


@dataclass(frozen=True)
class GridShape:
    """A resolved grid: regular points `0..K`, plus an optional appended `hi`.

    `extension_top` is the exclusive upper bound of the continuous chart
    built to floor values onto this grid (API.md: "chart built over the
    extension `[g_0, g_K + cell)`").
    """

    lo: float
    step: float | None
    factor: float | None
    K: int
    has_extra_hi: bool
    hi: float
    extension_top: float


def grid_point(lo: float, step: float | None, factor: float | None, k: int) -> float:
    if step is not None:
        return lo + k * step
    assert factor is not None
    return lo * factor**k


def _cell_width(lo: float, step: float | None, factor: float | None, k: int) -> float:
    if step is not None:
        return step
    assert factor is not None
    return grid_point(lo, step, factor, k) * (factor - 1)


def build_grid_shape(
    lo: float, hi: float, step: float | None, factor: float | None, include_hi: bool
) -> GridShape:
    if step is not None:
        degenerate = step >= hi - lo
        raw_k = 0.0 if degenerate else (hi - lo) / step
    else:
        assert factor is not None
        degenerate = factor >= hi / lo
        raw_k = 0.0 if degenerate else math.log(hi / lo) / math.log(factor)
    k = 0 if degenerate else math.floor(raw_k + _K_EPS)
    g_k = grid_point(lo, step, factor, k)
    cell = _cell_width(lo, step, factor, k)

    has_extra_hi = include_hi and hi > g_k + _DEFAULT_RTOL * max(1.0, abs(hi))
    if has_extra_hi:
        extra_cell = step if step is not None else hi * (factor - 1) if factor is not None else 0.0
        extension_top = hi + extra_cell
    else:
        extension_top = g_k + cell

    return GridShape(
        lo=lo,
        step=step,
        factor=factor,
        K=k,
        has_extra_hi=has_extra_hi,
        hi=hi,
        extension_top=extension_top,
    )


def floor_to_grid(shape: GridShape, x: float) -> float:
    """Greatest grid point <= x ("emitted value = greatest grid point <= the continuous draw").

    The recovered index carries `_K_EPS`, the same tolerance
    `build_grid_shape` floors with. A grid point is computed, not stored:
    `lo * factor**k` lands a few ulp either side of the exact value, so an
    index recovered from one arrives as `k - 1e-16` about as often as `k`.
    Flooring that untolerated drops a whole cell, which on a decade grid is
    a factor of ten, and breaks the value round trip `Chart.to_unit`
    promises. The tolerance is nine orders of magnitude below a cell, so it
    recovers a grid point without rounding a draw from inside a cell up to
    the next one.
    """
    if shape.has_extra_hi and x >= shape.hi:
        return shape.hi
    if shape.step is not None:
        raw = (x - shape.lo) / shape.step
    elif x > 0:
        assert shape.factor is not None
        raw = math.log(x / shape.lo) / math.log(shape.factor)
    else:
        raw = 0.0
    k = max(0, min(math.floor(raw + _K_EPS), shape.K))
    return grid_point(shape.lo, shape.step, shape.factor, k)


def grid_membership(shape: GridShape, value: float, *, rtol: float = _DEFAULT_RTOL) -> float | None:
    """Canonical grid value for `value` if it is (within `rtol`) a grid member, else `None`."""
    if shape.has_extra_hi and _isclose(value, shape.hi, rtol):
        return shape.hi
    if shape.step is not None:
        k = round((value - shape.lo) / shape.step)
    else:
        assert shape.factor is not None
        if value <= 0:
            return None
        k = round(math.log(value / shape.lo) / math.log(shape.factor))
    if 0 <= k <= shape.K:
        candidate = grid_point(shape.lo, shape.step, shape.factor, k)
        if _isclose(value, candidate, rtol):
            return candidate
    return None
