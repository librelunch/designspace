"""Structural relocation: merging a resolved child `Space` into its parent.

The child is a `.choice()` variant payload or a `.space()` struct payload,
and it is merged into the flat IR of its enclosing scope. See API.md, "Paths
and Scoping" on relocatability and "Expressions" rule 3 on cascading
deactivation.

A child Space resolves standalone and eagerly: `ParamExpr.space()` and
`.choice()` in `builder/_paramexpr.py` call `resolve_space` on the payload's
expressions immediately. A leaf reference binding in the child's own scope
is checked there, under rows 6 and 14. A reference binding nowhere locally
is tolerated as a possible enclosing-scope up-reference and re-checked at
finalization.

Relocation therefore does two things. It reprefixes the child's own paths, a
rename in which a local leaf is a hit and an up-reference deliberately is
not, so that the up-reference stays bare and binds against the enclosing
scope. It then folds in the enclosing activation condition, either the
struct's own `.when()` or the choice discriminator's `== variant` equality,
so that deactivation cascades down through nesting under the same Kleene
rule 3 the flat evaluator already implements. No new evaluator machinery is
required.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

from designspace.builder._paramexpr import ParamExpr
from designspace.expr import (
    ArithExpr,
    ArithOp,
    BoolExpr,
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
from designspace.ir import Condition, Constraint, ListDomain, ParamDef


def rewrite_expr(node: Expr, rename: Mapping[str, str]) -> Expr:
    """Rebuild `node` with every `ParamExpr` leaf's path substituted per `rename`.

    A local leaf is a hit. An unmatched path is left unchanged: for a child
    leaf that is really an enclosing-scope up-reference, staying bare is what
    binds it against the outer scope once this level's rename does not claim
    it. A genuine typo is unmatched at every level and is caught by
    finalization, in `check_fully_resolved`.
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
    if isinstance(node, Prop):
        return Prop(cast(ArithExpr, rewrite_expr(node.operand, rename)), node.name)
    if isinstance(node, Value):
        return Value(
            node.fn,
            tuple(rewrite_expr(o, rename) for o in node.operands),
            node.returns,
        )
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
    if isinstance(node, ChartApply):
        return ChartApply(
            rewrite_expr(node.operand, rename),
            node.chart,
            node.type_kind,
            node.domain,
            node.prior,
            node.quantized,
            node.periodic,
        )
    raise TypeError(f"cannot relocate expr kind {node.kind!r}")  # pragma: no cover


def rewrite_bool(expr: BoolExpr, rename: Mapping[str, str]) -> BoolExpr:
    return cast(BoolExpr, rewrite_expr(expr, rename))


def rewrite_domain(domain: Any, rename: Mapping[str, str]) -> Any:
    """Rename the param references a `ListDomain` carries inside the domain.

    A `ListDomain` holds two of them on the domain rather than on the
    `ParamDef`: its `count` expression and its `element_constraints`
    templates. That is why the `ParamDef`-level rewrite above misses them.

    Every other `Domain` holds declared values only, never expressions, and
    is returned unchanged. This recurses through `element_domain`, so a
    chained or variadic `.repeat().repeat()` renames at every level.
    """
    if not isinstance(domain, ListDomain):
        return domain
    count = domain.count
    new_count = count if isinstance(count, int) else cast(ArithExpr, rewrite_expr(count, rename))
    new_element_constraints = tuple(
        replace(c, expr=(e := rewrite_bool(c.expr, rename)), params=e.params)
        for c in domain.element_constraints
    )
    return replace(
        domain,
        element_domain=rewrite_domain(domain.element_domain, rename),
        count=new_count,
        element_constraints=new_element_constraints,
    )


def relocate_paramdef(pd: ParamDef, new_path: str, rename: Mapping[str, str]) -> ParamDef:
    """`replace(pd, path=...)` plus the domain-carried rewrite above.

    This is the one place that knows a `ParamDef`'s references are not all
    reachable from `pd.condition`.
    """
    return replace(pd, path=new_path, domain=rewrite_domain(pd.domain, rename))


def and_(a: BoolExpr | None, b: BoolExpr | None) -> BoolExpr | None:
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def _lift_depth(domain: Any) -> int:
    depth = 0
    while isinstance(domain, ListDomain):
        depth += 1
        domain = domain.element_domain
    return depth


def _rename_map(child: Any, new_prefix: str) -> dict[str, str]:
    """`{old_path: new_path}` for the reprefix.

    The map covers every path the child's expressions may reference, which
    is a superset of `child.params`.

    A lifted choice's discriminator template is the case that superset
    exists for. For a `.choice(...).repeat(2)` named `pipe`, the template
    `"pipe[]"` is referenced by the discriminator-equality condition folded
    into each variant payload at relocation, yet it is never a `params` key
    of its own: the lift is `"pipe"` and the payloads are `"pipe[].b.w"`.
    Deriving the map from `params` alone leaves that reference bare, and it
    then binds to nothing in the merged space. `instantiate_element` handles
    the identical gap for its own `"[]" -> "[k]"` expansion.

    Bracket templates are emitted for every lift level, so a nested lift's
    `"g[][]"` renames too. An entry that nothing references is harmless,
    since `rewrite_expr` substitutes on exact path match.
    """
    rename = {old_path: f"{new_prefix}{old_path}" for old_path in child.params}
    for old_path, pd in child.params.items():
        for level in range(1, _lift_depth(pd.domain) + 1):
            template = old_path + "[]" * level
            rename[template] = f"{new_prefix}{template}"
    return rename


def relocate_child(
    child: Any,  # designspace.builder._space.Space; Any avoids an import cycle
    new_prefix: str,
    injected_condition: BoolExpr | None,
) -> tuple[dict[str, ParamDef], list[Condition], list[Constraint]]:
    """Reprefix every param, condition and constraint in `child`.

    The new prefix is `new_prefix`, for instance `"layers."` or
    `"algo.svm."`. `injected_condition`, either the struct's own `.when()`
    or the choice discriminator's `== variant` equality, is folded into each
    descendant's own condition.

    `child.constraints` need no condition injection. Once a descendant
    param's activity is gated, a constraint referencing it goes
    Kleene-inapplicable on its own under rule 4, so no separate wrapping is
    required.
    """
    rename = _rename_map(child, new_prefix)
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    for old_path, pd in child.params.items():
        new_path = rename[old_path]
        own_condition = rewrite_bool(pd.condition, rename) if pd.condition is not None else None
        final_condition = and_(own_condition, injected_condition)
        params[new_path] = replace(
            relocate_paramdef(pd, new_path, rename), condition=final_condition
        )
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
    space: Any,  # designspace.builder._space.Space; Any avoids an import cycle
    template_prefix: str,
    concrete_prefix: str,
) -> tuple[dict[str, ParamDef], list[Condition]]:
    """Expand one lift instance's descendant template into concrete entries.

    `relocate_child` merged the template into `space.params` at resolution
    under a `"[]"`-bracketed prefix such as `"edges[]."`. This produces the
    per-instance entries under an index-bracketed prefix such as
    `"edges[3]."`.

    It is a second, simpler find-and-replace pass. `relocate_child` already
    rewrote each descendant's own condition against its sibling scope, so
    this substitutes one bracket placeholder for a concrete index and every
    reference is guaranteed to be a hit, as in `relocate_child` itself.
    """
    rename = {
        old_path: concrete_prefix + old_path[len(template_prefix) :]
        for old_path in space.params
        if old_path.startswith(template_prefix)
    }
    # A lifted choice's own discriminator template is bare, with no
    # descendant of its own, for instance `"pipeline[]"`. Its variant
    # payload templates' folded discriminator-equality condition references
    # it, but it never appears as a `space.params` key itself, so the loop
    # above does not cover it. Add it explicitly.
    rename[template_prefix[:-1]] = concrete_prefix[:-1]
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    for old_path in rename:
        if old_path not in space.params:
            continue
        new_path = rename[old_path]
        pd = space.params[old_path]
        new_condition = rewrite_bool(pd.condition, rename) if pd.condition is not None else None
        params[new_path] = replace(relocate_paramdef(pd, new_path, rename), condition=new_condition)
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
    """The `Constraint`-shaped sibling of `instantiate_element`.

    This expands a lift's element-scoped constraint templates, held on
    `ListDomain.element_constraints`, for one concrete instance. Each
    template carries its own referenced `params`, so the rename map is
    derived from that directly and no `space.params` lookup is needed.
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
    """A synthetic `ParamDef` describing one lift element.

    The `ListDomain.element_*` fields are reshaped into the ordinary
    `ParamDef` fields, so that the existing scalar machinery, meaning
    chart-driven sampling and domain, prior and quantized validation,
    applies to a lift element as it does to a non-lifted param. Shared by
    `validate/` and `sample/`.
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
