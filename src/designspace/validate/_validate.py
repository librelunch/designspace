"""`.validate()` / `.validate_param()` / `.is_feasible()` /
`.infeasibility_reasons()` / `.evaluate_constraints()`
(API.md, "Space: Validation").

Feasibility is param validity plus hard constraints alone. An
`.encourage()` declaration never affects `valid`, matching "Feasibility is
defined by param validity plus forbids only."

`validate()` and `evaluate_constraints()` take the canonical nested config,
while `compute_activity` and `evaluate_constraint` work over the flat,
path-keyed dict.

`validate()` must not route through the lenient `flatten()`. A malformed
choice or struct shape such as `{"algo": 123}` has to surface as a
`ParamError` rather than vanish, so it uses `flatten_with_errors` from
`config/` instead: one space-guided traversal, shared with `flatten()`,
that also collects shape errors.
"""

from __future__ import annotations

from typing import Any, assert_never

from designspace.builder._space import Space
from designspace.charts import build_grid_shape, grid_membership
from designspace.config import as_flat, as_nested, flatten_with_errors
from designspace.eval import (
    Unknown,
    compute_activity,
    evaluate_arith,
    evaluate_constraint,
    instance_constraint_evals,
    is_violated,
)
from designspace.expr import ArithExpr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    CodeDomain,
    ConstraintEval,
    CustomDomain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    ParamDef,
    ParamError,
    PermutationDomain,
    RealDomain,
    StructDomain,
    SubsetDomain,
    SymbolicDomain,
    ValidationResult,
)
from designspace.paths import element_prefix, strip_last_index
from designspace.paths._grammar import _INDEX_RE
from designspace.program._validate import program_value_error
from designspace.resolve._pipeline import check_fully_resolved
from designspace.resolve._relocate import element_paramdef


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
    if isinstance(domain, ListDomain):
        bad = not isinstance(value, int) or isinstance(value, bool) or value < 0
        return "wrong_type" if bad else None
    if isinstance(domain, CustomDomain):
        # `value` is already phenotype form, so bridge back to native only
        # to call the type's own validate(). Every other branch above
        # type-checks a submitted value before trusting its shape. Core
        # cannot do that for an opaque custom, so it catches whatever
        # `from_json`, `validate` or the shorthand `validator` raise on a
        # structurally wrong value and reports it the same way, as
        # "wrong_type" rather than as a crash escaping through a public
        # validate() call.
        try:
            if domain.param_type is not None:
                ok = domain.param_type.validate(domain.param_type.from_json(value))
            else:
                assert domain.validator is not None
                ok = domain.validator(value)
        except Exception:
            return "wrong_type"
        return None if ok else "out_of_bounds"
    if isinstance(domain, SymbolicDomain | CodeDomain):
        return program_value_error(domain, value)
    if isinstance(domain, StructDomain):
        # A struct holds no value of its own. Its fields are separate params
        # under a dotted path, each validated in its own right, so there is
        # nothing here to be in or out of the domain.
        return None
    assert_never(domain)


def _presence_error(
    path: str, pd_or_domain: ParamDef | ListDomain, flat: dict[str, Any], activity: dict[str, bool]
) -> ParamError | None:
    active = activity.get(path, True)
    present = path in flat
    if active and not present:
        return ParamError(param=path, reason="missing", value=None)
    if not active and present:
        return ParamError(param=path, reason="inactive_but_present", value=flat[path])
    if active and present:
        pd = (
            pd_or_domain
            if isinstance(pd_or_domain, ParamDef)
            else element_paramdef(path, pd_or_domain)
        )
        reason = _domain_error_reason(pd, flat[path])
        if reason is not None:
            return ParamError(param=path, reason=reason, value=flat[path])
    return None


def _validate_lift_element(
    space: Space,
    inst_path: str,
    domain: ListDomain,
    flat: dict[str, Any],
    activity: dict[str, bool],
) -> list[ParamError]:
    """One lift instance's worth of `ParamError` records.

    A struct or choice element is exactly one bracket level deep, resolution
    rejecting deeper nesting, so deriving the descendant template prefix
    from `inst_path` is unambiguous.
    """
    errors: list[ParamError] = []
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        n = flat.get(inst_path)
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            return errors  # shape error already caught by flatten_with_errors
        for j in range(n):
            errors.extend(
                _validate_lift_element(
                    space, f"{inst_path}[{j}]", domain.element_domain, flat, activity
                )
            )
        return errors
    if domain.element_kind in ("space", "choice"):
        if domain.element_kind == "choice":
            error = _presence_error(inst_path, domain, flat, activity)
            if error is not None:
                errors.append(error)
        template_prefix = element_prefix(strip_last_index(inst_path))
        for template_path, template_pd in space.params.items():
            if not template_path.startswith(template_prefix):
                continue
            if template_pd.type_kind in ("space", "list"):
                continue
            concrete_path = inst_path + "." + template_path[len(template_prefix) :]
            error = _presence_error(concrete_path, template_pd, flat, activity)
            if error is not None:
                errors.append(error)
        return errors
    error = _presence_error(inst_path, domain, flat, activity)
    if error is not None:
        errors.append(error)
    return errors


def _validate_lift_instances(
    space: Space, path: str, domain: ListDomain, flat: dict[str, Any], activity: dict[str, bool]
) -> list[ParamError]:
    errors: list[ParamError] = []
    if not activity.get(path, True):
        return errors
    n = flat.get(path)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return errors
    if isinstance(domain.count, ArithExpr):
        # A dynamic repeat count must match the submitted length.
        evaluated = evaluate_arith(domain.count, flat, activity, space)
        if not isinstance(evaluated, Unknown) and evaluated != n:
            errors.append(ParamError(param=path, reason="out_of_bounds", value=n))
    for i in range(n):
        errors.extend(_validate_lift_element(space, f"{path}[{i}]", domain, flat, activity))
    return errors


def evaluate_constraints(space: Space, config: dict[str, Any]) -> list[ConstraintEval]:
    check_fully_resolved(space)
    flat = as_flat(config, space)
    activity = compute_activity(space, flat)
    evals = [evaluate_constraint(c, flat, activity, space) for c in space.constraints]
    evals.extend(instance_constraint_evals(space, flat, activity))
    return evals


def validate(space: Space, config: dict[str, Any]) -> ValidationResult:
    check_fully_resolved(space)
    # A config keyed by path is rebuilt first, so the shape pass sees the
    # nested form it reports errors about, and a lift's length entry is
    # recovered rather than reported missing: a driver loop assigns instance
    # leaves and never a container, so what it builds carries no such entry.
    flat, param_errors_list = flatten_with_errors(as_nested(config, space), space)
    shape_error_paths = {pe.param for pe in param_errors_list}
    activity = compute_activity(space, flat)
    param_errors: list[ParamError] = list(param_errors_list)
    for path, pd in space.params.items():
        # `"[]" in path` marks a lift's descendant template rather than a
        # real config leaf. Its instances are validated separately below.
        if pd.type_kind == "space" or "[]" in path or path in shape_error_paths:
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
            elif pd.type_kind == "list":
                assert isinstance(pd.domain, ListDomain)
                param_errors.extend(
                    _validate_lift_instances(space, path, pd.domain, flat, activity)
                )

    constraint_evals = [evaluate_constraint(c, flat, activity, space) for c in space.constraints]
    constraint_evals.extend(instance_constraint_evals(space, flat, activity))
    hard_violated = any(ce.constraint.hard and is_violated(ce) for ce in constraint_evals)
    valid = not param_errors and not hard_violated
    return ValidationResult(
        valid=valid, param_errors=tuple(param_errors), constraint_evals=tuple(constraint_evals)
    )


def _lookup_param_shape(space: Space, path: str) -> ParamDef:
    """The `ParamDef` describing `path`, which may be an instance path.

    `path` may be a bare definition path; a struct-lift descendant instance
    path such as `"layers[2].width"`, whose `"[]"`-bracketed template is
    already a `ParamDef` in `space.params`; or a direct lift element
    instance path such as `"dropout[3]"` or `"pipeline[1]"`, synthesized
    through `_element_paramdef`. API.md states that "instance paths
    supported."

    A nested-lift instance path beyond one level is not resolved here,
    matching the single-bracket depth boundary a struct or choice element
    already carries.
    """
    if path in space.params:
        return space.params[path]
    template_path = _INDEX_RE.sub("[]", path)
    if template_path in space.params:
        return space.params[template_path]
    if "[" in path:
        base = strip_last_index(path)
        if base in space.params and space.params[base].type_kind == "list":
            domain = space.params[base].domain
            assert isinstance(domain, ListDomain)
            return element_paramdef(path, domain)
    raise TypeError(f"no such param {path!r} in this space")


def validate_param(
    space: Space, path: str, value: Any, context: dict[str, Any] | None = None
) -> ValidationResult:
    check_fully_resolved(space)
    pd = _lookup_param_shape(space, path)
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
    from designspace.display._expr import render_expr

    result = validate(space, config)
    reasons = [f"{pe.param}: {pe.reason}" for pe in result.param_errors]
    for ce in result.constraint_evals:
        if ce.constraint.hard and ce.violated:
            reasons.append(
                f"{ce.constraint.kind} violated (margin={ce.margin}): "
                f"{render_expr(ce.constraint.expr)}"
            )
    return reasons
