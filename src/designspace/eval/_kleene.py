"""Kleene evaluation (API.md, "Expressions" > "Three-valued semantics").

`Unknown` carries a provenance, under rule 5, and there is one singleton per
provenance:

- `"inactive"`, from rule 1, is the only provenance `.if_inactive()`
  coalesces.
- `"pending"` marks an operand not yet present in a partial config. It is
  never coalesced: eating it would let a driver loop conclude a constraint
  is satisfied while the value that will violate it is still unassigned.
- `"permanent"` marks rule 6 emptiness, the `min` or `max` of an active
  empty lift, or a structurally malformed leaf. It is never coalesced
  either, `.if_inactive()`'s own name disclaiming an active empty lift.

`_join_unknown` takes the maximum over `INACTIVE < PENDING < PERMANENT`
wherever a node combines more than one Unknown-valued operand, so a mixed
node never under-reports how resolvable it is. `UNKNOWN` is bound to the
`"permanent"` singleton, for the sites that only ever produce that
provenance, and `isinstance(x, Unknown)` matches all three.

Every evaluator here takes `space`, not `config` and `activity` alone,
because ordinal ordering compares by declaration position rather than by raw
value: "Ordered by declaration position. Comparison yes, arithmetic no." A
leaf's domain must be looked up to translate its value into an index before
`>`, `<`, `>=` and `<=` mean anything.

Internal to the library, and not part of the public surface, as
`resolve_space` is not.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise
from typing import Any, ClassVar, NamedTuple

from designspace.builder._paramexpr import ParamExpr
from designspace.builder._space import Space
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
from designspace.ir import CustomDomain, ListDomain, OrdinalDomain
from designspace.paths._grammar import (
    _INDEX_RE,
    element_prefix,
    instance_prefix,
    parse_path,
    split_instance_path,
    strip_last_index,
)

_PROVENANCE_RANK = {"inactive": 0, "pending": 1, "permanent": 2}


class Unknown:
    """Kleene's third truth value, carrying a provenance under rule 5.

    There is one singleton per provenance. Compare with `isinstance`, or
    with `is UNKNOWN_INACTIVE` where the provenance itself matters, as
    `IfInactive` does.
    """

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
    """The strongest, least resolvable provenance among Unknown arguments.

    This is rule 5's max-join over `INACTIVE < PENDING < PERMANENT`. A node
    with one coalescible operand and one pending or permanent operand must
    still block `.if_inactive()` from coalescing, so the join keeps the
    stronger side. Callers invoke this only once they know at least one
    argument is `Unknown`.
    """
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
    """Resolve every negative bracket index in `path` against its lift.

    API.md, "Expressions" says a negative index is "resolved against the
    lift's own realized length", which is read progressively from `config`.
    Each nesting level's own count is a flat `config` key at exactly the
    prefix built so far: `config["g"]` for the outer count,
    `config["g[0]"]` for the inner count of outer instance 0, and so on,
    matching `_gather_instance_paths`' key convention. No `space` or
    `ListDomain` lookup is needed, only the flat config.

    Returns the fully resolved, all-positive concrete path, or an `Unknown`.
    `UNKNOWN_PENDING` means a governing count is not yet present in
    `config`, so the count itself is still unassigned under partial
    evaluation. `UNKNOWN_INACTIVE` means an index, positive or resolved from
    a negative, is out of range against an already-known count. That is the
    dynamic out-of-range rule; the static case is rejected at resolution
    under row 29 and never reaches evaluation.

    A path with no brackets resolves to itself unchanged. That is the common
    scalar case, checked first to skip the parse.
    """
    if "[" not in path:
        return path
    segments = parse_path(path)
    prefix = ""
    for seg in segments:
        prefix = f"{prefix}.{seg.name}" if prefix else seg.name
        for idx in seg.brackets:
            if idx is None:
                # A bare "[]" virtual template marker evaluated
                # unsubstituted, as in a lifted choice's own discriminator
                # condition, which list-default validation checks
                # generically rather than per real instance. It is never a
                # literal `config` key; the branch below would have caught
                # it if it were.
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


# -- vector expressions and aggregates --------------------------------------
#
# A vector expression is a lift-referencing `ParamExpr`, or a `.field()`
# projection of one. It resolves to `UNKNOWN` when the lift itself is
# inactive, under rule 1 and mechanically identically to a scalar inactive
# leaf, or to a list of per-instance leaves, nested for a chained
# `.repeat()`. A leaf may itself be `UNKNOWN`, an interior Unknown reachable
# only through `.field()` on a struct element whose field carries a sibling
# `.when()`.
#
# `_vector_paths` builds the nested structure of instance paths rather than
# of values, so that `.field()` can chain onto it. `_vector_values` is the
# thin values view aggregates consume.


def _gather_instance_paths(path: str, domain: Any, config: dict[str, Any]) -> Any:
    assert isinstance(domain, ListDomain)
    n = config.get(path, 0)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return []
    if domain.element_kind == "list":
        return [
            _gather_instance_paths(f"{path}[{i}]", domain.element_domain, config) for i in range(n)
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
    # `path` is usually already a `space.params` key. A per-element
    # constraint's own nested lift reaches here renamed to a concrete
    # instance instead, `instantiate_constraints` turning "rows[].cells"
    # into "rows[0].cells" for row 0, and that form is never a declared key;
    # only its template is. `config`'s count and leaf entries are keyed by
    # the concrete form, which `_gather_instance_paths` requires, so only
    # the domain lookup falls back to the template.
    domain_path = path if path in space.params else _INDEX_RE.sub("[]", path)
    return _gather_instance_paths(path, space.params[domain_path].domain, config)


def _vector_values(
    expr: Expr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Any | Unknown:
    """Evaluate a `ChartApply` over a vector operand.

    `ChartApply` is a representation's decode, substituted by transport, and
    it is vector-polymorphic. Wrapping a lift or a `.field()` projection, it
    maps `chart.from_unit` element-wise over that operand's own vector
    values rather than gathering instance paths itself: a decode leaves the
    wrapped operand's shape untouched and changes only its leaves' values.
    API.md, "Expressions" states that chart application is
    "vector-polymorphic: applied to a lift or a projection it maps
    element-wise".
    """
    if isinstance(expr, ChartApply):
        inner = _vector_values(expr.operand, config, activity, space)
        if isinstance(inner, Unknown):
            return inner
        return _map_leaves(inner, expr.chart.from_unit)
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
    """The flat leaf list an aggregate consumes.

    Returns `UNKNOWN` when the base lift itself is inactive, under rule 1.
    Callers must still check for `[]`, rule 6's empty case, and for interior
    `Unknown` entries, since the empty, non-empty and Unknown-element
    handling differs per aggregate.
    """
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
    where the distinction is never meaningful. Everything else, meaning
    `str` and any other `Any`-typed categorical or ordinal value, requires
    an exact type match, matching the type-tagged distinctness declaration
    time applies under rows 3 and 4.

    One gap remains: a categorical or ordinal domain that deliberately
    declares both `1` and `1.0` as distinct variants
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
    instance path (`"stops[0].dwell"`, whose `"[]"`-bracketed template
    carries the real domain), or a direct scalar or choice lift element
    nested to any depth, such as `"dropout[3]"` or `"g[0][1]"`, which has no
    template of its own but whose element domain lives on the owning list's
    chained `ListDomain`.

    This mirrors `_resolve_entry` in `resolve/_expr_checks.py` through the
    shared `split_instance_path` walk in `paths._grammar`, at evaluation
    time. `space.params` is always the resolved `ParamDef` dict here, never
    a builder-time one, so there is no "not yet built" fallback to preserve.
    """
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
    return domain


def _ordinal_domain_of(node: Expr, space: Space) -> OrdinalDomain | None:
    if isinstance(node, ParamExpr):
        domain = _resolve_param_domain(node.path, space)
        if isinstance(domain, OrdinalDomain):
            return domain
    return None


def _ordinal_index(domain: OrdinalDomain, value: Any) -> int | Unknown:
    """`value`'s declaration-position index, or Unknown if it is not a member.

    A non-member value means a malformed config, which `validate()` reports
    rather than this function.
    """
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
    """Evaluate `.prop()`: bridge the operand to native, then extract.

    The operand's value is in phenotype form and is bridged back to native
    through `from_json`. API.md, "Protocols" states the contract law that
    `extract` is called only on a value that passed `validate`, so an
    invalid config value degrades to a permanent Unknown here rather than
    crashing. That is distinct from the operand's own inactive or pending
    state, propagated just above, which is coalescible and resolvable
    respectively. `validate()` must still report the value as a
    `ParamError`.
    """
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
        # A structurally malformed config value. `from_json` and `validate`
        # may themselves raise on it, core being unable to type-check an
        # opaque value in advance, so it degrades to a permanent Unknown
        # like any other malformed leaf. `validate()` must still report it
        # as a `ParamError`.
        return UNKNOWN_PERMANENT


def _evaluate_operand(
    operand: Expr,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    status: Mapping[str, str] | None,
    value_cache: dict[Value, Any] | None,
) -> Any | Unknown:
    """Evaluate one operand of an opaque leaf such as `ds.value`.

    An operand is an ordinary `ArithExpr` or `BoolExpr`. Row 30 checks at
    construction only that it is some expression. A bare vector expression,
    such as an unaggregated `.field()`, is neither and has no scalar value
    to hand to `fn`.
    """
    if isinstance(operand, ArithExpr):
        return evaluate_arith(
            operand, config, activity, space, status=status, value_cache=value_cache
        )
    if isinstance(operand, BoolExpr):
        return evaluate_bool(
            operand, config, activity, space, status=status, value_cache=value_cache
        )
    raise TypeError(
        f"ds.value(): operand kind {operand.kind!r} is not scalar-evaluable "
        "(a bare vector expression has no scalar value)"
    )


def _evaluate_value(
    expr: Value,
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    status: Mapping[str, str] | None = None,
    value_cache: dict[Value, Any] | None = None,
) -> Any | Unknown:
    """Evaluate `ds.value(fn, *operands, returns=type)`.

    The result is Unknown exactly when some operand evaluates Unknown,
    rather than when a literal scan of `expr.params` finds one, so that
    `.if_inactive()` and any other coercion inside an operand compose. API.md,
    "Expressions" promises that "`.if_inactive()` and any other coercion
    compose inside them".

    `fn` is called with exactly the operand values, positionally, and never
    with the config. An exception `fn` raises propagates uncaught. That is
    deliberately unlike `_evaluate_prop`'s defensive swallow, which the
    custom-type contract law licenses by promising that "extract is called
    only on a value that passed validate"; `fn` has no equivalent.

    `value_cache` is optional and identity-keyed on the `Value` node itself.
    It lets a caller that evaluates one expression tree twice call `fn` once
    per node rather than twice. Both `evaluate_constraint` in
    `eval/_constraint_eval.py` and `_classify_constraint` in
    `partial/_partial.py` compute a Kleene satisfaction value through
    `evaluate_bool` and then a margin through `margin` in
    `eval/_margins.py`, which re-walks the same `Compare` leaves
    independently. A `None` cache evaluates as if the cache did not exist.
    """
    if value_cache is not None and expr in value_cache:
        return value_cache[expr]
    values = [
        _evaluate_operand(operand, config, activity, space, status=status, value_cache=value_cache)
        for operand in expr.operands
    ]
    if any(isinstance(v, Unknown) for v in values):
        result = _join_unknown(*(v for v in values if isinstance(v, Unknown)))
    else:
        result = expr.fn(*values)
    if value_cache is not None:
        value_cache[expr] = result
    return result


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
    value_cache: dict[Value, Any] | None = None,
) -> tuple[int, int, Unknown]:
    """`(true_count, unknown_count, joined_unknown)` for `ds.count`.

    API.md has `ds.count` track `[t, t + u]`. `joined_unknown` is the
    strongest provenance among the operands that came back Unknown, under
    rule 5, and is meaningful only when `u > 0` and the caller reports
    Unknown.
    """
    t = 0
    u = 0
    joined = UNKNOWN_INACTIVE
    for operand in node.operands:
        v = evaluate_bool(operand, config, activity, space, status=status, value_cache=value_cache)
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
    value_cache: dict[Value, Any] | None = None,
) -> Any | Unknown:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ParamExpr):
        return _leaf_value(expr.path, config, activity)
    if isinstance(expr, ArithOp):
        left = evaluate_arith(
            expr.left, config, activity, space, status=status, value_cache=value_cache
        )
        right = evaluate_arith(
            expr.right, config, activity, space, status=status, value_cache=value_cache
        )
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return _join_unknown(left, right)
        return _apply_arith(expr.op, left, right)
    if isinstance(expr, IfInactive):
        operand_val = evaluate_arith(
            expr.operand, config, activity, space, status=status, value_cache=value_cache
        )
        if isinstance(operand_val, Unknown):
            if operand_val is UNKNOWN_INACTIVE:
                return evaluate_arith(
                    expr.fallback, config, activity, space, status=status, value_cache=value_cache
                )
            return operand_val  # rule 5: never coalesce pending or permanent
        return operand_val
    if isinstance(expr, Count):
        t, u, joined = _count_range(
            expr, config, activity, space, status=status, value_cache=value_cache
        )
        return t if u == 0 else joined
    if isinstance(expr, Size):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else len(value)
    if isinstance(expr, SumOver):
        value = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(value, Unknown):
            return UNKNOWN
        # A missing mapping key contributes 0. The spec constrains mapping
        # keys to a subset of the item universe, so partial coverage is
        # legal.
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
    if isinstance(expr, Value):
        return _evaluate_value(
            expr, config, activity, space, status=status, value_cache=value_cache
        )
    if isinstance(expr, ChartApply):
        # Scalar position: `operand` is always a bare `ParamExpr` here. A
        # `Field`-projected operand reaches this node only inside an
        # aggregate, which evaluates it through `_vector_values` instead.
        # `Field` has no arithmetic dunders of its own and so can never
        # appear directly under a `Compare` or `ArithOp`.
        assert isinstance(expr.operand, ArithExpr)
        value = evaluate_arith(
            expr.operand, config, activity, space, status=status, value_cache=value_cache
        )
        return value if isinstance(value, Unknown) else expr.chart.from_unit(value)
    if isinstance(expr, Sum):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return leaves
        if len(leaves) == 0:
            return 0  # rule 6: empty aggregate
        if any(isinstance(v, Unknown) for v in leaves):
            return _join_unknown(*leaves)  # an interior Unknown makes the aggregate Unknown
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
    """Evaluate `is_active()`, which is total only under full evaluation.

    Under full evaluation every param has a determined binary activity, by
    rule 1. Under partial evaluation it does not: API.md, "Space: Partial
    Configs"
    says `is_active(p)` is "determined for a determined `p`, Unknown for an
    `unknown` one".

    `status`, the four-valued partial status map, carries that extra
    distinction. Without it this falls back to the total, binary reading.
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
    value_cache: dict[Value, Any] | None = None,
) -> Kleene:
    if isinstance(expr, BoolLiteral):
        return expr.value
    if isinstance(expr, ParamExpr):
        v = _leaf_value(expr.path, config, activity)
        return v if isinstance(v, Unknown) else bool(v)
    if isinstance(expr, Prop):
        # A bool-declared prop used bare as a condition rather than inside
        # a Compare, under the same "coerce via bool()" convention a bare
        # ParamExpr uses above.
        value = _evaluate_prop(expr, config, activity, space, status=status)
        return value if isinstance(value, Unknown) else bool(value)
    if isinstance(expr, Value):
        # A bool-declared value used bare as a condition, under the same
        # "coerce via bool()" convention a bare ParamExpr or Prop uses
        # above.
        value = _evaluate_value(
            expr, config, activity, space, status=status, value_cache=value_cache
        )
        return value if isinstance(value, Unknown) else bool(value)
    if isinstance(expr, Compare):
        if isinstance(expr.left, Count) or isinstance(expr.right, Count):
            return _evaluate_count_compare(
                expr, config, activity, space, status=status, value_cache=value_cache
            )
        left = evaluate_arith(
            expr.left, config, activity, space, status=status, value_cache=value_cache
        )
        right = evaluate_arith(
            expr.right, config, activity, space, status=status, value_cache=value_cache
        )
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
        left_v = evaluate_bool(
            expr.left, config, activity, space, status=status, value_cache=value_cache
        )
        right_v = evaluate_bool(
            expr.right, config, activity, space, status=status, value_cache=value_cache
        )
        return _kleene_and(left_v, right_v) if expr.op == "and" else _kleene_or(left_v, right_v)
    if isinstance(expr, Not):
        v = evaluate_bool(
            expr.operand, config, activity, space, status=status, value_cache=value_cache
        )
        return v if isinstance(v, Unknown) else (not v)
    if isinstance(expr, IsIn):
        operand = evaluate_arith(
            expr.operand, config, activity, space, status=status, value_cache=value_cache
        )
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
    value_cache: dict[Value, Any] | None = None,
) -> Kleene:
    if isinstance(expr.left, Count):
        count_node, other_side, count_is_left = expr.left, expr.right, True
    else:
        assert isinstance(expr.right, Count)
        count_node, other_side, count_is_left = expr.right, expr.left, False
    other_val = evaluate_arith(
        other_side, config, activity, space, status=status, value_cache=value_cache
    )
    if isinstance(other_val, Unknown):
        return other_val
    t, u, joined = _count_range(
        count_node, config, activity, space, status=status, value_cache=value_cache
    )
    op = expr.op
    if not count_is_left:
        op = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le"}.get(op, op)
    return _count_vs_threshold(op, t, u, other_val, joined)


def compute_activity(space: Space, config: dict[str, Any]) -> dict[str, bool]:
    """Activity per param, walking the condition dependency order.

    Rule 3 coerces Unknown to False at `.when()`, which cascades
    deactivation.

    `config` must be fully materialized, with every lift's realized count
    and every instance's leaf values present. That holds for `validate()`,
    which flattens the whole submitted config up front, but not for the
    sampler, which interleaves drawing values with deciding activity and so
    performs its own incremental version of the per-instance expansion
    below, in `sample/_sample.py`.
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
    """Expand a lift's per-instance activity, one active instance at a time.

    A struct or choice lift element carries descendant templates, prefixed
    `"edges[]."`, with their own conditions, such as a sibling field's
    `.when()`. Scalar, subset, permutation and nested-list elements carry no
    per-element condition, so there is nothing to expand for them: an
    in-range instance is active by construction whenever the lift is.

    Each instance is walked in local dependency order, which resolves
    cross-field references inside one struct element.
    """
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
    """The binary view of a partial four-valued status map.

    Used for ordinary leaf and aggregate lookups. Every status other than
    `"inactive"`, meaning `"set"`, `"active_unset"` and `"unknown"`, reads
    as active. `_leaf_value` returns `UNKNOWN` for any param absent from
    `config` whatever this flag says, so `"active_unset"` and `"unknown"`
    differ from `"set"` only by presence, which `_leaf_value` already
    handles.

    Only `IsActive` needs the finer four-way distinction, and it receives
    `status` itself; see `_evaluate_is_active`.
    """
    return {p: s != "inactive" for p, s in status.items()}


def classify_condition(
    condition: Any,  # designspace.ir.Condition | None
    config: dict[str, Any],
    status: dict[str, str],
    space: Space,
) -> str:
    """One param's own condition as `"active"`, `"inactive"` or `"unknown"`.

    This applies the pending-dependency rule of API.md, "Space: Partial
    Configs",
    evaluating against the status already computed for the condition's
    dependencies; topological order guarantees they precede it.

    Kleene Unknown collapses to `"inactive"` when every param the condition
    references is itself determined, which is the cascading deactivation a
    full config applies. It collapses to `"unknown"`, meaning undetermined
    but resolvable, when at least one is `"active_unset"` or `"unknown"`.
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
    """`compute_activity_partial`'s result.

    Internal to `eval/` and `partial/`, and not part of the public
    `PartialEval` surface in `ir/_results.py`.

    `status` is four-valued, keyed by definition path and by instance path.
    A lift's instances appear only once its count is determined.

    `order` is every path visited, in dependency order: definition paths
    first, with lift instances expanded inline, since `topological_order`
    omits lift descendant templates and knows nothing of instances.
    `missing_params` and `next_assignable` in `partial/_partial.py` walk
    this to report instance paths "in topological order".

    `deps` is each visited path's own gating references: the condition's
    params, already instance-substituted inside a lift, plus, for a
    top-level list or bound-origin param, its repeat-count and
    bound-envelope references. `next_assignable` uses it as the readiness
    check.
    """

    status: dict[str, str]
    order: list[str]
    deps: dict[str, frozenset[str]]


def compute_activity_partial(space: Space, config: dict[str, Any]) -> PartialActivity:
    """Four-valued activity and presence over a partial flat config.

    See API.md, "Space: Partial Configs". The values are `"set"`, active and
    present; `"active_unset"`, active and absent; `"inactive"`; and
    `"unknown"`, Kleene Unknown but resolvable.

    Collapsing `"set"` and `"active_unset"` to `True` and everything else to
    `False` reproduces `compute_activity` exactly, which is the spec's
    collapse law. Both walk the same `topological_order`.
    """
    from designspace.resolve._bounds import bound_origin_targets

    status: dict[str, str] = {}
    order: list[str] = []
    deps: dict[str, frozenset[str]] = {}
    conditions_by_target = {c.target: c for c in space.conditions}
    for path in topological_order(space):
        if "[]" in path:
            continue  # a lift's descendant template, never a real leaf
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
            # A struct has no own value to await: API.md says "a struct
            # carries no own default value", and its activity never depends
            # on its members'. "active_unset" would be meaningless for it,
            # so it collapses to "set", as a list container's own shape does
            # once determined.
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
    """The Defaults section's count rule, reused for partial configs.

    API.md states that "an undetermined count (a pending count-dependency)
    contributes none". A static int is always determined. An `ArithExpr` is
    determined when it evaluates to a definite integer, or when it is
    Unknown solely because a referenced param is inactive, in which case it
    contributes 0, "the complete value []". Otherwise some referenced param
    is itself `active_unset` or `unknown`, the count is genuinely pending,
    and the result is `None`.
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
    """Assign a list container's partial status.

    A list container is `"set"`, `"unknown"` or `"inactive"`, and never
    `"active_unset"` (API.md, "Space: Partial Configs"). There is no value
    to await
    for the container itself, only for its count param, which appears
    elsewhere in `topological_order`, and for its instance leaves, expanded
    below once the count is known.
    """
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
    """`topological_order`'s algorithm, scoped to one lift instance.

    The instance's freshly instantiated params are guaranteed acyclic: the
    element's own fields were cycle-checked when it was originally resolved,
    before being lifted.
    """
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
    """Repeat-count references, which join the dependency graph.

    Recurses through chained and nested `.repeat()` levels.
    """
    deps: frozenset[str] = frozenset()
    while isinstance(domain, ListDomain):
        if isinstance(domain.count, ArithExpr):
            deps = deps | domain.count.params
        domain = domain.element_domain
    return deps


def _bound_order_deps(
    bound_targets: dict[str, tuple[ArithExpr | None, ArithExpr | None]], path: str
) -> frozenset[str]:
    """Bound-origin constraints impose assignment order too.

    Under API.md, "Expression bounds are sugar" > "Ordering", the params a
    bound expression references must be assigned before the param it bounds.
    """
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

    This is not the public `.topological_order` of Partial Configs, but an
    internal ordering the sampler and activity computation both need.
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
            # A per-instance virtual placeholder, such as a lifted
            # choice's bare discriminator template "pipeline[]", which a
            # variant payload's folded discriminator-equality condition
            # references. It is not a real definition, so it has no further
            # dependencies and never joins `order` itself.
            done.add(path)
            return
        condition = conditions_by_target.get(path)
        deps = condition.params if condition is not None else frozenset[str]()
        deps = (
            deps
            | _lift_count_deps(space.params[path].domain)
            | _bound_order_deps(bound_targets, path)
        )
        for dep in deps:
            visit(dep)
        done.add(path)
        order.append(path)

    for path in space.params:
        visit(path)
    return order
