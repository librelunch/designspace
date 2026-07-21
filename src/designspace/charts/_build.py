"""Chart dispatcher: resolve step 6 (API.md, "Resolution").

Only `real` and `integer` params carry a chart — categorical/ordinal/bool
use weights directly (no unit-interval map is needed for a finite discrete
choice), matching `ParamDef.chart: Chart | None  # None for non-chart kinds`.

Two bound pairs matter throughout: the *declared* envelope (`lo`, `hi`) —
what chart-family domain requirements (row 9) and external-prior containment
(row 19) are checked against — and the *math* upper bound actually used to
build the continuous chart, which is wider than `hi` for integers
(`[lo, hi + 1)`) and quantized reals (the grid's extension). They coincide
for a plain real.
"""

from __future__ import annotations

from typing import Any

from designspace.charts._builtin import (
    LogChart,
    LogitChart,
    PowerChart,
    UniformChart,
    check_log_domain,
    check_logit_domain,
    check_power_domain,
)
from designspace.charts._external import build_external_chart
from designspace.charts._grid import build_grid_shape
from designspace.charts._integer import IntegerChart
from designspace.charts._quantized import IntegerGridChart, QuantizedChart
from designspace.ir import (
    Chart,
    Domain,
    IntegerDomain,
    Log,
    Logit,
    Power,
    QuantizedSpec,
    RealDomain,
)


def _build_base_chart(path: str, lo: float, hi: float, math_hi: float, prior_spec: Any) -> Chart:
    if prior_spec is None:
        return UniformChart(lo, math_hi)
    if isinstance(prior_spec, Log):
        check_log_domain(path, lo)
        return LogChart(lo, math_hi)
    if isinstance(prior_spec, Logit):
        check_logit_domain(path, lo, hi)
        return LogitChart(lo, math_hi)
    if isinstance(prior_spec, Power):
        check_power_domain(path, prior_spec.p, lo, hi)
        return PowerChart(lo, math_hi, prior_spec.p)
    return build_external_chart(path, prior_spec, lo, hi, math_hi)


def build_chart(
    path: str,
    type_kind: str,
    domain: Domain,
    prior_spec: Any,
    quantized_spec: QuantizedSpec | None,
) -> Chart | None:
    if type_kind not in ("real", "integer"):
        return None
    assert isinstance(domain, RealDomain | IntegerDomain)
    # Bounds are confirmed non-ArithExpr by resolve/'s _check_bounds, which
    # runs (step 7) before chart-building for the same param.
    assert isinstance(domain.lo, int | float) and isinstance(domain.hi, int | float)
    lo, hi = float(domain.lo), float(domain.hi)

    if quantized_spec is None:
        math_hi = hi + 1.0 if type_kind == "integer" else hi
        base = _build_base_chart(path, lo, hi, math_hi, prior_spec)
        if type_kind == "integer":
            assert isinstance(domain, IntegerDomain)
            int_lo, int_hi = domain.lo, domain.hi
            assert isinstance(int_lo, int) and isinstance(int_hi, int)
            return IntegerChart(base=base, lo=int_lo, hi=int_hi)
        return base

    shape = build_grid_shape(
        lo, hi, quantized_spec.step, quantized_spec.factor, quantized_spec.include_hi
    )
    base = _build_base_chart(path, lo, hi, shape.extension_top, prior_spec)
    quantized = QuantizedChart(base=base, shape=shape)
    if type_kind == "integer":
        return IntegerGridChart(quantized=quantized)
    return quantized
