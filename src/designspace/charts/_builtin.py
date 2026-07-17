"""Built-in chart families (API_v3.md, "Charts" > "Built-in prior families").

Each is bounds-aware: resolution composes the parameterless `ds.Log()` /
`ds.Logit()` / `ds.Power(p)` markers (ir/_priors.py) with a param's envelope
`[lo, hi]` to build one of these. `lo == hi` is the degenerate constant chart
(still generative, per the Degeneracy Table); `to_unit` at that point has no
spec-given answer, so it returns `0.0` (documented in DECISIONS.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from designspace.errors import ResolutionError


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(x: float) -> float:
    return math.log(x / (1.0 - x))


def _signed_pow(base: float, exponent: float) -> float:
    """`base ** exponent`, defined for negative `base` via the signed real root.

    Only reachable when `Power`'s domain check has established this is a
    legal real result (see `check_power_domain`).
    """
    if base < 0:
        return -float((-base) ** exponent)
    return float(base**exponent)


@dataclass(frozen=True)
class UniformChart:
    lo: float
    hi: float

    def from_unit(self, u: float) -> float:
        return self.lo + u * (self.hi - self.lo)

    def to_unit(self, value: float) -> float:
        if self.hi == self.lo:
            return 0.0
        return (value - self.lo) / (self.hi - self.lo)


@dataclass(frozen=True)
class LogChart:
    lo: float
    hi: float

    def from_unit(self, u: float) -> float:
        log_lo, log_hi = math.log(self.lo), math.log(self.hi)
        return math.exp(log_lo + u * (log_hi - log_lo))

    def to_unit(self, value: float) -> float:
        if self.hi == self.lo:
            return 0.0
        log_lo, log_hi = math.log(self.lo), math.log(self.hi)
        return (math.log(value) - log_lo) / (log_hi - log_lo)


@dataclass(frozen=True)
class LogitChart:
    lo: float
    hi: float

    def from_unit(self, u: float) -> float:
        logit_lo, logit_hi = _logit(self.lo), _logit(self.hi)
        return _sigmoid(logit_lo + u * (logit_hi - logit_lo))

    def to_unit(self, value: float) -> float:
        if self.hi == self.lo:
            return 0.0
        logit_lo, logit_hi = _logit(self.lo), _logit(self.hi)
        return (_logit(value) - logit_lo) / (logit_hi - logit_lo)


@dataclass(frozen=True)
class PowerChart:
    lo: float
    hi: float
    p: float

    def from_unit(self, u: float) -> float:
        if self.hi == self.lo:
            return self.lo
        lo_p, hi_p = self.lo**self.p, self.hi**self.p
        interior = lo_p + u * (hi_p - lo_p)
        return _signed_pow(interior, 1.0 / self.p)

    def to_unit(self, value: float) -> float:
        if self.hi == self.lo:
            return 0.0
        lo_p, hi_p = self.lo**self.p, self.hi**self.p
        return float((value**self.p - lo_p) / (hi_p - lo_p))


def check_log_domain(path: str, lo: float) -> None:
    if lo <= 0:
        raise ResolutionError(f"param {path!r}: log_scale/Log requires lo > 0, got lo={lo!r}")


def check_logit_domain(path: str, lo: float, hi: float) -> None:
    if not (0 < lo <= hi < 1):
        raise ResolutionError(
            f"param {path!r}: Logit requires 0 < lo <= hi < 1, got lo={lo!r}, hi={hi!r}"
        )


def check_power_domain(path: str, p: float, lo: float, hi: float) -> None:
    if p == 0:
        raise ResolutionError(f"param {path!r}: Power(p=0) is undefined")
    if not float(p).is_integer() and lo < 0:
        raise ResolutionError(
            f"param {path!r}: Power(p={p!r}) requires lo >= 0 for non-integer p, got lo={lo!r}"
        )
    if p < 0 and lo <= 0:
        raise ResolutionError(
            f"param {path!r}: Power(p={p!r}) requires lo > 0 for negative p, got lo={lo!r}"
        )
