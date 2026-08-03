"""`.sample_one()` / `.sample_dicts()` (API.md, "Sampling and Generativity").

`sample_dicts` is M2's stand-in for the spec's `.sample(n) -> pl.DataFrame`
— PLAN.md's M10 line: "`sample(n)` return type switches to
`pl.DataFrame`... (`sample_dicts` retained as the M2 path)". `.sample_one()`
keeps its final spec signature (dict output) throughout.

M2 covered the generative scalar kinds (real, integer, categorical,
ordinal, bool); M3 adds choice (weighted variant pick, like categorical),
subset (Bernoulli-plus-size-rejection), and permutation (uniform
shuffle). Struct ("space") produces no value of its own — `_draw_config`
skips it — its members are separate, independently-drawn entries. Every
kind buildable through M3 is generative, so the non-generative
`SamplingError` (row 26's other half) has nothing to trigger on yet; only
retry exhaustion is reachable.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from designspace.build._space import Space
from designspace.charts import build_chart
from designspace.config import unflatten
from designspace.custom import is_generative
from designspace.errors import SamplingError
from designspace.eval import (
    Unknown,
    evaluate_arith,
    evaluate_bool,
    evaluate_constraint,
    instance_constraint_evals,
    is_violated,
    local_topological_order,
    topological_order,
)
from designspace.expr import ArithExpr
from designspace.ir import (
    CategoricalDomain,
    ChoiceDomain,
    CodeDomain,
    Constraint,
    CustomDomain,
    IntegerDomain,
    ListDomain,
    Log,
    Logit,
    OrdinalDomain,
    ParamDef,
    PermutationDomain,
    Power,
    RealDomain,
    SubsetDomain,
    SymbolicDomain,
    Weights,
)
from designspace.paths import element_prefix, strip_last_index
from designspace.resolve._bounds import bound_origin_targets
from designspace.resolve._pipeline import check_fully_resolved
from designspace.resolve._relocate import element_paramdef, instantiate_element

_MAX_RETRIES = 10_000

Seed = int | np.random.Generator | None
BoundTargets = dict[str, tuple[ArithExpr | None, ArithExpr | None]]


def _rng_from_seed(seed: Seed) -> np.random.Generator:
    if isinstance(seed, np.random.Generator):
        return seed
    return np.random.default_rng(seed)


def _draw_subset(domain: SubsetDomain, prior: Any, rng: np.random.Generator) -> list[Any]:
    probs = (
        np.asarray(prior.values, dtype=float)
        if isinstance(prior, Weights)
        else np.full(len(domain.items), 0.5)
    )
    max_size = domain.max_size if domain.max_size is not None else len(domain.items)
    for _ in range(_MAX_RETRIES):
        draws = rng.random(len(domain.items)) < probs
        size = int(draws.sum())
        if domain.min_size <= size <= max_size:
            return [item for item, included in zip(domain.items, draws, strict=True) if included]
    raise SamplingError(
        f"subset draw could not satisfy size bounds [{domain.min_size}, {max_size}] "
        f"after {_MAX_RETRIES} retries"
    )


def _draw_value(pd: ParamDef, rng: np.random.Generator) -> Any:
    if pd.type_kind in ("real", "integer"):
        assert pd.chart is not None
        return pd.chart.from_unit(float(rng.random()))
    if pd.type_kind == "bool":
        false_w, true_w = pd.prior.values if isinstance(pd.prior, Weights) else (1.0, 1.0)
        p_true = true_w / (false_w + true_w)
        return bool(rng.random() < p_true)
    if pd.type_kind in ("categorical", "ordinal"):
        assert isinstance(pd.domain, CategoricalDomain | OrdinalDomain)
        values = pd.domain.values
        weights = (
            np.asarray(pd.prior.values, dtype=float)
            if isinstance(pd.prior, Weights)
            else np.ones(len(values))
        )
        probs = weights / weights.sum()
        idx = int(rng.choice(len(values), p=probs))
        return values[idx]
    if pd.type_kind == "choice":
        assert isinstance(pd.domain, ChoiceDomain)
        variants = pd.domain.variants
        weights = (
            np.asarray(pd.prior.values, dtype=float)
            if isinstance(pd.prior, Weights)
            else np.ones(len(variants))
        )
        probs = weights / weights.sum()
        idx = int(rng.choice(len(variants), p=probs))
        return variants[idx]
    if pd.type_kind == "subset":
        assert isinstance(pd.domain, SubsetDomain)
        return _draw_subset(pd.domain, pd.prior, rng)
    if pd.type_kind == "permutation":
        assert isinstance(pd.domain, PermutationDomain)
        order = rng.permutation(len(pd.domain.items))
        return [pd.domain.items[i] for i in order]
    raise SamplingError(
        f"param has non-generative type_kind {pd.type_kind!r} (not yet implemented)"
    )


def _draw_custom(domain: CustomDomain, rng: np.random.Generator) -> Any:
    """A generative custom's draw (caller has already confirmed
    `is_generative`). Full protocol: `sample()` returns the type's native
    value, immediately bridged to phenotype form via `to_json` — every
    config-dict-shaped value is phenotype form (DECISIONS.md D-46).
    Shorthand: no `to_json` exists, so `sampler(rng)`'s return value is
    used directly (native and phenotype coincide)."""
    if domain.param_type is not None:
        pt = domain.param_type
        return pt.to_json(pt.sample(rng))
    assert domain.sampler is not None
    return domain.sampler(rng)


def _materialize_scalar(path: str, pd: ParamDef, rng: np.random.Generator) -> Any:
    """Draws (or falls back to `.default()`) an active scalar-shaped leaf's
    value. Every kind through M8 is generative; M9 adds the first
    non-generative case: a full-protocol custom whose `ParamType` has no
    `sample()` (API.md, "Sampling and Generativity"; DECISIONS.md D-46) —
    `.default()` satisfies materialization (row 26's other half), absent
    which sampling raises naming the param. M12 adds the second:
    `.code()`/`.symbolic()` without `sampler=` (a bare `.symbolic(...,
    sampler=...)` is generative; `.code()` has no `sampler=` form at all,
    so it is always non-generative unless a `.default()` covers it)."""
    if pd.type_kind == "custom":
        assert isinstance(pd.domain, CustomDomain)
        domain = pd.domain
        if domain.param_type is not None and not is_generative(domain.param_type):
            if pd.default is not None:
                return pd.default
            raise SamplingError(
                f"param {path!r}: non-generative custom type has no sample() "
                "and no .default() to materialize from (row 26)"
            )
        return _draw_custom(domain, rng)
    if pd.type_kind in ("symbolic", "code"):
        assert isinstance(pd.domain, SymbolicDomain | CodeDomain)
        sampler = pd.domain.sampler if isinstance(pd.domain, SymbolicDomain) else None
        if sampler is not None:
            return sampler(rng)
        if pd.default is not None:
            return pd.default
        raise SamplingError(
            f"param {path!r}: non-generative {pd.type_kind!r} param has no "
            "sampler and no .default() to materialize from (row 26)"
        )
    return _draw_value(pd, rng)


def _draw_lift(
    space: Space,
    path: str,
    domain: ListDomain,
    config: dict[str, Any],
    activity: dict[str, bool],
    rng: np.random.Generator,
) -> None:
    """Materializes an active lift at `path`: evaluates its (possibly
    runtime-dependent) count, records it at the lift's own flat key
    (DECISIONS.md D-18), then draws each instance."""
    if isinstance(domain.count, ArithExpr):
        n = evaluate_arith(domain.count, config, activity, space)
        if isinstance(n, Unknown):
            n = 0  # count depends on an inactive param: nothing to materialize
    else:
        n = domain.count
    if n < 0:
        raise SamplingError(
            f"param {path!r}: repeat() count evaluated to a negative value ({n}) (row 13)"
        )
    config[path] = n
    for i in range(n):
        _draw_lift_element(space, f"{path}[{i}]", domain, config, activity, rng)


def _draw_lift_element(
    space: Space,
    inst_path: str,
    domain: ListDomain,
    config: dict[str, Any],
    activity: dict[str, bool],
    rng: np.random.Generator,
) -> None:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        _draw_lift(space, inst_path, domain.element_domain, config, activity, rng)
        return
    if domain.element_kind not in ("space", "choice"):
        config[inst_path] = _materialize_scalar(inst_path, element_paramdef(inst_path, domain), rng)
        activity[inst_path] = True
        return
    if domain.element_kind == "choice":
        config[inst_path] = _materialize_scalar(inst_path, element_paramdef(inst_path, domain), rng)
        activity[inst_path] = True
    template_prefix = element_prefix(strip_last_index(inst_path))
    inst_params, inst_conditions = instantiate_element(space, template_prefix, f"{inst_path}.")
    inst_conditions_by_target = {c.target: c for c in inst_conditions}
    for local_path in local_topological_order(list(inst_params), inst_conditions_by_target):
        cond = inst_conditions_by_target.get(local_path)
        active = True if cond is None else evaluate_bool(cond.expr, config, activity, space) is True
        activity[local_path] = active
        pd = inst_params[local_path]
        if not active or pd.type_kind == "space":
            continue
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            _draw_lift(space, local_path, pd.domain, config, activity, rng)
        else:
            config[local_path] = _materialize_scalar(local_path, pd, rng)


def _tightenable(pd: ParamDef) -> bool:
    """Families where truncation provably equals conditioning (API.md,
    "All charts are static" — "the reference sampler *may* recognize a
    bound-origin constraint... and draw from the correspondingly tightened
    chart instead of rejecting"): the built-in closed-form priors (or
    uniform, `prior is None`) over a non-quantized real/integer. Explicitly
    excluded — the spec's own caveat: "tightening an external prior to a
    sub-interval needs `cdf`; absent that, rejection" — an arbitrary
    `Prior`-satisfying object (support containment could break under a
    narrower hi/lo) and a quantized/grid domain (cell-boundary effects are
    subtler; DECISIONS.md D-29). Both fall back to the hard constraint
    already sitting in `space.constraints`, rejected exactly as before.
    """
    if pd.type_kind not in ("real", "integer"):
        return False
    if pd.quantized is not None:
        return False
    return pd.prior is None or isinstance(pd.prior, Log | Logit | Power)


def _tighten(
    pd: ParamDef,
    bounds: tuple[ArithExpr | None, ArithExpr | None],
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
) -> ParamDef:
    """Narrows `pd`'s domain to the tightest bound its (already-assigned)
    bound-origin dependencies allow, rebuilding its chart the same way
    resolution built the original (`build_chart` is oblivious to *why* a
    domain is what it is). Falls back to `pd` unchanged — draw from the full
    envelope, let the hard constraint reject as before — whenever a
    dependency isn't assigned yet (Unknown) or the tightened interval would
    be empty (an infeasible config for this coupling; rejection is the only
    correct outcome, not a silently-empty chart).
    """
    lo_expr, hi_expr = bounds
    domain = pd.domain
    assert isinstance(domain, RealDomain | IntegerDomain)
    orig_lo, orig_hi = domain.lo, domain.hi
    # Envelopes are always plain numbers by sample time — resolution's
    # `compute_bound_envelopes` (M5, resolve/_bounds.py) already resolved
    # any expression bound before this param's chart was ever built.
    assert isinstance(orig_lo, int | float) and isinstance(orig_hi, int | float)
    new_lo, new_hi = orig_lo, orig_hi
    if lo_expr is not None:
        val = evaluate_arith(lo_expr, config, activity, space)
        if not isinstance(val, Unknown):
            new_lo = max(new_lo, val)
    if hi_expr is not None:
        val = evaluate_arith(hi_expr, config, activity, space)
        if not isinstance(val, Unknown):
            new_hi = min(new_hi, val)
    if new_lo > new_hi or (new_lo == orig_lo and new_hi == orig_hi):
        return pd
    new_domain: RealDomain | IntegerDomain = (
        RealDomain(new_lo, new_hi)
        if isinstance(domain, RealDomain)
        else IntegerDomain(int(new_lo), int(new_hi))
    )
    new_chart = build_chart(pd.path, pd.type_kind, new_domain, pd.prior, pd.quantized)
    return replace(pd, domain=new_domain, chart=new_chart)


def _draw_config(
    space: Space, rng: np.random.Generator, bound_targets: BoundTargets
) -> tuple[dict[str, Any], dict[str, bool]]:
    conditions_by_target = {c.target: c for c in space.conditions}
    config: dict[str, Any] = {}
    activity: dict[str, bool] = {}
    for path in topological_order(space):
        if "[]" in path:
            continue  # a lift's descendant template (D-18) -- never drawn
            # directly; materialized via _draw_lift when its owning list
            # param (below) is processed.
        condition = conditions_by_target.get(path)
        if condition is None:
            active = True
        else:
            active = evaluate_bool(condition.expr, config, activity, space) is True
        activity[path] = active
        if not active:
            continue
        pd = space.params[path]
        if pd.type_kind == "space":
            continue
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            _draw_lift(space, path, pd.domain, config, activity, rng)
        else:
            bounds = bound_targets.get(path)
            if bounds is not None and _tightenable(pd):
                pd = _tighten(pd, bounds, config, activity, space)
            config[path] = _materialize_scalar(path, pd, rng)
    return config, activity


def _violations(
    constraints: list[Constraint],
    config: dict[str, Any],
    activity: dict[str, bool],
    space: Space,
    *,
    reject_soft: bool,
) -> list[Constraint]:
    violated = []
    for c in constraints:
        ce = evaluate_constraint(c, config, activity, space)
        if is_violated(ce):
            violated.append(c)
    for ce in instance_constraint_evals(space, config, activity):
        if (reject_soft or ce.constraint.hard) and is_violated(ce):
            violated.append(ce.constraint)
    return violated


def sample_one(space: Space, seed: Seed = None, reject_soft: bool = False) -> dict[str, Any]:
    check_fully_resolved(space)
    config, _activity = _draw_one(space, _rng_from_seed(seed), reject_soft)
    return unflatten(config, space)


def _draw_one(
    space: Space, rng: np.random.Generator, reject_soft: bool
) -> tuple[dict[str, Any], dict[str, bool]]:
    """One retried draw, returned **flat** (path-grammar keyed `config` +
    parallel `activity`) — the shape shared by every sampling entry point.
    `sample_one`/`sample_dicts` nest it via `unflatten`; `sample_flat`/the
    DataFrame path (`frame/`) need the flat form directly, since `null`
    placement in a DataFrame column requires the activity a nested dict's
    "absent key" convention would otherwise discard.
    """
    constraints = (
        list(space.constraints) if reject_soft else [c for c in space.constraints if c.hard]
    )
    # Computed once per draw sequence, not per retry attempt (bound_origin_targets
    # is a single pass over space.constraints; tighten-not-reject, API.md
    # "All charts are static").
    bound_targets = bound_origin_targets(space)

    violation_counts: dict[int, int] = {}
    constraint_by_id: dict[int, Constraint] = {}
    for _ in range(_MAX_RETRIES):
        config, activity = _draw_config(space, rng, bound_targets)
        violated = _violations(constraints, config, activity, space, reject_soft=reject_soft)
        if not violated:
            return config, activity
        for c in violated:
            key = id(c)
            violation_counts[key] = violation_counts.get(key, 0) + 1
            constraint_by_id[key] = c

    ranked = sorted(violation_counts.items(), key=lambda kv: -kv[1])[:3]
    dominant = [f"{constraint_by_id[k].expr.kind!r} ({v}/{_MAX_RETRIES} draws)" for k, v in ranked]
    raise SamplingError(
        f"sample_one: no feasible draw found after {_MAX_RETRIES} retries; "
        f"dominant constraint(s): {dominant}"
    )


def sample_dicts(
    space: Space, n: int, seed: Seed = None, reject_soft: bool = False
) -> list[dict[str, Any]]:
    check_fully_resolved(space)  # once, not per draw
    rng = _rng_from_seed(seed)
    return [unflatten(config, space) for config, _activity in _n_draws(space, n, rng, reject_soft)]


def sample_flat(
    space: Space, n: int, seed: Seed = None, reject_soft: bool = False
) -> list[tuple[dict[str, Any], dict[str, bool]]]:
    """`n` flat `(config, activity)` draws — the primitive `frame/` builds
    the DataFrame path on. Same shared-`rng`-across-`n`-draws structure as
    `sample_dicts`, so `sample_flat(space, n, seed=s)` and
    `sample_dicts(space, n, seed=s)` describe the same `n` draws.
    """
    check_fully_resolved(space)
    rng = _rng_from_seed(seed)
    return _n_draws(space, n, rng, reject_soft)


def _n_draws(
    space: Space, n: int, rng: np.random.Generator, reject_soft: bool
) -> list[tuple[dict[str, Any], dict[str, bool]]]:
    return [_draw_one(space, rng, reject_soft) for _ in range(n)]
