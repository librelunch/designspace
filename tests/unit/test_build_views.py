"""M4.6 gate: build-layer view types (API_v3.md, "Builder view types";
DECISIONS.md D-27, D-28).

Pure build-layer typing sugar — no observable value, JSON format,
fingerprint, chart, or conformance-law change. These tests check the
class-shape guarantees (which view each type method/`.repeat()` returns,
that a second type method is a path-named `ResolutionError` "however it
was built", and that ordinary modifiers preserve the caller's view) that
M4.5-and-earlier tests never needed to assert.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.build import (
    BoolParamExpr,
    CategoricalParamExpr,
    ChoiceParamExpr,
    FreshParamExpr,
    IntegerParamExpr,
    ListParamExpr,
    OrdinalParamExpr,
    ParamExpr,
    PermutationParamExpr,
    RealParamExpr,
    StructParamExpr,
    SubsetParamExpr,
)
from designspace.errors import ResolutionError
from designspace.expr import BoolExpr
from designspace.ir import CategoricalDomain, IntegerDomain, QuantizedSpec


class TestParamReturnsFreshParamExpr:
    def test_param_is_fresh_and_base(self):
        x = ds.param("x")
        assert isinstance(x, FreshParamExpr)
        assert isinstance(x, ParamExpr)


class TestTypeMethodsReturnTypeSpecificViews:
    def test_real(self):
        assert isinstance(ds.param("x").real(0.0, 1.0), RealParamExpr)

    def test_integer(self):
        assert isinstance(ds.param("x").integer(0, 5), IntegerParamExpr)

    def test_categorical(self):
        assert isinstance(ds.param("x").categorical("a", "b"), CategoricalParamExpr)

    def test_ordinal(self):
        assert isinstance(ds.param("x").ordinal("a", "b"), OrdinalParamExpr)

    def test_bool(self):
        assert isinstance(ds.param("x").bool(), BoolParamExpr)

    def test_subset(self):
        assert isinstance(ds.param("x").subset(["a", "b"]), SubsetParamExpr)

    def test_permutation(self):
        assert isinstance(ds.param("x").permutation(["a", "b"]), PermutationParamExpr)

    def test_choice(self):
        assert isinstance(ds.param("x").choice("a", "b"), ChoiceParamExpr)

    def test_space(self):
        assert isinstance(
            ds.param("x").space(ds.param("y").bool()), StructParamExpr
        )

    def test_every_view_is_still_a_paramexpr(self):
        views = [
            ds.param("x").real(0.0, 1.0),
            ds.param("x").integer(0, 5),
            ds.param("x").categorical("a", "b"),
            ds.param("x").ordinal("a", "b"),
            ds.param("x").bool(),
            ds.param("x").subset(["a", "b"]),
            ds.param("x").permutation(["a", "b"]),
            ds.param("x").choice("a", "b"),
            ds.param("x").space(ds.param("y").bool()),
        ]
        assert all(isinstance(v, ParamExpr) for v in views)

    def test_bool_param_expr_is_also_a_bool_expr(self):
        # API_v3.md: "BoolParamExpr is additionally a BoolExpr (a boolean
        # param is usable directly as a condition)".
        assert isinstance(ds.param("x").bool(), BoolExpr)


class TestRepeatReturnsListParamExpr:
    def test_repeat_returns_list_param_expr(self):
        assert isinstance(ds.param("x").real(0.0, 1.0).repeat(4), ListParamExpr)

    def test_chained_repeat_returns_list_param_expr(self):
        lifted = ds.param("x").bool().repeat(8).repeat(8)
        assert isinstance(lifted, ListParamExpr)

    def test_variadic_repeat_returns_list_param_expr(self):
        lifted = ds.param("x").real(0.0, 1.0).repeat(2, 3)
        assert isinstance(lifted, ListParamExpr)

    def test_list_param_expr_still_resolves(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).repeat(4))
        assert space.params["x"].type_kind == "list"


class TestModifiersPreserveView:
    def test_log_scale_then_quantized_stays_real_param_expr(self):
        chained = ds.param("x").real(1e-5, 1.0).log_scale().quantized(step=0.1)
        assert isinstance(chained, RealParamExpr)

    def test_tag_when_meta_default_preserve_view(self):
        chained = (
            ds.param("x")
            .categorical("a", "b")
            .tag("t")
            .meta(k=1)
            .default("a")
        )
        assert isinstance(chained, CategoricalParamExpr)

    def test_when_preserves_view(self):
        chained = ds.param("x").integer(0, 5).when(ds.param("flag"))
        assert isinstance(chained, IntegerParamExpr)


class TestRow2SecondTypeMethod:
    """API_v3.md, "Builder view types": choosing a second type still raises
    the path-named row-2 ResolutionError "however it was built" — both the
    fluent route (now caught immediately, before any `ds.space()` call, by
    the narrowed view simply lacking the method) and a hand-built definition
    that bypasses the view system entirely (caught by the pre-existing
    `_check_types_and_names` resolution pass, unchanged)."""

    def test_fluent_second_type_method_raises_immediately(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.param("x").real(0.0, 1.0).bool()

    def test_fluent_second_type_method_is_resolution_error_not_attribute_error(self):
        with pytest.raises(ResolutionError):
            ds.param("x").categorical("a", "b").integer(0, 5)

    def test_fluent_still_raises_when_wrapped_in_space(self):
        # Existing M1 test shape (tests/unit/test_build_resolve.py) keeps
        # passing: the exception now fires while the argument expression is
        # evaluated, before ds.space() is even called, but pytest.raises
        # wraps the whole statement so this is unobservable from outside.
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).integer(0, 5))

    def test_programmatically_built_two_type_definition_raises(self):
        # Bypasses the view system entirely: a bare ParamExpr constructed
        # by hand with conflicting type_calls history, exactly as a
        # metaprogramming caller (not the fluent builder) might produce.
        bad = ParamExpr(
            path="x",
            type_kind="integer",
            type_calls=("real", "integer"),
            domain=IntegerDomain(0, 5),
        )
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(bad)


class TestRow11WrongTypeModifierIsStaticallyHidden:
    """The Gate's `.categorical(...).log_scale()` example: `.log_scale()`/
    `.quantized()` are removed from every view but Real/Integer (required
    for the static-typing check in test_static_typing.py), so misuse now
    surfaces through `__getattr__` — which must still raise row 11's
    ResolutionError, not degrade to a bare AttributeError (DECISIONS.md
    D-28)."""

    def test_log_scale_on_categorical_raises_resolution_error(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.param("x").categorical("a", "b").log_scale()

    def test_quantized_on_categorical_raises_resolution_error(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.param("x").categorical("a", "b").quantized(step=1)

    def test_quantized_on_categorical_still_raises_when_wrapped_in_space(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").quantized(step=1))

    def test_log_scale_after_repeat_still_says_row_11(self):
        with pytest.raises(ResolutionError, match="row 11"):
            ds.param("x").real(0.0, 1.0).repeat(4).log_scale()

    def test_quantized_after_repeat_still_says_row_11(self):
        with pytest.raises(ResolutionError, match="row 11"):
            ds.param("x").real(0.0, 1.0).repeat(4).quantized(step=0.1)

    def test_programmatically_built_quantized_on_categorical_raises(self):
        # The resolution-time backstop for _check_modifier_placement,
        # exercised the same way as the row-2 backstop above: a hand-built
        # ParamExpr that never went through .quantized() at all.
        bad = ParamExpr(
            path="x",
            type_kind="categorical",
            type_calls=("categorical",),
            domain=CategoricalDomain(("a", "b")),
            quantized_spec=QuantizedSpec(step=1.0, factor=None),
        )
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(bad)


class TestUnrelatedAttributeMissStaysPlainAttributeError:
    def test_unknown_attribute_raises_attribute_error(self):
        with pytest.raises(AttributeError):
            ds.param("x").bool().not_a_real_method()  # type: ignore[attr-defined]
