"""Variadic BoolExpr/ArithExpr constructors: `ds.all_`, `ds.any_`, `ds.count`,
`ds.value`."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from designspace.errors import ResolutionError
from designspace.expr._ast import SCALAR_TYPES, ArithExpr, BoolExpr, BoolLiteral, Count, Expr, Value

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


def _check_bool_exprs(fn_name: str, exprs: tuple[BoolExpr, ...]) -> None:
    for e in exprs:
        if not isinstance(e, BoolExpr):
            raise TypeError(f"ds.{fn_name}() requires BoolExpr arguments, got {type(e).__name__}")


def all_(*exprs: BoolExpr) -> BoolExpr:
    """Combine conditions with `and`.

    Python's own `and` cannot be used on expressions, since it would coerce
    them to a bool and lose the tree, so this is the n-ary form. It also
    behaves sensibly at zero arguments, which matters when the conditions
    are generated from a list that may be empty.

    Parameters
    ----------
    *exprs : BoolExpr
        Conditions to combine. With none, the result is the literal `True`,
        the identity of `and`.

    Returns
    -------
    BoolExpr
        The conjunction.

    Raises
    ------
    TypeError
        If any argument is not a boolean expression.

    Examples
    --------
    >>> s = ds.space(ds.param("a").bool(), ds.param("b").bool())
    >>> s = s.require(ds.all_(ds.param("a"), ds.param("b")))
    >>> s.is_feasible({"a": True, "b": True})
    True
    >>> s.is_feasible({"a": True, "b": False})
    False

    The empty fold constrains nothing:

    >>> ds.space(ds.param("x").bool()).require(ds.all_()).is_feasible({"x": True})
    True
    """
    _check_bool_exprs("all_", exprs)
    if not exprs:
        return BoolLiteral(True)
    result = exprs[0]
    for e in exprs[1:]:
        result = result & e
    return result


def any_(*exprs: BoolExpr) -> BoolExpr:
    """Combine conditions with `or`.

    The n-ary counterpart of `ds.all_()`, for the same reason: Python's
    `or` would coerce the expressions to bools.

    Parameters
    ----------
    *exprs : BoolExpr
        Conditions to combine. With none, the result is the literal
        `False`, the identity of `or`.

    Returns
    -------
    BoolExpr
        The disjunction.

    Raises
    ------
    TypeError
        If any argument is not a boolean expression.

    Examples
    --------
    >>> s = ds.space(ds.param("a").bool(), ds.param("b").bool())
    >>> s = s.require(ds.any_(ds.param("a"), ds.param("b")))
    >>> s.is_feasible({"a": False, "b": True})
    True
    >>> s.is_feasible({"a": False, "b": False})
    False
    """
    _check_bool_exprs("any_", exprs)
    if not exprs:
        return BoolLiteral(False)
    result = exprs[0]
    for e in exprs[1:]:
        result = result | e
    return result


def count(*exprs: BoolExpr) -> ArithExpr:
    """How many of `exprs` are true, as a number.

    The way to write "at most two of these", which is otherwise awkward:
    the result is arithmetic, so it can be compared.

    Parameters
    ----------
    *exprs : BoolExpr
        The conditions to count.

    Returns
    -------
    ArithExpr
        An integer-valued expression.

    Raises
    ------
    TypeError
        If any argument is not a boolean expression.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("a").bool(),
    ...     ds.param("b").bool(),
    ...     ds.param("c").bool(),
    ... )
    >>> s = s.require(ds.count(ds.param("a"), ds.param("b"), ds.param("c")) <= 2)
    >>> s.is_feasible({"a": True, "b": True, "c": False})
    True
    >>> s.is_feasible({"a": True, "b": True, "c": True})
    False
    """
    _check_bool_exprs("count", exprs)
    return Count(tuple(exprs))


def value(fn: Callable[..., Any], *operands: Expr, returns: type) -> Value:
    """Compute a derived quantity with your own function.

    An escape hatch for a constraint the expression language cannot say:
    a physical formula, a lookup, a simulation, without inventing a sham
    custom type just to hang a `.prop()` on.

    The trade is transparency. Prefer a plain expression when you can write
    one: the library can compute margins from it, narrow domains with
    `.remaining_domain()`, and tighten bounds during sampling, none of
    which it can do through an opaque function. A `returns=float` value
    still yields a usable margin; a `returns=bool` one is fully opaque and
    has no margin at all.

    `fn` is called with the operands' **values**, in order, never the
    configuration, so everything it reads must be passed as an operand.

    Parameters
    ----------
    fn : Callable[..., Any]
        Called with one value per operand. Not serializable: a space
        containing one cannot be written to JSON or fingerprinted without
        `on_unserializable="mark"`.
    *operands : Expr
        The expressions whose values `fn` receives. Every one must be an
        expression, not a bare literal.
    returns : type
        What `fn` returns: `int`, `float`, `bool`, or `str`.

    Returns
    -------
    Value
        An expression usable as a number or a condition, according to
        `returns`.

    Raises
    ------
    TypeError
        If `fn` is not callable.
    ResolutionError
        If `returns` is not a scalar type, or an operand is not an
        expression.

    Examples
    --------
    >>> def area(w, h):
    ...     return w * h
    >>> s = ds.space(ds.param("w").real(1, 10), ds.param("h").real(1, 10))
    >>> s = s.require(ds.value(area, ds.param("w"), ds.param("h"), returns=float) <= 20.0)
    >>> s.is_feasible({"w": 2.0, "h": 3.0})
    True
    >>> s.is_feasible({"w": 9.0, "h": 9.0})
    False
    >>> s.evaluate_constraints({"w": 2.0, "h": 3.0})[0].margin
    14.0
    """
    if not callable(fn):
        raise TypeError(f"ds.value(): fn must be callable, got {type(fn).__name__}")
    if returns not in SCALAR_TYPES:
        raise ResolutionError(
            f"ds.value(): returns={returns!r} is not scalar-typed; only "
            "int/float/bool/str are expression-visible"
        )
    for operand in operands:
        if not isinstance(operand, Expr):
            raise ResolutionError(f"ds.value(): operand {operand!r} is not an expression")
    return Value(fn, operands, returns)
