"""Margins (API.md, "Constraints and Feasibility" > "Margins").

`ConstraintEval.margin` is the signed distance to the boundary: positive
slack, negative violation, zero on the boundary. `None` absorbs through
Boolean composition (Kleene-Unknown leaves and non-numeric leaves both
yield `None`, per rule 4: inapplicable on a complete config).
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.eval._kleene import Unknown, evaluate_arith
from designspace.expr import BoolExpr, BoolOp, Compare, Not, Value


def _is_numeric(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def margin(
    expr: BoolExpr,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    value_cache: dict[Value, Any] | None = None,
) -> float | None:
    """`value_cache` (optional, identity-keyed on each `ds.value` node) lets
    a caller that already evaluated `expr` via `evaluate_bool` for
    satisfaction share those results here instead of re-invoking each
    `ds.value`'s `fn` a second time — `eval/_constraint_eval.py::
    evaluate_constraint` and `partial/_partial.py::_classify_constraint`
    both do exactly this. `None` (every other caller) computes exactly as
    before."""
    result = _margin(expr, config, activity, space, value_cache=value_cache)
    # Negation/eq/composition can land exactly on the boundary as IEEE-754
    # -0.0 (e.g. -abs(0.0), or negating a 0.0 inner margin); normalize so
    # "zero is on the boundary" is never observably signed.
    return 0.0 if result is not None and result == 0.0 else result


def _margin(
    expr: BoolExpr,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    value_cache: dict[Value, Any] | None = None,
) -> float | None:
    if isinstance(expr, Compare):
        left = evaluate_arith(expr.left, config, activity, space, value_cache=value_cache)
        right = evaluate_arith(expr.right, config, activity, space, value_cache=value_cache)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return None
        if not _is_numeric(left) or not _is_numeric(right):
            return None
        if expr.op in ("le", "lt"):
            return float(right - left)
        if expr.op in ("ge", "gt"):
            return float(left - right)
        if expr.op == "eq":
            return -abs(float(left - right))
        if expr.op == "ne":
            return abs(float(left - right))
        return None
    if isinstance(expr, BoolOp):
        left_m = margin(expr.left, config, activity, space, value_cache=value_cache)
        right_m = margin(expr.right, config, activity, space, value_cache=value_cache)
        if left_m is None or right_m is None:
            return None
        return min(left_m, right_m) if expr.op == "and" else max(left_m, right_m)
    if isinstance(expr, Not):
        inner = margin(expr.operand, config, activity, space, value_cache=value_cache)
        return None if inner is None else -inner
    return None
