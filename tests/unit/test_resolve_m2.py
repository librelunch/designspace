"""M2 gate: chart-family domain errors (row 9), external-prior support (row
19), and `.forbid()`/`.constrain()` resolution (rows 6/14 generalized to
constraints, row 23 tags/meta).

Per milestone gate: every implemented error-table row has a test asserting
the error class *and* that the message names the offending path.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError


class TestRow9ChartFamilyDomain:
    def test_log_scale_non_positive_lo_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(-1.0, 1.0).log_scale())

    def test_log_scale_zero_lo_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).log_scale())

    def test_logit_outside_unit_interval_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 0.5).prior(ds.Logit()))
        with pytest.raises(ResolutionError, match="'y'"):
            ds.space(ds.param("y").real(0.5, 1.0).prior(ds.Logit()))

    def test_power_zero_exponent_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(1.0, 4.0).prior(ds.Power(0)))

    def test_power_negative_exponent_at_zero_lo_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 4.0).prior(ds.Power(-1)))

    def test_power_straddles_zero_raises(self):
        # domain-incomplete: the signed-root formula would map onto [2, 3],
        # not [-2, 3] (API_v3.md, "Charts" > "Built-in prior families").
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(-2.0, 3.0).prior(ds.Power(2)))

    def test_power_degenerate_symmetric_domain_raises(self):
        # lo**p == hi**p: Power(2) over [-a, a].
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(-1.0, 1.0).prior(ds.Power(2)))

    def test_power_all_negative_even_p_raises(self):
        # monotone (t**2 decreases over [-4, -2]) yet unrecoverable by the
        # signed-root formula, which would return positive values.
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(-4.0, -2.0).prior(ds.Power(2)))

    def test_power_odd_p_over_negative_domain_is_legal(self):
        space = ds.space(ds.param("x").real(-4.0, -2.0).prior(ds.Power(3)))
        assert space.params["x"].chart is not None

    def test_power_odd_p_straddling_zero_is_legal(self):
        space = ds.space(ds.param("x").real(-2.0, 5.0).prior(ds.Power(3)))
        assert space.params["x"].chart is not None


class TestRow19ExternalPriorSupport:
    class _UnboundedNoCdf:
        def ppf(self, q: float) -> float:
            return q * 1000.0 - 500.0  # ppf(0)=-500, ppf(1)=500 -- outside [0,1]

    class _UnboundedWithCdf:
        def ppf(self, q: float) -> float:
            return q * 1000.0 - 500.0

        def cdf(self, value: float) -> float:
            return (value + 500.0) / 1000.0

    def test_support_exceeds_bounds_without_cdf_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).prior(self._UnboundedNoCdf()))

    def test_support_exceeds_bounds_with_cdf_truncates_without_error(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).prior(self._UnboundedWithCdf()))
        chart = space.params["x"].chart
        assert chart is not None
        v = chart.from_unit(0.5)
        assert 0.0 <= v <= 1.0


class TestForbidConstrainReferenceAndTypeChecks:
    def test_forbid_references_undeclared_param_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="'y'"):
            space.forbid(ds.param("y") > 0.5)

    def test_constrain_arithmetic_on_categorical_raises(self):
        space = ds.space(ds.param("algo").categorical("sgd", "adam"))
        with pytest.raises(ResolutionError, match="'algo'"):
            space.constrain((ds.param("algo") + 1) == 2)  # type: ignore[operator]

    def test_forbid_non_boolexpr_raises_typeerror(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(TypeError):
            space.forbid(ds.param("x") + 1)  # type: ignore[arg-type]


class TestRow23ForbidConstrainTagsMeta:
    def test_empty_string_tag_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="forbid"):
            space.forbid(ds.param("x") > 0.5, tags=("",))

    def test_non_json_serializable_meta_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="constrain"):
            space.constrain(ds.param("x") > 0.5, meta={"k": object()})


class TestForbidConstrainStructural:
    def test_each_condition_is_its_own_constraint(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0)).forbid(
            ds.param("x") > 0.9,
            ds.param("y") > 0.9,
        )
        assert len(space.constraints) == 2
        assert all(c.hard for c in space.constraints)

    def test_forbid_and_constrain_are_immutable_and_chainable(self):
        base = ds.space(ds.param("x").real(0.0, 1.0))
        forbidden = base.forbid(ds.param("x") > 0.9)
        assert len(base.constraints) == 0
        assert len(forbidden.constraints) == 1

    def test_tags_and_meta_stored_on_constraint(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).constrain(
            ds.param("x") > 0.1, tags=("budget",), meta={"note": "example"}
        )
        c = space.constraints[0]
        assert c.tags == frozenset({"budget"})
        assert dict(c.meta) == {"note": "example"}

    def test_implies_desugars_in_constraint(self):
        space = ds.space(
            ds.param("a").bool(),
            ds.param("b").bool(),
        ).forbid(ds.param("a").implies(ds.param("b")))
        expr = space.constraints[0].expr
        assert expr.kind == "or"  # ~a | b, not "implies"
