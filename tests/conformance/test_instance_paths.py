"""Conformance laws: M10.5 items 2-8 — expression and validation hygiene
around instance-path indexing, repeat-count typing, boolean/choice
misuse, and space_from_ir's anchor check (API.md, "Expressions" §instance
paths; "Modifiers and Layering" §the lift; error-table rows 6, 12, 22, 29).

All eight are pre-existing defects that failed *silently* — none crashed,
each returned a confident wrong answer — until this milestone. Every test
below fails against the pre-M10.5 tree.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError


class TestStaticOutOfRangeIndexIsResolutionError:
    """Item 2, row 29: against a *static* count the length is known at
    resolution, so an out-of-range index is a resolution error — not a
    silently inapplicable constraint (that stays the *dynamic*-count rule).
    Before M10.5 this resolved clean and made every config feasible."""

    def test_positive_out_of_range_raises(self):
        space = ds.space(ds.param("y").real(0.0, 1.0).repeat(3))
        with pytest.raises(ResolutionError, match=r"out of range.*row 29"):
            space.require(ds.param("y[7]") > 0.99)

    def test_negative_out_of_range_raises(self):
        space = ds.space(ds.param("y").real(0.0, 1.0).repeat(3))
        with pytest.raises(ResolutionError, match=r"out of range.*row 29"):
            space.require(ds.param("y[-7]") > 0.99)

    def test_in_range_resolves_and_is_feasibility_load_bearing(self):
        space = ds.space(ds.param("y").real(0.0, 1.0).repeat(3)).require(
            ds.param("y[2]") > 0.99
        )
        assert space.is_feasible({"y": [0.1, 0.2, 0.995]})
        assert not space.is_feasible({"y": [0.1, 0.2, 0.5]})

    def test_dynamic_count_out_of_range_stays_inapplicable_not_an_error(self):
        # A dynamic count keeps the runtime Unknown rule -- row 29 is
        # specifically the *static*-count case.
        space = ds.space(
            ds.param("n").integer(1, 3),
            ds.param("y").real(0.0, 1.0).repeat(ds.param("n")),
        ).require(ds.param("y[2]") > 0.99)
        assert space.is_feasible({"n": 1, "y": [0.1]})


class TestNestedAndMixedInstanceIndexing:
    """Item 3: `g[0][1]` (chained scalar nesting, arbitrary depth) and
    `layers[2].act[1]` (mixed struct-lift + scalar-lift) both resolve —
    `_is_declared`/`_resolve_entry` used to strip only a single trailing
    bracket group, so both raised a spurious row-6 "undeclared param"."""

    def test_nested_scalar_lift(self):
        space = ds.space(ds.param("g").real(0.0, 1.0).repeat(2, 2)).require(
            ds.param("g[0][1]") > 0.5
        )
        assert space.is_feasible({"g": [[0.1, 0.9], [0.1, 0.1]]})
        assert not space.is_feasible({"g": [[0.1, 0.1], [0.1, 0.1]]})

    def test_mixed_struct_then_scalar_lift(self):
        space = ds.space(
            ds.param("layers").space(ds.param("act").real(0.0, 1.0).repeat(2)).repeat(2)
        ).require(ds.param("layers[1].act[0]") > 0.5)
        assert space.is_feasible({"layers": [{"act": [0.1, 0.1]}, {"act": [0.9, 0.1]}]})
        assert not space.is_feasible({"layers": [{"act": [0.9, 0.1]}, {"act": [0.1, 0.1]}]})

    def test_plain_single_level_instance_path_still_works(self):
        # The M3/M4 baseline case must stay green -- pure regression guard.
        stop = ds.space(ds.param("dwell_min").integer(5, 30))
        space = ds.space(ds.param("stops").space(stop).repeat(3)).require(
            ds.param("stops[0].dwell_min") < 10
        )
        cfg = {"stops": [{"dwell_min": 5}, {"dwell_min": 20}, {"dwell_min": 20}]}
        assert space.is_feasible(cfg)


class TestNegativeIndexResolvesAtEvaluation:
    """Item 4: `x[-1]` resolves against the lift's own realized length —
    the only way to name a dynamic lift's last element. Before M10.5 it
    resolved but was vacuous (`applicable=False` regardless of the
    referenced value), since no config key is ever literally `"x[-1]"`."""

    def test_last_element_is_feasibility_load_bearing(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).repeat(3)).require(
            ds.param("x[-1]") > 0.5
        )
        assert space.is_feasible({"x": [0.1, 0.2, 0.9]})
        assert not space.is_feasible({"x": [0.9, 0.9, 0.1]})

    def test_negative_index_over_a_dynamic_count(self):
        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("x").real(0.0, 1.0).repeat(ds.param("n")),
        ).require(ds.param("x[-1]") > 0.5)
        assert space.is_feasible({"n": 2, "x": [0.1, 0.9]})
        assert not space.is_feasible({"n": 2, "x": [0.9, 0.1]})


class TestResultTypedRepeatCounts:
    """Item 5/D-72: a `.repeat()` count may be any integer-*valued*
    expression whose references resolve, not only a bare integer param —
    `Sum` over an integer- or bool-leaved lift, `Min`/`Max` over an
    integer-leaved lift only (the deliberate asymmetry: `sum([True, False])`
    is `int`, `min([True, False])` is `bool`). Before M10.5 `.sum()` over a
    bool lift raised row 12 even though the aggregate is itself int-valued."""

    def test_sum_over_bool_lift_drives_a_count(self):
        space = ds.space(
            ds.param("m").bool().repeat(4),
            ds.param("z").real(0.0, 1.0).repeat(ds.param("m").sum()),
        )
        c = {"m": [True, False, True, True]}
        flat = ds.flatten(c, space)
        assert flat["m"] == 4
        assert space.is_feasible({**c, "z": [0.1, 0.2, 0.3]})  # len 3 == true-count

    def test_min_over_bool_lift_still_rejected_row_12(self):
        with pytest.raises(ResolutionError, match=r"row 12"):
            ds.space(
                ds.param("m").bool().repeat(4),
                ds.param("z").real(0.0, 1.0).repeat(ds.param("m").min()),
            )

    def test_min_over_integer_lift_accepted(self):
        space = ds.space(
            ds.param("m").integer(0, 4).repeat(4),
            ds.param("z").real(0.0, 1.0).repeat(ds.param("m").min()),
        )
        assert space.is_feasible({"m": [0, 1, 2, 3], "z": []})

    def test_sum_over_real_lift_still_rejected_row_12(self):
        with pytest.raises(ResolutionError, match=r"row 12"):
            ds.space(
                ds.param("m").real(0.0, 4.0).repeat(4),
                ds.param("z").real(0.0, 1.0).repeat(ds.param("m").sum()),
            )

    def test_division_still_rejected_row_12(self):
        with pytest.raises(ResolutionError, match=r"row 12"):
            ds.space(
                ds.param("n").integer(0, 10),
                ds.param("z").real(0.0, 1.0).repeat(ds.param("n") / 2),
            )

    def test_end_to_end_count_tracks_true_count_over_samples(self):
        space = ds.space(
            ds.param("m").bool().repeat(4),
            ds.param("z").real(0.0, 1.0).repeat(ds.param("m").sum()),
        )
        for seed in range(10):
            cfg = space.sample_one(seed=seed)
            assert len(cfg["z"]) == sum(1 for v in cfg["m"] if v)
            assert space.is_feasible(cfg)


class TestBooleanOperatorOnLiftValuedOperandIsResolutionError:
    """Item 6, row 29: `~`/`&`/`|` (or a bare condition/constraint) applied
    to an operand that is still list-typed. Before M10.5, `~g[0]` on a
    `repeat(4, 4)` bool lift resolved, then coerced by truthiness (`g[0]`
    is the *inner* list's own count) and made every config infeasible."""

    def test_not_over_still_list_typed_operand_raises(self):
        with pytest.raises(ResolutionError, match=r"still a lift.*row 29"):
            ds.space(ds.param("g").bool().repeat(4, 4)).require(~ds.param("g[0]"))

    def test_bool_op_over_still_list_typed_operand_raises(self):
        with pytest.raises(ResolutionError, match=r"still a lift.*row 29"):
            ds.space(ds.param("g").bool().repeat(4, 4)).require(
                ds.param("g[0]") & ds.param("g[1]")
            )

    def test_bare_condition_over_still_list_typed_operand_raises(self):
        with pytest.raises(ResolutionError, match=r"still a lift.*row 29"):
            ds.space(
                ds.param("g").bool().repeat(4, 4),
                ds.param("x").real(0.0, 1.0).when(ds.param("g[0]")),
            )

    def test_single_level_lift_negation_still_works(self):
        # A single-repeat() bool lift's element IS a scalar bool -- must
        # not be over-rejected by the same check.
        space = ds.space(ds.param("g").bool().repeat(4)).require(~ds.param("g[0]"))
        assert space.is_feasible({"g": [False, False, True, True]})
        assert not space.is_feasible({"g": [True, False, True, True]})


class TestChoicePayloadMustBeASpace:
    """Item 7, row 29: a `.choice()` payload that is not a `Space` used to
    reach `relocate_child` and raise an opaque `AttributeError` (`Space`'s
    `Mapping` vs. an `Expr`'s `frozenset`) — now a path-named
    `ResolutionError`."""

    def test_bare_param_expr_payload_raises(self):
        with pytest.raises(ResolutionError, match=r"must be a Space.*row 29"):
            ds.space(ds.param("c").choice(("a", ds.param("x").real(0.0, 1.0)), "b"))

    def test_valid_space_payload_still_works(self):
        space = ds.space(
            ds.param("c").choice(("a", ds.space(ds.param("x").real(0.0, 1.0))), "b")
        )
        assert space.is_feasible({"c": "b"})


class TestSpaceFromIrValidatesAnchors:
    """Item 8, row 22: `space_from_ir`'s anchors used to bypass row 22
    entirely (`.anchor()` on a builder-built `Space` already raised it) —
    silently accepted, unlike every other entry point."""

    def _base(self) -> ds.Space:
        return ds.space(ds.param("x").real(0.0, 1.0))

    def test_invalid_anchor_raises(self):
        base = self._base()
        with pytest.raises(ResolutionError, match=r"row 22"):
            ds.space_from_ir(
                base.params, base.conditions, base.constraints, anchors={"bad": {"x": 99.0}}
            )

    def test_valid_anchor_is_kept(self):
        base = self._base()
        rebuilt = ds.space_from_ir(
            base.params, base.conditions, base.constraints, anchors={"good": {"x": 0.5}}
        )
        assert dict(rebuilt.anchors) == {"good": {"x": 0.5}}


class TestCheckFullyResolvedAlsoWalksConstraints:
    """The metaprogramming hole adjacent to item 8: `check_fully_resolved`
    used to re-check only `space.conditions`, never `space.constraints` —
    a builder-built space is already strict at `add_constraints`, so this
    was invisible there, but a raw-IR constraint arriving through
    `space_from_ir` was never expression-checked at all, making items 2/3/
    4/6's new row-29 rejections bypassable through the metaprogramming
    surface."""

    def test_static_out_of_range_constraint_rejected_via_space_from_ir(self):
        from designspace.build._paramexpr import ParamExpr
        from designspace.expr import Compare, Literal
        from designspace.ir import Constraint

        base = ds.space(ds.param("y").real(0.0, 1.0).repeat(3))
        bad_expr = Compare("gt", ParamExpr(path="y[7]"), Literal(0.99))
        bad_constraint = Constraint(
            expr=bad_expr,
            hard=True,
            origin="require",
            tags=frozenset(),
            meta={},
            params=bad_expr.params,
        )
        with pytest.raises(ResolutionError, match=r"row 29"):
            ds.space_from_ir(base.params, base.conditions, (bad_constraint,))

    def test_valid_constraint_round_trips_through_space_from_ir(self):
        space = ds.space(ds.param("y").real(0.0, 1.0).repeat(3)).require(
            ds.param("y[2]") > 0.5
        )
        rebuilt = ds.space_from_ir(space.params, space.conditions, space.constraints)
        assert rebuilt.is_feasible({"y": [0.1, 0.2, 0.9]})
