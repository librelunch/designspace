"""`slice`, `freeze`, `active_subspace`, `select`, `filter` and `extend`.

See API.md, "Space: Structural Operations". Each returns a new `Space`.
Anchor interactions and the positional-`dict` path-argument form are
documented per function: "Path arguments accept both keyword form and a
positional `dict[str, Any]` (required when paths contain `.` or `[]`)".
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from designspace.builder._paramexpr import ParamExpr
from designspace.builder._space import Space
from designspace.errors import ResolutionError
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
from designspace.ir import (
    CategoricalDomain,
    ChoiceDomain,
    Condition,
    Constraint,
    CustomDomain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    ParamDef,
    PermutationDomain,
    RealDomain,
    StructDomain,
    SubsetDomain,
)
from designspace.paths import strip_last_index
from designspace.paths._grammar import _INDEX_RE
from designspace.resolve._bounds import bound_origin_targets, hull

# -- shared path/value argument parsing (`.slice`/`.freeze`'s `values=None, **kw`) --


def parse_path_values(
    values: dict[str, Any] | None, kw: dict[str, Any], *, call: str
) -> dict[str, Any]:
    """Merge the positional `dict[str, Any]` form with `**kw`.

    API.md states that "Path arguments accept both keyword form and a
    positional `dict[str, Any]` (required when paths contain `.` or `[]`)".
    Python syntax forbids a keyword argument from spelling a dotted or
    bracketed path, so `**kw`'s keys are always bare single-segment names
    and the positional form is required for anything else. Using a bare
    keyword-shaped fragment where a nested path was meant is caught
    downstream, when the path fails to resolve to a real param.
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
            f"{call}: {path!r} is a {pd.type_kind!r} container; only a leaf param can be fixed"
        )
    result = space.validate_param(path, value)
    if not result.valid:
        reasons = "; ".join(f"{e.reason}" for e in result.param_errors) or "invalid value"
        raise ResolutionError(f"{call}: {path!r} = {value!r} is invalid ({reasons})")
    return pd


# -- substitution: replace a ParamExpr leaf with its fixed literal ----------


def substitute_expr(node: Expr, literals: Mapping[str, Expr]) -> Expr:
    """Rebuild `node`, replacing each `ParamExpr` leaf named in `literals`.

    This is the sibling of `rewrite_expr` in `resolve/_relocate.py`, which
    renames a path rather than replacing the node. Three callers use it:
    `.slice()` and `.freeze()`'s bound-origin envelope recompute,
    `.slice()`'s reference-site substitution, and leaf substitution in
    `represent/_transport.py`. The first two pass `Literal` or `BoolLiteral`
    values; transport passes an arbitrary decode expression, most often a
    `ChartApply`, which is why the parameter type is `Expr` rather than the
    narrower `Literal | BoolLiteral`.
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
    if isinstance(node, Prop):
        return Prop(cast_arith(substitute_expr(node.operand, literals)), node.name)
    if isinstance(node, Value):
        return Value(
            node.fn,
            tuple(substitute_expr(o, literals) for o in node.operands),
            node.returns,
        )
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
    if isinstance(node, ChartApply):
        return ChartApply(
            substitute_expr(node.operand, literals),
            node.chart,
            node.type_kind,
            node.domain,
            node.prior,
            node.quantized,
            node.periodic,
        )
    raise TypeError(f"cannot substitute into expr kind {node.kind!r}")  # pragma: no cover


def cast_arith(node: Expr) -> ArithExpr:
    assert isinstance(node, ArithExpr)
    return node


def cast_bool(node: Expr) -> BoolExpr:
    assert isinstance(node, BoolExpr)
    return node


def substitute_bool(expr: BoolExpr, literals: Mapping[str, Expr]) -> BoolExpr:
    return cast_bool(substitute_expr(expr, literals))


# -- static resolution: fold what substitution has determined --------------
#
# Substituting a fixed value at its reference sites is only half of
# `.slice()`/`.freeze()`. Once every param a piece of *derived* structure
# reads is determined, that structure is no longer derived, and leaving it
# in expression form makes the resulting space misreport itself: a count
# that is provably 3 still answers `has_variable_length == True`, still
# fails `coordinate_paths()`'s row-33 check, and still emits `List` rather
# than `Array`, because every one of those surfaces tests
# `isinstance(count, int)` rather than "constant-valued expression".


def _has_opaque_leaf(expr: Expr) -> bool:
    """Whether `expr` contains a node the fold must not evaluate through.

    `Value` wraps a user `fn` whose calling convention (API.md: called with
    exactly the operand values, at evaluation) never promised a call at
    structural-op time; `Prop` reaches into a custom type's `extract`.
    `IsActive` reads activity, which no reference-free expression can
    supply. Folding is best-effort, so refusing here merely leaves the
    expression alone, which is always sound.
    """
    if isinstance(expr, Value | Prop | IsActive):
        return True
    return any(_has_opaque_leaf(child) for child in expr.children if isinstance(child, Expr))


def _foldable(expr: Expr) -> bool:
    """Evaluate a reference-free, opaque-free expression to a constant.

    The evaluation runs against an empty config through the ordinary
    evaluator, so a folded value can never disagree with what evaluation
    would have produced at runtime.
    """
    return not expr.params and not _has_opaque_leaf(expr)


def fold_count(count: int | ArithExpr, space: Space) -> int | ArithExpr:
    """A count expression whose references are all determined becomes an `int`.

    Anything else is returned unchanged: a partially determined count, or
    one reaching an opaque leaf, stays an expression and the lift stays
    dynamic.
    """
    if isinstance(count, int) or not _foldable(count):
        return count
    from designspace.eval import Unknown, evaluate_arith

    value = evaluate_arith(count, {}, {}, space)
    if isinstance(value, Unknown) or not isinstance(value, int) or isinstance(value, bool):
        return count
    return value


def fold_condition(condition: BoolExpr | None, space: Space) -> BoolExpr | None:
    """A condition folding to literal `True` becomes no condition at all.

    An always-active param is an unconditional one, so the fold preserves
    information.

    A `False` fold is deliberately left alone. Dropping the param would
    remove a declared name from the path namespace, which `flatten`,
    `.params`, and the fingerprint preimage all observe; keeping a
    permanently-false condition is the conservative reading, matching how
    `cardinality()` stays sound-but-conservative elsewhere.
    """
    if condition is None or not _foldable(condition):
        return condition
    from designspace.eval import Unknown, evaluate_bool

    value = evaluate_bool(condition, {}, {}, space)
    if isinstance(value, Unknown):
        return condition
    return None if value else condition


def fold_domain(domain: Any, space: Space) -> Any:
    """`fold_count` applied down a possibly chained `ListDomain`.

    A domain carries exactly one piece of derived structure, its `count`.
    """
    if not isinstance(domain, ListDomain):
        return domain
    return replace(
        domain,
        element_domain=fold_domain(domain.element_domain, space),
        count=fold_count(domain.count, space),
    )


def substitute_domain(domain: Any, literals: Mapping[str, Expr]) -> Any:
    """Substitute fixed values into a `ListDomain`'s `count`.

    Recurses through `element_domain`. This is the domain-carried sibling of
    `.slice()`'s condition and constraint substitution, over the same store
    `rewrite_domain` in `resolve/_relocate.py` renames.

    `element_constraints` need no substitution. A prebuilt element `Space`'s
    constraints resolve eagerly against its own params, so they can
    reference only `"[]"`-templated paths, which `.slice()` refuses to
    remove in `_validate_fixed_value`.
    """
    if not isinstance(domain, ListDomain):
        return domain
    count = domain.count
    new_count = count if isinstance(count, int) else cast_arith(substitute_expr(count, literals))
    return replace(
        domain,
        element_domain=substitute_domain(domain.element_domain, literals),
        count=new_count,
    )


def _definition_path_of(concrete_path: str) -> str:
    """A concrete instance path back to its definition-path template.

    `flatten()` produces `"edges[3].weight"`; this returns
    `"edges[].weight"`, the shape `space.params` and prefix-based selection
    sets use.
    """
    return _INDEX_RE.sub("[]", concrete_path)


def _governing_definition_path(space: Space, path: str) -> str:
    """The `space.params` key that owns `path`.

    This mirrors `_lookup_param_shape`'s fallback chain in
    `validate/_validate.py`. A bare definition path owns itself. A
    struct-lift descendant instance path such as `"stops[2].location"` is
    owned by its `"[]"`-templated form `"stops[].location"`, a real
    relocated `ParamDef`. A direct lift element instance path such as
    `"pipeline[0]"` or `"dropout[3]"` has no template key at all, only the
    base list param `"pipeline"`, so `_definition_path_of`'s blanket
    `"[]"` substitution is wrong for that case: `"pipeline[]"` is never a
    key.

    Used wherever a path from a `Constraint.params` entry or an anchor flat
    key is checked against a keep-set of `space.params` keys.
    """
    if path in space.params:
        return path
    templated = _definition_path_of(path)
    if templated in space.params:
        return templated
    if "[" in path:
        return strip_last_index(path)
    return path


def _values_equal(a: Any, b: Any) -> bool:
    """Strict, membership-style equality.

    Python's `==` holds for `1 == 1.0`, but the two must not count as the
    same value for identity purposes, matching the type-tagged equality used
    throughout the library.
    """
    return type(a) is type(b) and a == b


def _revalidate_anchors_unchanged_shape(space: Space, *, call: str) -> Space:
    """Re-validate every anchor after `.freeze()` or `.extend()`.

    Both operations keep each param's identity and shape, so an anchor's
    existing config is re-validated against the new space unchanged. A
    frozen param's narrowed domain, or an extended space's new
    unconditionally active param, rejects a stored anchor value that no
    longer fits. API.md states that "a conflict ... is a resolution error".
    """
    for name, config in space.anchors.items():
        result = space.validate(config)
        if not result.valid:
            reasons = "; ".join(f"{e.param!r}: {e.reason}" for e in result.param_errors)
            raise ResolutionError(
                f"{call}: anchor {name!r} is invalid after the operation "
                f"({reasons or 'a declared constraint is violated'})"
            )
    return space


# -- extend ------------------------------------------------------------------


def extend(space: Space, exprs: tuple[ParamExpr, ...]) -> Space:
    """`.extend(*exprs)`: add declarations to an existing space.

    The operation is additive, inheriting params, conditions, constraints,
    anchors and metadata. Passing no new expressions is the identity, per
    the Degeneracy Table.

    A new expression's `.when()` may reference the existing space's params.
    That is an up-reference, which `resolve_space` tolerates standalone and
    `check_fully_resolved` resolves once merged, the same mechanism a nested
    struct or choice payload uses for an enclosing-scope reference.
    """
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
    """`.active_subspace(config)`: the params active for one config.

    The config must be fully materialized. Activity comes from
    `eval.compute_activity`, under Kleene rule 3's cascading deactivation.
    Every inactive param is dropped, along with any condition or constraint
    that referenced one.
    """
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
    """Close the `keep` set over ancestors and descendants.

    Ancestors: a kept nested path such as `"cfg.inner"` needs every
    enclosing struct or choice container, here `"cfg"`, to be reachable
    too. Ordinary `flatten` and `unflatten` traversal walks top-down through
    declared containers, so without the ancestor it could never reach the
    kept path, leaving an unreachable orphan. An ancestor is added as a bare
    pass-through node and does not drag in its own other, unselected
    descendants.

    Descendants: a container in the original `keep` set brings every
    already-relocated payload and field under its own prefix, since API.md
    says of `.select()` that "selecting a choice brings its variants". This
    recurses through any further-nested container pulled in that way,
    because a container without its descendants is not a coherent space.

    "Container" spans `list` as well as `space` and `choice`. A lifted
    struct or choice relocates its fields under a `"[]"`-bracketed prefix
    such as `"layers[].width"`, which is a descendant of `"layers"` by the
    path grammar just as `"solver.cdcl.restart"` is a descendant of
    `"solver"`. Matching only `f"{p}."`, and only `space` and `choice`,
    would leave a selected lift holding a `ListDomain` whose element fields
    are no longer params of the space.
    """
    closed = set(keep)
    for p in keep:
        for other in space.params:
            if other != p and _is_descendant_path(p, other):
                closed.add(other)

    frontier = list(keep)
    expanded = set(keep)
    while frontier:
        p = frontier.pop()
        pd = space.params.get(p)
        if pd is None or pd.type_kind not in ("space", "choice", "list"):
            continue
        for q in space.params:
            if not _is_descendant_path(q, p):
                continue
            closed.add(q)
            if q not in expanded:
                expanded.add(q)
                frontier.append(q)
    return closed


def _is_descendant_path(path: str, ancestor: str) -> bool:
    """Whether `path` is nested under `ancestor` in the path grammar.

    `"grp.x"` is nested under `"grp"` and `"layers[].width"` under
    `"layers"`, but `"grp_other"` is not nested under `"grp"`.
    """
    return path.startswith(f"{ancestor}.") or path.startswith(f"{ancestor}[")


def _apply_keep_set(space: Space, keep: set[str], *, strict: bool, call: str) -> Space:
    """Prune a space to an exact keep-set.

    This is the second half of `.select()`'s pruning: `_prune_to` closes
    `keep` over ancestor and descendant structure first, then delegates
    here. Params, conditions and constraints are filtered to `keep`, warning
    or, under `strict`, raising on a dropped constraint; anchors are
    stripped or dropped; and the result is rebuilt through `space_from_ir`.

    Choice-freeze's structural pruning calls this directly. It already knows
    its exact keep-set, every variant-descendant path it is removing, and
    has no ancestor or descendant closure to compute.

    `keep` holds definition paths only, since `space.params`' own keys are
    never instance-path-shaped. A constraint's `.params` must therefore be
    compared through `_governing_definition_path`. Otherwise a require-pin
    on a `.repeat()` instance path such as `"pipeline[0]"`, which is what
    freeze's per-element choice and list pins produce, would always look
    excluded and be dropped even though its owning param survives.
    `_strip_anchor_keys` performs the identical normalization for anchor
    config keys.
    """
    from designspace.meta._meta import _build_space_from_ir

    new_params = {p: pd for p, pd in space.params.items() if p in keep}
    new_conditions = [c for c in space.conditions if c.target in keep]

    new_constraints: list[Constraint] = []
    dropped_constraints: list[Constraint] = []
    for c in space.constraints:
        kept = all(_governing_definition_path(space, p) in keep for p in c.params)
        (new_constraints if kept else dropped_constraints).append(c)
    if dropped_constraints:
        excluded = sorted(
            {
                p
                for c in dropped_constraints
                for p in c.params
                if _governing_definition_path(space, p) not in keep
            }
        )
        if strict:
            raise ResolutionError(
                f"{call}: constraint(s) reference excluded param(s) {excluded} (strict=True)"
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

    result = _build_space_from_ir(
        new_params,
        new_conditions,
        new_constraints,
        anchors=stripped_anchors,
        meta=dict(space.meta_map),
    )
    return _drop_invalid_anchors(result, call=call)


def _prune_to(space: Space, keep: set[str], *, strict: bool, call: str) -> Space:
    keep = _close_over_structure(space, keep)
    return _apply_keep_set(space, keep, strict=strict, call=call)


def select(space: Space, paths: tuple[str, ...], *, strict: bool) -> Space:
    """`.select(*paths, strict=False)`: the definition-path prefix subtree."""
    if not paths:
        raise TypeError(".select(): at least one path is required")
    keep: set[str] = set()
    for p in paths:
        if p not in space.params:
            raise ResolutionError(f".select(): no such param {p!r}")
        keep.add(p)
    return _prune_to(space, keep, strict=strict, call=".select()")


def filter_space(space: Space, tags: tuple[str, ...], *, mode: str, strict: bool) -> Space:
    """`.filter(tags=..., mode="any", strict=False)`: select by tag.

    The semantics are `.select()`'s, best-effort by default, selecting on
    param `tags` rather than on path prefix.
    """
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
    """Drop each anchor config's keys that reference an excluded param.

    API.md requires `.select()` and `.filter()` to "drop conflicting anchor
    keys with the same warning mechanism". This is a partial-key strip
    rather than the removal of the whole named anchor, which happens only if
    the stripped result still fails to validate. `_drop_invalid_anchors`
    performs that second step, after the new space is assembled.
    """
    from designspace.config._flatten import flatten
    from designspace.config._unflatten import unflatten

    skeleton = Space(params=MappingProxyType(dict(new_params)), conditions=())
    result: dict[str, dict[str, Any]] = {}
    any_dropped = False
    for name, config in old_space.anchors.items():
        flat = flatten(config, old_space)
        stripped = {
            p: v for p, v in flat.items() if _governing_definition_path(old_space, p) in keep
        }
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


def _require_pin(expr: BoolExpr) -> Constraint:
    """The hard `require`-pin `Constraint` every non-narrowing freeze uses.

    Bool, custom, and the subset, permutation, choice and list-element pins
    all take this shape. It is built directly rather than through
    `Space.require()` and `add_constraints`, because the param is already
    declared and resolved and so `check_refs_declared`, `check_expr_types`
    and `desugar_bool` have nothing left to check.
    """
    return Constraint(
        expr=expr,
        hard=True,
        origin="require",
        tags=frozenset(),
        meta=MappingProxyType({}),
        params=expr.params,
    )


def _validate_leaf(space: Space, path: str, value: Any, *, call: str) -> None:
    """The value-shape check for choice, subset and permutation.

    `validate_param` validates all three through `_domain_error_reason`'s
    `ChoiceDomain`, `SubsetDomain` and `PermutationDomain` branches, whether
    `path` is a bare definition path or a `.repeat()` instance path, which
    it resolves by synthesizing an `element_paramdef`.
    """
    result = space.validate_param(path, value)
    if not result.valid:
        reasons = "; ".join(f"{e.reason}" for e in result.param_errors) or "invalid value"
        raise ResolutionError(f"{call}: {path!r} = {value!r} is invalid ({reasons})")


@dataclass(frozen=True)
class _FreezeExpansion:
    """One `.freeze()` target's full expansion.

    An expansion holds three things: the `ParamDef` records it replaces, for
    the domain-narrowing and default-setting kinds; the paths it removes
    entirely, which is choice's structural pruning; and the extra hard
    `require` constraints it pins.

    Struct fan-out and list per-element pinning merge sub-expansions from
    recursive calls. A plain scalar, bool or custom target, and subset,
    permutation and choice's own per-path expansion, are each complete and
    non-recursive.
    """

    param_updates: dict[str, ParamDef]
    removed_paths: frozenset[str]
    constraints: tuple[Constraint, ...]


def _expand_subset(path: str, pd: ParamDef, value: list[Any]) -> _FreezeExpansion:
    """Freeze a subset: one `contains` pin per declared item.

    Each item gets `require(contains(p, i))` or `require(~contains(p, i))`.
    There is no domain to narrow, since `SubsetDomain` has no single-value
    shape.

    `default = value` is set at a genuine per-occurrence path, matching
    `_default_is_valid_subset`'s value shape, but not at a `.repeat()`
    instance path, which `_INDEX_RE.search(path)` detects. There `pd` is the
    element template shared across instances rather than a `ParamDef`
    dedicated to this one.
    """
    domain = pd.domain
    assert isinstance(domain, SubsetDomain)
    constraints = tuple(
        _require_pin(
            Contains(ParamExpr(path=path), item)
            if any(_values_equal(v, item) for v in value)
            else Not(Contains(ParamExpr(path=path), item))
        )
        for item in domain.items
    )
    if _INDEX_RE.search(path):
        return _FreezeExpansion({}, frozenset(), constraints)
    return _FreezeExpansion({path: replace(pd, default=value)}, frozenset(), constraints)


def _expand_permutation(path: str, pd: ParamDef, value: list[Any]) -> _FreezeExpansion:
    """Freeze a permutation: one position pin per index.

    Each index gets `require(position_of(p, item) == k)`. There is no domain
    to narrow, and `default = value` is set at a per-occurrence path only,
    as in `_expand_subset`.
    """
    assert isinstance(pd.domain, PermutationDomain)
    constraints = tuple(
        _require_pin(Compare("eq", PositionOf(ParamExpr(path=path), item), Literal(k)))
        for k, item in enumerate(value)
    )
    if _INDEX_RE.search(path):
        return _FreezeExpansion({}, frozenset(), constraints)
    return _FreezeExpansion({path: replace(pd, default=value)}, frozenset(), constraints)


def _expand_choice(space: Space, path: str, domain: ChoiceDomain, value: str) -> _FreezeExpansion:
    """Freeze a choice: a discriminator pin plus the unified pruning rule.

    The pin is `require(c == variant)`. Under the pruning rule, a variant's
    relocated descendants, the paths under `f"{template}.{variant}."`, are
    pruned exactly when no instance being frozen in this call selects it. A
    plain, non-lifted choice has one instance, so the rule reduces to
    pruning every variant but the chosen one.

    `ChoiceDomain.variants` is never narrowed, there being nothing analogous
    to `lo == hi` for it, as with bool. No `default` is set either: choice
    sampling is always generative, and the pin alone determines the value.

    A choice reached at a `.repeat()` instance path, such as
    `stops[2].category`, is a choice-typed field of a struct-in-list element
    rather than a direct list-of-choice element. It shares its relocated
    descendants with every other instance's own struct fan-out call, so
    pruning from this one instance's selection would be unsound: a sibling
    instance's freeze call may still need the variant this one does not
    select. A direct list-of-choice element never reaches this function,
    because `_expand_list_body` aggregates over every instance inline first.
    This branch is therefore a deliberately conservative fallback, unpruned
    but still correctly pinned, for the nested-struct-field composition
    alone.
    """
    pin = _require_pin(Compare("eq", ParamExpr(path=path), Literal(value)))
    if _INDEX_RE.search(path):
        return _FreezeExpansion({}, frozenset(), (pin,))
    template = _definition_path_of(path)
    removed_prefixes = tuple(f"{template}.{v}." for v in domain.variants if v != value)
    removed_paths = frozenset(
        p for p in space.params if any(p.startswith(pre) for pre in removed_prefixes)
    )
    return _FreezeExpansion({}, removed_paths, (pin,))


def _expand_struct(
    space: Space, struct_path: str, value: dict[str, Any], *, call: str
) -> _FreezeExpansion:
    """Freeze a struct: fan out to each named field.

    A struct has no value of its own. `StructDomain` is "a pure namespace",
    and `.default()` on a struct is already row 21's resolution error. This
    dispatches per kind at each given field's fully-qualified path.

    A partial dict fixes the given fields only. A field that is itself a
    struct, choice, subset, permutation or list recurses through the same
    dispatch with no extra code. It works the same whether `struct_path` is
    a plain definition path or a `.repeat()` instance path such as
    `stops[2]`, since the field lookup goes through the definition-path
    template either way.
    """
    template_base = _definition_path_of(struct_path)
    param_updates: dict[str, ParamDef] = {}
    removed_paths: set[str] = set()
    constraints: list[Constraint] = []
    for field, subvalue in value.items():
        field_path = f"{struct_path}.{field}"
        field_pd = space.params.get(f"{template_base}.{field}")
        if field_pd is None:
            raise ResolutionError(f"{call}: no such param {field_path!r}")
        expansion = _expand_leaf_or_container(space, field_path, field_pd, subvalue, call=call)
        param_updates.update(expansion.param_updates)
        removed_paths.update(expansion.removed_paths)
        constraints.extend(expansion.constraints)
    return _FreezeExpansion(param_updates, frozenset(removed_paths), tuple(constraints))


def _expand_list_body(
    space: Space, path: str, domain: ListDomain, value: list[Any], *, call: str
) -> tuple[dict[str, ParamDef], frozenset[str], tuple[Constraint, ...], ListDomain]:
    """Freeze a list, at the outermost level or one nesting level down.

    `count` narrows to the literal `len(value)`, dropping whatever
    `int | ArithExpr` governed it before, as real and integer drop any prior
    when they narrow. `list_default` is set to `value`, for the reason
    custom's pin sets a default: it is inert when the elements are
    generative and satisfies the non-generative-element `SamplingError`
    guarantee when they are not.

    A pre-existing literal `count` disagreeing with `len(value)` is a
    resolution error, checked here. This is the only place a literal count
    is cross-checked against a realized length; neither
    `_validate_lift_instances` in `validate/_validate.py` nor
    `_validate_list_default_level` in `resolve/_pipeline.py` does so.

    Each element is then pinned according to `element_kind`. A scalar,
    custom or bool element takes a per-instance `require(p[i] == value[i])`.
    A struct element takes the same field fan-out, rooted at the instance
    path. A lifted choice takes a per-instance discriminator pin plus the
    unified pruning rule, aggregated once over every element rather than per
    instance, since a variant chosen by even one element keeps its shared
    `"[]."` template descendants for all of them. A nested list recurses
    into this function one level deeper.

    Only the outermost level's own domain is ever narrowed. A nested level's
    `element_domain` is a template shared across every outer row rather than
    a per-instance fact, which is how `_validate_list_default_level` treats
    a nested `list_default`.

    `list_default` is skipped for a choice-kind list. Its validation, run by
    `space_from_ir`'s revalidation through `_validate_list_default_level`,
    treats it as a complete nested-config value, so a payload-bearing
    variant needs its full payload spelled out as
    `{"local_search": {"iters": 5}}` rather than the bare discriminator
    string `.freeze()` accepts. That bare-string convention is the one
    `_domain_error_reason`'s `ChoiceDomain` branch uses for the
    discriminator alone. Freeze is never given the payload, so
    `list_default` is left untouched, as top-level choice-freeze sets no
    `default` at all. Choice is always generative, so no
    `SamplingError`-avoidance guarantee is lost.

    Per-element validation runs at the outermost, non-nested level only.
    `space.validate_param` resolves a single-bracket instance path such as
    `"xs[0]"` or `"pipeline[1]"` by synthesizing an `element_paramdef`, but
    `_lookup_param_shape` in `validate/_validate.py` has no resolution path
    for a doubly bracketed one such as `"m[0][0]"`, a nested
    `.repeat().repeat()` element. That is a pre-existing limit of
    `validate_param`, unrelated to freeze. A nested recursive call, which
    `_INDEX_RE.search(path)` detects on the incoming `path`, therefore skips
    the pre-check and relies on the outer level's `list_default`-triggered
    deep revalidation to catch a malformed nested value.
    """
    if isinstance(domain.count, int) and domain.count != len(value):
        raise ResolutionError(
            f"{call}: {path!r} has a fixed count of {domain.count}, but the "
            f"given list has {len(value)} element(s)"
        )
    already_nested = bool(_INDEX_RE.search(path))
    new_domain = (
        replace(domain, count=len(value))
        if domain.element_kind == "choice"
        else replace(domain, count=len(value), list_default=value)
    )
    param_updates: dict[str, ParamDef] = {}
    removed_paths: set[str] = set()
    constraints: list[Constraint] = []

    if domain.element_kind == "choice":
        assert isinstance(domain.element_domain, ChoiceDomain)
        el_domain = domain.element_domain
        for i, elem_value in enumerate(value):
            inst_path = f"{path}[{i}]"
            if not already_nested:
                _validate_leaf(space, inst_path, elem_value, call=call)
            constraints.append(
                _require_pin(Compare("eq", ParamExpr(path=inst_path), Literal(elem_value)))
            )
        selected = set(value)
        removed_prefixes = tuple(f"{path}[].{v}." for v in el_domain.variants if v not in selected)
        removed_paths = {
            p for p in space.params if any(p.startswith(pre) for pre in removed_prefixes)
        }
        return param_updates, frozenset(removed_paths), tuple(constraints), new_domain

    for i, elem_value in enumerate(value):
        inst_path = f"{path}[{i}]"
        sub: _FreezeExpansion
        if domain.element_kind == "space":
            if not isinstance(elem_value, dict):
                raise ResolutionError(f"{call}: {inst_path!r} is a struct element; expected a dict")
            sub = _expand_struct(space, inst_path, elem_value, call=call)
        elif domain.element_kind == "list":
            assert isinstance(domain.element_domain, ListDomain)
            if not isinstance(elem_value, list):
                raise ResolutionError(
                    f"{call}: {inst_path!r} is a nested list element; expected a list"
                )
            inner_updates, inner_removed, inner_constraints, _inner_domain = _expand_list_body(
                space, inst_path, domain.element_domain, elem_value, call=call
            )
            sub = _FreezeExpansion(inner_updates, inner_removed, inner_constraints)
        else:
            if not already_nested:
                _validate_leaf(space, inst_path, elem_value, call=call)
            sub = _FreezeExpansion(
                {},
                frozenset(),
                (_require_pin(Compare("eq", ParamExpr(path=inst_path), Literal(elem_value))),),
            )
        param_updates.update(sub.param_updates)
        removed_paths.update(sub.removed_paths)
        constraints.extend(sub.constraints)
    return param_updates, frozenset(removed_paths), tuple(constraints), new_domain


def _expand_list(
    space: Space, path: str, list_pd: ParamDef, value: list[Any], *, call: str
) -> _FreezeExpansion:
    if _INDEX_RE.search(path):
        # A list reached at a `.repeat()` instance path, meaning a
        # list-typed field of a struct-in-list element, shares its
        # `ListDomain` across every instance as a scalar, subset or
        # permutation field would, so there is no per-instance count or
        # list_default to narrow. Direct `.repeat().repeat()` nesting never
        # reaches this function; `_expand_list_body`'s own nested-list
        # branch handles it.
        raise ResolutionError(
            f"{call}: {path!r} is a list nested inside another list's element "
            "and is not supported by .freeze()"
        )
    domain = list_pd.domain
    assert isinstance(domain, ListDomain)
    param_updates, removed_paths, constraints, new_domain = _expand_list_body(
        space, path, domain, value, call=call
    )
    param_updates = {path: replace(list_pd, domain=new_domain), **param_updates}
    return _FreezeExpansion(param_updates, removed_paths, constraints)


def _expand_leaf_or_container(
    space: Space, path: str, pd: ParamDef, value: Any, *, call: str
) -> _FreezeExpansion:
    """The recursive dispatcher every `.freeze()` expansion goes through.

    Every top-level target and every struct fan-out or list per-element
    recursive call enters here. The same dispatch serves a top-level
    `to_fix` path, a struct field's own path and a list element's instance
    path, which is what makes struct-of-struct nesting, a struct field that
    is itself a subset, choice or list, and list-of-struct fall out with no
    per-shape special casing beyond the branches here.
    """
    kind = pd.type_kind
    if kind == "space":
        assert isinstance(pd.domain, StructDomain)
        if not isinstance(value, dict):
            raise ResolutionError(f"{call}: {path!r} is a struct; expected a dict of field values")
        return _expand_struct(space, path, value, call=call)
    if kind == "list":
        assert isinstance(pd.domain, ListDomain)
        if not isinstance(value, list):
            raise ResolutionError(f"{call}: {path!r} is a list param; expected a list value")
        return _expand_list(space, path, pd, value, call=call)
    if kind == "choice":
        assert isinstance(pd.domain, ChoiceDomain)
        _validate_leaf(space, path, value, call=call)
        return _expand_choice(space, path, pd.domain, value)
    if kind == "subset":
        _validate_leaf(space, path, value, call=call)
        return _expand_subset(path, pd, value)
    if kind == "permutation":
        _validate_leaf(space, path, value, call=call)
        return _expand_permutation(path, pd, value)
    if _INDEX_RE.search(path):
        # A scalar or custom leaf inside a `.repeat()`, such as
        # `dropout[3]`, or a scalar or custom field of a struct-in-list
        # element, such as `stops[2].dwell_min`. The enclosing `ParamDef` is
        # a template shared by every instance, so there is no
        # single-occurrence domain to narrow. Pin this one instance with a
        # hard equality constraint instead, the mechanism
        # `_expand_list_body` uses for its own direct per-element pins.
        _validate_leaf(space, path, value, call=call)
        return _FreezeExpansion(
            {},
            frozenset(),
            (_require_pin(Compare("eq", ParamExpr(path=path), Literal(value))),),
        )
    validated_pd = _validate_fixed_value(space, path, value, call=call)
    new_pd, extra = _narrow_or_pin(validated_pd, value, call=call)
    return _FreezeExpansion({path: new_pd}, frozenset(), (extra,) if extra is not None else ())


def _expand_freeze_target(space: Space, path: str, value: Any, *, call: str) -> _FreezeExpansion:
    if path not in space.params:
        raise ResolutionError(f"{call}: no such param {path!r}")
    return _expand_leaf_or_container(space, path, space.params[path], value, call=call)


def _narrow_or_pin(pd: ParamDef, value: Any, *, call: str) -> tuple[ParamDef, Constraint | None]:
    """Freeze one of the six kinds with a dedicated per-occurrence `ParamDef`.

    Real, integer, categorical and ordinal narrow their domain to the single
    fixed value, which the Degeneracy Table already makes legal for
    `lo == hi`. Bool has no domain to narrow and is pinned with a hard
    `require` or `require(~.)` constraint. Custom delegates to `_pin_custom`.
    Every kind also gets `default = value`.

    Choice, subset, permutation, struct and list, and any bracket-containing
    `.repeat()` instance path, which shares its `ParamDef` across instances
    and so has nothing of its own to narrow, are dispatched by
    `_expand_leaf_or_container` before reaching this function.
    """
    kind = pd.type_kind
    if kind == "real":
        assert isinstance(pd.domain, RealDomain)
        return replace(
            pd,
            domain=RealDomain(value, value),
            periodic=False,
            prior=None,
            quantized=None,
            default=value,
        ), None
    if kind == "integer":
        assert isinstance(pd.domain, IntegerDomain)
        return replace(
            pd, domain=IntegerDomain(value, value), prior=None, quantized=None, default=value
        ), None
    if kind == "categorical":
        assert isinstance(pd.domain, CategoricalDomain)
        return replace(pd, domain=CategoricalDomain((value,)), prior=None, default=value), None
    if kind == "ordinal":
        assert isinstance(pd.domain, OrdinalDomain)
        return replace(pd, domain=OrdinalDomain((value,)), prior=None, default=value), None
    if kind == "bool":
        expr: BoolExpr = ParamExpr(path=pd.path) if value else Not(ParamExpr(path=pd.path))
        constraint = Constraint(
            expr=expr,
            hard=True,
            origin="require",
            tags=frozenset(),
            meta=MappingProxyType({}),
            params=expr.params,
        )
        return replace(pd, default=value), constraint
    if kind == "custom":
        return _pin_custom(pd, value, call=call)
    if kind in ("symbolic", "code"):
        return _pin_program(pd, value)
    raise AssertionError(f"unreachable: {kind!r} is dispatched before _narrow_or_pin")


def _pin_custom(pd: ParamDef, value: Any, *, call: str) -> tuple[ParamDef, Constraint | None]:
    """Freeze a custom param with a `require(p == value)` hard pin.

    This generalizes bool's pin mechanism. It is the only freeze mechanism
    generically available for an opaque value, a custom domain having
    nothing to narrow. `value` is already phenotype form, so equality
    compares structurally on the type's own `to_json()` shape; every
    full-protocol type supports that for free, with no `__eq__` requirement
    on the native value.

    Full protocol only. The shorthand form has no `to_json`, and therefore
    no comparable, serializable value to pin against.

    `default = value` is also set. Bool's pin never needs this, bool being
    always generative, but a non-generative custom has no other route to a
    value at `sample()` time. Setting the default is what makes API.md's
    ".freeze() removes [the non-generative SamplingError]" (API.md,
    "Sampling and Generativity") hold for custom, following the
    domain-narrowing kinds rather than bool's bare pin.
    """
    domain = pd.domain
    assert isinstance(domain, CustomDomain)
    if domain.param_type is None:
        raise ResolutionError(
            f"{call}: {pd.path!r} uses the .custom(sampler, validator) "
            "shorthand; freeze requires the full ParamType protocol "
            "(needs to_json() for a comparable, serializable pinned value)"
        )
    expr: BoolExpr = Compare("eq", ParamExpr(path=pd.path), Literal(value))
    constraint = Constraint(
        expr=expr,
        hard=True,
        origin="require",
        tags=frozenset(),
        meta=MappingProxyType({}),
        params=expr.params,
    )
    return replace(pd, default=value), constraint


def _pin_program(pd: ParamDef, value: Any) -> tuple[ParamDef, Constraint | None]:
    """Freeze a `.symbolic()` or `.code()` param.

    This generalizes `_pin_custom`: a `require(p == value)` hard pin plus
    `default = value`, for the same reasons. There is no domain to narrow
    for an opaque value, and a non-generative program param has no other
    route to a value at `sample()` time.

    There is no shorthand exception. Unlike a custom type, a program value
    is always a plain, comparable, serializable JSON dict, so freezing is
    unconditionally available.
    """
    expr: BoolExpr = Compare("eq", ParamExpr(path=pd.path), Literal(value))
    constraint = Constraint(
        expr=expr,
        hard=True,
        origin="require",
        tags=frozenset(),
        meta=MappingProxyType({}),
        params=expr.params,
    )
    return replace(pd, default=value), constraint


def _domain_is_singleton(domain: Any) -> bool:
    """Whether a domain admits exactly one value.

    This is the gate on `.freeze()`'s fold; see `_statically_resolve_frozen`.
    It is true only for the kinds freeze narrows: real and integer at
    `lo == hi`, categorical and ordinal at one value. Every
    constraint-pinned kind answers False, which is the point.
    """
    if isinstance(domain, RealDomain | IntegerDomain):
        return bool(domain.lo == domain.hi)
    if isinstance(domain, CategoricalDomain | OrdinalDomain):
        return len(domain.values) == 1
    return False


def _statically_resolve_frozen(
    space: Space, merged_params: dict[str, ParamDef], to_fix: dict[str, Any]
) -> tuple[dict[str, ParamDef], tuple[Condition, ...]]:
    """Substitute the frozen values into derived structure, then fold.

    Freeze keeps the param, unlike `.slice()`, which is why its fold is the
    narrower of the two. A literal may be substituted only where the frozen
    param's domain admits a single value: real and integer narrowed to
    `lo == hi`, categorical and ordinal to one value.

    The kinds freeze pins with a hard `require` instead, meaning bool,
    choice, subset, permutation, custom and program under API.md's per-kind
    mechanism, keep a domain that still admits their other values. A config
    may then legally hold one of those values and merely be infeasible, and
    folding a condition against the pinned value would wrongly report a
    param active there. `.slice()` faces no such case, having removed the
    param outright.

    The valid-config set is the same either way, since every config the
    distinction touches already fails the pin. What it would change is the
    fingerprint, and a choice freeze must stay fingerprint-equal to its
    hand-written pin-and-prune expansion, which is `TestFreezeChoice`'s
    permanent law.

    Only leaf entries of `to_fix` contribute a literal. A struct or list
    path fans out through `_expand_freeze_target` into per-field or
    per-instance fixes and has no scalar value of its own to substitute.
    That is conservative: a count reading a frozen struct's field folds when
    the field is named directly, as `freeze(**{"grp.n": 3})`, and not when
    the struct is, as `freeze(grp={"n": 3})`. Conservative is always sound
    here, since an unfolded count merely stays dynamic.
    """
    literals: dict[str, Expr] = {}
    for path, value in to_fix.items():
        pd = space.params.get(path)
        if pd is None or pd.type_kind in ("space", "list"):
            continue
        if not _domain_is_singleton(merged_params[path].domain):
            continue
        literals[path] = _literal_for(pd, value)
    if not literals:
        return merged_params, tuple(space.conditions)

    folded: dict[str, ParamDef] = {}
    for path, pd in merged_params.items():
        new_condition = (
            fold_condition(substitute_bool(pd.condition, literals), space)
            if pd.condition is not None
            else None
        )
        folded[path] = replace(
            pd,
            condition=new_condition,
            domain=fold_domain(substitute_domain(pd.domain, literals), space),
        )
    conditions = tuple(
        c
        for c in space.conditions
        if folded.get(c.target) is None or folded[c.target].condition is not None
    )
    return folded, conditions


def freeze(space: Space, to_fix: dict[str, Any]) -> Space:
    """`.freeze(values=None, **kw)`: fix values and keep the params.

    See API.md, "Space: Structural Operations". Conditions resolve
    statically. Each top-level path expands into `ParamDef` replacements
    that narrow a domain or set a default, removed paths from choice's
    structural pruning, which is the only kind that drops params, and extra
    hard `require` constraints.

    Choice pruning is the only reason the two final branches diverge. With
    no removed params, every kind gets `space_from_ir` plus a hard-fail
    anchor re-validation. With removed params, the result goes through
    `.select()`'s anchor strip and drop machinery in `_apply_keep_set`,
    since a hard-fail re-validation would wrongly assume no param was
    removed.
    """
    param_updates: dict[str, ParamDef] = {}
    removed_paths: set[str] = set()
    extra_constraints: list[Constraint] = []
    for path, value in to_fix.items():
        expansion = _expand_freeze_target(space, path, value, call=".freeze()")
        param_updates.update(expansion.param_updates)
        removed_paths.update(expansion.removed_paths)
        extra_constraints.extend(expansion.constraints)

    merged_params: dict[str, ParamDef] = {**space.params, **param_updates}
    merged_constraints = tuple(space.constraints) + tuple(extra_constraints)
    merged_params, merged_conditions = _statically_resolve_frozen(space, merged_params, to_fix)

    if not removed_paths:
        from designspace.meta import space_from_ir

        result = space_from_ir(
            merged_params,
            merged_conditions,
            merged_constraints,
            anchors=dict(space.anchors),
            meta=dict(space.meta_map),
        )
        return _revalidate_anchors_unchanged_shape(result, call=".freeze()")

    pre_prune = Space(
        params=MappingProxyType(merged_params),
        conditions=merged_conditions,
        constraints=merged_constraints,
        anchors=space.anchors,
        meta_map=space.meta_map,
    )
    keep = set(merged_params) - removed_paths
    return _apply_keep_set(pre_prune, keep, strict=False, call=".freeze()")


# -- slice ---------------------------------------------------------------------


def slice_space(space: Space, to_remove: dict[str, Any]) -> Space:
    from designspace.meta import space_from_ir

    removed_defs: dict[str, ParamDef] = {
        path: _validate_fixed_value(space, path, value, call=".slice()")
        for path, value in to_remove.items()
    }
    for path, pd in removed_defs.items():
        if pd.type_kind == "custom":
            # A custom value's only expression-visible surface is
            # `.prop()`, a Prop node wrapping the param reference.
            # Substituting the whole param away would leave that Prop
            # wrapping a bare Literal, which evaluate_arith's Prop handling
            # does not support. Reject cleanly rather than producing a space
            # that fails unpredictably at evaluation.
            raise ResolutionError(
                f".slice(): {path!r} is a custom param; .slice() does not "
                "support removing/substituting custom-typed params"
            )
    literals: dict[str, Literal | BoolLiteral] = {
        path: _literal_for(pd, to_remove[path]) for path, pd in removed_defs.items()
    }
    bound_targets = bound_origin_targets(space)

    new_params: dict[str, ParamDef] = {}
    for path, pd in space.params.items():
        if path in to_remove:
            continue
        new_condition = (
            fold_condition(substitute_bool(pd.condition, literals), space)
            if pd.condition is not None
            else None
        )
        new_params[path] = replace(
            pd,
            condition=new_condition,
            domain=fold_domain(substitute_domain(pd.domain, literals), space),
        )

    new_conditions: list[Condition] = []
    for c in space.conditions:
        if c.target in to_remove:
            continue
        # Keep the `Condition` store in step with the `ParamDef` it
        # targets: a condition folded away there must not survive here.
        if new_params.get(c.target) is not None and new_params[c.target].condition is None:
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
        new_params,
        new_conditions,
        new_constraints,
        anchors=new_anchors,
        meta=dict(space.meta_map),
    )
    for name, config in result.anchors.items():
        if not result.validate(config).valid:
            raise ResolutionError(f".slice(): anchor {name!r} invalid after slicing")
    return result


def _recompute_bound_envelopes(
    new_params: dict[str, ParamDef],
    bound_targets: dict[str, tuple[ArithExpr | None, ArithExpr | None]],
    literals: dict[str, Literal | BoolLiteral],
) -> None:
    """Recompute bound envelopes after a `.slice()`.

    API.md says of `.slice()` that "envelopes recompute on re-resolution".
    The domain's own lo and hi collapsed to numbers at the first resolution,
    so the bound-origin constraint's original expression is recovered from
    `bound_origin_targets` instead, substituted, and re-hulled through the
    same interval-arithmetic `hull` in `resolve/_bounds.py` that
    `compute_bound_envelopes` used. The recomputation bootstraps from the
    current, already-numeric envelopes of whatever params remain.
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
                        f"{def_path!r} = {fixed!r} (anchor has {v!r})"
                    )
                continue
            stripped[concrete_path] = v
        result[name] = unflatten(stripped, skeleton)
    return result
