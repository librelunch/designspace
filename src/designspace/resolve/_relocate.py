"""Structural relocation: merging an already-resolved child `Space` (a
`.choice()` variant payload, or a `.space()` struct payload) into the flat
IR of its enclosing scope (API_v3.md, "Paths and Scoping" — relocatability;
"Expressions" rule 3 — cascading deactivation).

A child Space resolves standalone and eagerly: `ParamExpr.space()`/
`.choice()` (build/_paramexpr.py) call `resolve_space` immediately on the
payload's exprs, so every reference inside it was already checked (row 6)
against *its own* scope alone (see DECISIONS.md for why an escaping
`.when()` reference from inside an inline payload is therefore
unsupported). Relocation only ever (1) reprefixes the child's own paths —
a pure rename, since every leaf reference is guaranteed to already be a
hit in the rename map — and (2) folds in the enclosing activation
condition (the struct's own `.when()`, or the choice discriminator's
`== variant` equality) so deactivation cascades down through nesting via
the same Kleene rule 3 the flat M2 evaluator already implements. No new
evaluator machinery is needed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

from designspace.build._paramexpr import ParamExpr
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
    Implies,
    IsActive,
    IsIn,
    Literal,
    Not,
    PositionOf,
    Size,
    SumOver,
)
from designspace.ir import Condition, Constraint, ParamDef


def rewrite_expr(node: Expr, rename: Mapping[str, str]) -> Expr:
    """Rebuild `node` with every `ParamExpr` leaf's path substituted per
    `rename`. Every leaf here is guaranteed to be a hit (see module
    docstring) — an unmatched path would mean the child's own eager
    resolution let an undeclared reference through, which row 6 forbids.
    """
    if isinstance(node, ParamExpr):
        new_path = rename.get(node.path, node.path)
        return replace(node, path=new_path) if new_path != node.path else node
    if isinstance(node, Literal | BoolLiteral):
        return node
    if isinstance(node, Compare):
        return Compare(
            node.op,
            cast(ArithExpr, rewrite_expr(node.left, rename)),
            cast(ArithExpr, rewrite_expr(node.right, rename)),
        )
    if isinstance(node, ArithOp):
        return ArithOp(
            node.op,
            cast(ArithExpr, rewrite_expr(node.left, rename)),
            cast(ArithExpr, rewrite_expr(node.right, rename)),
        )
    if isinstance(node, BoolOp):
        return BoolOp(
            node.op,
            cast(BoolExpr, rewrite_expr(node.left, rename)),
            cast(BoolExpr, rewrite_expr(node.right, rename)),
        )
    if isinstance(node, Not):
        return Not(cast(BoolExpr, rewrite_expr(node.operand, rename)))
    if isinstance(node, Implies):
        return Implies(
            cast(BoolExpr, rewrite_expr(node.left, rename)),
            cast(BoolExpr, rewrite_expr(node.right, rename)),
        )
    if isinstance(node, IsIn):
        return IsIn(cast(ArithExpr, rewrite_expr(node.operand, rename)), node.values)
    if isinstance(node, IsActive):
        return IsActive(rewrite_expr(node.operand, rename))
    if isinstance(node, Count):
        return Count(tuple(cast(BoolExpr, rewrite_expr(o, rename)) for o in node.operands))
    if isinstance(node, IfInactive):
        return IfInactive(
            cast(ArithExpr, rewrite_expr(node.operand, rename)),
            cast(ArithExpr, rewrite_expr(node.fallback, rename)),
        )
    if isinstance(node, Contains):
        return Contains(cast(ArithExpr, rewrite_expr(node.operand, rename)), node.item)
    if isinstance(node, Size):
        return Size(cast(ArithExpr, rewrite_expr(node.operand, rename)))
    if isinstance(node, SumOver):
        return SumOver(cast(ArithExpr, rewrite_expr(node.operand, rename)), node.mapping)
    if isinstance(node, PositionOf):
        return PositionOf(cast(ArithExpr, rewrite_expr(node.operand, rename)), node.item)
    raise TypeError(f"cannot relocate expr kind {node.kind!r}")  # pragma: no cover


def rewrite_bool(expr: BoolExpr, rename: Mapping[str, str]) -> BoolExpr:
    return cast(BoolExpr, rewrite_expr(expr, rename))


def and_(a: BoolExpr | None, b: BoolExpr | None) -> BoolExpr | None:
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def relocate_child(
    child: Any,  # designspace.build._space.Space; Any avoids an import cycle
    new_prefix: str,
    injected_condition: BoolExpr | None,
) -> tuple[dict[str, ParamDef], list[Condition], list[Constraint]]:
    """Reprefix every param/condition/constraint in `child` under
    `new_prefix` (e.g. `"layers."` or `"algo.svm."`), folding
    `injected_condition` (the struct's own `.when()`, or the choice
    discriminator's `== variant` equality) into each descendant's own
    condition. `child.constraints` need no condition injection: a
    constraint referencing a now-inactive descendant param already goes
    Kleene-inapplicable on its own (rule 4) once that param's activity is
    gated — no separate wrapping is needed.
    """
    rename = {old_path: f"{new_prefix}{old_path}" for old_path in child.params}
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    for old_path, pd in child.params.items():
        new_path = rename[old_path]
        own_condition = rewrite_bool(pd.condition, rename) if pd.condition is not None else None
        final_condition = and_(own_condition, injected_condition)
        params[new_path] = replace(pd, path=new_path, condition=final_condition)
        if final_condition is not None:
            conditions.append(
                Condition(target=new_path, expr=final_condition, params=final_condition.params)
            )
    constraints: list[Constraint] = []
    for c in child.constraints:
        new_expr = rewrite_bool(c.expr, rename)
        constraints.append(replace(c, expr=new_expr, params=new_expr.params))
    return params, conditions, constraints
