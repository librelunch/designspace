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
from types import MappingProxyType
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
    Size,
    Sum,
    SumOver,
)
from designspace.ir import Condition, Constraint, ListDomain, ParamDef


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
    if isinstance(node, Length):
        return Length(cast(ArithExpr, rewrite_expr(node.operand, rename)))
    if isinstance(node, Field):
        return Field(rewrite_expr(node.operand, rename), node.name)
    if isinstance(node, Sum):
        return Sum(rewrite_expr(node.operand, rename))
    if isinstance(node, Min):
        return Min(rewrite_expr(node.operand, rename))
    if isinstance(node, Max):
        return Max(rewrite_expr(node.operand, rename))
    if isinstance(node, CountOf):
        return CountOf(rewrite_expr(node.operand, rename), node.values)
    if isinstance(node, IsSorted):
        return IsSorted(rewrite_expr(node.operand, rename), node.descending)
    if isinstance(node, Distinct):
        return Distinct(rewrite_expr(node.operand, rename), node.fields)
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


def instantiate_element(
    space: Any,  # designspace.build._space.Space; Any avoids an import cycle
    template_prefix: str,
    concrete_prefix: str,
) -> tuple[dict[str, ParamDef], list[Condition]]:
    """Expand one lift instance's descendant *template* — already merged
    into `space.params` under a `"[]"`-bracketed prefix (e.g.
    `"edges[]."`) by `relocate_child` at resolution (DECISIONS.md D-18) —
    into concrete per-instance entries under an index-bracketed prefix
    (e.g. `"edges[3]."`). A second, simpler find-and-replace pass:
    `relocate_child` already rewrote each descendant's own condition
    against its sibling scope, so this only ever substitutes one bracket
    placeholder for a concrete index — every reference is guaranteed to
    already be a hit, same as `relocate_child` itself.
    """
    rename = {
        old_path: concrete_prefix + old_path[len(template_prefix) :]
        for old_path in space.params
        if old_path.startswith(template_prefix)
    }
    # A lifted choice's own discriminator template (bare, no descendant of
    # its own — e.g. `"pipeline[]"`) is referenced *by* its variant
    # payload templates' folded discriminator-equality condition, but
    # never appears as a `space.params` key itself, so the loop above
    # never covers it — add it explicitly.
    rename[template_prefix[:-1]] = concrete_prefix[:-1]
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    for old_path in rename:
        if old_path not in space.params:
            continue
        new_path = rename[old_path]
        pd = space.params[old_path]
        new_condition = rewrite_bool(pd.condition, rename) if pd.condition is not None else None
        params[new_path] = replace(pd, path=new_path, condition=new_condition)
        if new_condition is not None:
            conditions.append(
                Condition(target=new_path, expr=new_condition, params=new_condition.params)
            )
    return params, conditions


def instantiate_constraints(
    templates: Any,  # tuple[Constraint, ...]; Any to match ListDomain.element_constraints
    template_prefix: str,
    concrete_prefix: str,
) -> list[Constraint]:
    """The `Constraint`-shaped sibling of `instantiate_element`: expand a
    lift's element-scoped constraint templates (`ListDomain.
    element_constraints`, DECISIONS.md D-20) for one concrete instance.
    Each template already carries its own referenced `params`, so the
    rename map is derived from that directly — no `space.params` lookup
    needed.
    """
    result: list[Constraint] = []
    for c in templates:
        rename = {
            p: concrete_prefix + p[len(template_prefix) :]
            for p in c.params
            if p.startswith(template_prefix)
        }
        new_expr = rewrite_bool(c.expr, rename)
        result.append(replace(c, expr=new_expr, params=new_expr.params))
    return result


def element_paramdef(path: str, domain: ListDomain) -> ParamDef:
    """A synthetic `ParamDef` describing one lift *element* (DECISIONS.md
    D-18): `ListDomain.element_*` reshaped into the ordinary `ParamDef`
    fields, so the existing scalar machinery (chart-driven sampling,
    domain/prior/quantized validation) applies to a lift element exactly
    as it does to a non-lifted param — shared by validate/ and sample/.
    """
    return ParamDef(
        path=path,
        type_kind=domain.element_kind,
        domain=domain.element_domain,
        prior=domain.element_prior,
        periodic=domain.element_periodic,
        default=domain.element_default,
        condition=None,
        tags=frozenset(),
        meta=MappingProxyType({}),
        chart=domain.element_chart,
        quantized=domain.element_quantized,
    )
