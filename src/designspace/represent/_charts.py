"""The induced chart representation, which `space.represent()` builds.

See API.md, "The Representation Layer" > "The induced chart
representation". `induced_rule` is the whole rule set the derived tier uses
when a caller passes none, in `represent/_build.py`. It is never a fallback
behind user rules, which would break the identity law.

The rule matches a param carrying a chart at its own level or at any element
level of its `ListDomain` chain. `ParamDef.chart is not None` is not the
test: a scalar lift's chart lives in `ListDomain.element_chart`, and the
literal reading would silently drop whole vectors from the genotype.

There are two encoding classes rather than one flag. `_ChartEncoding`
supplies `decode`, `decode_expr` and `measure_preserving`;
`_InvertibleChartEncoding` adds `encode`. `hasattr` is the capability
protocol, so "cannot encode" must be the attribute's absence. Which class
applies is decided once per param at dispatch time, by probing whether the
param's own charts support `to_unit`. Every built-in family does. Only an
external `Prior` supplying `ppf` without `cdf` does not; API.md, "Charts"
says "a `Prior` with `ppf` alone yields a chart that decodes but cannot
encode".
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from designspace.builder._paramexpr import ParamExpr
from designspace.expr import ChartApply, ChartKind, Expr
from designspace.ir import Chart, ListDomain, ParamDef, RealDomain
from designspace.ir._domain import TypeKind


def _bottom_list_domain(domain: ListDomain) -> ListDomain:
    """The innermost `ListDomain` in a chained or nested `.repeat()` chain.

    That is the only level ever carrying `element_chart`; every wrapping
    level has `element_kind == "list"` and `element_chart is None`. The
    recursion shape mirrors `_innermost_element_kind` in `meta/_meta.py`.
    """
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
    """Whether this chart supports `to_unit`, decided by probing it.

    Probing beats inspection here because the one failure mode, an external
    `Prior` with `ppf` but no `cdf` however deeply nested inside an
    `IntegerChart` or `QuantizedChart` wrapper, always raises `TypeError`
    from `ExternalPriorChart.to_unit` in `charts/_external.py`. Every
    built-in family's `to_unit` succeeds.
    """
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
    """Replace the bottom `ListDomain` level's chart facts with unit reals.

    Recurses to that level and rewrites only its chart-bearing element
    facts. Each wrapping level's `count`, `list_default` and
    `element_constraints` are not chart facts and are left untouched.
    """
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
        # element_periodic is mirrored and left as is: without the mirror,
        # from_unit(1.0) == hi is not a domain member for a periodic real.
    )


def _target_domain_facts(param: ParamDef) -> tuple[TypeKind, Any, bool]:
    """`(type_kind, domain, periodic)` for the target `ParamDef`.

    Always `real(0, 1)` at whatever level the chart was found, API.md
    stating that "Each becomes real(0, 1)", with `periodic` mirrored.
    """
    if param.type_kind == "list":
        assert isinstance(param.domain, ListDomain)
        return "list", _unit_list_domain(param.domain), param.periodic
    return "real", RealDomain(0.0, 1.0), param.periodic


def _element_expr_facts(param: ParamDef) -> tuple[Chart, ChartKind, Any, Any, Any, bool]:
    """The source chart's own declaration facts.

    Returns `(chart, type_kind, domain, prior, quantized, periodic)` at the
    level `decode` and `decode_expr` must read: the own-level facts for a
    plain scalar, or the bottom `ListDomain` level's element facts for a
    lift.

    Reached only for a chart-bearing param, callers selecting on
    `is_chart_bearing`, and only the two chart-bearing kinds have a chart to
    find. The kind is narrowed to that pair here so the `ChartApply` built
    from it carries the restriction rather than restating it.
    """
    if param.type_kind == "list":
        assert isinstance(param.domain, ListDomain)
        bottom = _bottom_list_domain(param.domain)
        chart = bottom.element_chart
        assert chart is not None
        assert bottom.element_kind in ("real", "integer")
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
    assert param.type_kind in ("real", "integer")
    return chart, param.type_kind, param.domain, param.prior, param.quantized, param.periodic


class _ChartEncoding:
    """The induced chart representation's per-param arrow, decode-only.

    Used when the source chart has no working `to_unit`.
    """

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
        # Core proves measure preservation only for the induced chart
        # representation, where chart(u) on u ~ U[0, 1] is the declared
        # measure.
        return True


class _InvertibleChartEncoding(_ChartEncoding):
    """As `_ChartEncoding`, plus `encode`, present only when every chart
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
