"""Kleene evaluation (API_v3.md, "Expressions" > "Three-valued semantics").

`Unknown` arises only from inactivity (rule 1) — M2 has no partial-config
API yet (M6), so there is no separate "pending" state to confuse it with
(rule 5 becomes meaningful only once one exists); an "active but missing
from config" leaf is a caller bug, not a spec state, and is treated the same
as inactive here defensively so evaluation degrades rather than crashes —
`validate()` is what must still report it as a `ParamError("missing")`.

Every evaluator here takes `space` (not just `config`/`activity`), because
ordinal ordering compares by *declaration position*, not by the raw value
("Ordered by declaration position. Comparison yes, arithmetic no.") — a
leaf's domain has to be looked up to translate its value to an index before
`>`/`<`/`>=`/`<=` mean anything.

Internal to the library: not part of the public surface (mirrors how
`resolve_space` isn't re-exported either).
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

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
    Size,
    Sum,
    SumOver,
)
from designspace.ir import ListDomain, OrdinalDomain


class Unknown:
    """Kleene's third truth value. A singleton; compare with `is`."""

    _instance: Unknown | None = None

    def __new__(cls) -> Unknown:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "Unknown"


UNKNOWN = Unknown()

Kleene = bool | Unknown


def _leaf_value(path: str, config: dict[str, Any], activity: dict[str, bool]) -> Any | Unknown:
    if not activity.get(path, True):
        return UNKNOWN
    if path not in config:
        return UNKNOWN
    return config[path]


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
            return UNKNOWN
        return _map_leaves(base, lambda p: f"{p}.{expr.name}")
    assert isinstance(expr, ParamExpr)
    path = expr.path
    if not activity.get(path, True):
        return UNKNOWN
    if path not in config:
        return UNKNOWN
    return _gather_instance_paths(path, space.params[path].domain, config)


def _vector_values(
    expr: Expr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Any | Unknown:
    paths = _vector_paths(expr, config, activity, space)
    if isinstance(paths, Unknown):
        return UNKNOWN
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
        return UNKNOWN
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
        return UNKNOWN
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


_INDEX_RE = re.compile(r"\[\d+\]")


def _resolve_param_domain(path: str, space: Space) -> Any:
    """`path` may be an ordinary definition path, a struct/choice lift
    instance path (`"stops[0].dwell"` — its `"[]"`-bracketed template
    carries the real domain), or a direct scalar/choice lift element
    (`"dropout[3]"` — no template, but the element domain lives on the
    owning list's `ListDomain`). Mirrors resolve/_expr_checks.py's
    `_resolve_entry`, at evaluation time (`space.params` is always the
    resolved `ParamDef` dict here, never a builder-time one)."""
    if path in space.params:
        return space.params[path].domain
    if "[" not in path:
        return None
    template = _INDEX_RE.sub("[]", path)
    if template in space.params:
        return space.params[template].domain
    base = path[: path.rindex("[")]
    if base in space.params:
        domain = space.params[base].domain
        if isinstance(domain, ListDomain):
            return domain.element_domain
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
    node: Count, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> tuple[int, int]:
    """`(true_count, unknown_count)` — API_v3.md: `ds.count` tracks `[t, t + u]`."""
    t = 0
    u = 0
    for operand in node.operands:
        v = evaluate_bool(operand, config, activity, space)
        if isinstance(v, Unknown):
            u += 1
        elif v:
            t += 1
    return t, u


def _count_vs_threshold(op: str, t: int, u: int, threshold: Any) -> Kleene:
    hi = t + u
    achievable = _is_integer_valued(threshold) and t <= threshold <= hi
    if op in ("lt", "le", "gt", "ge"):
        lo_result = _apply_compare(op, t, threshold)
        hi_result = _apply_compare(op, hi, threshold)
        return lo_result if lo_result == hi_result else UNKNOWN
    if op == "eq":
        if not achievable:
            return False
        return UNKNOWN if u > 0 else True
    if op == "ne":
        if not achievable:
            return True
        return UNKNOWN if u > 0 else False
    raise ValueError(f"unknown compare op {op!r}")


def evaluate_arith(
    expr: ArithExpr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Any | Unknown:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ParamExpr):
        return _leaf_value(expr.path, config, activity)
    if isinstance(expr, ArithOp):
        left = evaluate_arith(expr.left, config, activity, space)
        right = evaluate_arith(expr.right, config, activity, space)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return UNKNOWN
        return _apply_arith(expr.op, left, right)
    if isinstance(expr, IfInactive):
        operand_val = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(operand_val, Unknown):
            return evaluate_arith(expr.fallback, config, activity, space)
        return operand_val
    if isinstance(expr, Count):
        t, u = _count_range(expr, config, activity, space)
        return t if u == 0 else UNKNOWN
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
    if isinstance(expr, Sum):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return UNKNOWN
        if len(leaves) == 0:
            return 0  # rule 6: empty aggregate
        if any(isinstance(v, Unknown) for v in leaves):
            return UNKNOWN  # D-19: interior Unknown -> aggregate Unknown
        return sum(leaves)
    if isinstance(expr, Min):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return UNKNOWN
        if len(leaves) == 0:
            return UNKNOWN  # rule 6: min/max of empty -> Unknown
        if any(isinstance(v, Unknown) for v in leaves):
            return UNKNOWN
        return min(leaves)
    if isinstance(expr, Max):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return UNKNOWN
        if len(leaves) == 0:
            return UNKNOWN
        if any(isinstance(v, Unknown) for v in leaves):
            return UNKNOWN
        return max(leaves)
    if isinstance(expr, CountOf):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return UNKNOWN
        if len(leaves) == 0:
            return 0
        if any(isinstance(v, Unknown) for v in leaves):
            return UNKNOWN
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
        return UNKNOWN
    return True


def _kleene_or(a: Kleene, b: Kleene) -> Kleene:
    if a is True or b is True:
        return True
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        return UNKNOWN
    return False


def evaluate_bool(
    expr: BoolExpr, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Kleene:
    if isinstance(expr, BoolLiteral):
        return expr.value
    if isinstance(expr, ParamExpr):
        v = _leaf_value(expr.path, config, activity)
        return UNKNOWN if isinstance(v, Unknown) else bool(v)
    if isinstance(expr, Compare):
        if isinstance(expr.left, Count) or isinstance(expr.right, Count):
            return _evaluate_count_compare(expr, config, activity, space)
        left = evaluate_arith(expr.left, config, activity, space)
        right = evaluate_arith(expr.right, config, activity, space)
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return UNKNOWN
        if expr.op in ("gt", "lt", "ge", "le"):
            ordinal_domain = _ordinal_domain_of(expr.left, space) or _ordinal_domain_of(
                expr.right, space
            )
            if ordinal_domain is not None:
                left = _ordinal_index(ordinal_domain, left)
                right = _ordinal_index(ordinal_domain, right)
                if isinstance(left, Unknown) or isinstance(right, Unknown):
                    return UNKNOWN
        return _apply_compare(expr.op, left, right)
    if isinstance(expr, BoolOp):
        left_v = evaluate_bool(expr.left, config, activity, space)
        right_v = evaluate_bool(expr.right, config, activity, space)
        return _kleene_and(left_v, right_v) if expr.op == "and" else _kleene_or(left_v, right_v)
    if isinstance(expr, Not):
        v = evaluate_bool(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(v, Unknown) else (not v)
    if isinstance(expr, IsIn):
        operand = evaluate_arith(expr.operand, config, activity, space)
        if isinstance(operand, Unknown):
            return UNKNOWN
        return any(_values_equal(operand, v) for v in expr.values)
    if isinstance(expr, IsActive):
        return all(activity.get(p, True) for p in expr.operand.params)
    if isinstance(expr, Contains):
        value = evaluate_arith(expr.operand, config, activity, space)
        return UNKNOWN if isinstance(value, Unknown) else expr.item in value
    if isinstance(expr, IsSorted):
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return UNKNOWN
        if len(leaves) == 0:
            return True  # rule 6
        if any(isinstance(v, Unknown) for v in leaves):
            return UNKNOWN
        pairs = list(pairwise(leaves))
        if expr.descending:
            return all(a >= b for a, b in pairs)
        return all(a <= b for a, b in pairs)
    if isinstance(expr, Distinct):
        if expr.fields:
            tuples = _distinct_tuples(expr, config, activity, space)
            if isinstance(tuples, Unknown):
                return UNKNOWN
            if len(tuples) == 0:
                return True
            if any(any(isinstance(x, Unknown) for x in t) for t in tuples):
                return UNKNOWN
            seen: list[tuple[Any, ...]] = []
            for t in tuples:
                if any(_tuple_equal(t, s) for s in seen):
                    return False
                seen.append(t)
            return True
        leaves = _aggregate_leaves(expr, config, activity, space)
        if isinstance(leaves, Unknown):
            return UNKNOWN
        if len(leaves) == 0:
            return True
        if any(isinstance(v, Unknown) for v in leaves):
            return UNKNOWN
        return _all_distinct(leaves)
    raise TypeError(f"cannot evaluate bool expr kind {expr.kind!r}")


def _evaluate_count_compare(
    expr: Compare, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> Kleene:
    if isinstance(expr.left, Count):
        count_node, other_side, count_is_left = expr.left, expr.right, True
    else:
        assert isinstance(expr.right, Count)
        count_node, other_side, count_is_left = expr.right, expr.left, False
    other_val = evaluate_arith(other_side, config, activity, space)
    if isinstance(other_val, Unknown):
        return UNKNOWN
    t, u = _count_range(count_node, config, activity, space)
    op = expr.op
    if not count_is_left:
        op = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le"}.get(op, op)
    return _count_vs_threshold(op, t, u, other_val)


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
    template_prefix = f"{path}[]."
    for i in range(n):
        concrete_prefix = f"{path}[{i}]."
        inst_params, inst_conditions = instantiate_element(space, template_prefix, concrete_prefix)
        inst_conditions_by_target = {c.target: c for c in inst_conditions}
        for local_path in local_topological_order(list(inst_params), inst_conditions_by_target):
            cond = inst_conditions_by_target.get(local_path)
            if cond is None:
                activity[local_path] = True
            else:
                value = evaluate_bool(cond.expr, config, activity, space)
                activity[local_path] = value is True


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
    """Bound-origin constraints impose assignment order too (M5, API_v3.md
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
