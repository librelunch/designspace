"""Kleene evaluation (API_v3.md, "Expressions" > "Three-valued semantics").

`Unknown` arises only from inactivity (rule 1) — M2 has no partial-config
API yet (M6), so there is no separate "pending" state to confuse it with
(rule 5 becomes meaningful only once one exists); an "active but missing
from config" leaf is a caller bug, not a spec state, and is treated the same
as inactive here defensively so evaluation degrades rather than crashes —
`validate()` is what must still report it as a `ParamError("missing")`.

Every evaluator here takes `space` (not just `config`/`activity`), because
ordinal ordering compares by *declaration position*, not by the raw value
("Ordered by declaration position. Comparison yes, arithmetic no.") — a
leaf's domain has to be looked up to translate its value to an index before
`>`/`<`/`>=`/`<=` mean anything.

Internal to the library: not part of the public surface (mirrors how
`resolve_space` isn't re-exported either).
"""

from __future__ import annotations

from typing import Any

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.expr import (
    ArithExpr,
    ArithOp,
    BoolExpr,
    BoolLiteral,
    BoolOp,
    Compare,
    Contains,
    Count,
    Expr,
    IfInactive,
    IsActive,
    IsIn,
    Literal,
    Not,
    PositionOf,
    Size,
    SumOver,
)
from designspace.ir import OrdinalDomain


class Unknown:
    """Kleene's third truth value. A singleton; compare with `is`."""

    _instance: Unknown | None = None

    def __new__(cls) -> Unknown:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "Unknown"


UNKNOWN = Unknown()

Kleene = bool | Unknown


def _leaf_value(path: str, config: dict[str, Any], activity: dict[str, bool]) -> Any | Unknown:
    if not activity.get(path, True):
        return UNKNOWN
    if path not in config:
        return UNKNOWN
    return config[path]


def _values_equal(a: Any, b: Any) -> bool:
    """Equality for `Compare`/`IsIn` leaves.

    Bool is type-tagged (Python's `True == 1` would otherwise leak through);
    int/float compare numerically (`5 == 5.0`), matching real/integer domains
    where the distinction is never meaningful — everything else (str, and
    any other `Any`-typed categorical/ordinal value) requires an exact type
    match, matching declaration-time type-tagged distinctness (rows 3/4).
    See DECISIONS.md for the one gap this leaves: a categorical/ordinal
    domain that deliberately declares both `1` and `1.0` as distinct variants
    cannot be told apart by `==` at evaluation time.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return bool(a == b)
    if type(a) is not type(b):
        return False
    return bool(a == b)


def _ordinal_domain_of(node: Expr, space: Space) -> OrdinalDomain | None:
    if isinstance(node, ParamExpr):
        domain = space.params[node.path].domain
        if isinstance(domain, OrdinalDomain):
            return domain
    return None


def _ordinal_index(domain: OrdinalDomain, value: Any) -> int | Unknown:
    """`value`'s declaration-position index, or Unknown if it isn't a member
    (a malformed config — `validate()` is what reports that, not this)."""
    for i, v in enumerate(domain.values):
        if type(v) is type(value) and v == value:
            return i
    return UNKNOWN


def _apply_compare(op: str, left: Any, right: Any) -> bool:
    if op == "eq":
        return _values_equal(left, right)
    if op == "ne":
        return not _values_equal(left, right)
    if op == "gt":
        return bool(left > right)
    if op == "lt":
        return bool(left < right)
    if op == "ge":
        return bool(left >= right)
    if op == "le":
        return bool(left <= right)
    raise ValueError(f"unknown compare op {op!r}")


def _is_integer_valued(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def _count_range(
    node: Count, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> tuple[int, int]:
    """`(true_count, unknown_count)` — API_v3.md: `ds.count` tracks `[t, t + u]`."""
    t = 0
    u = 0
    for operand in node.operands:
        v = evaluate_bool(operand, config, activity, space)
        if isinstance(v, Unknown):
            u += 1
        elif v:
            t += 1
    return t, u


def _count_vs_threshold(op: str, t: int, u: int, threshold: Any) -> Kleene:
    hi = t + u
    achievable = _is_integer_valued(threshold) and t <= threshold <= hi
    if op in ("lt", "le", "gt", "ge"):
        lo_result = _apply_compare(op, t, threshold)
        hi_result = _apply_compare(op, hi, threshold)
        return lo_result if lo_result == hi_result else UNKNOWN
    if op == "eq":
        if not achievable:
            return False
        return UNKNOWN if u > 0 else True
    if op == "ne":
        if not achievable:
            return True
        return UNKNOWN if u > 0 else False
    raise ValueError(f"unknown compare op {op!r}")


def evaluate_arith(
    expr: ArithExpr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Any | Unknown:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ParamExpr):
        return _leaf_value(expr.path, config, activity)
    if isinstance(expr, ArithOp):
        left = evaluate_arith(expr.left, config, activity, space)
        right = evaluate_arith(expr.right, config, activity, space)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return UNKNOWN
        return _apply_arith(expr.op, left, right)
    if isinstance(expr, IfInactive):
        operand_val = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(operand_val, Unknown):
            return evaluate_arith(expr.fallback, config, activity, space)
        return operand_val
    if isinstance(expr, Count):
        t, u = _count_range(expr, config, activity, space)
        return t if u == 0 else UNKNOWN
    if isinstance(expr, Size):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else len(value)
    if isinstance(expr, SumOver):
        value = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(value, Unknown):
            return UNKNOWN
        # Missing mapping keys contribute 0 (spec: mapping keys ⊆ item
        # universe, so partial coverage is legal — see DECISIONS.md).
        return sum(expr.mapping.get(item, 0) for item in value)
    if isinstance(expr, PositionOf):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else value.index(expr.item)
    raise TypeError(f"cannot evaluate arith expr kind {expr.kind!r}")


def _apply_arith(op: str, left: Any, right: Any) -> Any:
    if op == "add":
        return left + right
    if op == "sub":
        return left - right
    if op == "mul":
        return left * right
    if op == "div":
        return left / right
    if op == "pow":
        return left**right
    if op == "mod":
        return left % right
    raise ValueError(f"unknown arith op {op!r}")


def _kleene_and(a: Kleene, b: Kleene) -> Kleene:
    if a is False or b is False:
        return False
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        return UNKNOWN
    return True


def _kleene_or(a: Kleene, b: Kleene) -> Kleene:
    if a is True or b is True:
        return True
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        return UNKNOWN
    return False


def evaluate_bool(
    expr: BoolExpr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Kleene:
    if isinstance(expr, BoolLiteral):
        return expr.value
    if isinstance(expr, ParamExpr):
        v = _leaf_value(expr.path, config, activity)
        return UNKNOWN if isinstance(v, Unknown) else bool(v)
    if isinstance(expr, Compare):
        if isinstance(expr.left, Count) or isinstance(expr.right, Count):
            return _evaluate_count_compare(expr, config, activity, space)
        left = evaluate_arith(expr.left, config, activity, space)
        right = evaluate_arith(expr.right, config, activity, space)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return UNKNOWN
        if expr.op in ("gt", "lt", "ge", "le"):
            ordinal_domain = _ordinal_domain_of(expr.left, space) or _ordinal_domain_of(
                expr.right, space
            )
            if ordinal_domain is not None:
                left = _ordinal_index(ordinal_domain, left)
                right = _ordinal_index(ordinal_domain, right)
                if isinstance(left, Unknown) or isinstance(right, Unknown):
                    return UNKNOWN
        return _apply_compare(expr.op, left, right)
    if isinstance(expr, BoolOp):
        left_v = evaluate_bool(expr.left, config, activity, space)
        right_v = evaluate_bool(expr.right, config, activity, space)
        return _kleene_and(left_v, right_v) if expr.op == "and" else _kleene_or(left_v, right_v)
    if isinstance(expr, Not):
        v = evaluate_bool(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(v, Unknown) else (not v)
    if isinstance(expr, IsIn):
        operand = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(operand, Unknown):
            return UNKNOWN
        return any(_values_equal(operand, v) for v in expr.values)
    if isinstance(expr, IsActive):
        return all(activity.get(p, True) for p in expr.operand.params)
    if isinstance(expr, Contains):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else expr.item in value
    raise TypeError(f"cannot evaluate bool expr kind {expr.kind!r}")


def _evaluate_count_compare(
    expr: Compare, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Kleene:
    if isinstance(expr.left, Count):
        count_node, other_side, count_is_left = expr.left, expr.right, True
    else:
        assert isinstance(expr.right, Count)
        count_node, other_side, count_is_left = expr.right, expr.left, False
    other_val = evaluate_arith(other_side, config, activity, space)
    if isinstance(other_val, Unknown):
        return UNKNOWN
    t, u = _count_range(count_node, config, activity, space)
    op = expr.op
    if not count_is_left:
        op = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le"}.get(op, op)
    return _count_vs_threshold(op, t, u, other_val)


def compute_activity(space: Space, config: dict[str, Any]) -> dict[str, bool]:
    """Activity per param, walking the condition dependency order (rule 3:
    Unknown coerces to False at `.when()`, cascading deactivation)."""
    activity: dict[str, bool] = {}
    conditions_by_target = {c.target: c for c in space.conditions}
    for path in topological_order(space):
        condition = conditions_by_target.get(path)
        if condition is None:
            activity[path] = True
        else:
            value = evaluate_bool(condition.expr, config, activity, space)
            activity[path] = value is True
    return activity


def topological_order(space: Space) -> list[str]:
    """Params in an order where each one's condition dependencies come first.

    Not the public `.topological_order` (M6, Partial Configs) — an internal
    ordering the sampler and activity computation both need now.
    """
    conditions_by_target = {c.target: c for c in space.conditions}
    order: list[str] = []
    done: set[str] = set()

    def visit(path: str) -> None:
        if path in done:
            return
        condition = conditions_by_target.get(path)
        if condition is not None:
            for dep in condition.params:
                visit(dep)
        done.add(path)
        order.append(path)

    for path in space.params:
        visit(path)
    return order
