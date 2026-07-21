"""M5 gate: expression-bounds desugaring mechanics (API.md, "Constraints
and Feasibility" > "Expression bounds are sugar").

The milestone's *laws* (bound-origin margins, structural/behavioral
equivalence to the hand-written expansion, tighten-vs-reject distributional
equivalence) live in tests/conformance/test_bounds.py. This file covers the
mechanics: envelope arithmetic per op, row 6/7/14/20 message-content tests,
the dependency-order/cycle interaction, and the lift-element scope boundary.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.eval import topological_order
from designspace.ir import IntegerDomain, RealDomain


class TestEnvelopeArithmetic:
    def test_hi_bound_expression_resolves_to_sup_of_hull(self):
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        assert space.params["x"].domain == RealDomain(0.0, 20.0)

    def test_lo_bound_expression_resolves_to_inf_of_hull(self):
        space = ds.space(
            ds.param("y").real(0.0, 50.0),
            ds.param("x").real(ds.param("y"), 100.0),
        )
        assert space.params["x"].domain == RealDomain(0.0, 100.0)

    def test_both_bounds_can_be_expressions(self):
        space = ds.space(
            ds.param("y1").real(0.0, 10.0),
            ds.param("y2").real(50.0, 100.0),
            ds.param("x").real(ds.param("y1"), ds.param("y2")),
        )
        assert space.params["x"].domain == RealDomain(0.0, 100.0)
        origins = {c.origin for c in space.constraints}
        assert origins == {"bound"}
        assert len(space.constraints) == 2

    def test_integer_bound_expression(self):
        space = ds.space(
            ds.param("y").integer(0, 100),
            ds.param("x").integer(1, ds.param("y")),
        )
        assert space.params["x"].domain == IntegerDomain(1, 100)

    def test_add_constant(self):
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y") + 5),
        )
        assert space.params["x"].domain == RealDomain(0.0, 25.0)

    def test_sub_constant(self):
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y") - 5),
        )
        assert space.params["x"].domain == RealDomain(0.0, 15.0)

    def test_mul_by_positive_constant(self):
        space = ds.space(
            ds.param("y").real(1.0, 10.0),
            ds.param("x").real(0.0, ds.param("y") * 2),
        )
        assert space.params["x"].domain == RealDomain(0.0, 20.0)

    def test_mul_by_negative_constant_flips_hull(self):
        space = ds.space(
            ds.param("y").real(1.0, 10.0),
            ds.param("x").real(-100.0, ds.param("y") * -1),
        )
        # hull(y * -1) over y in [1, 10] is [-10, -1]; the hi-bound envelope
        # is the hull's *supremum* (-1), not its infimum.
        assert space.params["x"].domain == RealDomain(-100.0, -1.0)

    def test_chained_dependency_resolves_transitively(self):
        space = ds.space(
            ds.param("z").real(1.0, 5.0),
            ds.param("y").real(0.0, ds.param("z") + 10),
            ds.param("x").real(0.0, ds.param("y")),
        )
        assert space.params["y"].domain == RealDomain(0.0, 15.0)
        assert space.params["x"].domain == RealDomain(0.0, 15.0)


class TestUncomputableHullRow20:
    def test_mul_of_two_non_constant_operands_raises(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("y1").real(1.0, 10.0),
                ds.param("y2").real(1.0, 10.0),
                ds.param("x").real(0.0, ds.param("y1") * ds.param("y2")),
            )

    def test_division_raises(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("y").real(1.0, 10.0),
                ds.param("x").real(0.0, ds.param("y") / 2),
            )

    def test_power_raises(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("y").real(1.0, 10.0),
                ds.param("x").real(0.0, ds.param("y") ** 2),
            )

    def test_modulo_raises(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("y").real(1.0, 10.0),
                ds.param("x").real(0.0, ds.param("y") % 3),
            )

    def test_reference_to_non_numeric_param_raises(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("b").bool(),
                ds.param("x").real(0.0, ds.param("b")),
            )

    def test_count_operator_in_bound_raises(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("flag1").bool(),
                ds.param("flag2").bool(),
                ds.param("x").real(0.0, ds.count(ds.param("flag1"), ds.param("flag2"))),
            )


class TestBoundRefChecks:
    def test_undeclared_reference_raises_row6(self):
        with pytest.raises(ResolutionError, match="undeclared param 'nope'"):
            ds.space(ds.param("x").real(0.0, ds.param("nope")))

    def test_arithmetic_on_categorical_raises_row14(self):
        with pytest.raises(ResolutionError, match="categorical"):
            ds.space(
                ds.param("c").categorical("a", "b"),
                ds.param("x").real(0.0, ds.param("c") + 1),
            )

    def test_self_reference_raises_row7(self):
        with pytest.raises(ResolutionError, match="references itself"):
            ds.space(ds.param("x").real(0.0, ds.param("x")))

    def test_two_param_bound_cycle_raises_row7(self):
        with pytest.raises(ResolutionError, match="cycle detected"):
            ds.space(
                ds.param("x").real(0.0, ds.param("y")),
                ds.param("y").real(0.0, ds.param("x")),
            )

    def test_bound_and_condition_mixed_cycle_raises_row7(self):
        with pytest.raises(ResolutionError, match="cycle detected"):
            ds.space(
                ds.param("x").real(0.0, ds.param("y")),
                ds.param("y").real(0.0, 100.0).when(ds.param("x") > 0),
            )


class TestDependencyOrder:
    def test_referenced_param_precedes_bounded_param(self):
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        order = topological_order(space)
        assert order.index("y") < order.index("x")

    def test_order_holds_across_nested_scope_relocation(self):
        space = ds.space(
            ds.param("algo").choice(
                svm=ds.space(
                    ds.param("y").real(0.0, 100.0),
                    ds.param("x").real(0.0, ds.param("y")),
                ),
            ),
        )
        order = topological_order(space)
        assert order.index("algo.svm.y") < order.index("algo.svm.x")


class TestBoundOriginProvenance:
    def test_origin_is_bound_not_user(self):
        space = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        assert len(space.constraints) == 1
        c = space.constraints[0]
        assert c.origin == "bound"
        assert c.hard is True

    def test_relocation_preserves_bound_origin_under_nesting(self):
        space = ds.space(
            ds.param("layers").space(
                ds.param("y").real(0.0, 100.0),
                ds.param("x").real(0.0, ds.param("y")),
            ),
        )
        assert len(space.constraints) == 1
        c = space.constraints[0]
        assert c.origin == "bound"
        assert c.params == {"layers.x", "layers.y"}


class TestLiftElementExpressionBoundsNotYetSupported:
    def test_lift_element_bound_raises_clear_error(self):
        with pytest.raises(ResolutionError, match="repeated element"):
            ds.space(
                ds.param("y").real(0.0, 1.0),
                ds.param("xs").real(0.0, ds.param("y")).repeat(3),
            )
