"""`.apply_defaults()` (API.md, "Defaults").

A partial-evaluation operator: idempotent, monotone (never overwrites,
never removes), activity-respecting. Modeled on `sample/_sample.py::
_draw_config` (fill-from-default replaces draw) — the same topological
walk and the same per-lift/per-choice/per-struct expansion, with
`eval.classify_condition` deciding "should this get filled" (three-valued:
inactive/unknown are both left untouched) in place of `evaluate_bool` +
a chart draw deciding "what value to draw."
"""

from __future__ import annotations

from typing import Any

from designspace.builder._space import Space
from designspace.config import flatten, unflatten
from designspace.config._flatten import _flatten_list_element
from designspace.eval import (
    Unknown,
    classify_condition,
    evaluate_arith,
    local_topological_order,
    status_activity_view,
    topological_order,
)
from designspace.expr import ArithExpr
from designspace.ir import ListDomain
from designspace.paths import element_prefix, instance_prefix, strip_last_index
from designspace.resolve._pipeline import check_fully_resolved
from designspace.resolve._relocate import instantiate_element


def apply_defaults(space: Space, config: dict[str, Any]) -> dict[str, Any]:
    check_fully_resolved(space)
    flat = flatten(config, space)
    status: dict[str, str] = {}
    conditions_by_target = {c.target: c for c in space.conditions}
    for path in topological_order(space):
        if "[]" in path:
            continue  # a lift's descendant template (D-18) -- filled via _fill_instance
        pd = space.params[path]
        condition = conditions_by_target.get(path)
        activity_class = classify_condition(condition, flat, status, space)
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            _fill_list(space, path, pd.domain, activity_class, flat, status)
        elif pd.type_kind == "space":
            # No own value to fill (API.md: "a struct carries no own
            # default value") -- its members are filled independently,
            # later in topological order.
            status[path] = "set" if activity_class == "active" else activity_class
        else:
            _fill_scalar(path, pd.default, activity_class, flat, status)
    return unflatten(flat, space)


def _fill_scalar(
    path: str, default: Any, activity_class: str, flat: dict[str, Any], status: dict[str, str]
) -> bool:
    if activity_class != "active":
        status[path] = activity_class
        return False
    if path in flat:
        status[path] = "set"
        return False
    if default is not None:
        flat[path] = default
        status[path] = "set"
        return True
    status[path] = "active_unset"
    return False


def _determine_count(
    count: int | ArithExpr, flat: dict[str, Any], status: dict[str, str], space: Space
) -> int | None:
    """The count rule (API.md, "Defaults" > "Counts and lifts"): a
    static int is always determined; an `ArithExpr` is determined if it
    evaluates to a definite integer, or is Unknown *solely* because a
    referenced param is inactive (-> 0, "the complete value []");
    otherwise (some referenced param is itself unresolved) -> `None`,
    genuinely pending.
    """
    if not isinstance(count, ArithExpr):
        return count
    value = evaluate_arith(count, flat, status_activity_view(status), space, status=status)
    if not isinstance(value, Unknown):
        assert isinstance(value, int) and not isinstance(value, bool)
        return value
    if any(status.get(d) in ("active_unset", "unknown") for d in count.params):
        return None
    return 0


def _fill_list(
    space: Space,
    path: str,
    domain: ListDomain,
    activity_class: str,
    flat: dict[str, Any],
    status: dict[str, str],
) -> bool:
    """Fills one (possibly nested/struct-field) list's defaults in place;
    returns whether anything was actually written — the "at least one
    instance leaf receives a default" trigger a *containing* list checks
    for its own materialization decision.
    """
    if activity_class != "active":
        status[path] = activity_class
        return False
    n = _determine_count(domain.count, flat, status, space)
    if n is None:
        status[path] = "unknown"
        return False
    if n == 0:
        # "either the count is 0 ... " -- unconditional: the empty list []
        # is itself a complete default value.
        flat[path] = 0
        status[path] = "set"
        return True
    if domain.list_default is not None:
        # Post-lift `.default([...])`: a literal phenotype value per index
        # (any element shape -- scalar, struct, choice, nested list), so
        # reuse the same structural writer `flatten()` itself uses rather
        # than re-deriving per-element-kind logic here.
        assert isinstance(domain.count, int)  # static-only, already resolution-checked
        for i, item in enumerate(domain.list_default):
            _flatten_list_element(
                item,
                domain,
                space,
                template_prefix=element_prefix(path),
                concrete_prefix=instance_prefix(path, i),
                out=flat,
                errors=None,
            )
        flat[path] = n
        status[path] = "set"
        return True
    any_filled = False
    for i in range(n):
        if _fill_instance(space, f"{path}[{i}]", domain, flat, status):
            any_filled = True
    if any_filled:
        flat[path] = n
        status[path] = "set"
    else:
        # "otherwise the lift is left implicit" -- container stays
        # un-materialized (active, but not emitted).
        status[path] = "active_unset"
    return any_filled


def _fill_instance(
    space: Space,
    inst_path: str,
    domain: ListDomain,
    flat: dict[str, Any],
    status: dict[str, str],
) -> bool:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _fill_list(space, inst_path, domain.element_domain, "active", flat, status)
    if domain.element_kind not in ("space", "choice"):
        if inst_path in flat:
            status[inst_path] = "set"
            return False
        if domain.element_default is not None:
            flat[inst_path] = domain.element_default
            status[inst_path] = "set"
            return True
        status[inst_path] = "active_unset"
        return False

    any_filled = False
    if domain.element_kind == "choice":
        # The discriminator itself: "a choice default names a variant" --
        # `element_default` is that variant name, filled like any scalar.
        if inst_path in flat:
            status[inst_path] = "set"
        elif domain.element_default is not None:
            flat[inst_path] = domain.element_default
            status[inst_path] = "set"
            any_filled = True
        else:
            status[inst_path] = "active_unset"

    template_prefix = element_prefix(strip_last_index(inst_path))
    inst_params, inst_conditions = instantiate_element(space, template_prefix, f"{inst_path}.")
    inst_conditions_by_target = {c.target: c for c in inst_conditions}
    for local_path in local_topological_order(list(inst_params), inst_conditions_by_target):
        pd = inst_params[local_path]
        cond = inst_conditions_by_target.get(local_path)
        activity_class = classify_condition(cond, flat, status, space)
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            if _fill_list(space, local_path, pd.domain, activity_class, flat, status):
                any_filled = True
        elif pd.type_kind == "space":
            status[local_path] = "set" if activity_class == "active" else activity_class
        else:
            if _fill_scalar(local_path, pd.default, activity_class, flat, status):
                any_filled = True
    return any_filled
