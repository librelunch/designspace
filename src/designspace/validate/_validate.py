"""`.validate()` / `.validate_param()` / `.is_feasible()` /
`.infeasibility_reasons()` / `.evaluate_constraints()`
(API_v3.md, "Space — Validation").

Feasibility is param validity plus hard constraints (forbids) only —
`.constrain()` declarations never affect `valid`, matching
"Feasibility is defined by param validity plus forbids only."

`validate()`/`evaluate_constraints()` take the canonical *nested* config;
internally everything still works over the flat, path-keyed dict M2 built
(`compute_activity`/`evaluate_constraint` are unchanged). `validate()`
specifically must not route through the lenient `flatten()`: a malformed
choice/struct shape (`{"algo": 123}`) has to surface as a `ParamError`,
not vanish silently, so it uses `flatten_with_errors` instead (config/) —
one space-guided traversal, shared with `flatten()`, that also collects
shape errors.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.charts import build_grid_shape, grid_membership
from designspace.config import flatten, flatten_with_errors
from designspace.eval import compute_activity, evaluate_constraint, is_violated
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    ConstraintEval,
    IntegerDomain,
    OrdinalDomain,
    ParamDef,
    ParamError,
    PermutationDomain,
    RealDomain,
    SubsetDomain,
    ValidationResult,
)


def _strict_member(value: Any, values: tuple[Any, ...]) -> bool:
    return any(type(value) is type(v) and value == v for v in values)


def _has_duplicates_strict(values: list[Any]) -> bool:
    seen: list[Any] = []
    for v in values:
        if any(type(existing) is type(v) and existing == v for existing in seen):
            return True
        seen.append(v)
    return False


def _domain_error_reason(pd: ParamDef, value: Any) -> str | None:
    domain = pd.domain
    if isinstance(domain, SubsetDomain):
        if not isinstance(value, list):
            return "wrong_type"
        if _has_duplicates_strict(value) or not all(_strict_member(v, domain.items) for v in value):
            return "out_of_bounds"
        max_size = domain.max_size if domain.max_size is not None else len(domain.items)
        if not (domain.min_size <= len(value) <= max_size):
            return "out_of_bounds"
        return None
    if isinstance(domain, PermutationDomain):
        if not isinstance(value, list):
            return "wrong_type"
        if len(value) != len(domain.items) or _has_duplicates_strict(value):
            return "out_of_bounds"
        if not all(_strict_member(v, domain.items) for v in value):
            return "out_of_bounds"
        return None
    if isinstance(domain, ChoiceDomain):
        return None if isinstance(value, str) and value in domain.variants else "out_of_bounds"
    if isinstance(domain, RealDomain):
        if not isinstance(value, int | float) or isinstance(value, bool):
            return "wrong_type"
        lo, hi = domain.lo, domain.hi
        assert isinstance(lo, int | float) and isinstance(hi, int | float)
        in_bounds = lo <= value < hi if pd.periodic else lo <= value <= hi
        if not in_bounds:
            return "out_of_bounds"
        if pd.quantized is not None:
            shape = build_grid_shape(
                float(lo),
                float(hi),
                pd.quantized.step,
                pd.quantized.factor,
                pd.quantized.include_hi,
            )
            if grid_membership(shape, float(value)) is None:
                return "not_on_grid"
        return None
    if isinstance(domain, IntegerDomain):
        if not isinstance(value, int) or isinstance(value, bool):
            return "wrong_type"
        int_lo, int_hi = domain.lo, domain.hi
        assert isinstance(int_lo, int) and isinstance(int_hi, int)
        if not (int_lo <= value <= int_hi):
            return "out_of_bounds"
        if pd.quantized is not None:
            shape = build_grid_shape(
                float(int_lo),
                float(int_hi),
                pd.quantized.step,
                pd.quantized.factor,
                pd.quantized.include_hi,
            )
            if grid_membership(shape, float(value)) is None:
                return "not_on_grid"
        return None
    if isinstance(domain, CategoricalDomain | OrdinalDomain):
        return None if _strict_member(value, domain.values) else "out_of_bounds"
    if isinstance(domain, BoolDomain):
        return None if isinstance(value, bool) else "wrong_type"
    return None  # pragma: no cover - unreachable for M2 scalar kinds


def evaluate_constraints(space: Space, config: dict[str, Any]) -> list[ConstraintEval]:
    flat = flatten(config, space)
    activity = compute_activity(space, flat)
    return [evaluate_constraint(c, flat, activity, space) for c in space.constraints]


def validate(space: Space, config: dict[str, Any]) -> ValidationResult:
    flat, param_errors_list = flatten_with_errors(config, space)
    shape_error_paths = {pe.param for pe in param_errors_list}
    activity = compute_activity(space, flat)
    param_errors: list[ParamError] = list(param_errors_list)
    for path, pd in space.params.items():
        if pd.type_kind == "space" or path in shape_error_paths:
            continue
        active = activity[path]
        present = path in flat
        if active and not present:
            param_errors.append(ParamError(param=path, reason="missing", value=None))
        elif not active and present:
            param_errors.append(
                ParamError(param=path, reason="inactive_but_present", value=flat[path])
            )
        elif active and present:
            reason = _domain_error_reason(pd, flat[path])
            if reason is not None:
                param_errors.append(ParamError(param=path, reason=reason, value=flat[path]))

    constraint_evals = [evaluate_constraint(c, flat, activity, space) for c in space.constraints]
    hard_violated = any(ce.constraint.hard and is_violated(ce) for ce in constraint_evals)
    valid = not param_errors and not hard_violated
    return ValidationResult(
        valid=valid, param_errors=tuple(param_errors), constraint_evals=tuple(constraint_evals)
    )


def validate_param(
    space: Space, path: str, value: Any, context: dict[str, Any] | None = None
) -> ValidationResult:
    if path not in space.params:
        raise TypeError(f"no such param {path!r} in this space")
    pd = space.params[path]
    reason = _domain_error_reason(pd, value)
    param_errors = [ParamError(param=path, reason=reason, value=value)] if reason else []

    config = dict(context) if context is not None else {}
    config[path] = value
    activity = compute_activity(space, config)
    known_paths = set(config.keys())
    constraint_evals = [
        evaluate_constraint(c, config, activity, space)
        for c in space.constraints
        if path in c.params and c.params <= known_paths
    ]
    hard_violated = any(ce.constraint.hard and is_violated(ce) for ce in constraint_evals)
    valid = not param_errors and not hard_violated
    return ValidationResult(
        valid=valid, param_errors=tuple(param_errors), constraint_evals=tuple(constraint_evals)
    )


def is_feasible(space: Space, config: dict[str, Any]) -> bool:
    return validate(space, config).valid


def infeasibility_reasons(space: Space, config: dict[str, Any]) -> list[str]:
    result = validate(space, config)
    reasons = [f"{pe.param}: {pe.reason}" for pe in result.param_errors]
    for ce in result.constraint_evals:
        if ce.constraint.hard and is_violated(ce):
            reasons.append(f"forbid violated (margin={ce.margin}): {ce.constraint.expr.kind}")
    return reasons
