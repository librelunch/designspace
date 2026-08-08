"""Unit tests for `.repeat()` and vector-aggregate mechanics.

Covers what `tests/conformance/test_lifts.py` does not.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.config import flatten
from designspace.errors import ResolutionError, SamplingError
from designspace.eval import compute_activity, evaluate_arith
from designspace.ir import ListDomain


class TestRepeatDomain:
    def test_scalar_lift_resolves(self):
        space = ds.space(ds.param("dropout").real(0.0, 0.6).repeat(4))
        domain = space.params["dropout"].domain
        assert isinstance(domain, ListDomain)
        assert domain.element_kind == "real"
        assert domain.count == 4
        assert domain.element_chart is not None

    def test_struct_lift_relocates_descendants_under_bracket_prefix(self):
        space = ds.space(ds.param("layers").space(ds.param("width").integer(16, 1024)).repeat(3))
        assert "layers[].width" in space.params
        assert space.params["layers[].width"].type_kind == "integer"
        assert space.params["layers"].domain.element_kind == "space"

    def test_choice_lift_relocates_variant_payloads(self):
        space = ds.space(
            ds.param("pipeline")
            .choice("shuffle", pmx=ds.space(ds.param("swap_p").real(0.0, 1.0)))
            .repeat(2)
        )
        assert "pipeline[].pmx.swap_p" in space.params

    def test_nested_repeat_is_recursive(self):
        space = ds.space(ds.param("mask").bool().repeat(8).repeat(8))
        outer = space.params["mask"].domain
        assert outer.element_kind == "list"
        assert outer.count == 8
        assert outer.element_domain.element_kind == "bool"
        assert outer.element_domain.count == 8

    def test_zero_count_is_legal(self):
        space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(0))
        assert space.params["xs"].domain.count == 0

    def test_variadic_sugar_desugars_in_reverse_order(self):
        variadic = ds.space(ds.param("grid").real(0.0, 1.0).repeat(2, 3))
        chained = ds.space(ds.param("grid").real(0.0, 1.0).repeat(3).repeat(2))
        assert variadic.params["grid"].domain == chained.params["grid"].domain

    def test_dynamic_count_via_arith_expr(self):
        space = ds.space(
            ds.param("n").integer(0, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )
        from designspace.expr import ArithExpr

        assert isinstance(space.params["xs"].domain.count, ArithExpr)


class TestPrebuiltSpaceForm:
    def test_space_prebuilt_carries_its_own_constraints_as_element_templates(self):
        edge = ds.space(ds.param("src").integer(0, 10), ds.param("dst").integer(0, 10)).forbid(
            ds.param("src") == ds.param("dst")
        )
        space = ds.space(ds.param("edges").space(edge).repeat(3))
        assert len(space.params["edges"].domain.element_constraints) == 1

    def test_inline_form_has_no_element_constraints(self):
        space = ds.space(
            ds.param("edges")
            .space(ds.param("src").integer(0, 10), ds.param("dst").integer(0, 10))
            .repeat(3)
        )
        assert space.params["edges"].domain.element_constraints == ()


class TestRow11MisplacedLayerModifier:
    def test_prior_after_repeat_raises(self):
        with pytest.raises(ResolutionError, match="row 11"):
            ds.space(ds.param("x").real(0.0, 1.0).repeat(4).log_scale())

    def test_quantized_after_repeat_raises(self):
        with pytest.raises(ResolutionError, match="row 11"):
            ds.space(ds.param("x").real(0.0, 1.0).repeat(4).quantized(step=0.1))

    def test_prior_before_repeat_is_legal(self):
        ds.space(ds.param("x").real(1.0, 100.0).log_scale().repeat(4))


class TestRow12CountNotIntegerTyped:
    def test_float_literal_count_raises(self):
        with pytest.raises(ResolutionError, match="row 12"):
            ds.space(ds.param("x").real(0.0, 1.0).repeat(2.5))  # type: ignore[arg-type]

    def test_real_typed_count_reference_raises(self):
        with pytest.raises(ResolutionError, match="row 12"):
            ds.space(
                ds.param("y").real(0.0, 5.0), ds.param("x").real(0.0, 1.0).repeat(ds.param("y"))
            )

    def test_negative_literal_count_raises(self):
        with pytest.raises(ResolutionError):
            ds.space(ds.param("x").real(0.0, 1.0).repeat(-1))


class TestRow13NegativeEvaluatedCount:
    def test_sampler_raises_on_negative_evaluated_count(self):
        space = ds.space(
            ds.param("n").integer(-3, -1),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )
        with pytest.raises(SamplingError, match="row 13"):
            space.sample_one(seed=0)

    def test_validate_flags_count_mismatch_against_a_dynamic_reference(self):
        space = ds.space(
            ds.param("n").integer(0, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )
        result = space.validate({"n": 3, "xs": [0.1, 0.2]})
        assert not result.valid
        assert any(pe.param == "xs" and pe.reason == "out_of_bounds" for pe in result.param_errors)


class TestRow21Defaults:
    def test_element_and_list_default_together_raises(self):
        with pytest.raises(ResolutionError, match="row 21"):
            ds.space(ds.param("x").real(0.0, 1.0).default(0.5).repeat(3).default([0.1, 0.2, 0.3]))

    def test_list_default_under_dynamic_count_raises(self):
        with pytest.raises(ResolutionError, match="row 21"):
            ds.space(
                ds.param("n").integer(0, 5),
                ds.param("x").real(0.0, 1.0).repeat(ds.param("n")).default([0.1, 0.2]),
            )

    def test_list_default_length_mismatch_raises(self):
        with pytest.raises(ResolutionError, match="row 21"):
            ds.space(ds.param("x").real(0.0, 1.0).repeat(3).default([0.1, 0.2]))

    def test_valid_list_default(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).repeat(3).default([0.1, 0.2, 0.3]))
        assert space.params["x"].domain.list_default == [0.1, 0.2, 0.3]

    def test_valid_element_default(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).default(0.5).repeat(3))
        assert space.params["x"].domain.element_default == 0.5


class TestNestedStructChoiceLiftBoundary:
    """A struct or choice element under more than one `.repeat()` level is
    rejected at resolution rather than left silently wrong."""

    def test_double_nested_struct_element_raises(self):
        with pytest.raises(ResolutionError, match="nested under more than one"):
            ds.space(ds.param("grid").space(ds.param("w").integer(0, 5)).repeat(3).repeat(2))

    def test_double_nested_scalar_element_is_fine(self):
        ds.space(ds.param("mask").bool().repeat(3).repeat(2))

    # The boundary is about the shape, a struct or choice element under two
    # lift levels, rather than about the syntax that reaches it. Declaring
    # the inner lift inside the outer lift's element `Space` composes to the
    # same `"row[].spans[].lo"` template as the chained spelling, so it is
    # the same unsupported shape and is rejected the same way. Unguarded, it
    # produces silently invalid configs: empty element dicts for a struct,
    # and an empty payload that `validate()` accepts for a choice.

    def test_struct_lift_inside_a_struct_lift_element_raises(self):
        inner = ds.space(ds.param("spans").space(ds.space(ds.param("v").integer(0, 5))).repeat(2))
        with pytest.raises(ResolutionError, match="nested under more than one"):
            ds.space(ds.param("row").space(inner).repeat(2))

    def test_choice_lift_inside_a_struct_lift_element_raises(self):
        inner = ds.space(
            ds.param("pipe").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))).repeat(2),
        )
        with pytest.raises(ResolutionError, match="nested under more than one"):
            ds.space(ds.param("row").space(inner).repeat(2))

    def test_struct_lift_inside_a_choice_lift_variant_raises(self):
        payload = ds.space(ds.param("spans").space(ds.space(ds.param("v").integer(0, 5))).repeat(2))
        with pytest.raises(ResolutionError, match="nested under more than one"):
            ds.space(ds.param("row").choice("x", y=payload).repeat(2))

    def test_the_error_names_the_offending_param(self):
        inner = ds.space(ds.param("spans").space(ds.space(ds.param("v").integer(0, 5))).repeat(2))
        with pytest.raises(ResolutionError, match=r"row\[\]\.spans"):
            ds.space(ds.param("row").space(inner).repeat(2))

    def test_scalar_lift_inside_a_struct_lift_element_is_fine(self):
        """The supported neighbour: only a struct or choice element is
        bounded, a scalar lift nesting arbitrarily."""
        inner = ds.space(ds.param("xs").real(0.0, 1.0).repeat(2))
        space = ds.space(ds.param("row").space(inner).repeat(2))
        config = space.sample_one(seed=0)
        assert [len(row["xs"]) for row in config["row"]] == [2, 2]
        assert space.validate(config).valid

    def test_struct_lift_in_a_non_lifted_container_is_fine(self):
        """Equally, the boundary is two lift levels. A struct lift inside a
        plain struct or a choice variant is one, and stays supported."""
        inner = ds.space(ds.param("s").space(ds.space(ds.param("v").integer(0, 5))).repeat(2))
        for space in (
            ds.space(ds.param("g").space(inner)),
            ds.space(ds.param("m").choice("off", on=inner)),
        ):
            config = space.sample_one(seed=0)
            assert space.validate(config).valid


class TestVectorAggregateMethods:
    def _space(self):
        return ds.space(ds.param("xs").real(0.0, 1.0).repeat(3))

    def test_sum_min_max(self):
        space = self._space()
        flat = flatten({"xs": [0.1, 0.5, 0.2]}, space)
        activity = compute_activity(space, flat)
        assert evaluate_arith(ds.param("xs").sum(), flat, activity, space) == pytest.approx(0.8)
        assert evaluate_arith(ds.param("xs").min(), flat, activity, space) == pytest.approx(0.1)
        assert evaluate_arith(ds.param("xs").max(), flat, activity, space) == pytest.approx(0.5)

    def test_length(self):
        space = self._space()
        flat = flatten({"xs": [0.1, 0.5, 0.2]}, space)
        activity = compute_activity(space, flat)
        assert evaluate_arith(ds.param("xs").length(), flat, activity, space) == 3

    def test_length_on_non_lift_raises(self):
        with pytest.raises(ResolutionError):
            ds.space(ds.param("x").real(0.0, 1.0)).encourage(ds.param("x").length() > 0)

    def test_sum_on_non_lift_raises(self):
        with pytest.raises(ResolutionError):
            ds.space(ds.param("x").real(0.0, 1.0)).encourage(ds.param("x").sum() > 0)


class TestValidateParamOnInstancePaths:
    """`Space.validate_param` accepts an instance-bracketed path
    (`"stops[0].dwell_min"`), resolving it through the `"[]"`-template
    (`_lookup_param_shape`'s `[i]->[]` fallback) rather than only literal
    definition paths."""

    def _space(self):
        stop = ds.space(
            ds.param("location").integer(0, 10),
            ds.param("dwell_min").integer(0, 60),
        )
        return ds.space(ds.param("stops").space(stop).repeat(3))

    def test_in_range_instance_path_validates_against_the_element_domain(self):
        space = self._space()
        result = space.validate_param("stops[0].dwell_min", 30)
        assert result.valid

    def test_in_range_instance_path_rejects_out_of_domain_value(self):
        space = self._space()
        result = space.validate_param("stops[0].dwell_min", 999)
        assert not result.valid

    def test_a_different_instance_index_resolves_to_the_same_template(self):
        space = self._space()
        result = space.validate_param("stops[2].location", 5)
        assert result.valid


class TestStructLiftElementFieldIsItselfAnIndependentLift:
    """A struct-lift element whose own field is an independent scalar lift.

    The shape is `.space(...).repeat(n)` where a field of the inner space is
    itself `.repeat()`-ed. The two-lift-level boundary does not reject it:
    that boundary covers a struct or choice element nested under more than
    one `.repeat()`, and a scalar-lift field one level inside a struct
    element is a different shape.
    """

    def _space(self):
        row = ds.space(
            ds.param("label").integer(0, 10),
            ds.param("cells").real(0.0, 1.0).repeat(2),
        )
        return ds.space(ds.param("rows").space(row).repeat(2))

    def test_resolves(self):
        space = self._space()
        # n/a top-level count; rows, rows[].label, rows[].cells
        assert "rows" in space.params
        assert space.params["rows[].cells"].domain.element_kind == "real"

    def test_draws_and_validates(self):
        space = self._space()
        configs = space.sample_dicts(20, seed=0)
        for cfg in configs:
            assert len(cfg["rows"]) == 2
            for row in cfg["rows"]:
                assert len(row["cells"]) == 2
            result = space.validate(cfg)
            assert result.valid

    def test_flatten_unflatten_round_trip(self):
        from designspace.config import unflatten

        space = self._space()
        config = {
            "rows": [
                {"label": 1, "cells": [0.1, 0.2]},
                {"label": 2, "cells": [0.3, 0.4]},
            ]
        }
        flat = flatten(config, space)
        assert unflatten(flat, space) == config
