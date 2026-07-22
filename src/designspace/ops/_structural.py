"""Space — Structural Operations (API.md): `slice`, `freeze`,
`active_subspace`, `select`, `filter`, `extend`.

Each returns a new `Space`; anchor interactions and the positional-`dict`
path-argument form are documented per-function (API.md, "Space —
Structural Operations": "Path arguments accept both keyword form and a
positional `dict[str, Any]` (required when paths contain `.` or `[]`)").
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.errors import ResolutionError
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
from designspace.ir import (
    CategoricalDomain,
    Condition,
    Constraint,
    IntegerDomain,
    OrdinalDomain,
    ParamDef,
    RealDomain,
)
from designspace.resolve._bounds import bound_origin_targets, hull

# -- shared path/value argument parsing (`.slice`/`.freeze`'s `values=None, **kw`) --


def parse_path_values(
    values: dict[str, Any] | None, kw: dict[str, Any], *, call: str
) -> dict[str, Any]:
    """Merge the positional `dict[str, Any]` form with `**kw` (API.md:
    "Path arguments accept both keyword form and a positional `dict[str,
    Any]` (required when paths contain `.` or `[]`)"). A keyword argument
    can never spell a dotted/bracketed path (Python syntax itself forbids
    it), so `**kw`'s keys are always bare single-segment names; the
    positional form is required for anything else — misusing a bare
    keyword-shaped path fragment for a nested one is caught downstream when
    the path doesn't resolve to a real param.
    """
    merged: dict[str, Any] = dict(values) if values else {}
    overlap = merged.keys() & kw.keys()
    if overlap:
        raise TypeError(f"{call}: path(s) {sorted(overlap)} given in both `values` and `**kw`")
    merged.update(kw)
    if not merged:
        raise TypeError(f"{call}: no paths given (pass `values` and/or `**kw`)")
    return merged


def _literal_for(pd: ParamDef, value: Any) -> Literal | BoolLiteral:
    return BoolLiteral(value) if pd.type_kind == "bool" else Literal(value)


def _validate_fixed_value(space: Space, path: str, value: Any, *, call: str) -> ParamDef:
    if path not in space.params:
        raise ResolutionError(f"{call}: no such param {path!r}")
    pd = space.params[path]
    if "[]" in path or pd.type_kind in ("space", "list"):
        raise ResolutionError(
            f"{call}: {path!r} is a {pd.type_kind!r} container — only a leaf "
            "param can be fixed"
        )
    result = space.validate_param(path, value)
    if not result.valid:
        reasons = "; ".join(f"{e.reason}" for e in result.param_errors) or "invalid value"
        raise ResolutionError(f"{call}: {path!r} = {value!r} is invalid ({reasons})")
    return pd


# -- substitution: replace a ParamExpr leaf with its fixed literal ----------


def substitute_expr(node: Expr, literals: dict[str, Literal | BoolLiteral]) -> Expr:
    """Rebuild `node` with every `ParamExpr` leaf whose path is in
    `literals` replaced by the corresponding literal — the sibling of
    `resolve/_relocate.py::rewrite_expr` (which renames a path instead of
    replacing the node), used by `.slice()`/`.freeze()`'s bound-origin
    envelope recompute and `.slice()`'s reference-site substitution.
    """
    if isinstance(node, ParamExpr):
        return literals.get(node.path, node)
    if isinstance(node, Literal | BoolLiteral):
        return node
    if isinstance(node, Compare):
        return Compare(
            node.op,
            cast_arith(substitute_expr(node.left, literals)),
            cast_arith(substitute_expr(node.right, literals)),
        )
    if isinstance(node, ArithOp):
        return ArithOp(
            node.op,
            cast_arith(substitute_expr(node.left, literals)),
            cast_arith(substitute_expr(node.right, literals)),
        )
    if isinstance(node, BoolOp):
        return BoolOp(
            node.op,
            cast_bool(substitute_expr(node.left, literals)),
            cast_bool(substitute_expr(node.right, literals)),
        )
    if isinstance(node, Not):
        return Not(cast_bool(substitute_expr(node.operand, literals)))
    if isinstance(node, Implies):
        return Implies(
            cast_bool(substitute_expr(node.left, literals)),
            cast_bool(substitute_expr(node.right, literals)),
        )
    if isinstance(node, IsIn):
        return IsIn(cast_arith(substitute_expr(node.operand, literals)), node.values)
    if isinstance(node, IsActive):
        return IsActive(substitute_expr(node.operand, literals))
    if isinstance(node, Count):
        return Count(tuple(cast_bool(substitute_expr(o, literals)) for o in node.operands))
    if isinstance(node, IfInactive):
        return IfInactive(
            cast_arith(substitute_expr(node.operand, literals)),
            cast_arith(substitute_expr(node.fallback, literals)),
        )
    if isinstance(node, Contains):
        return Contains(cast_arith(substitute_expr(node.operand, literals)), node.item)
    if isinstance(node, Size):
        return Size(cast_arith(substitute_expr(node.operand, literals)))
    if isinstance(node, SumOver):
        return SumOver(cast_arith(substitute_expr(node.operand, literals)), node.mapping)
    if isinstance(node, PositionOf):
        return PositionOf(cast_arith(substitute_expr(node.operand, literals)), node.item)
    if isinstance(node, Length):
        return Length(cast_arith(substitute_expr(node.operand, literals)))
    if isinstance(node, Field):
        return Field(substitute_expr(node.operand, literals), node.name)
    if isinstance(node, Sum):
        return Sum(substitute_expr(node.operand, literals))
    if isinstance(node, Min):
        return Min(substitute_expr(node.operand, literals))
    if isinstance(node, Max):
        return Max(substitute_expr(node.operand, literals))
    if isinstance(node, CountOf):
        return CountOf(substitute_expr(node.operand, literals), node.values)
    if isinstance(node, IsSorted):
        return IsSorted(substitute_expr(node.operand, literals), node.descending)
    if isinstance(node, Distinct):
        return Distinct(substitute_expr(node.operand, literals), node.fields)
    raise TypeError(f"cannot substitute into expr kind {node.kind!r}")  # pragma: no cover


def cast_arith(node: Expr) -> ArithExpr:
    assert isinstance(node, ArithExpr)
    return node


def cast_bool(node: Expr) -> BoolExpr:
    assert isinstance(node, BoolExpr)
    return node


def substitute_bool(expr: BoolExpr, literals: dict[str, Literal | BoolLiteral]) -> BoolExpr:
    return cast_bool(substitute_expr(expr, literals))


_INDEX_RE = re.compile(r"\[\d+\]")


def _definition_path_of(concrete_path: str) -> str:
    """A `flatten()`-produced concrete instance path (`"edges[3].weight"`)
    back to its definition-path template (`"edges[].weight"`) — the shape
    `space.params`/prefix-based selection sets use."""
    return _INDEX_RE.sub("[]", concrete_path)


def _values_equal(a: Any, b: Any) -> bool:
    """Strict membership-style equality (DECISIONS.md D-34 precedent):
    `1 == 1.0` under Python's `==` but must not count as "the same value"
    for identity purposes (`1 != 1.0`)."""
    return type(a) is type(b) and a == b


def _revalidate_anchors_unchanged_shape(space: Space, *, call: str) -> Space:
    """`.freeze()`/`.extend()`: params keep their identity/shape, so each
    anchor's *existing* config is simply re-validated against the new
    space — a frozen param's narrowed domain (or an extended space's new,
    unconditionally-active param) naturally rejects a stored anchor value
    that no longer fits. API.md: "a conflict ... is a resolution error"."""
    for name, config in space.anchors.items():
        result = space.validate(config)
        if not result.valid:
            reasons = "; ".join(f"{e.param!r}: {e.reason}" for e in result.param_errors)
            raise ResolutionError(
                f"{call}: anchor {name!r} is invalid after the operation "
                f"({reasons or 'a declared constraint is violated'}) (row 22)"
            )
    return space


# -- extend ------------------------------------------------------------------


def extend(space: Space, exprs: tuple[ParamExpr, ...]) -> Space:
    """`.extend(*exprs)` (API.md): additive — inherits params, conditions,
    constraints, anchors, meta. `ds.space()` (no new exprs) is the identity
    (Degeneracy Table). A new expr's `.when()` may reference the existing
    space's params — an up-reference `resolve_space` tolerates standalone
    and `check_fully_resolved` resolves once merged, the same mechanism a
    nested struct/choice payload uses for an enclosing-scope reference
    (D-26)."""
    from designspace.resolve import check_fully_resolved, resolve_space

    added = resolve_space(exprs)
    merged_params = dict(space.params)
    for path, pd in added.params.items():
        if path in merged_params:
            raise ResolutionError(f".extend(): duplicate param path {path!r}")
        merged_params[path] = pd
    result = Space(
        params=MappingProxyType(merged_params),
        conditions=space.conditions + added.conditions,
        constraints=space.constraints + added.constraints,
        anchors=space.anchors,
        meta_map=space.meta_map,
    )
    check_fully_resolved(result)
    return _revalidate_anchors_unchanged_shape(result, call=".extend()")


# -- active_subspace -----------------------------------------------------------


def active_subspace(space: Space, config: dict[str, Any]) -> Space:
    """`.active_subspace(config)` (API.md): the subspace of params active
    for this (fully materialized) config, via `eval.compute_activity`
    (Kleene rule 3's cascading deactivation) — drops every inactive param
    and any condition/constraint that referenced one."""
    from designspace.config import flatten
    from designspace.eval import compute_activity
    from designspace.meta import space_from_ir

    flat = flatten(config, space)
    activity = compute_activity(space, flat)
    active_paths = {p for p, is_active in activity.items() if is_active}
    new_params = {p: pd for p, pd in space.params.items() if p in active_paths}
    new_conditions = [c for c in space.conditions if c.target in active_paths]
    new_constraints = [c for c in space.constraints if c.params <= active_paths]
    return space_from_ir(
        new_params,
        new_conditions,
        new_constraints,
        anchors=dict(space.anchors),
        meta=dict(space.meta_map),
    )


# -- select / filter -----------------------------------------------------------


def _close_over_structure(space: Space, keep: set[str]) -> set[str]:
    """Two closures over the *original* `keep` set:

    - **Ancestors**: a kept nested path (`"cfg.inner"`) needs every
      enclosing struct/choice container (`"cfg"`) reachable too, or
      ordinary `flatten`/`unflatten` traversal — which walks top-down
      through *declared* containers — could never reach it at all, leaving
      an unreachable orphan. Added as bare pass-through nodes: an ancestor
      pulled in this way does **not** also drag in its own *other*,
      unselected descendants.
    - **Descendants**: a struct/choice container *in the original `keep`
      set* brings every already-relocated payload/field under its own
      prefix (API.md, `.select()`: "selecting a choice brings its
      variants"), recursing through any further-nested container pulled in
      this way — a struct/choice container without its descendants is not
      a coherent space.
    """
    closed = set(keep)
    for p in keep:
        for other in space.params:
            if other != p and (p.startswith(f"{other}.") or p.startswith(f"{other}[")):
                closed.add(other)

    frontier = list(keep)
    expanded = set(keep)
    while frontier:
        p = frontier.pop()
        pd = space.params.get(p)
        if pd is None or pd.type_kind not in ("space", "choice"):
            continue
        prefix = f"{p}."
        for q in space.params:
            if not q.startswith(prefix):
                continue
            closed.add(q)
            if q not in expanded:
                expanded.add(q)
                frontier.append(q)
    return closed


def _prune_to(space: Space, keep: set[str], *, strict: bool, call: str) -> Space:
    from designspace.meta import space_from_ir

    keep = _close_over_structure(space, keep)
    new_params = {p: pd for p, pd in space.params.items() if p in keep}
    new_conditions = [c for c in space.conditions if c.target in keep]

    new_constraints: list[Constraint] = []
    dropped_constraints: list[Constraint] = []
    for c in space.constraints:
        (new_constraints if c.params <= keep else dropped_constraints).append(c)
    if dropped_constraints:
        excluded = sorted({p for c in dropped_constraints for p in c.params if p not in keep})
        if strict:
            raise ResolutionError(
                f"{call}: constraint(s) reference excluded param(s) {excluded} "
                "(strict=True)"
            )
        warnings.warn(
            f"{call}: dropped {len(dropped_constraints)} constraint(s) referencing "
            f"excluded param(s) {excluded}",
            UserWarning,
            stacklevel=4,
        )

    stripped_anchors, any_key_dropped = _strip_anchor_keys(space, new_params, keep)
    if any_key_dropped:
        warnings.warn(
            f"{call}: dropped anchor key(s) referencing excluded params",
            UserWarning,
            stacklevel=4,
        )

    result = space_from_ir(
        new_params, new_conditions, new_constraints,
        anchors=stripped_anchors, meta=dict(space.meta_map),
    )
    return _drop_invalid_anchors(result, call=call)


def select(space: Space, paths: tuple[str, ...], *, strict: bool) -> Space:
    """`.select(*paths, strict=False)` (API.md): definition-path prefix
    subtree."""
    if not paths:
        raise TypeError(".select(): at least one path is required")
    keep: set[str] = set()
    for p in paths:
        if p not in space.params:
            raise ResolutionError(f".select(): no such param {p!r}")
        keep.add(p)
    return _prune_to(space, keep, strict=strict, call=".select()")


def filter_space(space: Space, tags: tuple[str, ...], *, mode: str, strict: bool) -> Space:
    """`.filter(tags=..., mode="any", strict=False)` (API.md): same
    best-effort semantics as `.select()`, selecting by param `tags`
    instead of by path prefix."""
    tag_set = frozenset(tags)
    if mode == "any":
        keep = {p for p, pd in space.params.items() if pd.tags & tag_set}
    elif mode == "all":
        keep = {p for p, pd in space.params.items() if tag_set.issubset(pd.tags)}
    else:
        raise TypeError(f".filter(): mode must be 'any' or 'all', got {mode!r}")
    return _prune_to(space, keep, strict=strict, call=".filter()")


def _strip_anchor_keys(
    old_space: Space, new_params: Mapping[str, ParamDef], keep: set[str]
) -> tuple[dict[str, dict[str, Any]], bool]:
    """`.select()`/`.filter()`: drop each anchor config's keys referencing
    an excluded param (API.md: "drop conflicting anchor keys with the same
    warning mechanism") — a partial-key strip, not dropping the whole
    named anchor (that only happens if the *stripped* result still doesn't
    validate — `_drop_invalid_anchors`, after the new space is assembled).
    """
    from designspace.config._flatten import flatten
    from designspace.config._unflatten import unflatten

    skeleton = Space(params=MappingProxyType(dict(new_params)), conditions=())
    result: dict[str, dict[str, Any]] = {}
    any_dropped = False
    for name, config in old_space.anchors.items():
        flat = flatten(config, old_space)
        stripped = {p: v for p, v in flat.items() if _definition_path_of(p) in keep}
        if len(stripped) != len(flat):
            any_dropped = True
        result[name] = unflatten(stripped, skeleton)
    return result, any_dropped


def _drop_invalid_anchors(space: Space, *, call: str) -> Space:
    kept: dict[str, Any] = {}
    any_dropped = False
    for name, config in space.anchors.items():
        if space.validate(config).valid:
            kept[name] = config
        else:
            any_dropped = True
    if any_dropped:
        warnings.warn(
            f"{call}: dropped anchor(s) no longer valid after pruning",
            UserWarning,
            stacklevel=4,
        )
        return replace(space, anchors=MappingProxyType(kept))
    return space


# -- freeze --------------------------------------------------------------------


def _narrow_or_pin(pd: ParamDef, value: Any, *, call: str) -> tuple[ParamDef, Constraint | None]:
    """`.freeze()`'s per-kind mechanism (DECISIONS.md D-44): real/integer/
    categorical/ordinal narrow their domain to the single fixed value
    (Degeneracy Table: `lo == hi` is already legal); bool has no domain to
    narrow, so it's pinned via a hard `require`/`require(~.)` constraint
    instead. Every kind also gets `default = value`. Choice/subset/
    permutation/struct/list are out of scope for `.freeze()` in M8 (D-44)
    — pinning them would need to prune non-selected structure, which is
    `.select()`'s job, not a value-fixing one.
    """
    kind = pd.type_kind
    if kind == "real":
        assert isinstance(pd.domain, RealDomain)
        return replace(pd, domain=RealDomain(value, value), periodic=False, prior=None,
                        quantized=None, default=value), None
    if kind == "integer":
        assert isinstance(pd.domain, IntegerDomain)
        return replace(pd, domain=IntegerDomain(value, value), prior=None,
                        quantized=None, default=value), None
    if kind == "categorical":
        assert isinstance(pd.domain, CategoricalDomain)
        return replace(pd, domain=CategoricalDomain((value,)), prior=None, default=value), None
    if kind == "ordinal":
        assert isinstance(pd.domain, OrdinalDomain)
        return replace(pd, domain=OrdinalDomain((value,)), prior=None, default=value), None
    if kind == "bool":
        expr: BoolExpr = ParamExpr(path=pd.path) if value else Not(ParamExpr(path=pd.path))
        constraint = Constraint(
            expr=expr, hard=True, origin="require", tags=frozenset(),
            meta=MappingProxyType({}), params=expr.params,
        )
        return replace(pd, default=value), constraint
    raise ResolutionError(
        f"{call}: {pd.path!r} is a {kind!r} param — .freeze() supports real/"
        "integer/categorical/ordinal/bool only in this milestone (M8); "
        "choice/subset/permutation/struct/list are not yet supported"
    )


def freeze(space: Space, to_fix: dict[str, Any]) -> Space:
    from designspace.meta import space_from_ir

    new_params = dict(space.params)
    extra_constraints: list[Constraint] = []
    for path, value in to_fix.items():
        pd = _validate_fixed_value(space, path, value, call=".freeze()")
        new_pd, extra = _narrow_or_pin(pd, value, call=".freeze()")
        new_params[path] = new_pd
        if extra is not None:
            extra_constraints.append(extra)
    result = space_from_ir(
        new_params,
        space.conditions,
        tuple(space.constraints) + tuple(extra_constraints),
        anchors=dict(space.anchors),
        meta=dict(space.meta_map),
    )
    return _revalidate_anchors_unchanged_shape(result, call=".freeze()")


# -- slice ---------------------------------------------------------------------


def slice_space(space: Space, to_remove: dict[str, Any]) -> Space:
    from designspace.meta import space_from_ir

    removed_defs: dict[str, ParamDef] = {
        path: _validate_fixed_value(space, path, value, call=".slice()")
        for path, value in to_remove.items()
    }
    literals: dict[str, Literal | BoolLiteral] = {
        path: _literal_for(pd, to_remove[path]) for path, pd in removed_defs.items()
    }
    bound_targets = bound_origin_targets(space)

    new_params: dict[str, ParamDef] = {}
    for path, pd in space.params.items():
        if path in to_remove:
            continue
        new_condition = (
            substitute_bool(pd.condition, literals) if pd.condition is not None else None
        )
        new_params[path] = replace(pd, condition=new_condition)

    new_conditions: list[Condition] = []
    for c in space.conditions:
        if c.target in to_remove:
            continue
        new_expr = substitute_bool(c.expr, literals)
        new_conditions.append(Condition(target=c.target, expr=new_expr, params=new_expr.params))

    new_constraints: list[Constraint] = []
    for constraint in space.constraints:
        new_c_expr = substitute_bool(constraint.expr, literals)
        new_constraints.append(replace(constraint, expr=new_c_expr, params=new_c_expr.params))

    _recompute_bound_envelopes(new_params, bound_targets, literals)

    new_anchors = _strip_and_check_anchors_after_slice(space, new_params, to_remove)
    result = space_from_ir(
        new_params, new_conditions, new_constraints,
        anchors=new_anchors, meta=dict(space.meta_map),
    )
    for name, config in result.anchors.items():
        if not result.validate(config).valid:
            raise ResolutionError(f".slice(): anchor {name!r} invalid after slicing (row 22)")
    return result


def _recompute_bound_envelopes(
    new_params: dict[str, ParamDef],
    bound_targets: dict[str, tuple[ArithExpr | None, ArithExpr | None]],
    literals: dict[str, Literal | BoolLiteral],
) -> None:
    """API.md, `.slice()`: "envelopes recompute on re-resolution" — a
    bound-origin constraint's *original* expression is recovered from
    `bound_origin_targets` (unlike the domain's own lo/hi, already
    collapsed to a number at the first resolution), substituted, and
    re-hulled via the same interval-arithmetic `resolve/_bounds.py::hull`
    the original `compute_bound_envelopes` uses — bootstrapped from the
    *current* (already-numeric) envelopes of whatever params remain.
    """

    def envelope_of(path: str) -> tuple[float, float]:
        pd = new_params[path]
        assert isinstance(pd.domain, RealDomain | IntegerDomain)
        lo, hi = pd.domain.lo, pd.domain.hi
        assert isinstance(lo, int | float) and isinstance(hi, int | float)
        return (float(lo), float(hi))

    for path, (lo_expr, hi_expr) in bound_targets.items():
        if path not in new_params:
            continue  # the bound's own target was sliced away
        pd = new_params[path]
        domain = pd.domain
        if not isinstance(domain, RealDomain | IntegerDomain):
            continue
        old_lo, old_hi = domain.lo, domain.hi
        assert isinstance(old_lo, int | float) and isinstance(old_hi, int | float)
        new_lo, new_hi = float(old_lo), float(old_hi)
        touched = False
        if lo_expr is not None:
            sub = substitute_expr(lo_expr, literals)
            new_lo = (
                float(sub.value)
                if isinstance(sub, Literal)
                else hull(cast_arith(sub), envelope_of, path=path)[0]
            )
            touched = True
        if hi_expr is not None:
            sub = substitute_expr(hi_expr, literals)
            new_hi = (
                float(sub.value)
                if isinstance(sub, Literal)
                else hull(cast_arith(sub), envelope_of, path=path)[1]
            )
            touched = True
        if touched:
            new_domain: RealDomain | IntegerDomain = (
                RealDomain(new_lo, new_hi)
                if isinstance(domain, RealDomain)
                else IntegerDomain(int(new_lo), int(new_hi))
            )
            new_params[path] = replace(pd, domain=new_domain)


def _strip_and_check_anchors_after_slice(
    old_space: Space, new_params: Mapping[str, ParamDef], to_remove: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    from designspace.config._flatten import flatten
    from designspace.config._unflatten import unflatten

    skeleton = Space(params=MappingProxyType(dict(new_params)), conditions=())
    result: dict[str, dict[str, Any]] = {}
    for name, config in old_space.anchors.items():
        flat = flatten(config, old_space)
        stripped: dict[str, Any] = {}
        for concrete_path, v in flat.items():
            def_path = _definition_path_of(concrete_path)
            if def_path in to_remove:
                fixed = to_remove[def_path]
                if not _values_equal(v, fixed):
                    raise ResolutionError(
                        f".slice(): anchor {name!r} conflicts with sliced value "
                        f"{def_path!r} = {fixed!r} (anchor has {v!r}) (row 22)"
                    )
                continue
            stripped[concrete_path] = v
        result[name] = unflatten(stripped, skeleton)
    return result
