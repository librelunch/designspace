"""The induced chart representation (API.md, "The Representation Layer" >
"The induced chart representation"; DECISIONS.md D-58/D-56).

`space.represent()` with no rules. `induced_rule` is the sole rule the
derived tier falls back to when a caller passes none (`represent/_build.py`
— never as a fallback *behind* user rules, which would break the identity
law). It matches a param carrying a chart **at its own level or at any
element level of its `ListDomain` chain** — `ParamDef.chart is not None` is
*not* the test: a scalar lift's chart lives in `ListDomain.element_chart`,
and the literal reading would silently drop whole vectors from the
genotype (D-58).

Two encoding classes, not one flag: `_ChartEncoding` (decode/decode_expr/
measure_preserving) and `_InvertibleChartEncoding` (adds `encode`) —
`hasattr` is the capability protocol, so "cannot encode" must be the
attribute's *absence*, decided once per param at dispatch time by probing
whether the param's own chart(s) actually support `to_unit` (every
built-in family does; only an external `Prior` supplying `ppf` without
`cdf` does not — API.md, "Charts": "a `Prior` with `ppf` alone yields a
chart that decodes but cannot encode").
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from designspace.build._paramexpr import ParamExpr
from designspace.expr import ChartApply, Expr
from designspace.ir import Chart, ListDomain, ParamDef, RealDomain


def _bottom_list_domain(domain: ListDomain) -> ListDomain:
    """The innermost `ListDomain` in a chained/nested `.repeat()` chain —
    the only level that ever carries `element_chart` (every wrapping level
    has `element_kind == "list"` and `element_chart is None`), mirroring
    `meta/_meta.py::_innermost_element_kind`'s own recursion shape."""
    d = domain
    while d.element_kind == "list":
        assert isinstance(d.element_domain, ListDomain)
        d = d.element_domain
    return d


def _chart_of(param: ParamDef) -> Chart | None:
    if param.chart is not None:
        return param.chart
    if param.type_kind == "list":
        assert isinstance(param.domain, ListDomain)
        return _bottom_list_domain(param.domain).element_chart
    return None


def is_chart_bearing(param: ParamDef) -> bool:
    return _chart_of(param) is not None


def _chart_is_invertible(chart: Chart) -> bool:
    """Probes rather than inspects: the one failure mode (an external
    `Prior` with `ppf` but no `cdf`, however deeply nested inside an
    `IntegerChart`/`QuantizedChart` wrapper) always raises `TypeError` from
    `charts/_external.py::ExternalPriorChart.to_unit` — every built-in
    family's `to_unit` always succeeds."""
    try:
        chart.to_unit(chart.from_unit(0.5))
    except TypeError:
        return False
    return True


def _is_invertible(param: ParamDef) -> bool:
    chart = _chart_of(param)
    assert chart is not None  # only called once is_chart_bearing(param) is True
    return _chart_is_invertible(chart)


def _map_nested(value: Any, fn: Any) -> Any:
    if isinstance(value, list):
        return [_map_nested(v, fn) for v in value]
    return fn(value)


def _unit_list_domain(domain: ListDomain) -> ListDomain:
    """Recurses to the bottom `ListDomain` level and replaces only its
    chart-bearing element facts with the unit-real equivalent — every
    wrapping level's `count`/`list_default`/`element_constraints` (not
    chart facts) is untouched."""
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return replace(domain, element_domain=_unit_list_domain(domain.element_domain))
    return replace(
        domain,
        element_kind="real",
        element_domain=RealDomain(0.0, 1.0),
        element_chart=None,  # rebuilt fresh by space_from_ir/rebuild_charts
        element_prior=None,
        element_quantized=None,
        element_default=None,  # settled by _build.py, like the scalar default below
        # element_periodic: mirrored, left as-is (D-58 -- from_unit(1.0) == hi
        # is not a domain member for a periodic real without the mirror).
    )


def _target_domain_facts(param: ParamDef) -> tuple[str, Any, bool]:
    """`(type_kind, domain, periodic)` for the target `ParamDef` `target()`
    builds — unconditionally `real(0, 1)` at whatever level the chart was
    found (API.md: "Each becomes real(0, 1)"), `periodic` mirrored."""
    if param.type_kind == "list":
        assert isinstance(param.domain, ListDomain)
        return "list", _unit_list_domain(param.domain), param.periodic
    return "real", RealDomain(0.0, 1.0), param.periodic


def _element_expr_facts(param: ParamDef) -> tuple[Chart, str, Any, Any, Any, bool]:
    """`(chart, type_kind, domain, prior, quantized, periodic)` describing
    the *source* chart's own declaration at the level `decode`/`decode_expr`
    must read — the own-level facts for a plain scalar, or the bottom
    `ListDomain` level's element facts for a lift."""
    if param.type_kind == "list":
        assert isinstance(param.domain, ListDomain)
        bottom = _bottom_list_domain(param.domain)
        chart = bottom.element_chart
        assert chart is not None
        return (
            chart,
            bottom.element_kind,
            bottom.element_domain,
            bottom.element_prior,
            bottom.element_quantized,
            bottom.element_periodic,
        )
    chart = param.chart
    assert chart is not None
    return chart, param.type_kind, param.domain, param.prior, param.quantized, param.periodic


class _ChartEncoding:
    """The induced chart representation's per-param arrow: decode-only
    (source chart lacks a working `to_unit`)."""

    def target(self, param: ParamDef) -> ParamDef:
        type_kind, domain, periodic = _target_domain_facts(param)
        return replace(
            param,
            type_kind=type_kind,
            domain=domain,
            prior=None,
            periodic=periodic,
            default=None,  # settled by _build.py (encode-and-validate, or drop)
            quantized=None,
            chart=None,  # rebuilt fresh by space_from_ir
        )

    def decode(self, param: ParamDef, value: Any) -> Any:
        chart = _element_expr_facts(param)[0]
        return _map_nested(value, chart.from_unit)

    def decode_expr(self, param: ParamDef) -> Expr | None:
        chart, type_kind, domain, prior, quantized, periodic = _element_expr_facts(param)
        return ChartApply(
            ParamExpr(path=param.path), chart, type_kind, domain, prior, quantized, periodic
        )

    def measure_preserving(self) -> bool:
        # D-56: core proves it only for the induced chart representation,
        # where chart(u) on u ~ U[0,1] *is* the declared measure.
        return True


class _InvertibleChartEncoding(_ChartEncoding):
    """As `_ChartEncoding`, plus `encode` — present only when every chart
    along the param's own (or element) level actually supports `to_unit`."""

    def encode(self, param: ParamDef, value: Any) -> Any:
        chart = _element_expr_facts(param)[0]
        return _map_nested(value, chart.to_unit)


def induced_rule(param: ParamDef) -> _ChartEncoding | _InvertibleChartEncoding | None:
    if not is_chart_bearing(param):
        return None
    if _is_invertible(param):
        return _InvertibleChartEncoding()
    return _ChartEncoding()
