"""Rendering an expression tree as infix text (API.md, "Human-Readable
Rendering").

Dispatch mirrors `identity/_tags.py`'s `encode_expr`, the package's other
exhaustive expression walk: same node order, same leaf precedence, so a
node kind added to one is easy to notice missing from the other. A
`ParamExpr` leaf renders as its bare path, exactly as `encode_expr` treats
it as a `"ref"`, never through its own declaration `__str__`
(`builder/_paramexpr.py`'s override), which is what a *standalone*
`str(param_expr)` shows instead.
"""

from __future__ import annotations

from typing import Any

from designspace.display._values import render_seq, render_value
from designspace.expr import (
    ArithOp,
    BoolLiteral,
    BoolOp,
    ChartApply,
    Compare,
    Contains,
    Count,
    CountOf,
    Distinct,
    Expr,
    Field,
    IfInactive,
    Implies,
    IsActive,
    IsIn,
    IsSorted,
    Length,
    Literal,
    Max,
    Min,
    Not,
    PositionOf,
    Prop,
    Size,
    Sum,
    SumOver,
    Value,
)

_COMPARE_SYMBOLS = {"eq": "==", "ne": "!=", "gt": ">", "lt": "<", "ge": ">=", "le": "<="}
_ARITH_SYMBOLS = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "**", "mod": "%"}

# Higher binds tighter. `implies` lowest, matching how it reads: "a implies
# b" is the outermost claim a constraint usually makes.
_PRECEDENCE = {
    "implies": 1,
    "or": 2,
    "and": 3,
    "not": 4,
    "cmp": 5,
    "add": 6,
    "sub": 6,
    "mul": 7,
    "div": 7,
    "mod": 7,
    "pow": 8,
}


def _wrap(text: str, *, inner: int, outer: int) -> str:
    return f"({text})" if inner < outer else text


def render_expr(node: Expr, *, prec: int = 0) -> str:
    """Render one expression node as infix text.

    Parameters
    ----------
    node : Expr
        The tree to render.
    prec : int
        The precedence context `node` sits in; a subtree binding looser
        than `prec` is parenthesized. `0` (the default) never
        parenthesizes the whole result.
    """
    # Deferred: builder/ depends on expr/ and ir/, so importing ParamExpr
    # at module scope here, in a module ir/ and builder/ classes are
    # decorated to reach lazily, would cycle.
    from designspace.builder._paramexpr import ParamExpr

    if isinstance(node, ParamExpr):  # a reference leaf; check before Literal
        return node.path
    if isinstance(node, BoolLiteral):
        return repr(node.value)
    if isinstance(node, Literal):
        return render_value(node.value)
    if isinstance(node, Compare):
        if isinstance(node.right, BoolLiteral) and node.op in ("eq", "ne"):
            is_true = (node.op == "eq") == node.right.value
            inner = render_expr(node.left, prec=_PRECEDENCE["not"])
            return inner if is_true else _wrap(f"not {inner}", inner=0, outer=prec)
        p = _PRECEDENCE["cmp"]
        text = (
            f"{render_expr(node.left, prec=p + 1)} {_COMPARE_SYMBOLS[node.op]} "
            f"{render_expr(node.right, prec=p + 1)}"
        )
        return _wrap(text, inner=p, outer=prec)
    if isinstance(node, ArithOp):
        p = _PRECEDENCE[node.op]
        text = (
            f"{render_expr(node.left, prec=p)} {_ARITH_SYMBOLS[node.op]} "
            f"{render_expr(node.right, prec=p + 1)}"
        )
        return _wrap(text, inner=p, outer=prec)
    if isinstance(node, BoolOp):
        p = _PRECEDENCE[node.op]
        # `and` nested directly inside `or` gets clarifying parens: correct
        # by precedence alone (`_PRECEDENCE["and"] > _PRECEDENCE["or"]`),
        # but easy to misread at a glance. `_PRECEDENCE["and"] + 1`, not
        # `p + 1`, is what forces it: an `and` child renders at exactly
        # `_PRECEDENCE["and"]`, so only a strictly higher bound wraps it.
        child_p = _PRECEDENCE["and"] + 1 if node.op == "or" else p
        text = (
            f"{render_expr(node.left, prec=child_p)} {node.op} "
            f"{render_expr(node.right, prec=child_p)}"
        )
        return _wrap(text, inner=p, outer=prec)
    if isinstance(node, Not):
        p = _PRECEDENCE["not"]
        return _wrap(f"not {render_expr(node.operand, prec=p)}", inner=p, outer=prec)
    if isinstance(node, Implies):
        p = _PRECEDENCE["implies"]
        text = f"{render_expr(node.left, prec=p + 1)} implies {render_expr(node.right, prec=p)}"
        return _wrap(text, inner=p, outer=prec)
    if isinstance(node, IsIn):
        return f"{render_expr(node.operand, prec=99)} in {render_seq(node.values)}"
    if isinstance(node, IsActive):
        return f"is_active({render_expr(node.operand)})"
    if isinstance(node, Count):
        return "count(" + ", ".join(render_expr(o) for o in node.operands) + ")"
    if isinstance(node, IfInactive):
        fallback = render_expr(node.fallback)
        return f"{render_expr(node.operand, prec=99)}.if_inactive({fallback})"
    if isinstance(node, Contains):
        return f"{render_value(node.item)} in {render_expr(node.operand, prec=99)}"
    if isinstance(node, Size):
        return f"size({render_expr(node.operand)})"
    if isinstance(node, SumOver):
        mapping = render_value(dict(node.mapping))
        return f"sum_over({render_expr(node.operand)}, {mapping})"
    if isinstance(node, PositionOf):
        return f"position_of({render_expr(node.operand)}, {render_value(node.item)})"
    if isinstance(node, Length):
        return f"length({render_expr(node.operand)})"
    if isinstance(node, Prop):
        return f"{render_expr(node.operand, prec=99)}.prop({node.name!r})"
    if isinstance(node, Value):
        fn_name = getattr(node.fn, "__name__", None) or repr(node.fn)
        return f"value({fn_name}, ...)"
    if isinstance(node, ChartApply):
        return f"{render_expr(node.operand, prec=99)}.chart()"
    if isinstance(node, Field):
        return f"{render_expr(node.operand, prec=99)}[].{node.name}"
    if isinstance(node, Sum):
        return f"sum({render_expr(node.operand)})"
    if isinstance(node, Min):
        return f"min({render_expr(node.operand)})"
    if isinstance(node, Max):
        return f"max({render_expr(node.operand)})"
    if isinstance(node, CountOf):
        return f"count_of({render_expr(node.operand)}, {render_seq(node.values)})"
    if isinstance(node, IsSorted):
        tail = ", descending=True" if node.descending else ""
        return f"is_sorted({render_expr(node.operand)}{tail})"
    if isinstance(node, Distinct):
        tail = ", " + render_value(node.fields) if node.fields else ""
        return f"distinct({render_expr(node.operand)}{tail})"
    return f"<{type(node).__name__}>"


def render_expr_standalone(node: Any) -> str:
    """`(self) -> str` entry point for `displayable`, decorating `Expr`."""
    return render_expr(node)
