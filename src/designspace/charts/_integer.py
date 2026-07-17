"""Integer chart (API_v3.md, "Charts" > "Integers").

Wraps a continuous chart built over `[lo, hi + 1)`; the emitted value is
`floor(chart(u))`, clamped defensively into `[lo, hi]` for the `u == 1.0`
boundary. The inverse is interval-valued: value `k` owns
`[chart⁻¹(k), chart⁻¹(k+1))`; `to_unit(k)` returns the midpoint of that
u-space interval.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from designspace.ir import Chart


@dataclass(frozen=True)
class IntegerChart:
    base: Chart
    lo: int
    hi: int

    def from_unit(self, u: float) -> int:
        k = math.floor(self.base.from_unit(u))
        return int(min(max(k, self.lo), self.hi))

    def to_unit(self, value: int) -> float:
        u_lo = self.base.to_unit(float(value))
        u_hi = self.base.to_unit(float(value + 1))
        return (u_lo + u_hi) / 2

    def unit_interval(self, value: int) -> tuple[float, float]:
        """`[chart⁻¹(k), chart⁻¹(k+1))`, exposed for solvers (not part of `Chart`)."""
        return (self.base.to_unit(float(value)), self.base.to_unit(float(value + 1)))
