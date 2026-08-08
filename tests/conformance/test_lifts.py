"""Conformance laws: lifts and aggregates.

See API.md, "Modifiers and Layering" > "The lift", "Expressions" > "Vector
expressions and aggregates", and "Three-valued semantics" rules 1 and 6.

Laws enforced here: `per_element_instantiation_counts`,
`nested_lift_leaf_aggregates`.

Also asserted: the empty-aggregate values of rule 6, where `sum`,
`count_of`, `distinct` and `is_sorted` over an active empty lift take their
stated values and `min` and `max` go Unknown; the distinction between an
inactive-lift projection and an active empty list, which is the spec's own
worked example; `.distinct(*fields)` over a struct lift in its satisfied,
violated and interior-Unknown cases; that `is_sorted` on a lift nested
deeper than one level is row 24; that `unflatten(flatten(c)) == c` over
lifted configs; that variadic `.repeat(a, b)` is structurally identical to
the chained `.repeat(b).repeat(a)`; that an out-of-range instance path index
is Unknown; and that `.field(name)` on a non-struct lift, or naming an
undeclared element field, is row 6 rather than a silent Unknown cascade.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.config import flatten
from designspace.errors import ResolutionError
from designspace.eval import Unknown, compute_activity, evaluate_arith, evaluate_bool


class TestEmptyAggregateValues:
    """Rule 6: active lift, zero elements."""

    def _space_and_exprs(self):
        space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(0))
        xs = ds.param("xs")
        return space, xs

    def test_sum_is_zero(self):
        space, xs = self._space_and_exprs()
        activity = compute_activity(space, {"xs": 0})
        assert evaluate_arith(xs.sum(), {"xs": 0}, activity, space) == 0

    def test_count_of_is_zero(self):
        space, xs = self._space_and_exprs()
        activity = compute_activity(space, {"xs": 0})
        assert evaluate_arith(xs.count_of(0.5), {"xs": 0}, activity, space) == 0

    def test_distinct_is_true(self):
        space, xs = self._space_and_exprs()
        activity = compute_activity(space, {"xs": 0})
        assert evaluate_bool(xs.distinct(), {"xs": 0}, activity, space) is True

    def test_is_sorted_is_true(self):
        space, xs = self._space_and_exprs()
        activity = compute_activity(space, {"xs": 0})
        assert evaluate_bool(xs.is_sorted(), {"xs": 0}, activity, space) is True

    def test_min_is_unknown(self):
        space, xs = self._space_and_exprs()
        activity = compute_activity(space, {"xs": 0})
        assert isinstance(evaluate_arith(xs.min(), {"xs": 0}, activity, space), Unknown)

    def test_max_is_unknown(self):
        space, xs = self._space_and_exprs()
        activity = compute_activity(space, {"xs": 0})
        assert isinstance(evaluate_arith(xs.max(), {"xs": 0}, activity, space), Unknown)


class TestInactiveLiftVsActiveEmpty:
    """The spec's own worked example (API.md, "Three-valued semantics",
    lines 295-298), verbatim:

        # use_aux = False  -> aux_layers inactive -> .field("w").sum() is
        #   Unknown -> constraint inapplicable
        # use_aux = True, n_aux count yields []  -> sum() == 0 ->
        #   constraint applies and is satisfied

    Built through an actual `.encourage()` so the law is checked at the
    `ConstraintEval` level the spec itself describes it at, not by reading
    a raw evaluator return value.
    """

    def _space(self):
        return ds.space(
            ds.param("use_aux").bool(),
            ds.param("n_aux").integer(0, 5),
            ds.param("aux_layers")
            .space(ds.param("w").real(0.0, 1.0))
            .repeat(ds.param("n_aux"))
            .when(ds.param("use_aux")),
        ).encourage(ds.param("aux_layers").field("w").sum() <= 1.0)

    def test_inactive_lift_makes_the_constraint_inapplicable(self):
        space = self._space()
        result = space.validate({"use_aux": False, "n_aux": 0})
        (ce,) = result.constraint_evals
        assert ce.applicable is False
        assert ce.satisfied is None

    def test_active_empty_list_applies_and_is_satisfied(self):
        space = self._space()
        result = space.validate({"use_aux": True, "n_aux": 0, "aux_layers": []})
        (ce,) = result.constraint_evals
        assert ce.applicable is True
        assert ce.satisfied is True


class TestNonCountAggregatesPlainPropagateUnknown:
    """Three-valued semantics rule 2: "Every *other* aggregate (`sum`,
    `min`, `max`, `count_of`, `is_sorted`, `distinct`) containing any
    Unknown element is itself Unknown: plain propagation, no range
    computed."
    """

    def _space(self):
        return ds.space(
            ds.param("rows")
            .space(
                ds.param("active").bool(),
                ds.param("cells").real(0.0, 1.0).when(ds.param("active")),
            )
            .repeat(3)
        )

    def test_sum_is_unknown_when_any_element_is_interior_unknown(self):
        space = self._space()
        config = {
            "rows": [
                {"active": True, "cells": 0.5},
                {"active": False},
                {"active": True, "cells": 0.25},
            ]
        }
        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        result = evaluate_arith(ds.param("rows").field("cells").sum(), flat, activity, space)
        assert isinstance(result, Unknown)

    def test_sum_is_the_plain_total_when_no_interior_unknowns(self):
        space = self._space()
        config = {
            "rows": [
                {"active": True, "cells": 0.5},
                {"active": True, "cells": 0.1},
                {"active": True, "cells": 0.25},
            ]
        }
        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        result = evaluate_arith(ds.param("rows").field("cells").sum(), flat, activity, space)
        assert result == pytest.approx(0.85)


class TestRow6FieldProjection:
    """`.field(name)` requires a struct lift whose element declares `name`
    (API.md, "Expressions"). Projecting an undeclared field, or calling
    `.field()` on a non-struct lift, is a resolution error under row 6
    rather than a silent Unknown.
    """

    def test_field_on_scalar_lift_raises(self):
        with pytest.raises(ResolutionError, match="'xs'"):
            ds.space(ds.param("xs").real(0.0, 1.0).repeat(3)).encourage(
                ds.param("xs").field("y").sum() > 0
            )

    def test_field_on_non_lift_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0)).encourage(ds.param("x").field("y").sum() > 0)

    def test_undeclared_field_name_raises(self):
        item = ds.space(ds.param("width").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="'items'"):
            ds.space(ds.param("items").space(item).repeat(3)).encourage(
                ds.param("items").field("nonexistent").sum() > 0
            )

    def test_declared_field_name_resolves(self):
        item = ds.space(ds.param("width").real(0.0, 1.0))
        space = ds.space(ds.param("items").space(item).repeat(3)).encourage(
            ds.param("items").field("width").sum() > 0
        )
        result = space.validate({"items": [{"width": 0.1}, {"width": 0.2}, {"width": 0.3}]})
        assert result.valid


class TestPerInstanceConstraintInstantiation:
    """ "Constraints declared inside a repeated element `Space` are
    instantiated per element": introspection lists them once under the
    definition path; evaluation reports one `ConstraintEval` per instance
    path."""

    def _space(self):
        edge = ds.space(
            ds.param("src").integer(0, 10),
            ds.param("dst").integer(0, 10),
        ).forbid(ds.param("src") == ds.param("dst"))
        return ds.space(ds.param("edges").space(edge).repeat(3))

    def test_declared_once_under_the_definition_path(self):
        space = self._space()
        assert space.params["edges"].domain.element_constraints
        assert len(space.params["edges"].domain.element_constraints) == 1

    def test_evaluated_once_per_instance_path(self):
        space = self._space()
        config = {"edges": [{"src": 1, "dst": 2}, {"src": 3, "dst": 3}, {"src": 5, "dst": 6}]}
        result = space.validate(config)
        assert len(result.constraint_evals) == 3
        by_instance = {ce.instance_path: ce for ce in result.constraint_evals}
        assert set(by_instance) == {"edges[0]", "edges[1]", "edges[2]"}
        assert by_instance["edges[1]"].satisfied is True  # src == dst: forbid violated
        assert not result.valid


class TestPerElementConstraintOverNestedLift:
    """A struct-lift element that itself declares a nested `.repeat()`,
    aggregated by a per-element constraint declared in that same inner
    scope, such as a repeated "row" whose own "cells" field is a repeated
    real, constrained by `.sum()` inside the row's own scope. Distinct
    from `TestPerInstanceConstraintInstantiation` (whose element fields
    are plain scalars): `instantiate_constraints` renames the template's
    governing path (`"rows[].cells"`, a real `space.params` key) to a
    concrete instance path (`"rows[0].cells"`, never itself a key) before
    evaluation reaches the aggregate, which must resolve it back to its
    governing `ListDomain` to gather instance paths."""

    def _space(self):
        # forbid(sum <= 0.1): almost never binding for random draws (P(sum
        # of 4 uniform[0,1] > 0.1) is close to 1), so sample_dicts succeeds
        # easily while still exercising a genuine, occasionally-checked
        # per-row constraint.
        row = ds.space(ds.param("cells").real(0.0, 1.0).repeat(4)).forbid(
            ds.param("cells").sum() <= 0.1
        )
        return ds.space(ds.param("rows").space(row).repeat(2))

    def test_samples_without_crashing(self):
        space = self._space()
        configs = space.sample_dicts(20, seed=0)
        assert len(configs) == 20

    def test_per_row_forbid_is_evaluated_and_enforced(self):
        space = self._space()
        feasible = {"rows": [{"cells": [1.0, 1.0, 1.0, 1.0]}, {"cells": [1.0, 1.0, 1.0, 1.0]}]}
        assert space.is_feasible(feasible)
        infeasible = {
            "rows": [{"cells": [0.01, 0.01, 0.01, 0.01]}, {"cells": [1.0, 1.0, 1.0, 1.0]}]
        }
        assert not space.is_feasible(infeasible)


class TestDistinctFieldTuples:
    """`.distinct(*fields)` (struct lift: distinct field-tuples), per the
    spec's "Vector expressions and aggregates". Exercises `_distinct_tuples`
    / `_tuple_equal`, which the no-arg `.distinct()` tests elsewhere in this
    file never reach."""

    def _space(self):
        item = ds.space(
            ds.param("a").integer(0, 10),
            ds.param("flag").bool(),
            ds.param("b").integer(0, 10).when(ds.param("flag")),
        )
        return ds.space(ds.param("items").space(item).repeat(3)).encourage(
            ds.param("items").distinct("a", "b")
        )

    def test_all_distinct_tuples_is_satisfied(self):
        space = self._space()
        config = {
            "items": [
                {"a": 1, "flag": True, "b": 1},
                {"a": 1, "flag": True, "b": 2},
                {"a": 2, "flag": True, "b": 1},
            ]
        }
        result = space.validate(config)
        (ce,) = result.constraint_evals
        assert ce.applicable is True
        assert ce.satisfied is True

    def test_duplicate_tuple_is_not_satisfied(self):
        space = self._space()
        config = {
            "items": [
                {"a": 1, "flag": True, "b": 1},
                {"a": 1, "flag": True, "b": 1},
                {"a": 2, "flag": True, "b": 1},
            ]
        }
        result = space.validate(config)
        (ce,) = result.constraint_evals
        assert ce.applicable is True
        assert ce.satisfied is False

    def test_interior_unknown_field_makes_it_inapplicable(self):
        space = self._space()
        config = {
            "items": [
                {"a": 1, "flag": True, "b": 1},
                {"a": 1, "flag": False},  # b inactive -> Unknown
                {"a": 2, "flag": True, "b": 1},
            ]
        }
        result = space.validate(config)
        (ce,) = result.constraint_evals
        assert ce.applicable is False
        assert ce.satisfied is None


class TestIsSortedDepthRestriction:
    """Row 24: `is_sorted` is restricted to depth 1, "a grid has no
    canonical order"."""

    def test_depth_1_is_legal(self):
        ds.space(ds.param("order").integer(0, 10).repeat(4)).encourage(
            ds.param("order").is_sorted()
        )

    def test_depth_2_is_a_resolution_error(self):
        with pytest.raises(ResolutionError, match="row 24"):
            ds.space(ds.param("grid").real(0.0, 1.0).repeat(3).repeat(2)).encourage(
                ds.param("grid").is_sorted()
            )


class TestNestedLiftLeafFlattening:
    """ "Numeric and equality aggregates... operate over the leaves,
    flattened across all levels.\""""

    def test_sum_flattens_across_nesting_levels(self):
        space = ds.space(ds.param("grid").real(0.0, 1.0).repeat(2).repeat(2))
        config = {"grid": [[0.1, 0.2], [0.3, 0.4]]}
        from designspace.config import flatten

        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        total = evaluate_arith(ds.param("grid").sum(), flat, activity, space)
        assert total == pytest.approx(1.0)

    def test_count_of_flattens_across_nesting_levels(self):
        space = ds.space(ds.param("grid").integer(0, 5).repeat(2).repeat(2))
        config = {"grid": [[1, 2], [1, 4]]}
        from designspace.config import flatten

        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        n_ones = evaluate_arith(ds.param("grid").count_of(1), flat, activity, space)
        assert n_ones == 2


class TestFlattenUnflattenRoundTripWithLifts:
    def _space(self):
        return ds.space(
            ds.param("dropout").real(0.0, 0.6).repeat(4),
            ds.param("layers").space(ds.param("width").integer(16, 1024)).repeat(3),
            ds.param("pipeline")
            .choice("shuffle", pmx=ds.space(ds.param("swap_p").real(0.0, 1.0)))
            .repeat(2),
        )

    def test_round_trip_over_sampled_configs(self):
        from designspace.config import flatten, unflatten

        space = self._space()
        for seed in range(50):
            cfg = space.sample_one(seed=seed)
            assert unflatten(flatten(cfg, space), space) == cfg


class TestVariadicSugarStructuralEquality:
    """`.repeat(2, 3)` desugars to `.repeat(3).repeat(2)`.

    Chained lifts desugar in reverse order, and the two spellings are
    "fingerprint-equal by the sugar-equivalence law". Structural equality is
    what this asserts.
    """

    def test_variadic_equals_reverse_chain(self):
        variadic = ds.space(ds.param("grid").real(0.0, 1.0).repeat(2, 3))
        chained = ds.space(ds.param("grid").real(0.0, 1.0).repeat(3).repeat(2))
        assert variadic.params["grid"].domain == chained.params["grid"].domain


class TestInstancePathOutOfRange:
    """ "Instance paths are legal in expressions... An out-of-range index
    makes the leaf inactive (-> Unknown)"."""

    def _space(self):
        return ds.space(ds.param("stops").space(ds.param("dwell").integer(0, 60)).repeat(2)).forbid(
            ds.param("stops[1].dwell") > 10
        )

    def test_in_range_index_is_evaluated(self):
        space = self._space()
        result = space.validate({"stops": [{"dwell": 5}, {"dwell": 20}]})
        (ce,) = result.constraint_evals
        assert ce.applicable is True

    def test_out_of_range_index_is_inapplicable(self):
        space = self._space()
        result = space.validate({"stops": [{"dwell": 5}]})
        (ce,) = result.constraint_evals
        assert ce.applicable is False
        assert ce.satisfied is None
        assert result.valid  # an inapplicable forbid never fails feasibility
