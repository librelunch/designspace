"""Space — Structural Operations (API.md): `slice`, `freeze`,
`active_subspace`, `select`, `filter`, `extend`.

Each returns a new `Space`; anchor interactions and the positional-`dict`
path-argument form are documented per-function (API.md, "Space —
Structural Operations": "Path arguments accept both keyword form and a
positional `dict[str, Any]` (required when paths contain `.` or `[]`)").
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
    Prop,
    Size,
    Sum,
    SumOver,
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
    if isinstance(node, Prop):
        return Prop(cast_arith(substitute_expr(node.operand, literals)), node.name)
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


def _definition_path_of(concrete_path: str) -> str:
    """A `flatten()`-produced concrete instance path (`"edges[3].weight"`)
    back to its definition-path template (`"edges[].weight"`) — the shape
    `space.params`/prefix-based selection sets use."""
    return _INDEX_RE.sub("[]", concrete_path)


def _governing_definition_path(space: Space, path: str) -> str:
    """The `space.params` key that actually owns `path`, mirroring
    `validate/_validate.py::_lookup_param_shape`'s own fallback chain
    (D-50): a bare definition path is its own owner; a struct-lift
    descendant instance path (`"stops[2].location"`) is owned by its
    `"[]"`-templated form (`"stops[].location"`, a real relocated
    `ParamDef`); a *direct* lift element instance path (`"pipeline[0]"`,
    `"dropout[3]"`) has no such template key at all — only the base list
    param (`"pipeline"`) is real — so `_definition_path_of`'s blanket
    `"[]"`-substitution is wrong for it specifically (`"pipeline[]"` is
    never a key). Used wherever a path from a `Constraint.params`/anchor
    flat key needs to be checked against a keep-set of `space.params` keys.
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


def _apply_keep_set(space: Space, keep: set[str], *, strict: bool, call: str) -> Space:
    """The exact-keep-set half of `.select()`'s pruning (`_prune_to` closes
    `keep` over ancestor/descendant structure first, then delegates here):
    filter params/conditions/constraints to `keep` (warn, or raise if
    `strict`, on a dropped constraint), strip/drop anchors, rebuild via
    `space_from_ir`. Also used directly by choice-freeze's structural
    pruning (DECISIONS.md D-50), which already knows its exact keep-set
    (every variant-descendant path it's removing) and has no ancestor/
    descendant closure to compute.

    `keep` holds only *definition* paths (`space.params`' own keys are
    never instance-path-shaped), so a constraint's `.params` must be
    compared through `_governing_definition_path` — otherwise a
    require-pin on a `.repeat()` instance path (`"pipeline[0]"`, D-50's own
    per-element choice/list pins) would always look "excluded" and be
    dropped, even though its owning param survives. Mirrors
    `_strip_anchor_keys`'s identical normalization for anchor config keys.
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

    result = _build_space_from_ir(
        new_params, new_conditions, new_constraints,
        anchors=stripped_anchors, meta=dict(space.meta_map),
    )
    return _drop_invalid_anchors(result, call=call)


def _prune_to(space: Space, keep: set[str], *, strict: bool, call: str) -> Space:
    keep = _close_over_structure(space, keep)
    return _apply_keep_set(space, keep, strict=strict, call=call)


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
    """The hard `require`-pin `Constraint` shape every freeze mechanism
    that isn't a domain-narrow uses (bool, custom, and — from M9.5 —
    subset/permutation/choice/list-element pins), built directly rather
    than through `Space.require()`/`add_constraints`: the param is already
    declared and resolved, so none of `check_refs_declared`/
    `check_expr_types`/`desugar_bool` has anything left to check.
    """
    return Constraint(
        expr=expr, hard=True, origin="require", tags=frozenset(),
        meta=MappingProxyType({}), params=expr.params,
    )


def _validate_leaf(space: Space, path: str, value: Any, *, call: str) -> None:
    """Choice/subset/permutation's own value-shape check — `validate_param`
    already fully validates these via `_domain_error_reason`'s existing
    `ChoiceDomain`/`SubsetDomain`/`PermutationDomain` branches (unchanged),
    whether `path` is a bare definition path or a `.repeat()` instance path
    (resolved via `element_paramdef` synthesis)."""
    result = space.validate_param(path, value)
    if not result.valid:
        reasons = "; ".join(f"{e.reason}" for e in result.param_errors) or "invalid value"
        raise ResolutionError(f"{call}: {path!r} = {value!r} is invalid ({reasons})")


@dataclass(frozen=True)
class _FreezeExpansion:
    """One `.freeze()` target's full expansion (DECISIONS.md D-50): the
    `ParamDef`s it replaces (domain-narrow/default-set kinds), the paths it
    removes entirely (choice's structural pruning), and the extra hard
    `require` constraints it pins. Struct fan-out and list per-element
    pinning merge sub-expansions from recursive calls; a plain scalar/bool/
    custom target and subset/permutation/choice's own per-path expansion
    are each already a complete, non-recursive one."""

    param_updates: dict[str, ParamDef]
    removed_paths: frozenset[str]
    constraints: tuple[Constraint, ...]


def _expand_subset(path: str, pd: ParamDef, value: list[Any]) -> _FreezeExpansion:
    """subset (D-50): a per-item `require(contains(p, i))` /
    `require(~contains(p, i))` pin for every declared item — no domain to
    narrow (`SubsetDomain` has no single-value shape). Sets `default =
    value` at a genuine per-occurrence path (matches `_default_is_valid_subset`'s
    identical value shape) — but *not* at a `.repeat()` instance path
    (`_INDEX_RE.search(path)`), where `pd` is the shared element template,
    not a dedicated `ParamDef` for this one instance."""
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
    """permutation (D-50): a per-position `require(position_of(p, item) ==
    k)` pin for each index. No domain to narrow; `default = value` at a
    per-occurrence path only (mirrors `_expand_subset`)."""
    assert isinstance(pd.domain, PermutationDomain)
    constraints = tuple(
        _require_pin(Compare("eq", PositionOf(ParamExpr(path=path), item), Literal(k)))
        for k, item in enumerate(value)
    )
    if _INDEX_RE.search(path):
        return _FreezeExpansion({}, frozenset(), constraints)
    return _FreezeExpansion({path: replace(pd, default=value)}, frozenset(), constraints)


def _expand_choice(space: Space, path: str, domain: ChoiceDomain, value: str) -> _FreezeExpansion:
    """choice (D-50): a discriminator pin `require(c == variant)`, plus the
    **unified pruning rule** — a variant's relocated descendants (paths
    under `f"{template}.{variant}."`) are pruned iff *no* instance being
    frozen in this call selects it. A plain (non-lifted) choice has exactly
    one instance, so this reduces to "prune every variant but the chosen
    one" (D-44's originally anticipated behavior). `ChoiceDomain.variants`
    itself is never narrowed (nothing analogous to `lo == hi` exists for
    it — mirrors bool) and no `default` is set (choice sampling is always
    generative; the pin alone fully determines it).

    A choice reached at a `.repeat()` instance path (`stops[2].category` —
    a choice-typed *field* of a struct-in-list element, not a direct
    list-of-choice element) shares its relocated descendants with every
    *other* instance's own struct fan-out call: pruning from only this
    one instance's selection would be unsound (a sibling instance's own
    freeze call may still need the variant this one doesn't select). A
    direct list-of-choice element never reaches this function at all —
    `_expand_list_body` aggregates over every instance inline, first —
    so this is a narrow, deliberately conservative (unpruned, still
    correctly pinned) fallback for the nested-struct-field composition
    only.
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
    """struct (D-50): no value of its own (`StructDomain` — "a pure
    namespace"; `.default()` on a struct is already row 21's resolution
    error) — fans out to the *same* per-kind dispatch at each given field's
    fully-qualified path. A partial dict fixes only the given fields; a
    field that is itself a struct/choice/subset/permutation/list recurses
    with no extra code. Works identically whether `struct_path` is a plain
    definition path or a `.repeat()` instance path (`stops[2]`) — the field
    lookup goes through the definition-path template either way."""
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
    """list (D-50), shared between the outermost `.repeat()` level and a
    nested `.repeat().repeat()` recursive call: narrows `count` to the
    literal `len(value)` (dropping whatever `int | ArithExpr` governed it
    before, mirroring real/integer's "drop any prior" narrowing) and sets
    `list_default = value` (mirrors custom's D-47 rationale — inert when
    elements are generative, satisfies the non-generative-element
    `SamplingError` guarantee when they aren't). A pre-existing *literal*
    `count` that doesn't match `len(value)` is a resolution error, checked
    here — the only place a literal count is ever cross-checked against a
    realized length (neither `validate/_validate.py::_validate_lift_instances`
    nor `resolve/_pipeline.py::_validate_list_default_level` do this for a
    literal count). Each element is then pinned per `element_kind`: scalar/
    custom/bool via a per-instance `require(p[i] == value[i])`; struct via
    the same field fan-out rooted at the instance path; a lifted choice via
    a per-instance discriminator pin plus the unified pruning rule,
    aggregated once over every element (not per-instance — a variant
    chosen by even one element keeps its shared `"[]."` template
    descendants for every element); a nested list via this same function
    one level deeper — only the *outermost* level's own domain is ever
    narrowed, since a nested level's `element_domain` is a template shared
    across every outer row (confirmed via `_validate_list_default_level`'s
    treatment of a nested `list_default` as one shared value applied
    identically to every outer row), not a per-instance fact.

    **`list_default` is skipped for a choice-kind list.** `list_default`'s
    own validation (`resolve/_pipeline.py::_validate_list_default_level`,
    run automatically by `space_from_ir`'s revalidation) treats it as a
    *complete nested-config value* — a payload-bearing variant there needs
    its full payload spelled out (`{"local_search": {"iters": 5}}`), not
    the bare discriminator string `.freeze()` accepts (matching the same
    bare-string convention `_domain_error_reason`'s `ChoiceDomain` branch
    already uses for the discriminator alone). Since freeze is never given
    that payload, `list_default` is left untouched (mirrors top-level
    choice-freeze setting no `default` at all) — choice is always
    generative, so this loses no `SamplingError`-avoidance guarantee.

    **Per-element validation only at the outermost, non-nested level.**
    `space.validate_param` (`_validate_leaf`) resolves a single-bracket
    instance path (`"xs[0]"`, `"pipeline[1]"`) via `element_paramdef`
    synthesis, but `validate/_validate.py::_lookup_param_shape` has no
    resolution path for a *doubly*-bracketed one (`"m[0][0]"` — a nested
    `.repeat().repeat()` element) — a pre-existing scope limit of
    `validate_param` itself, unrelated to freeze. A nested recursive call
    (`_INDEX_RE.search(path)` true on the *incoming* `path`) therefore
    skips the pre-check and relies entirely on the outer level's
    `list_default`-triggered automatic deep revalidation to catch a
    malformed nested value instead.
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
        removed_prefixes = tuple(
            f"{path}[].{v}." for v in el_domain.variants if v not in selected
        )
        removed_paths = {
            p for p in space.params if any(p.startswith(pre) for pre in removed_prefixes)
        }
        return param_updates, frozenset(removed_paths), tuple(constraints), new_domain

    for i, elem_value in enumerate(value):
        inst_path = f"{path}[{i}]"
        sub: _FreezeExpansion
        if domain.element_kind == "space":
            if not isinstance(elem_value, dict):
                raise ResolutionError(
                    f"{call}: {inst_path!r} is a struct element — expected a dict"
                )
            sub = _expand_struct(space, inst_path, elem_value, call=call)
        elif domain.element_kind == "list":
            assert isinstance(domain.element_domain, ListDomain)
            if not isinstance(elem_value, list):
                raise ResolutionError(
                    f"{call}: {inst_path!r} is a nested list element — expected a list"
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
        # A list reached at a `.repeat()` instance path (a list-typed field
        # of a struct-in-list element) shares its `ListDomain` across every
        # instance the same way a scalar/subset/permutation field would —
        # there is no per-instance count/list_default to narrow. Direct
        # `.repeat().repeat()` nesting never reaches this function (handled
        # entirely inside `_expand_list_body`'s own nested-list branch).
        raise ResolutionError(
            f"{call}: {path!r} is a list nested inside another list's element "
            "— not yet supported by .freeze()"
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
    """The single recursive dispatcher every `.freeze()` target and every
    struct-fan-out/list-per-element recursive call goes through (D-50) —
    reused identically at a top-level `to_fix` path, a struct field's own
    path, and a list element's instance path, which is what makes nested
    struct-of-struct, a struct field that is itself a subset/choice/list,
    list-of-struct, etc. fall out with no per-shape special casing beyond
    the dispatch branches here."""
    kind = pd.type_kind
    if kind == "space":
        assert isinstance(pd.domain, StructDomain)
        if not isinstance(value, dict):
            raise ResolutionError(
                f"{call}: {path!r} is a struct — expected a dict of field values"
            )
        return _expand_struct(space, path, value, call=call)
    if kind == "list":
        assert isinstance(pd.domain, ListDomain)
        if not isinstance(value, list):
            raise ResolutionError(f"{call}: {path!r} is a list param — expected a list value")
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
        # A scalar/custom leaf inside a `.repeat()` (`dropout[3]`, or a
        # scalar/custom *field* of a struct-in-list element,
        # `stops[2].dwell_min`): the enclosing `ParamDef` is a template
        # shared by every instance, so there is no single-occurrence domain
        # to narrow — pin this one instance via a hard equality constraint
        # instead (D-50), the same mechanism `_expand_list_body` uses for
        # its own direct per-element pins.
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
    """`.freeze()`'s per-kind mechanism for the six kinds with a genuine,
    dedicated per-occurrence `ParamDef` (DECISIONS.md D-44/D-47): real/
    integer/categorical/ordinal narrow their domain to the single fixed
    value (Degeneracy Table: `lo == hi` is already legal); bool has no
    domain to narrow, so it's pinned via a hard `require`/`require(~.)`
    constraint instead; custom delegates to `_pin_custom`. Every kind also
    gets `default = value`. Choice/subset/permutation/struct/list (M9.5,
    DECISIONS.md D-50), and any bracket-containing `.repeat()` instance
    path (which shares its `ParamDef` across every instance, so has nothing
    of its own to narrow), are dispatched by `_expand_leaf_or_container`
    before ever reaching this function.
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
    if kind == "custom":
        return _pin_custom(pd, value, call=call)
    raise AssertionError(f"unreachable: {kind!r} is dispatched before _narrow_or_pin (D-50)")


def _pin_custom(pd: ParamDef, value: Any, *, call: str) -> tuple[ParamDef, Constraint | None]:
    """Freeze-on-custom (DECISIONS.md D-47, generalizing D-44's bool-pin
    mechanism): a `require(p == value)` hard pin — the *only* generically
    available freeze mechanism for an opaque value, since a custom domain
    has nothing to narrow. `value` is already phenotype form (D-46), so
    equality compares structurally on the type's own `to_json()` shape —
    every full-protocol type supports this "equality" for free, with no
    `__eq__` requirement on the native value at all. **Full protocol
    only**: the shorthand form has no `to_json`, hence no comparable,
    serializable value to pin against.

    Also sets `default = value` — unlike bool's pin (which never needs
    this, since bool is always generative), a *non-generative* custom has
    no other route to a value at sample() time; setting the default here
    is what makes ".freeze() removes [the non-generative SamplingError]"
    (API.md, "Sampling and Generativity") hold for custom, mirroring the
    domain-narrowing kinds' `default = value` rather than bool's bare pin.
    """
    domain = pd.domain
    assert isinstance(domain, CustomDomain)
    if domain.param_type is None:
        raise ResolutionError(
            f"{call}: {pd.path!r} uses the .custom(sampler, validator) "
            "shorthand — freeze requires the full ParamType protocol "
            "(needs to_json() for a comparable, serializable pinned value)"
        )
    expr: BoolExpr = Compare("eq", ParamExpr(path=pd.path), Literal(value))
    constraint = Constraint(
        expr=expr, hard=True, origin="require", tags=frozenset(),
        meta=MappingProxyType({}), params=expr.params,
    )
    return replace(pd, default=value), constraint


def freeze(space: Space, to_fix: dict[str, Any]) -> Space:
    """`.freeze(values=None, **kw)` (API.md, "Space — Structural
    Operations"): fix values, keep params in output, conditions resolve
    statically. Each top-level path expands (D-50) into a set of `ParamDef`
    replacements (domain-narrow/default-set), removed paths (choice's
    structural pruning, the only kind that drops params), and extra hard
    `require` constraints. Choice pruning is the only reason the two final
    branches diverge: with no removed params, every already-shipped kind
    (real/integer/categorical/ordinal/bool/custom) gets the exact same
    `space_from_ir` + hard-fail anchor re-validation as before M9.5; with
    removed params, the result instead goes through `.select()`'s anchor
    strip/drop machinery (`_apply_keep_set`), since params were genuinely
    removed and a hard-fail re-validation would wrongly assume none were.
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

    if not removed_paths:
        from designspace.meta import space_from_ir

        result = space_from_ir(
            merged_params,
            space.conditions,
            merged_constraints,
            anchors=dict(space.anchors),
            meta=dict(space.meta_map),
        )
        return _revalidate_anchors_unchanged_shape(result, call=".freeze()")

    pre_prune = Space(
        params=MappingProxyType(merged_params),
        conditions=space.conditions,
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
            # A custom value's only expression-visible surface is `.prop()`
            # (a Prop node wrapping the param reference); substituting the
            # whole param away would leave that Prop wrapping a bare
            # Literal, which evaluate_arith's Prop handling does not
            # support (DECISIONS.md D-47) — reject cleanly rather than
            # producing a space that fails unpredictably at evaluation.
            raise ResolutionError(
                f".slice(): {path!r} is a custom param — .slice() does not "
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
