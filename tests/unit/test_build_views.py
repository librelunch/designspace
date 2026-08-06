"""M4.6 gate: build-layer view types (API.md, "Builder view types";
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
from designspace import (
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
from designspace.ir import CategoricalDomain, QuantizedSpec, RealDomain


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
        assert isinstance(ds.param("x").space(ds.param("y").bool()), StructParamExpr)

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
        # API.md: "BoolParamExpr is additionally a BoolExpr (a boolean
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
        chained = ds.param("x").categorical("a", "b").tag("t").meta(k=1).default("a")
        assert isinstance(chained, CategoricalParamExpr)

    def test_when_preserves_view(self):
        chained = ds.param("x").integer(0, 5).when(ds.param("flag"))
        assert isinstance(chained, IntegerParamExpr)


class TestRow2SecondTypeMethod:
    """API.md, "Builder view types": choosing a second type still raises
    the path-named row-2 ResolutionError, caught immediately on the fluent
    route (before any `ds.space()` call, since the narrowed view simply
    lacks the method). The "however it was built" half of the law — a
    hand-built definition that bypasses the fluent builder — is covered
    more strongly in TestTypeKindIsNotAConstructorArgument below: since
    DECISIONS.md D-28, there is no longer a resolution-time check to test,
    because there is no longer any way to *construct* such an object at
    all."""

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


class TestTypeKindIsNotAConstructorArgument:
    """DECISIONS.md D-28: `type_kind` moved from a plain field to a
    `ClassVar` fixed per view, excluded from `__init__` everywhere in the
    hierarchy. This makes row 2's "however it was built" guarantee
    structural rather than checked: there is no longer any way — fluent or
    hand-built — to construct an object whose `type_kind` disagrees with
    its class, so `ParamExpr(type_kind=...)` fails before resolution (or
    `_check_types_and_names`) ever runs."""

    def test_base_paramexpr_rejects_type_kind_kwarg(self):
        with pytest.raises(TypeError):
            ParamExpr(path="x", type_kind="integer")  # type: ignore[call-arg]

    def test_leaf_view_rejects_type_kind_kwarg(self):
        with pytest.raises(TypeError):
            RealParamExpr(  # type: ignore[call-arg]
                path="x", domain=RealDomain(0.0, 1.0), type_kind="integer"
            )

    def test_fresh_param_expr_type_kind_is_none(self):
        assert ds.param("x").type_kind is None

    def test_leaf_type_kind_matches_class(self):
        assert ds.param("x").real(0.0, 1.0).type_kind == "real"
        assert ds.param("x").integer(0, 5).type_kind == "integer"


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
        # _check_modifier_placement's backstop, unaffected by D-28: unlike
        # type_kind, quantized_spec remains a plain, freely-settable field
        # on every view — .quantized() just isn't the route to it here. A
        # CategoricalParamExpr built directly (bypassing .quantized(),
        # which doesn't exist on this view) can still carry one, and
        # resolution still has to catch it.
        bad = CategoricalParamExpr(
            path="x",
            domain=CategoricalDomain(("a", "b")),
            quantized_spec=QuantizedSpec(step=1.0, factor=None),
        )
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(bad)


class TestUnrelatedAttributeMissStaysPlainAttributeError:
    def test_unknown_attribute_raises_attribute_error(self):
        with pytest.raises(AttributeError):
            ds.param("x").bool().not_a_real_method()  # type: ignore[attr-defined]
