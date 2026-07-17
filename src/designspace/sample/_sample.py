"""`.sample_one()` / `.sample_dicts()` (API_v3.md, "Sampling and Generativity").

`sample_dicts` is M2's stand-in for the spec's `.sample(n) -> pl.DataFrame`
— IMPLEMENTATION_PLAN.md's M10 line: "`sample(n)` return type switches to
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

from typing import Any

import numpy as np

from designspace.build._space import Space
from designspace.config import unflatten
from designspace.errors import SamplingError
from designspace.eval import evaluate_bool, evaluate_constraint, is_violated, topological_order
from designspace.ir import (
    CategoricalDomain,
    ChoiceDomain,
    Constraint,
    OrdinalDomain,
    ParamDef,
    PermutationDomain,
    SubsetDomain,
    Weights,
)

_MAX_RETRIES = 10_000

Seed = int | np.random.Generator | None


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


def _draw_config(space: Space, rng: np.random.Generator) -> tuple[dict[str, Any], dict[str, bool]]:
    conditions_by_target = {c.target: c for c in space.conditions}
    config: dict[str, Any] = {}
    activity: dict[str, bool] = {}
    for path in topological_order(space):
        condition = conditions_by_target.get(path)
        if condition is None:
            active = True
        else:
            active = evaluate_bool(condition.expr, config, activity, space) is True
        activity[path] = active
        if active and space.params[path].type_kind != "space":
            config[path] = _draw_value(space.params[path], rng)
    return config, activity


def _violations(
    constraints: list[Constraint], config: dict[str, Any], activity: dict[str, bool], space: Space
) -> list[Constraint]:
    violated = []
    for c in constraints:
        ce = evaluate_constraint(c, config, activity, space)
        if is_violated(ce):
            violated.append(c)
    return violated


def sample_one(space: Space, seed: Seed = None, reject_soft: bool = False) -> dict[str, Any]:
    rng = _rng_from_seed(seed)
    constraints = (
        list(space.constraints) if reject_soft else [c for c in space.constraints if c.hard]
    )

    violation_counts: dict[int, int] = {}
    constraint_by_id: dict[int, Constraint] = {}
    for _ in range(_MAX_RETRIES):
        config, activity = _draw_config(space, rng)
        violated = _violations(constraints, config, activity, space)
        if not violated:
            return unflatten(config, space)
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
    rng = _rng_from_seed(seed)
    return [sample_one(space, seed=rng, reject_soft=reject_soft) for _ in range(n)]
