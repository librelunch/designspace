"""External prior charts (API.md, "Charts" > "External priors").

Any object satisfying `Prior` (`.ppf(q)` required, `.cdf(value)` optional).
If the support is contained in `[lo, hi]`, `ppf` is used directly; otherwise
the chart truncates via `cdf`, which is a resolution error (row 19) if
absent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from designspace.errors import ResolutionError
from designspace.ir import Prior


@dataclass(frozen=True)
class ExternalPriorChart:
    prior: Prior
    lo: float
    hi: float
    truncated: bool

    def from_unit(self, u: float) -> float:
        if not self.truncated:
            return self.prior.ppf(u)
        cdf = getattr(self.prior, "cdf")  # noqa: B009
        cdf_lo, cdf_hi = cdf(self.lo), cdf(self.hi)
        return self.prior.ppf(cdf_lo + u * (cdf_hi - cdf_lo))

    def to_unit(self, value: float) -> float:
        if not hasattr(self.prior, "cdf"):
            raise TypeError(
                "this chart's prior has no cdf(), so it is not invertible (to_unit unavailable)"
            )
        cdf = getattr(self.prior, "cdf")  # noqa: B009
        if not self.truncated:
            return float(cdf(value))
        cdf_lo, cdf_hi = cdf(self.lo), cdf(self.hi)
        return float((cdf(value) - cdf_lo) / (cdf_hi - cdf_lo))


def build_external_chart(
    path: str, prior: Any, lo: float, hi: float, math_hi: float | None = None
) -> ExternalPriorChart:
    """`hi` is the declared envelope (row 19's containment check); `math_hi`
    is the possibly-wider bound the actual chart math is built over (e.g.
    a quantization grid's extension). They coincide unless quantized.
    """
    if math_hi is None:
        math_hi = hi
    p0, p1 = prior.ppf(0.0), prior.ppf(1.0)
    contained = math.isfinite(p0) and math.isfinite(p1) and lo <= p0 <= hi and lo <= p1 <= hi
    if contained:
        return ExternalPriorChart(prior=prior, lo=lo, hi=math_hi, truncated=False)
    if not hasattr(prior, "cdf"):
        raise ResolutionError(
            f"param {path!r}: external prior's support exceeds its declared bounds "
            "[lo, hi] and it has no cdf() to truncate with"
        )
    return ExternalPriorChart(prior=prior, lo=lo, hi=math_hi, truncated=True)
