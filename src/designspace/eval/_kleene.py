"""Kleene evaluation (API.md, "Expressions" > "Three-valued semantics").

`Unknown` carries a **provenance** (rule 5, M10.5/D-71): `"inactive"` (rule
1 — the only one `.if_inactive()` coalesces), `"pending"` (an operand not
yet present in a *partial* config — never coalesced, since eating it would
make a driver loop conclude a constraint is satisfied while the value that
will violate it is still unassigned), or `"permanent"` (rule 6 emptiness —
`min`/`max` of an active empty lift — or a structurally malformed leaf;
never coalesced either, since the method's own name disclaims an *active*
empty lift). `_leaf_value`'s "active but missing from config" branch used
to be a defensive M2-era catch-all (no partial-config API existed yet to
give it meaning); it is now exactly the "pending" case Partial Configs (M6)
defines. Three singletons — `UNKNOWN_INACTIVE`/`UNKNOWN_PENDING`/
`UNKNOWN_PERMANENT` — are joined by `_join_unknown` (max over
`INACTIVE < PENDING < PERMANENT`) wherever a node combines more than one
Unknown-valued operand, so a mixed node never under-reports how resolvable
it is. `UNKNOWN` stays bound to the `"permanent"` singleton for sites that
only ever produce that provenance (rule-6 emptiness, a malformed value);
`isinstance(x, Unknown)` still matches all three, unchanged for every
existing caller outside this module.

Every evaluator here takes `space` (not just `config`/`activity`), because
ordinal ordering compares by *declaration position*, not by the raw value
("Ordered by declaration position. Comparison yes, arithmetic no.") — a
leaf's domain has to be looked up to translate its value to an index before
`>`/`<`/`>=`/`<=` mean anything.

Internal to the library: not part of the public surface (mirrors how
`resolve_space` isn't re-exported either).
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise
from typing import Any, ClassVar, NamedTuple

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
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
from designspace.ir import CustomDomain, ListDomain, OrdinalDomain
from designspace.paths._grammar import (
    element_prefix,
    instance_prefix,
    parse_path,
    split_instance_path,
    strip_last_index,
)

_PROVENANCE_RANK = {"inactive": 0, "pending": 1, "permanent": 2}


class Unknown:
    """Kleene's third truth value, carrying a provenance (rule 5). One
    singleton per provenance — compare with `isinstance`, or `is
    UNKNOWN_INACTIVE` where the provenance itself matters (as
    `IfInactive` does)."""

    _instances: ClassVar[dict[str, Unknown]] = {}

    provenance: str

    def __new__(cls, provenance: str = "permanent") -> Unknown:
        if provenance not in _PROVENANCE_RANK:
            raise ValueError(f"unknown provenance {provenance!r}")
        if provenance not in cls._instances:
            inst = super().__new__(cls)
            inst.provenance = provenance
            cls._instances[provenance] = inst
        return cls._instances[provenance]

    def __repr__(self) -> str:
        return f"Unknown({self.provenance!r})"


UNKNOWN_INACTIVE = Unknown("inactive")
UNKNOWN_PENDING = Unknown("pending")
UNKNOWN_PERMANENT = Unknown("permanent")
UNKNOWN = UNKNOWN_PERMANENT

Kleene = bool | Unknown


def _join_unknown(*values: Any) -> Unknown:
    """The strongest (least-resolvable) provenance among the Unknown-valued
    arguments — rule 5's max-join, `INACTIVE < PENDING < PERMANENT`. A node
    with one coalescible operand and one pending/permanent one must still
    block `.if_inactive()` from coalescing, so the join always keeps the
    stronger side. Callers only invoke this once they already know at least
    one argument is `Unknown`."""
    best: Unknown | None = None
    best_rank = -1
    for v in values:
        if isinstance(v, Unknown):
            rank = _PROVENANCE_RANK[v.provenance]
            if rank > best_rank:
                best_rank = rank
                best = v
    assert best is not None
    return best


def _resolve_negative_indices(path: str, config: dict[str, Any]) -> str | Unknown:
    """Resolves every negative bracket index in `path` against its lift's
    realized length, read progressively from `config` (API.md,
    "Expressions": negative indices are "resolved against the lift's own
    realized length"). Each nesting level's own count is already a flat
    `config` key at exactly the prefix built so far — `config["g"]` (outer
    count), `config["g[0]"]` (inner count for outer-instance 0), etc.,
    mirroring `_gather_instance_paths`'s own key convention — so no
    `space`/`ListDomain` lookup is needed here, just the flat config.

    Returns the fully-resolved (all-positive) concrete path, or an
    `Unknown`: `UNKNOWN_PENDING` if a governing count is not yet present
    in `config` (partial eval — the count itself is still unassigned);
    `UNKNOWN_INACTIVE` if a (positive or resolved-negative) index is out
    of range against an already-known count — the *dynamic* out-of-range
    rule (item 2's static case is rejected at resolution, row 29, and
    never reaches evaluation). A path with no brackets at all resolves to
    itself unchanged (the common scalar case, checked first to skip the
    parse)."""
    if "[" not in path:
        return path
    segments = parse_path(path)
    prefix = ""
    for seg in segments:
        prefix = f"{prefix}.{seg.name}" if prefix else seg.name
        for idx in seg.brackets:
            if idx is None:
                # A bare "[]" virtual template marker (D-18) evaluated
                # unsubstituted -- e.g. a lifted choice's own discriminator
                # condition, checked generically (not per real instance) by
                # list-default validation. Never a literal `config` key
                # (that branch below would have caught it too); matches
                # this path's pre-M10.5 undifferentiated Unknown.
                return UNKNOWN_PENDING
            count = config.get(prefix)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                return UNKNOWN_PENDING
            resolved = idx if idx >= 0 else idx + count
            if not (0 <= resolved < count):
                return UNKNOWN_INACTIVE
            prefix = f"{prefix}[{resolved}]"
    return prefix


def _leaf_value(path: str, config: dict[str, Any], activity: dict[str, bool]) -> Any | Unknown:
    resolved = _resolve_negative_indices(path, config)
    if isinstance(resolved, Unknown):
        return resolved
    if not activity.get(resolved, True):
        return UNKNOWN_INACTIVE
    if resolved not in config:
        return UNKNOWN_PENDING
    return config[resolved]


# -- vector expressions and aggregates (M4; DECISIONS.md D-18/D-19) ----------
#
# A vector expression (a lift-referencing `ParamExpr`, or a `.field()`
# projection of one) resolves to `UNKNOWN` if the lift itself is inactive
# (rule 1 — mechanically identical to a scalar inactive leaf) or to a
# (possibly nested, for chained `.repeat()`) list of per-instance leaves,
# each itself possibly `UNKNOWN` (an *interior* Unknown — only reachable
# via `.field()` on a struct element whose field carries a sibling
# `.when()`). `_vector_paths` builds the nested structure of *instance
# paths* rather than values so `.field()` can chain onto it; `_vector_values`
# is the thin values-view aggregates consume.


def _gather_instance_paths(path: str, domain: Any, config: dict[str, Any]) -> Any:
    assert isinstance(domain, ListDomain)
    n = config.get(path, 0)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return []
    if domain.element_kind == "list":
        return [
            _gather_instance_paths(f"{path}[{i}]", domain.element_domain, config)
            for i in range(n)
        ]
    return [f"{path}[{i}]" for i in range(n)]


def _map_leaves(structure: Any, fn: Any) -> Any:
    if isinstance(structure, list):
        return [_map_leaves(s, fn) for s in structure]
    return fn(structure)


def _flatten_leaves(structure: Any) -> list[Any]:
    if isinstance(structure, list):
        result: list[Any] = []
        for s in structure:
            result.extend(_flatten_leaves(s))
        return result
    return [structure]


def _vector_paths(
    expr: Expr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Any | Unknown:
    if isinstance(expr, Field):
        base = _vector_paths(expr.operand, config, activity, space)
        if isinstance(base, Unknown):
            return base  # propagate the base lift's own provenance
        return _map_leaves(base, lambda p: f"{p}.{expr.name}")
    assert isinstance(expr, ParamExpr)
    path = expr.path
    if not activity.get(path, True):
        return UNKNOWN_INACTIVE
    if path not in config:
        return UNKNOWN_PENDING  # the lift's own count is still unset (partial eval)
    return _gather_instance_paths(path, space.params[path].domain, config)


def _vector_values(
    expr: Expr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Any | Unknown:
    paths = _vector_paths(expr, config, activity, space)
    if isinstance(paths, Unknown):
        return paths
    return _map_leaves(paths, lambda p: _leaf_value(p, config, activity))


def _aggregate_leaves(
    expr: Sum | Min | Max | CountOf | IsSorted | Distinct,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
) -> list[Any] | Unknown:
    """The flat leaf list an aggregate consumes, or `UNKNOWN` if the base
    lift itself is inactive (rule 1). Callers still need to check for `[]`
    (rule 6, empty) and interior `Unknown` entries (D-19) themselves, since
    the empty/non-empty/Unknown-element handling differs per aggregate."""
    values = _vector_values(expr.operand, config, activity, space)
    if isinstance(values, Unknown):
        return values
    return _flatten_leaves(values)


def _all_distinct(values: list[Any]) -> bool:
    seen: list[Any] = []
    for v in values:
        if any(_values_equal(v, s) for s in seen):
            return False
        seen.append(v)
    return True


def _distinct_tuples(
    expr: Distinct, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> list[tuple[Any, ...]] | Unknown:
    paths = _vector_paths(expr.operand, config, activity, space)
    if isinstance(paths, Unknown):
        return paths
    flat_paths = _flatten_leaves(paths)
    return [
        tuple(_leaf_value(f"{p}.{f}", config, activity) for f in expr.fields) for p in flat_paths
    ]


def _tuple_equal(a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
    return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b, strict=True))


def _values_equal(a: Any, b: Any) -> bool:
    """Equality for `Compare`/`IsIn` leaves.

    Bool is type-tagged (Python's `True == 1` would otherwise leak through);
    int/float compare numerically (`5 == 5.0`), matching real/integer domains
    where the distinction is never meaningful — everything else (str, and
    any other `Any`-typed categorical/ordinal value) requires an exact type
    match, matching declaration-time type-tagged distinctness (rows 3/4).
    See DECISIONS.md for the one gap this leaves: a categorical/ordinal
    domain that deliberately declares both `1` and `1.0` as distinct variants
    cannot be told apart by `==` at evaluation time.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return bool(a == b)
    if type(a) is not type(b):
        return False
    return bool(a == b)


def _resolve_param_domain(path: str, space: Space) -> Any:
    """`path` may be an ordinary definition path, a struct/choice lift
    instance path (`"stops[0].dwell"` — its `"[]"`-bracketed template
    carries the real domain), or a direct scalar/choice lift element
    nested to any depth (`"dropout[3]"`, `"g[0][1]"` — no template of its
    own, but the element domain lives on the owning list's chained
    `ListDomain`). Mirrors resolve/_expr_checks.py's `_resolve_entry` via
    the shared `paths._grammar.split_instance_path` walk, at evaluation
    time (`space.params` is always the resolved `ParamDef` dict here,
    never a builder-time one, so there is no "not yet built" fallback to
    preserve)."""
    if path in space.params:
        return space.params[path].domain
    if "[" not in path:
        return None
    split = split_instance_path(path)
    if split is None:
        return None
    base_key, brackets = split
    if base_key not in space.params:
        return None
    domain = space.params[base_key].domain
    for _ in brackets:
        if not isinstance(domain, ListDomain):
            return None
        domain = domain.element_domain
    return None


def _ordinal_domain_of(node: Expr, space: Space) -> OrdinalDomain | None:
    if isinstance(node, ParamExpr):
        domain = _resolve_param_domain(node.path, space)
        if isinstance(domain, OrdinalDomain):
            return domain
    return None


def _ordinal_index(domain: OrdinalDomain, value: Any) -> int | Unknown:
    """`value`'s declaration-position index, or Unknown if it isn't a member
    (a malformed config — `validate()` is what reports that, not this)."""
    for i, v in enumerate(domain.values):
        if type(v) is type(value) and v == value:
            return i
    return UNKNOWN


def _evaluate_prop(
    expr: Prop,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    status: Mapping[str, str] | None = None,
) -> Any | Unknown:
    """`.prop()`: the operand's own (phenotype-form, DECISIONS.md D-46)
    value, bridged back to native via `from_json` and extracted. Contract
    law (API.md, "Protocols"): `extract` is called only on a value that
    passed `validate` — an invalid config value degrades to a *permanent*
    Unknown here (never a crash; distinct from the operand's own
    inactive/pending state propagated just above, which is coalescible or
    resolvable respectively); `validate()` itself is what must still report
    it as a `ParamError`."""
    value = evaluate_arith(expr.operand, config, activity, space, status=status)
    if isinstance(value, Unknown):
        return value  # propagate the custom param's own inactive/pending state
    assert isinstance(expr.operand, ParamExpr)
    domain = _resolve_param_domain(expr.operand.path, space)
    assert isinstance(domain, CustomDomain)
    assert domain.param_type is not None  # row 16 rejects .prop() on a shorthand custom
    pt = domain.param_type
    try:
        native = pt.from_json(value)
        if not pt.validate(native):
            return UNKNOWN_PERMANENT
        return pt.extract(native, expr.name)
    except Exception:
        # A structurally-malformed config value: `from_json`/`validate`
        # themselves may raise on it (core cannot type-check an opaque
        # value in advance) — degrades to a permanent Unknown, same as any
        # other malformed leaf; `validate()` is what must still report it
        # as a `ParamError`.
        return UNKNOWN_PERMANENT


def _apply_compare(op: str, left: Any, right: Any) -> bool:
    if op == "eq":
        return _values_equal(left, right)
    if op == "ne":
        return not _values_equal(left, right)
    if op == "gt":
        return bool(left > right)
    if op == "lt":
        return bool(left < right)
    if op == "ge":
        return bool(left >= right)
    if op == "le":
        return bool(left <= right)
    raise ValueError(f"unknown compare op {op!r}")


def _is_integer_valued(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def _count_range(
    node: Count,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    status: Mapping[str, str] | None = None,
) -> tuple[int, int, Unknown]:
    """`(true_count, unknown_count, joined_unknown)` — API.md: `ds.count`
    tracks `[t, t + u]`. `joined_unknown` is the strongest provenance among
    the operands that came back Unknown (rule 5); meaningful only when
    `u > 0` and the caller ends up reporting Unknown."""
    t = 0
    u = 0
    joined = UNKNOWN_INACTIVE
    for operand in node.operands:
        v = evaluate_bool(operand, config, activity, space, status=status)
        if isinstance(v, Unknown):
            u += 1
            joined = _join_unknown(joined, v)
        elif v:
            t += 1
    return t, u, joined


def _count_vs_threshold(op: str, t: int, u: int, threshold: Any, unknown: Unknown) -> Kleene:
    hi = t + u
    achievable = _is_integer_valued(threshold) and t <= threshold <= hi
    if op in ("lt", "le", "gt", "ge"):
        lo_result = _apply_compare(op, t, threshold)
        hi_result = _apply_compare(op, hi, threshold)
        return lo_result if lo_result == hi_result else unknown
    if op == "eq":
        if not achievable:
            return False
        return unknown if u > 0 else True
    if op == "ne":
        if not achievable:
            return True
        return unknown if u > 0 else False
    raise ValueError(f"unknown compare op {op!r}")


def evaluate_arith(
    expr: ArithExpr,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    status: Mapping[str, str] | None = None,
) -> Any | Unknown:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ParamExpr):
        return _leaf_value(expr.path, config, activity)
    if isinstance(expr, ArithOp):
        left = evaluate_arith(expr.left, config, activity, space, status=status)
        right = evaluate_arith(expr.right, config, activity, space, status=status)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return _join_unknown(left, right)
        return _apply_arith(expr.op, left, right)
    if isinstance(expr, IfInactive):
        operand_val = evaluate_arith(expr.operand, config, activity, space, status=status)
        if isinstance(operand_val, Unknown):
            if operand_val is UNKNOWN_INACTIVE:
                return evaluate_arith(expr.fallback, config, activity, space, status=status)
            return operand_val  # rule 5: never coalesce pending or permanent
        return operand_val
    if isinstance(expr, Count):
        t, u, joined = _count_range(expr, config, activity, space, status=status)
        return t if u == 0 else joined
    if isinstance(expr, Size):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else len(value)
    if isinstance(expr, SumOver):
        value = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(value, Unknown):
            return UNKNOWN
        # Missing mapping keys contribute 0 (spec: mapping keys ⊆ item
        # universe, so partial coverage is legal — see DECISIONS.md).
        return sum(expr.mapping.get(item, 0) for item in value)
    if isinstance(expr, PositionOf):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else value.index(expr.item)
    if isinstance(expr, Length):
        assert isinstance(expr.operand, ParamExpr)
        path = expr.operand.path
        if not activity.get(path, True):
            return UNKNOWN
        return config.get(path, UNKNOWN)
    if isinstance(expr, Prop):
        return _evaluate_prop(expr, config, activity, space, status=status)
    if isinstance(expr, Sum):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return 0  # rule 6: empty aggregate
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)  # D-19: interior Unknown -> aggregate Unknown
        return sum(leaves)
    if isinstance(expr, Min):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return UNKNOWN_PERMANENT  # rule 6: min/max of empty -> Unknown
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)
        return min(leaves)
    if isinstance(expr, Max):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return UNKNOWN_PERMANENT
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)
        return max(leaves)
    if isinstance(expr, CountOf):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return 0
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)
        return sum(1 for v in leaves if any(_values_equal(v, target) for target in expr.values))
    raise TypeError(f"cannot evaluate arith expr kind {expr.kind!r}")


def _apply_arith(op: str, left: Any, right: Any) -> Any:
    if op == "add":
        return left + right
    if op == "sub":
        return left - right
    if op == "mul":
        return left * right
    if op == "div":
        return left / right
    if op == "pow":
        return left**right
    if op == "mod":
        return left % right
    raise ValueError(f"unknown arith op {op!r}")


def _kleene_and(a: Kleene, b: Kleene) -> Kleene:
    if a is False or b is False:
        return False
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        return _join_unknown(a, b)
    return True


def _kleene_or(a: Kleene, b: Kleene) -> Kleene:
    if a is True or b is True:
        return True
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        return _join_unknown(a, b)
    return False


def _evaluate_is_active(
    expr: IsActive, activity: dict[str, bool], status: Mapping[str, str] | None
) -> Kleene:
    """`is_active()` is total under *full* evaluation (rule 1: every param has
    a determined binary activity) but not under *partial* evaluation — API.md,
    "Partial Configs": "`is_active(p)` ... determined for a determined `p`,
    Unknown for an `unknown` one." `status` (the four-valued partial status
    map) carries that extra distinction; absent it, this falls back to the
    old total/binary reading unchanged.
    """
    if status is None:
        return all(activity.get(p, True) for p in expr.operand.params)
    result: Kleene = True
    for p in expr.operand.params:
        s = status.get(p, "set")
        if s == "inactive":
            return False  # Kleene AND: False dominates regardless of order
        if s == "unknown":
            result = UNKNOWN_PENDING
    return result


def evaluate_bool(
    expr: BoolExpr,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    status: Mapping[str, str] | None = None,
) -> Kleene:
    if isinstance(expr, BoolLiteral):
        return expr.value
    if isinstance(expr, ParamExpr):
        v = _leaf_value(expr.path, config, activity)
        return v if isinstance(v, Unknown) else bool(v)
    if isinstance(expr, Prop):
        # A bool-declared prop used bare as a condition (not inside a
        # Compare) — same "coerce via bool()" convention as a bare
        # ParamExpr, above.
        value = _evaluate_prop(expr, config, activity, space, status=status)
        return value if isinstance(value, Unknown) else bool(value)
    if isinstance(expr, Compare):
        if isinstance(expr.left, Count) or isinstance(expr.right, Count):
            return _evaluate_count_compare(expr, config, activity, space, status=status)
        left = evaluate_arith(expr.left, config, activity, space, status=status)
        right = evaluate_arith(expr.right, config, activity, space, status=status)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return _join_unknown(left, right)
        if expr.op in ("gt", "lt", "ge", "le"):
            ordinal_domain = _ordinal_domain_of(expr.left, space) or _ordinal_domain_of(
                expr.right, space
            )
            if ordinal_domain is not None:
                left = _ordinal_index(ordinal_domain, left)
                right = _ordinal_index(ordinal_domain, right)
                if isinstance(left, Unknown) or isinstance(right, Unknown):
                    # a non-member literal: malformed, not inactive/pending
                    return UNKNOWN_PERMANENT
        return _apply_compare(expr.op, left, right)
    if isinstance(expr, BoolOp):
        left_v = evaluate_bool(expr.left, config, activity, space, status=status)
        right_v = evaluate_bool(expr.right, config, activity, space, status=status)
        return _kleene_and(left_v, right_v) if expr.op == "and" else _kleene_or(left_v, right_v)
    if isinstance(expr, Not):
        v = evaluate_bool(expr.operand, config, activity, space, status=status)
        return v if isinstance(v, Unknown) else (not v)
    if isinstance(expr, IsIn):
        operand = evaluate_arith(expr.operand, config, activity, space, status=status)
        if isinstance(operand, Unknown):
            return operand
        return any(_values_equal(operand, v) for v in expr.values)
    if isinstance(expr, IsActive):
        return _evaluate_is_active(expr, activity, status)
    if isinstance(expr, Contains):
        value = evaluate_arith(expr.operand, config, activity, space)
        return value if isinstance(value, Unknown) else expr.item in value
    if isinstance(expr, IsSorted):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return True  # rule 6
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)
        pairs = list(pairwise(leaves))
        if expr.descending:
            return all(a >= b for a, b in pairs)
        return all(a <= b for a, b in pairs)
    if isinstance(expr, Distinct):
        if expr.fields:
            tuples = _distinct_tuples(expr, config, activity, space)
            if isinstance(tuples, Unknown):
                return tuples
            if len(tuples) == 0:
                return True
            if any(any(isinstance(x, Unknown) for x in t) for t in tuples):
                return _join_unknown(*(x for t in tuples for x in t))
            seen: list[tuple[Any, ...]] = []
            for t in tuples:
                if any(_tuple_equal(t, s) for s in seen):
                    return False
                seen.append(t)
            return True
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return True
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)
        return _all_distinct(leaves)
    raise TypeError(f"cannot evaluate bool expr kind {expr.kind!r}")


def _evaluate_count_compare(
    expr: Compare,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    status: Mapping[str, str] | None = None,
) -> Kleene:
    if isinstance(expr.left, Count):
        count_node, other_side, count_is_left = expr.left, expr.right, True
    else:
        assert isinstance(expr.right, Count)
        count_node, other_side, count_is_left = expr.right, expr.left, False
    other_val = evaluate_arith(other_side, config, activity, space, status=status)
    if isinstance(other_val, Unknown):
        return other_val
    t, u, joined = _count_range(count_node, config, activity, space, status=status)
    op = expr.op
    if not count_is_left:
        op = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le"}.get(op, op)
    return _count_vs_threshold(op, t, u, other_val, joined)


def compute_activity(space: Space, config: dict[str, Any]) -> dict[str, bool]:
    """Activity per param, walking the condition dependency order (rule 3:
    Unknown coerces to False at `.when()`, cascading deactivation).

    Assumes `config` is *fully* materialized already (every lift's
    realized count, and every instance's leaf values, already present) —
    true for `validate()` (which flattens the whole submitted config up
    front) but not for the sampler, which must interleave drawing values
    with deciding activity and so does its own, incremental version of
    the per-instance expansion below (sample/_sample.py).
    """
    activity: dict[str, bool] = {}
    conditions_by_target = {c.target: c for c in space.conditions}
    for path in topological_order(space):
        condition = conditions_by_target.get(path)
        if condition is None:
            active = True
        else:
            value = evaluate_bool(condition.expr, config, activity, space)
            active = value is True
        activity[path] = active
        pd = space.params[path]
        if active and pd.type_kind == "list":
            _expand_lift_activity(space, path, pd.domain, config, activity)
    return activity


def _expand_lift_activity(
    space: Space, path: str, domain: Any, config: dict[str, Any], activity: dict[str, bool]
) -> None:
    """Struct/choice lift elements carry descendant *templates*
    (`"edges[]."`, DECISIONS.md D-18) with their own conditions (a
    sibling field's `.when()`); scalar/subset/permutation/nested-list
    elements have no such per-element condition, so there is nothing to
    expand for them (an in-range instance is active by construction
    whenever the lift itself is). One active instance at a time, in
    local dependency order within that instance (cross-field references
    inside one struct element)."""
    from designspace.resolve._relocate import instantiate_element

    assert isinstance(domain, ListDomain)
    if domain.element_kind not in ("space", "choice"):
        return
    n = config.get(path, 0)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return
    template_prefix = element_prefix(path)
    for i in range(n):
        concrete_prefix = instance_prefix(path, i)
        inst_params, inst_conditions = instantiate_element(space, template_prefix, concrete_prefix)
        inst_conditions_by_target = {c.target: c for c in inst_conditions}
        for local_path in local_topological_order(list(inst_params), inst_conditions_by_target):
            cond = inst_conditions_by_target.get(local_path)
            if cond is None:
                activity[local_path] = True
            else:
                value = evaluate_bool(cond.expr, config, activity, space)
                activity[local_path] = value is True


def status_activity_view(status: Mapping[str, str]) -> dict[str, bool]:
    """The binary view of a partial four-valued status map, for ordinary
    leaf/aggregate lookups: every non-`"inactive"` status (`"set"`,
    `"active_unset"`, `"unknown"`) reads as activity-True — `_leaf_value`
    already returns `UNKNOWN` for any param absent from `config` regardless
    of this flag, so `"active_unset"`/`"unknown"` and `"set"` only ever
    differ by presence, which `_leaf_value` already handles on its own.
    Only `IsActive` needs the finer four-way distinction (`status` itself,
    threaded straight through) — see `_evaluate_is_active`.
    """
    return {p: s != "inactive" for p, s in status.items()}


def classify_condition(
    condition: Any,  # designspace.ir.Condition | None
    config: dict[str, Any],
    status: dict[str, str],
    space: Space,
) -> str:
    """`"active"` / `"inactive"` / `"unknown"` for one param's own condition
    (API.md, "Partial Configs" — the pending-dependency rule), evaluated
    against the status already computed for its dependencies (topological
    order guarantees they precede it). Kleene-Unknown collapses to
    `"inactive"` when every param the condition references is itself
    determined (the same cascading deactivation a full config applies), or
    to `"unknown"` when at least one is `"active_unset"`/`"unknown"` —
    "undetermined but resolvable."
    """
    if condition is None:
        return "active"
    value = evaluate_bool(
        condition.expr, config, status_activity_view(status), space, status=status
    )
    if value is True:
        return "active"
    if value is False:
        return "inactive"
    if any(status.get(d) in ("active_unset", "unknown") for d in condition.params):
        return "unknown"
    return "inactive"


class PartialActivity(NamedTuple):
    """`compute_activity_partial`'s result — internal to eval/partial, not
    part of the public `PartialEval` surface (ir/_results.py).

    `status`: four-valued, keyed by definition *and* instance path (a
    lift's instances appear only once its count is determined).
    `order`: every path visited, in dependency order — definition paths
    first, lift instances expanded inline, since `topological_order` itself
    omits lift descendant templates and knows nothing of instances;
    `partial/_partial.py`'s `missing_params`/`next_assignable` walk this to
    report *instance* paths "in topological order."
    `deps`: each visited path's own gating references (condition params,
    already instance-substituted inside a lift, plus — for a top-level
    list/bound-origin param — its repeat-count/bound-envelope references)
    — `next_assignable`'s readiness check.
    """

    status: dict[str, str]
    order: list[str]
    deps: dict[str, frozenset[str]]


def compute_activity_partial(space: Space, config: dict[str, Any]) -> PartialActivity:
    """Three/four-valued activity + presence over a *partial* flat config
    (API.md, "Space — Partial Configs"): `"set"` (active & present),
    `"active_unset"` (active & absent), `"inactive"`, `"unknown"` (Kleene-
    Unknown but resolvable). Collapsing `"set"`/`"active_unset"` to `True`
    and everything else to `False` reproduces `compute_activity` exactly
    (the spec's collapse law) — both walk the same `topological_order`.
    """
    from designspace.resolve._bounds import bound_origin_targets

    status: dict[str, str] = {}
    order: list[str] = []
    deps: dict[str, frozenset[str]] = {}
    conditions_by_target = {c.target: c for c in space.conditions}
    for path in topological_order(space):
        if "[]" in path:
            continue  # a lift's descendant template (D-18) -- never a real leaf
        pd = space.params[path]
        condition = conditions_by_target.get(path)
        deps[path] = condition.params if condition is not None else frozenset()
        activity_class = classify_condition(condition, config, status, space)
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            _resolve_list_status(
                space, path, pd.domain, activity_class, config, status, order, deps
            )
        elif pd.type_kind == "space":
            # A struct has no own value to await (API.md: "a struct
            # carries no own default value"; its activity never depends on
            # its own members') -- "active_unset" would be meaningless for
            # it, so it collapses to "set" the same way a list container's
            # own shape does once determined.
            status[path] = "set" if activity_class == "active" else activity_class
            order.append(path)
        else:
            if activity_class == "active":
                status[path] = "set" if path in config else "active_unset"
            else:
                status[path] = activity_class
            order.append(path)

    bound_targets = bound_origin_targets(space)
    for path, pd in space.params.items():
        if "[]" in path or path not in deps:
            continue
        if pd.type_kind == "list":
            deps[path] = deps[path] | _lift_count_deps(pd.domain)
        deps[path] = deps[path] | _bound_order_deps(bound_targets, path)
    return PartialActivity(status=status, order=order, deps=deps)


def _determine_count_partial(
    count: int | ArithExpr, config: dict[str, Any], status: dict[str, str], space: Space
) -> int | None:
    """The Defaults section's count rule, reused for Partial Configs
    (API.md: "an undetermined count (a pending count-dependency)
    contributes none"): a static int is always determined; an `ArithExpr`
    is determined if it evaluates to a definite integer, or is Unknown
    *solely* because a referenced param is inactive (-> 0, "the complete
    value []"); otherwise (some referenced param is itself
    `active_unset`/`unknown`) it is genuinely pending -> `None`.
    """
    if not isinstance(count, ArithExpr):
        return count
    value = evaluate_arith(count, config, status_activity_view(status), space, status=status)
    if not isinstance(value, Unknown):
        assert isinstance(value, int) and not isinstance(value, bool)
        return value
    if any(status.get(d) in ("active_unset", "unknown") for d in count.params):
        return None
    return 0


def _resolve_list_status(
    space: Space,
    path: str,
    domain: ListDomain,
    activity_class: str,
    config: dict[str, Any],
    status: dict[str, str],
    order: list[str],
    deps: dict[str, frozenset[str]],
) -> None:
    """A list container is `"set"`/`"unknown"`/`"inactive"`, never
    `"active_unset"` (API.md, "Partial Configs") — there is no value to
    await for the container itself, only for its count param (elsewhere in
    `topological_order`) and its instance leaves (expanded below, once the
    count is known)."""
    if activity_class != "active":
        status[path] = activity_class
        order.append(path)
        return
    n = _determine_count_partial(domain.count, config, status, space)
    if n is None:
        status[path] = "unknown"  # count is pending on an unresolved dependency
        order.append(path)
        return
    status[path] = "set"
    order.append(path)
    for i in range(n):
        _expand_instance_status(space, f"{path}[{i}]", domain, config, status, order, deps)


def _expand_instance_status(
    space: Space,
    inst_path: str,
    domain: ListDomain,
    config: dict[str, Any],
    status: dict[str, str],
    order: list[str],
    deps: dict[str, frozenset[str]],
) -> None:
    from designspace.resolve._relocate import instantiate_element

    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        _resolve_list_status(
            space, inst_path, domain.element_domain, "active", config, status, order, deps
        )
        return
    if domain.element_kind not in ("space", "choice"):
        status[inst_path] = "set" if inst_path in config else "active_unset"
        order.append(inst_path)
        deps[inst_path] = frozenset()
        return
    if domain.element_kind == "choice":
        status[inst_path] = "set" if inst_path in config else "active_unset"
        order.append(inst_path)
        deps[inst_path] = frozenset()
    template_prefix = element_prefix(strip_last_index(inst_path))
    inst_params, inst_conditions = instantiate_element(space, template_prefix, f"{inst_path}.")
    inst_conditions_by_target = {c.target: c for c in inst_conditions}
    for local_path in local_topological_order(list(inst_params), inst_conditions_by_target):
        pd = inst_params[local_path]
        cond = inst_conditions_by_target.get(local_path)
        deps[local_path] = cond.params if cond is not None else frozenset()
        activity_class = classify_condition(cond, config, status, space)
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            _resolve_list_status(
                space, local_path, pd.domain, activity_class, config, status, order, deps
            )
        elif pd.type_kind == "space":
            status[local_path] = "set" if activity_class == "active" else activity_class
            order.append(local_path)
        else:
            if activity_class == "active":
                status[local_path] = "set" if local_path in config else "active_unset"
            else:
                status[local_path] = activity_class
            order.append(local_path)


def local_topological_order(paths: list[str], conditions_by_target: dict[str, Any]) -> list[str]:
    """`topological_order`'s algorithm, scoped to one lift instance's
    freshly-instantiated params (already guaranteed acyclic — the
    element's own fields were cycle-checked when it was originally
    resolved, before ever being lifted)."""
    path_set = set(paths)
    order: list[str] = []
    done: set[str] = set()

    def visit(p: str) -> None:
        if p in done:
            return
        cond = conditions_by_target.get(p)
        if cond is not None:
            for dep in cond.params:
                if dep in path_set:
                    visit(dep)
        done.add(p)
        order.append(p)

    for p in paths:
        visit(p)
    return order


def _lift_count_deps(domain: Any) -> frozenset[str]:
    """Repeat-count references join the dependency graph (DECISIONS.md
    D-21) — recurse through chained/nested `.repeat()` levels."""
    deps: frozenset[str] = frozenset()
    while isinstance(domain, ListDomain):
        if isinstance(domain.count, ArithExpr):
            deps = deps | domain.count.params
        domain = domain.element_domain
    return deps


def _bound_order_deps(
    bound_targets: dict[str, tuple[ArithExpr | None, ArithExpr | None]], path: str
) -> frozenset[str]:
    """Bound-origin constraints impose assignment order too (M5, API.md
    "Expression bounds are sugar" — "Ordering"): the params a bound
    expression references must be assigned before the param it bounds."""
    lo_expr, hi_expr = bound_targets.get(path, (None, None))
    deps: frozenset[str] = frozenset()
    if lo_expr is not None:
        deps = deps | lo_expr.params
    if hi_expr is not None:
        deps = deps | hi_expr.params
    return deps


def topological_order(space: Space) -> list[str]:
    """Params in an order where each one's condition, repeat-count, and
    bound-origin-constraint dependencies come first.

    Not the public `.topological_order` (M6, Partial Configs) — an internal
    ordering the sampler and activity computation both need now.
    """
    from designspace.resolve._bounds import bound_origin_targets

    conditions_by_target = {c.target: c for c in space.conditions}
    bound_targets = bound_origin_targets(space)
    order: list[str] = []
    done: set[str] = set()

    def visit(path: str) -> None:
        if path in done:
            return
        if path not in space.params:
            # A per-instance virtual placeholder — e.g. a lifted choice's
            # bare discriminator template ("pipeline[]", referenced by a
            # variant payload's folded discriminator-equality condition,
            # DECISIONS.md D-18) — not a real definition, so it has no
            # further dependencies and never joins `order` itself.
            done.add(path)
            return
        condition = conditions_by_target.get(path)
        deps = condition.params if condition is not None else frozenset[str]()
        deps = deps | _lift_count_deps(space.params[path].domain) | _bound_order_deps(
            bound_targets, path
        )
        for dep in deps:
            visit(dep)
        done.add(path)
        order.append(path)

    for path in space.params:
        visit(path)
    return order
