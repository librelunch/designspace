"""Variadic BoolExpr/ArithExpr constructors: `ds.all_`, `ds.any_`, `ds.count`."""

from __future__ import annotations

from designspace.expr._ast import BoolExpr, BoolLiteral, Count


def _check_bool_exprs(fn_name: str, exprs: tuple[BoolExpr, ...]) -> None:
    for e in exprs:
        if not isinstance(e, BoolExpr):
            raise TypeError(
                f"ds.{fn_name}() requires BoolExpr arguments, got {type(e).__name__}"
            )


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
