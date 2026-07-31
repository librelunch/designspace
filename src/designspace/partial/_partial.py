"""Space — Partial Configs (API.md).

`evaluate_partial` / `remaining_domain` / `param_activity` / `is_complete` /
`missing_params` / `next_assignable` / the public `topological_order`, all
built on `eval.compute_activity_partial`'s four-valued status walk.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.config import flatten
from designspace.eval import (
    Unknown,
    compute_activity_partial,
    evaluate_arith,
    evaluate_bool,
    margin,
    status_activity_view,
)
from designspace.eval._kleene import _apply_compare, _ordinal_index, _values_equal
from designspace.expr import ArithExpr, BoolExpr, Compare, Contains, Not, Value
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    Constraint,
    ConstraintEval,
    IntegerDomain,
    IntegerRemaining,
    ListDomain,
    OrdinalDomain,
    ParamDef,
    PartialEval,
    PermutationDomain,
    PermutationRemaining,
    RealDomain,
    RealRemaining,
    RemainingDomain,
    SubsetDomain,
    SubsetRemaining,
    ValueRemaining,
)
from designspace.paths import element_prefix, instance_prefix
from designspace.resolve._pipeline import check_fully_resolved
from designspace.resolve._relocate import instantiate_constraints
from designspace.validate._validate import _lookup_param_shape

_ACTIVE_STATUSES = ("set", "active_unset")
_PENDING_STATUSES = ("active_unset", "unknown")


def topological_order(space: Space) -> list[str]:
    """Definition paths in dependency order, omitting lift descendant
    templates (API.md, "Space — Partial Configs")."""
    from designspace.eval._kleene import topological_order as _internal_order

    check_fully_resolved(space)
    return [p for p in _internal_order(space) if "[]" not in p]


def param_activity(space: Space, config: dict[str, Any]) -> dict[str, str]:
    check_fully_resolved(space)
    flat = flatten(config, space)
    status, _order, _deps = compute_activity_partial(space, flat)
    return {p: ("active" if s in _ACTIVE_STATUSES else s) for p, s in status.items()}


def is_complete(space: Space, config: dict[str, Any]) -> bool:
    check_fully_resolved(space)
    flat = flatten(config, space)
    status, _order, _deps = compute_activity_partial(space, flat)
    return not any(s in _PENDING_STATUSES for s in status.values())


def missing_params(space: Space, config: dict[str, Any]) -> list[str]:
    check_fully_resolved(space)
    flat = flatten(config, space)
    status, order, _deps = compute_activity_partial(space, flat)
    return [p for p in order if status[p] == "active_unset"]


def next_assignable(space: Space, config: dict[str, Any]) -> list[str]:
    check_fully_resolved(space)
    flat = flatten(config, space)
    status, order, deps = compute_activity_partial(space, flat)
    result = []
    for p in order:
        if status[p] != "active_unset":
            continue
        if all(status.get(d, "set") in ("set", "inactive") for d in deps.get(p, frozenset())):
            result.append(p)
    return result


def _instance_constraint_evals_partial(
    space: Space,
    flat: dict[str, Any],
    status: dict[str, str],
    activity: dict[str, bool],
) -> tuple[list[ConstraintEval], list[Constraint]]:
    """The per-instance sibling of the top-level loop below — element-scoped
    constraint templates (`ListDomain.element_constraints`) instantiated per
    active index, once that lift's own count is determined (`status == "set"`
    for the container; an undetermined/inactive container contributes none,
    same as `evaluate_partial`'s general instance-status rule)."""
    evaluable: list[ConstraintEval] = []
    pending: list[Constraint] = []
    for path, pd in space.params.items():
        if pd.type_kind != "list":
            continue
        domain = pd.domain
        assert isinstance(domain, ListDomain)
        if not domain.element_constraints or status.get(path) != "set":
            continue
        n = flat.get(path, 0)
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            continue
        template_prefix = element_prefix(path)
        for i in range(n):
            concrete_prefix = instance_prefix(path, i)
            for c in instantiate_constraints(
                domain.element_constraints, template_prefix, concrete_prefix
            ):
                _classify_constraint(
                    c, flat, status, activity, space, f"{path}[{i}]", evaluable, pending
                )
    return evaluable, pending


def _classify_constraint(
    c: Constraint,
    flat: dict[str, Any],
    status: dict[str, str],
    activity: dict[str, bool],
    space: Space,
    instance_path: str | None,
    evaluable: list[ConstraintEval],
    pending: list[Constraint],
) -> None:
    # Shared across the satisfaction walk (evaluate_bool) and the margin
    # walk (margin(), which independently re-evaluates the same Compare
    # leaves) so a ds.value node's fn is called once per constraint, not
    # twice -- eval/_constraint_eval.py::evaluate_constraint's own reason.
    value_cache: dict[Value, Any] = {}
    value = evaluate_bool(c.expr, flat, activity, space, status=status, value_cache=value_cache)
    if isinstance(value, Unknown):
        if value.provenance == "pending":
            pending.append(c)
        else:
            evaluable.append(
                ConstraintEval(
                    constraint=c,
                    instance_path=instance_path,
                    applicable=False,
                    satisfied=None,
                    margin=None,
                )
            )
        return
    evaluable.append(
        ConstraintEval(
            constraint=c,
            instance_path=instance_path,
            applicable=True,
            satisfied=bool(value),
            margin=margin(c.expr, flat, activity, space, value_cache=value_cache),
        )
    )


def evaluate_partial(space: Space, config: dict[str, Any]) -> PartialEval:
    check_fully_resolved(space)
    flat = flatten(config, space)
    status, _order, _deps = compute_activity_partial(space, flat)
    activity = status_activity_view(status)

    evaluable: list[ConstraintEval] = []
    pending: list[Constraint] = []
    for c in space.constraints:
        _classify_constraint(c, flat, status, activity, space, None, evaluable, pending)
    inst_evaluable, inst_pending = _instance_constraint_evals_partial(
        space, flat, status, activity
    )
    evaluable.extend(inst_evaluable)
    pending.extend(inst_pending)

    n_remaining = sum(1 for s in status.values() if s == "active_unset")
    return PartialEval(
        param_status=MappingProxyType(status),
        evaluable_constraints=tuple(evaluable),
        pending_constraints=tuple(pending),
        n_remaining=n_remaining,
    )


# -- remaining_domain ---------------------------------------------------------


def _base_descriptor(pd: ParamDef) -> RemainingDomain:
    domain = pd.domain
    if isinstance(domain, RealDomain):
        lo, hi = domain.lo, domain.hi
        assert isinstance(lo, int | float) and isinstance(hi, int | float)
        return RealRemaining(
            lo=float(lo), hi=float(hi), lo_inclusive=True, hi_inclusive=not pd.periodic,
            grid=pd.quantized,
        )
    if isinstance(domain, IntegerDomain):
        lo, hi = domain.lo, domain.hi
        assert isinstance(lo, int) and isinstance(hi, int)
        return IntegerRemaining(lo=lo, hi=hi, grid=pd.quantized)
    if isinstance(domain, BoolDomain):
        return ValueRemaining(values=(False, True))
    if isinstance(domain, CategoricalDomain | OrdinalDomain):
        return ValueRemaining(values=domain.values)
    if isinstance(domain, ChoiceDomain):
        return ValueRemaining(values=domain.variants)
    if isinstance(domain, SubsetDomain):
        max_size = domain.max_size if domain.max_size is not None else len(domain.items)
        return SubsetRemaining(
            forced_in=(), forced_out=(), free=domain.items,
            min_size=domain.min_size, max_size=max_size,
        )
    if isinstance(domain, PermutationDomain):
        return PermutationRemaining(items=domain.items)
    raise TypeError(
        f"remaining_domain: {pd.path!r} is a {pd.type_kind!r} param — "
        "remaining_domain does not support this kind"
    )


_NEGATE_OP = {"gt": "le", "lt": "ge", "ge": "lt", "le": "gt", "eq": "ne", "ne": "eq"}
_FLIP_OP = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le", "eq": "eq", "ne": "ne"}


def _negate_compare(cmp: Compare) -> Compare:
    return Compare(_NEGATE_OP[cmp.op], cmp.left, cmp.right)


def _feasible_expr(c: Constraint) -> BoolExpr:
    """The feasible-side predicate for a *hard* constraint, by origin
    (API.md, "Space — Partial Configs"): a feasible-predicate constraint
    (`origin` `"bound"` or `"require"`) already stores the desired (feasible)
    predicate; a forbid's `expr` names the *forbidden* state, so feasible = its
    negation. One level of double-negation is collapsed (`~Not(x) == x`) so a
    forbid written in forbidden-state form (`.forbid(~cond)`) reduces just as
    readily as the plain form.
    """
    if c.origin in ("bound", "require"):
        return c.expr
    if isinstance(c.expr, Not):
        return c.expr.operand
    return Not(c.expr)


def _target_and_other(path: str, cmp: Compare) -> tuple[str, ArithExpr] | None:
    """`(op, other)` read as "`path` <op> other" — `path` must be a bare
    (non-arithmetic) operand of `cmp`, and the *other* side must not itself
    reference `path` (two-unset/self-referential is not reducible)."""
    if isinstance(cmp.left, ParamExpr) and cmp.left.path == path:
        other = cmp.right
        if path in other.params:
            return None
        return cmp.op, other
    if isinstance(cmp.right, ParamExpr) and cmp.right.path == path:
        other = cmp.left
        if path in other.params:
            return None
        return _FLIP_OP[cmp.op], other
    return None


def _narrow_numeric(
    base: RealRemaining | IntegerRemaining, op: str, value: float
) -> RealRemaining | IntegerRemaining | None:
    lo, hi = base.lo, base.hi
    lo_incl = base.lo_inclusive if isinstance(base, RealRemaining) else True
    hi_incl = base.hi_inclusive if isinstance(base, RealRemaining) else True
    if op == "le":
        if value < hi or (value == hi and not hi_incl):
            hi, hi_incl = value, True
    elif op == "lt":
        if value <= hi:
            hi, hi_incl = value, False
    elif op == "ge":
        if value > lo or (value == lo and not lo_incl):
            lo, lo_incl = value, True
    elif op == "gt":
        if value >= lo:
            lo, lo_incl = value, False
    elif op == "eq":
        lo, hi, lo_incl, hi_incl = value, value, True, True
    else:  # "ne": hole-punching an interval is not representable -- unreduced
        return None
    if isinstance(base, IntegerRemaining):
        int_lo = math.ceil(lo) if lo_incl else math.floor(lo) + 1
        int_hi = math.floor(hi) if hi_incl else math.ceil(hi) - 1
        return IntegerRemaining(lo=int(int_lo), hi=int(int_hi), grid=base.grid)
    return RealRemaining(lo=lo, hi=hi, lo_inclusive=lo_incl, hi_inclusive=hi_incl, grid=base.grid)


def _narrow_value(
    base: ValueRemaining, op: str, value: Any, ordinal_domain: OrdinalDomain | None
) -> ValueRemaining | None:
    if ordinal_domain is not None and op in ("lt", "gt", "le", "ge"):
        target_idx = _ordinal_index(ordinal_domain, value)
        if isinstance(target_idx, Unknown):
            return None
        kept = []
        for v in base.values:
            idx = _ordinal_index(ordinal_domain, v)
            if not isinstance(idx, Unknown) and _apply_compare(op, idx, target_idx):
                kept.append(v)
        return ValueRemaining(values=tuple(kept))
    if op == "eq":
        return ValueRemaining(values=tuple(v for v in base.values if _values_equal(v, value)))
    if op == "ne":
        return ValueRemaining(values=tuple(v for v in base.values if not _values_equal(v, value)))
    return None  # lt/gt/le/ge on a non-ordinal value domain: unsupported, unreduced


def _narrow_subset(base: SubsetRemaining, *, forced_in: bool, item: Any) -> SubsetRemaining:
    if forced_in:
        if any(_values_equal(item, v) for v in base.forced_in):
            return base
        free = tuple(v for v in base.free if not _values_equal(v, item))
        return SubsetRemaining(
            forced_in=(*base.forced_in, item), forced_out=base.forced_out,
            free=free, min_size=base.min_size, max_size=base.max_size,
        )
    if any(_values_equal(item, v) for v in base.forced_out):
        return base
    free = tuple(v for v in base.free if not _values_equal(v, item))
    return SubsetRemaining(
        forced_in=base.forced_in, forced_out=(*base.forced_out, item),
        free=free, min_size=base.min_size, max_size=base.max_size,
    )


def _resolved_op_value(
    path: str,
    feasible: BoolExpr,
    flat: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
) -> tuple[str, Any] | None:
    """`(op, other_value)` read as "`path` <op> other_value", or `None` if
    `feasible` isn't a `Compare` reducible for `path` (per `_target_and_other`)
    or the other side isn't a determined value."""
    if not isinstance(feasible, Compare):
        return None
    reduced = _target_and_other(path, feasible)
    if reduced is None:
        return None
    op, other = reduced
    other_val = evaluate_arith(other, flat, activity, space)
    if isinstance(other_val, Unknown):
        return None
    return op, other_val


def _reduce_one(
    path: str,
    current: RemainingDomain,
    c: Constraint,
    flat: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    ordinal_domain: OrdinalDomain | None,
) -> RemainingDomain:
    feasible = _feasible_expr(c)
    if isinstance(feasible, Not) and isinstance(feasible.operand, Compare):
        feasible = _negate_compare(feasible.operand)
    if isinstance(current, RealRemaining | IntegerRemaining):
        resolved = _resolved_op_value(path, feasible, flat, activity, space)
        if resolved is None:
            return current
        op, other_val = resolved
        if not isinstance(other_val, int | float) or isinstance(other_val, bool):
            return current
        narrowed_num = _narrow_numeric(current, op, float(other_val))
        return narrowed_num if narrowed_num is not None else current
    if isinstance(current, ValueRemaining):
        resolved = _resolved_op_value(path, feasible, flat, activity, space)
        if resolved is None:
            return current
        op, other_val = resolved
        narrowed_val = _narrow_value(current, op, other_val, ordinal_domain)
        return narrowed_val if narrowed_val is not None else current
    if isinstance(current, SubsetRemaining):
        if (
            isinstance(feasible, Contains)
            and isinstance(feasible.operand, ParamExpr)
            and feasible.operand.path == path
        ):
            return _narrow_subset(current, forced_in=True, item=feasible.item)
        if (
            isinstance(feasible, Not)
            and isinstance(feasible.operand, Contains)
            and isinstance(feasible.operand.operand, ParamExpr)
            and feasible.operand.operand.path == path
        ):
            return _narrow_subset(current, forced_in=False, item=feasible.operand.item)
    return current  # unsupported shape -- not reducible (sound: leave as-is)


def remaining_domain(space: Space, path: str, config: dict[str, Any]) -> RemainingDomain | None:
    check_fully_resolved(space)
    pd = _lookup_param_shape(space, path)
    if pd.type_kind in ("space", "list"):
        raise TypeError(
            f"remaining_domain: {path!r} is a struct/list container, not a leaf param"
        )
    flat = flatten(config, space)
    status, _order, _deps = compute_activity_partial(space, flat)
    if status.get(path, "inactive") == "inactive":
        return None

    activity = status_activity_view(status)
    current = _base_descriptor(pd)
    ordinal_domain = pd.domain if isinstance(pd.domain, OrdinalDomain) else None
    for c in space.constraints:
        if not c.hard or path not in c.params:
            continue
        current = _reduce_one(path, current, c, flat, activity, space, ordinal_domain)
    return current
