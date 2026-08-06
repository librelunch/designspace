"""M0 gate: expression-node construction, guardrails, all_/any_/count, hash/immutability.

No evaluation or resolution is exercised here — these nodes are pure, unresolved
AST fragments built directly against designspace.expr (ds.param does not exist
until M1's builder/).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from hypothesis import given
from hypothesis import strategies as st

import designspace as ds
from designspace.expr import (
    ArithOp,
    BoolLiteral,
    BoolOp,
    Compare,
    Count,
    IfInactive,
    Implies,
    IsActive,
    IsIn,
    Literal,
    Not,
    Value,
)


def lit(value: float) -> Literal:
    return Literal(value)


def blit(value: bool = True) -> BoolLiteral:
    return BoolLiteral(value)


class TestComparisons:
    @pytest.mark.parametrize(
        ("op", "kind"),
        [
            (lambda a, b: a == b, "eq"),
            (lambda a, b: a != b, "ne"),
            (lambda a, b: a > b, "gt"),
            (lambda a, b: a < b, "lt"),
            (lambda a, b: a >= b, "ge"),
            (lambda a, b: a <= b, "le"),
        ],
    )
    def test_expr_vs_expr(self, op, kind):
        a, b = lit(1.0), lit(2.0)
        node = op(a, b)
        assert isinstance(node, Compare)
        assert node.kind == kind
        assert node.children[0] is a
        assert node.children[1] is b

    def test_literal_rhs_is_wrapped(self):
        a = lit(1.0)
        node = a > 3
        assert isinstance(node, Compare)
        assert node.right.value == 3

    def test_reflected_comparison_swaps_and_flips_op(self):
        a = lit(1.0)
        node = 5 > a  # noqa: SIM300 -- intentionally testing __gt__/__lt__ reflection
        assert isinstance(node, Compare)
        assert node.kind == "lt"
        assert node.left is a
        assert node.right.value == 5

    def test_roundtrip(self):
        node = lit(1.0) > lit(2.0)
        rebuilt = Compare(node.kind, *node.children)
        assert rebuilt.kind == node.kind
        assert rebuilt.children[0] is node.children[0]
        assert rebuilt.children[1] is node.children[1]


class TestArithmetic:
    @pytest.mark.parametrize(
        ("op", "kind"),
        [
            (lambda a, b: a + b, "add"),
            (lambda a, b: a - b, "sub"),
            (lambda a, b: a * b, "mul"),
            (lambda a, b: a / b, "div"),
            (lambda a, b: a**b, "pow"),
            (lambda a, b: a % b, "mod"),
        ],
    )
    def test_expr_vs_expr(self, op, kind):
        a, b = lit(2.0), lit(3.0)
        node = op(a, b)
        assert isinstance(node, ArithOp)
        assert node.kind == kind
        assert node.left is a
        assert node.right is b

    @pytest.mark.parametrize(
        ("op", "kind"),
        [
            (lambda a: 1 + a, "add"),
            (lambda a: 1 - a, "sub"),
            (lambda a: 2 * a, "mul"),
            (lambda a: 2 / a, "div"),
            (lambda a: 2**a, "pow"),
            (lambda a: 2 % a, "mod"),
        ],
    )
    def test_reflected_literal_lhs(self, op, kind):
        a = lit(3.0)
        node = op(a)
        assert isinstance(node, ArithOp)
        assert node.kind == kind
        assert node.left.value in (1, 2)
        assert node.right is a

    def test_roundtrip(self):
        node = lit(2.0) + lit(3.0)
        rebuilt = ArithOp(node.kind, *node.children)
        assert rebuilt.left is node.left
        assert rebuilt.right is node.right


class TestBoolOps:
    def test_and(self):
        a, b = blit(True), blit(False)
        node = a & b
        assert isinstance(node, BoolOp)
        assert node.kind == "and"
        assert node.children[0] is a
        assert node.children[1] is b

    def test_or(self):
        a, b = blit(True), blit(False)
        node = a | b
        assert isinstance(node, BoolOp)
        assert node.kind == "or"
        assert node.children[0] is a
        assert node.children[1] is b

    def test_not(self):
        a = blit(True)
        node = ~a
        assert isinstance(node, Not)
        assert node.kind == "not"
        assert node.children[0] is a

    def test_and_rejects_non_boolexpr(self):
        with pytest.raises(TypeError):
            blit(True) & lit(1.0)  # type: ignore[operator]

    def test_or_rejects_non_boolexpr(self):
        with pytest.raises(TypeError):
            blit(True) | lit(1.0)  # type: ignore[operator]

    def test_boolop_roundtrip(self):
        node = blit(True) & blit(False)
        rebuilt = BoolOp(node.kind, *node.children)
        assert rebuilt.left is node.left
        assert rebuilt.right is node.right

    def test_not_roundtrip(self):
        node = ~blit(True)
        rebuilt = Not(*node.children)
        assert rebuilt.operand is node.operand


class TestImplies:
    def test_implies_builds_node(self):
        a, b = blit(True), blit(False)
        node = a.implies(b)
        assert isinstance(node, Implies)
        assert node.kind == "implies"
        assert node.children[0] is a
        assert node.children[1] is b

    def test_implies_requires_boolexpr(self):
        with pytest.raises(TypeError):
            blit(True).implies(lit(1.0))  # type: ignore[arg-type]

    def test_roundtrip(self):
        node = blit(True).implies(blit(False))
        rebuilt = Implies(*node.children)
        assert rebuilt.left is node.left
        assert rebuilt.right is node.right


class TestIsInIsActive:
    def test_is_in(self):
        a = lit(1.0)
        node = a.is_in(1, 2, 3)
        assert isinstance(node, IsIn)
        assert node.kind == "is_in"
        assert node.children == (a,)
        assert node.values == (1, 2, 3)

    def test_is_active_on_arith(self):
        a = lit(1.0)
        node = a.is_active()
        assert isinstance(node, IsActive)
        assert node.kind == "is_active"
        assert node.children == (a,)

    def test_is_active_on_bool(self):
        a = blit(True)
        node = a.is_active()
        assert isinstance(node, IsActive)
        assert node.children == (a,)

    def test_is_in_roundtrip(self):
        node = lit(1.0).is_in(1, 2)
        rebuilt = IsIn(node.children[0], node.values)
        assert rebuilt.operand is node.operand
        assert rebuilt.values == node.values


class TestCount:
    def test_count_builds_node(self):
        a, b, c = blit(True), blit(False), blit(True)
        node = ds.count(a, b, c)
        assert isinstance(node, Count)
        assert node.kind == "count"
        assert node.children == (a, b, c)

    def test_count_is_arith_expr_comparable(self):
        a, b = blit(True), blit(False)
        node = ds.count(a, b) >= 2
        assert isinstance(node, Compare)
        assert node.kind == "ge"
        assert isinstance(node.left, Count)

    def test_count_rejects_non_boolexpr(self):
        with pytest.raises(TypeError):
            ds.count(lit(1.0))  # type: ignore[arg-type]

    def test_count_zero_args(self):
        node = ds.count()
        assert isinstance(node, Count)
        assert node.children == ()


class TestIfInactive:
    def test_literal_fallback_wrapped(self):
        a = lit(1.0)
        node = a.if_inactive(0)
        assert isinstance(node, IfInactive)
        assert node.kind == "if_inactive"
        assert node.operand is a
        assert node.fallback.value == 0

    def test_expr_fallback(self):
        a, b = lit(1.0), lit(2.0)
        node = a.if_inactive(b)
        assert node.fallback is b

    def test_roundtrip(self):
        node = lit(1.0).if_inactive(lit(0.0))
        rebuilt = IfInactive(*node.children)
        assert rebuilt.operand is node.operand
        assert rebuilt.fallback is node.fallback


class TestValueConstruction:
    """`ds.value(fn, *operands, returns=type)` — the second (and, per API.md's
    Out of Scope list, final) opaque expression leaf, dual-typed like `Prop`.
    Row 30's error paths (non-scalar `returns`, a non-expression operand)
    and every evaluation/resolution/identity law live in
    tests/conformance/test_opaque_values.py; this file stays scoped to M0's
    "construction only" surface."""

    def test_builds_node(self):
        a, b = lit(1.0), lit(2.0)

        def fn(x: float, y: float) -> float:
            return x + y

        node = ds.value(fn, a, b, returns=float)
        assert isinstance(node, Value)
        assert node.kind == "value"
        assert node.children == (a, b)
        assert node.fn is fn
        assert node.returns is float

    def test_zero_operands(self):
        node = ds.value(lambda: True, returns=bool)
        assert node.children == ()

    def test_dual_typed_as_arith(self):
        node = ds.value(lambda: 1, returns=int)
        cmp = node > 0
        assert isinstance(cmp, Compare)
        assert cmp.kind == "gt"

    def test_dual_typed_as_bool(self):
        node = ds.value(lambda: True, returns=bool)
        combined = node & blit(True)
        assert isinstance(combined, BoolOp)
        assert combined.kind == "and"

    def test_is_hashable(self):
        assert isinstance(hash(ds.value(lambda: True, returns=bool)), int)

    def test_is_frozen(self):
        node = ds.value(lambda: True, returns=bool)
        with pytest.raises(FrozenInstanceError):
            node.returns = int  # type: ignore[misc]


class TestAllAny:
    def test_all_zero_args_is_true_literal(self):
        node = ds.all_()
        assert isinstance(node, BoolLiteral)
        assert node.value is True

    def test_any_zero_args_is_false_literal(self):
        node = ds.any_()
        assert isinstance(node, BoolLiteral)
        assert node.value is False

    def test_all_single_arg_is_identity(self):
        a = blit(True)
        assert ds.all_(a) is a

    def test_any_single_arg_is_identity(self):
        a = blit(True)
        assert ds.any_(a) is a

    def test_all_folds_and_in_order(self):
        a, b, c = blit(True), blit(False), blit(True)
        node = ds.all_(a, b, c)
        assert isinstance(node, BoolOp)
        assert node.kind == "and"
        assert node.right is c
        inner = node.left
        assert isinstance(inner, BoolOp)
        assert inner.kind == "and"
        assert inner.left is a
        assert inner.right is b

    def test_any_folds_or_in_order(self):
        a, b, c = blit(True), blit(False), blit(True)
        node = ds.any_(a, b, c)
        assert isinstance(node, BoolOp)
        assert node.kind == "or"
        assert node.right is c
        inner = node.left
        assert isinstance(inner, BoolOp)
        assert inner.kind == "or"
        assert inner.left is a
        assert inner.right is b

    def test_all_rejects_non_boolexpr(self):
        with pytest.raises(TypeError):
            ds.all_(lit(1.0))  # type: ignore[arg-type]

    def test_any_rejects_non_boolexpr(self):
        with pytest.raises(TypeError):
            ds.any_(lit(1.0))  # type: ignore[arg-type]


class TestParams:
    def test_params_empty_without_param_refs(self):
        # M0 has no param-referencing leaf (that lands in builder/ at M1);
        # params is exercised here only for the empty case.
        node = (lit(1.0) + lit(2.0)) > 3
        assert node.params == frozenset()

    def test_params_union_recurses_through_children(self):
        node = ds.all_(blit(True), blit(False) & blit(True))
        assert node.params == frozenset()


class TestGuardrails:
    def test_bool_raises_on_boolexpr(self):
        with pytest.raises(TypeError):
            bool(blit(True))

    def test_bool_raises_on_arithexpr(self):
        with pytest.raises(TypeError):
            bool(lit(1.0))

    def test_and_keyword_raises(self):
        a, b = blit(True), blit(False)
        with pytest.raises(TypeError):
            a and b  # noqa: B018

    def test_chained_comparison_raises(self):
        a = lit(1.0)
        with pytest.raises(TypeError):
            0 < a < 1  # noqa: B015

    def test_contains_raises(self):
        a = lit(1.0)
        with pytest.raises(TypeError):
            5 in a  # noqa: B015


class TestImmutabilityHashability:
    def test_literal_is_frozen(self):
        node = lit(1.0)
        with pytest.raises(FrozenInstanceError):
            node.value = 2.0  # type: ignore[misc]

    def test_compare_is_frozen(self):
        node = lit(1.0) > lit(2.0)
        with pytest.raises(FrozenInstanceError):
            node.op = "ne"  # type: ignore[misc]

    def test_nodes_are_hashable(self):
        nodes = [
            lit(1.0),
            blit(True),
            lit(1.0) == lit(3.0),
            lit(1.0) + lit(1.0),
            ~blit(True),
            ds.all_(),
            ds.any_(),
            ds.count(blit(True)),
            lit(1.0).is_in(1, 2),
            lit(1.0).if_inactive(0),
        ]
        for node in nodes:
            assert isinstance(hash(node), int)

    @given(
        st.recursive(
            st.floats(allow_nan=False, allow_infinity=False).map(Literal),
            lambda children: st.tuples(children, children).map(
                lambda cs: ArithOp("add", cs[0], cs[1])
            ),
            max_leaves=8,
        )
    )
    def test_arith_trees_hashable_and_frozen(self, node):
        assert isinstance(hash(node), int)
        with pytest.raises(FrozenInstanceError):
            node.anything = 1  # type: ignore[attr-defined]
