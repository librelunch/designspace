"""Chart dispatcher: resolve step 6 (API.md, "Resolution").

Only a `real` or `integer` param carries a chart. Categorical, ordinal and
bool params use weights directly, a finite discrete choice needing no
unit-interval map, which is why `ParamDef.chart` is `Chart | None`.

Two bound pairs matter throughout. The declared envelope, `lo` and `hi`, is
what the chart-family domain requirements of row 9 and the external-prior
containment of row 19 are checked against. The math upper bound is what
actually builds the continuous chart, and is wider than `hi` for an integer,
at `[lo, hi + 1)`, and for a quantized real, at the grid's extension. The
two coincide for a plain real.
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
