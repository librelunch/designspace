"""Variadic BoolExpr/ArithExpr constructors: `ds.all_`, `ds.any_`, `ds.count`,
`ds.value`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from designspace.errors import ResolutionError
from designspace.expr._ast import SCALAR_TYPES, BoolExpr, BoolLiteral, Count, Expr, Value


def _check_bool_exprs(fn_name: str, exprs: tuple[BoolExpr, ...]) -> None:
    for e in exprs:
        if not isinstance(e, BoolExpr):
            raise TypeError(f"ds.{fn_name}() requires BoolExpr arguments, got {type(e).__name__}")


def all_(*exprs: BoolExpr) -> BoolExpr:
    """AND-fold; zero args yields the literal True (the AND identity)."""
    _check_bool_exprs("all_", exprs)
    if not exprs:
        return BoolLiteral(True)
    result = exprs[0]
    for e in exprs[1:]:
        result = result & e
    return result


def any_(*exprs: BoolExpr) -> BoolExpr:
    """OR-fold; zero args yields the literal False (the OR identity)."""
    _check_bool_exprs("any_", exprs)
    if not exprs:
        return BoolLiteral(False)
    result = exprs[0]
    for e in exprs[1:]:
        result = result | e
    return result


def count(*exprs: BoolExpr) -> Count:
    """Number of True operands among `exprs` (an ArithExpr)."""
    _check_bool_exprs("count", exprs)
    return Count(tuple(exprs))


def value(fn: Callable[..., Any], *operands: Expr, returns: type) -> Value:
    """`ds.value(fn, *operands, returns=type)`: an opaque derived quantity
    (API.md, "Expressions"). Row 30 checks both closed-set conditions at
    construction (the same "construction-time ResolutionError" precedent as
    `build/_views.py`'s modifier checks): `returns` must be scalar
    (int/float/bool/str), and every operand must itself be an expression —
    `fn` is called with exactly the operand *values*, never the config, so a
    non-expression argument (a bare Python literal, say) could never be
    evaluated. A non-callable `fn` is a misuse guard, not a row-30 case (no
    space is ever resolved with it), so it stays a plain `TypeError`.
    """
    if not callable(fn):
        raise TypeError(f"ds.value(): fn must be callable, got {type(fn).__name__}")
    if returns not in SCALAR_TYPES:
        raise ResolutionError(
            f"ds.value(): returns={returns!r} is not scalar-typed — only "
            "int/float/bool/str are expression-visible (row 30)"
        )
    for operand in operands:
        if not isinstance(operand, Expr):
            raise ResolutionError(f"ds.value(): operand {operand!r} is not an expression (row 30)")
    return Value(fn, operands, returns)
