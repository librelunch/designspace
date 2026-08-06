"""Conformance laws: `.sampling_report()` (API.md, "Sampling diagnostics";
"Conformance Laws" > "Sampling diagnostics"; PLAN.md M10.6 gate).

`sampling_report` draws the **unconditioned** measure (before rejection) and
aggregates what happened — it reports, never repairs/reweights/suggests.
The laws:

- **Never rejects, never mutates.** Every row is backed by exactly `n`
  draws regardless of `acceptance_rate`; `space.fingerprint()` is unchanged;
  seed-reproducible.
- **`satisfied` is conditioned on `applicable`**, not on all draws.
- **Unknown-swallowing is visible**: an unguarded optional aggregate reports
  `applicable < 1.0`; the identical space with `.if_inactive()` reports
  `applicable == 1.0` — all else equal.
- **The funnel is visible and correct-by-spec** (Kleene rule 4):
  `acceptance_rate` matches the analytic value, and the *conditioned*
  (post-rejection) sample concentrates away from where the constraint was
  inapplicable — documented here beside rule 4, not "fixed" by this
  milestone.
- **Per-instance folding and template activity share the report's one
  denominator, `n`** (D-73).
- **`tighten_bounds` is off by default** and matches the reference sampler's
  own acceptance rate when turned on (D-74).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

import designspace as ds
from designspace import Space
from designspace.config import unflatten
from designspace.errors import SamplingError
from designspace.eval import instance_constraint_evals
from designspace.sample._sample import _draw_config

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))


def _build_delivery_routes() -> Space:
    return importlib.import_module("delivery_routes").build_space()  # type: ignore[no-any-return]


def _build_firmware_buffers() -> Space:
    return importlib.import_module("firmware_buffers").build_space()  # type: ignore[no-any-return]


def _build_solver_portfolio() -> Space:
    return importlib.import_module("solver_portfolio").build_space()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Fixture spaces
# ---------------------------------------------------------------------------


def _funnel_space() -> Space:
    """`n = integer(1,10)` uniform; `x = real(0,1).repeat(n)`;
    `require(x[2] > 0.99)`. Analytic: `applicable = P(n>=3) = 0.8`;
    `acceptance_rate = P(n<3)*1 + P(n>=3)*0.01 = 0.208`."""
    n = ds.param("n").integer(1, 10)
    x = ds.param("x").real(0.0, 1.0).repeat(n)
    return ds.space(n, x).require(ds.param("x[2]") > 0.99)


def _optional_aggregate_space(*, guard: bool) -> Space:
    """Two independently-optional lifted structs, each gated by a bool
    (`prior(weights=(0.4, 0.6))` so "on" is more likely than 50/50, giving
    a low naive-applicable fraction without being degenerate); one
    constraint over both sums, guarded or not by `.if_inactive(0)`."""
    item = ds.space(ds.param("size").integer(1, 64))
    agg_a = ds.param("a").field("size").sum()
    agg_b = ds.param("b").field("size").sum()
    if guard:
        agg_a = agg_a.if_inactive(0)
        agg_b = agg_b.if_inactive(0)
    return ds.space(
        ds.param("use_a").bool().prior(weights=(0.4, 0.6)),
        ds.param("use_b").bool().prior(weights=(0.4, 0.6)),
        ds.param("a").space(item).repeat(2).when(ds.param("use_a")),
        ds.param("b").space(item).repeat(2).when(ds.param("use_b")),
    ).require(agg_a + agg_b <= 512)


def _rare_but_always_satisfied_space() -> Space:
    """A constraint applicable in ~1% of draws and always satisfied there —
    the case `satisfied` must report as `1.0`, not `0.01`. `flag` is True
    with probability 0.01 (`weights=(99, 1)`); when False, `y` is inactive
    and the unguarded aggregate is Unknown (inapplicable); when True, `y`
    is a single real in `[0,1]`, so `sum(y) >= 0.0` always holds."""
    flag = ds.param("flag").bool().prior(weights=(99, 1))
    guarded = ds.param("y").real(0.0, 1.0).repeat(1).when(flag)
    return ds.space(flag, guarded).encourage(ds.param("y").sum() >= 0.0)


def _impossible_space() -> Space:
    return ds.space(ds.param("x").real(0.0, 1.0)).require(ds.param("x") > 2.0)


# ---------------------------------------------------------------------------
# Never rejects / never mutates / seed-reproducible
# ---------------------------------------------------------------------------


def test_never_rejects_every_row_backed_by_n_draws():
    space = _impossible_space()
    report = space.sampling_report(200, seed=0)
    assert report.n == 200
    assert report.acceptance_rate == 0.0
    (row,) = report.constraints
    assert row.applicable == 1.0  # `x > 2.0` is always Kleene-defined
    assert row.satisfied == 0.0


def test_never_rejects_where_sample_one_would_raise():
    space = _impossible_space()
    with pytest.raises(SamplingError):
        space.sample_one(seed=0)
    # The identical space, diagnosed instead of sampled: returns normally.
    report = space.sampling_report(50, seed=0)
    assert report.n == 50


def test_never_mutates_fingerprint_unchanged():
    space = _funnel_space()
    before = space.fingerprint()
    space.sampling_report(200, seed=0)
    assert space.fingerprint() == before


def test_seed_reproducible():
    space = _funnel_space()
    r1 = space.sampling_report(300, seed=42)
    r2 = space.sampling_report(300, seed=42)
    assert r1 == r2


@pytest.mark.parametrize("seed", [0, np.random.default_rng(0), None])
def test_seed_accepts_full_seed_type(seed):
    space = _funnel_space()
    report = space.sampling_report(20, seed=seed)
    assert report.n == 20


def test_n_must_be_positive():
    space = _funnel_space()
    with pytest.raises(TypeError):
        space.sampling_report(0)
    with pytest.raises(TypeError):
        space.sampling_report(-5)


# ---------------------------------------------------------------------------
# satisfied conditioned on applicable, not on all draws
# ---------------------------------------------------------------------------


def test_satisfied_conditioned_on_applicable_not_all_draws():
    space = _rare_but_always_satisfied_space()
    report = space.sampling_report(3000, seed=0)
    (row,) = report.constraints
    assert row.applicable == pytest.approx(0.01, abs=0.02)
    # Always satisfied whenever applicable -- 1.0, not ~0.01.
    assert row.satisfied == 1.0


# ---------------------------------------------------------------------------
# ConstraintReport.violation_rate: the polarity-resolved reading
# `ConstraintEval.violated` already gives the per-config case; `satisfied`
# alone is raw (a forbid/discourage names a *bad* state, so a high
# `satisfied` there is unhealthy, the opposite of encourage/require/bound).
# ---------------------------------------------------------------------------


def _one_row(space: Space, n: int = 400, seed: int = 0):
    report = space.sampling_report(n, seed=seed)
    (row,) = report.constraints
    return row


def test_forbid_violation_rate_equals_satisfied_directly():
    # forbid names the bad state -- satisfied *is* the violation fraction.
    space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") > 0.5)
    row = _one_row(space)
    assert not row.constraint.feasible_when_satisfied
    assert row.violation_rate == row.satisfied


def test_discourage_violation_rate_equals_satisfied_directly():
    space = ds.space(ds.param("x").real(0.0, 1.0)).discourage(ds.param("x") > 0.5)
    row = _one_row(space)
    assert not row.constraint.feasible_when_satisfied
    assert row.violation_rate == row.satisfied


def test_require_violation_rate_is_one_minus_satisfied():
    # require names the good state -- violated is the complement.
    space = ds.space(ds.param("x").real(0.0, 1.0)).encourage(ds.param("x") <= 0.7)
    row = _one_row(space)
    assert row.constraint.feasible_when_satisfied
    assert row.violation_rate == pytest.approx(1.0 - row.satisfied)


def test_impossible_require_is_always_violated():
    # The clearest case: a require that can never hold reports
    # violation_rate == 1.0 directly, not a satisfied == 0.0 a reader must
    # flip by hand.
    space = ds.space(ds.param("x").real(0.0, 1.0)).require(ds.param("x") > 2.0)
    row = _one_row(space)
    assert row.satisfied == 0.0
    assert row.violation_rate == 1.0


def test_encourage_violation_rate_is_one_minus_satisfied():
    space = ds.space(ds.param("x").real(0.0, 1.0)).encourage(ds.param("x") <= 0.7)
    row = _one_row(space)
    assert row.constraint.feasible_when_satisfied
    assert row.violation_rate == pytest.approx(1.0 - row.satisfied)


@pytest.mark.parametrize("verb", ["encourage", "discourage"])
def test_applicable_zero_gives_violation_rate_zero_regardless_of_polarity(verb):
    # Mirrors `ConstraintEval.violated`'s own "inapplicable is never
    # violated" (Kleene rule 4) and `satisfied`'s own "0.0 by convention,
    # never NaN" default -- extended consistently to both polarities, not
    # derived mechanically from `1 - satisfied` (which would read a
    # never-evaluated encourage/require row as "always violated").
    flag = ds.param("flag").bool().prior(weights=(1, 0))  # never True
    guarded = ds.param("y").real(0.0, 1.0).when(flag)
    space = ds.space(flag, guarded)
    space = getattr(space, verb)(ds.param("y") > 0.0)
    row = _one_row(space, n=50)
    assert row.applicable == 0.0
    assert row.satisfied == 0.0
    assert row.violation_rate == 0.0


# ---------------------------------------------------------------------------
# Unknown-swallowing
# ---------------------------------------------------------------------------


def test_unknown_swallowing_visible_without_guard():
    space = _optional_aggregate_space(guard=False)
    report = space.sampling_report(4000, seed=0)
    (row,) = report.constraints
    assert row.applicable == pytest.approx(0.35, abs=0.05)


def test_unknown_swallowing_fixed_by_if_inactive():
    space = _optional_aggregate_space(guard=True)
    report = space.sampling_report(4000, seed=0)
    (row,) = report.constraints
    assert row.applicable == 1.0


# ---------------------------------------------------------------------------
# The funnel: visible, correct-by-spec (Kleene rule 4), not "fixed"
# ---------------------------------------------------------------------------


def test_funnel_acceptance_rate_matches_analytic_value():
    space = _funnel_space()
    report = space.sampling_report(4000, seed=0)
    assert report.acceptance_rate == pytest.approx(0.208, abs=0.02)
    (row,) = report.constraints
    assert row.applicable == pytest.approx(0.8, abs=0.03)


def test_funnel_conditioned_sample_concentrates_on_short_lifts():
    """The pathology `sampling_report` exists to make visible: `sample()`'s
    post-rejection distribution concentrates ~96% of accepted configs on
    n <= 2, even though those account for only 20% of the *declared*
    measure -- because the constraint is simply inapplicable there and
    every such draw is accepted unconditionally (Kleene rule 4). Not a
    defect; API.md documents it beside rule 4."""
    space = _funnel_space()
    configs = space.sample_dicts(500, seed=1)
    short = sum(1 for c in configs if len(c.get("x", [])) <= 2)
    assert short / len(configs) > 0.9


# ---------------------------------------------------------------------------
# tighten_bounds (D-74)
# ---------------------------------------------------------------------------


def test_tighten_bounds_default_off_shows_declared_measure_cost():
    space = _build_firmware_buffers()
    report = space.sampling_report(2000, seed=0)
    assert report.acceptance_rate < 0.2
    bound_rows = [r for r in report.constraints if r.constraint.kind == "bound"]
    assert len(bound_rows) == 3
    assert all(r.satisfied < 0.9 for r in bound_rows)


def test_tighten_bounds_true_matches_reference_sampler():
    space = _build_firmware_buffers()
    report = space.sampling_report(2000, seed=0, tighten_bounds=True)
    assert report.acceptance_rate == 1.0
    bound_rows = [r for r in report.constraints if r.constraint.kind == "bound"]
    assert all(r.satisfied == 1.0 for r in bound_rows)


# ---------------------------------------------------------------------------
# Per-instance folding and activity template keys (D-73)
# ---------------------------------------------------------------------------


def test_per_draw_fold_matches_hand_computed_fraction():
    space = _build_delivery_routes()
    n = 500
    report = space.sampling_report(n, seed=0)
    # Rows are ordered `space.constraints` order, then element templates
    # (API.md, "Sampling diagnostics") -- the fixture declares 2 top-level
    # constraints and 1 per-element template on `stop`.
    assert len(report.constraints) == len(space.constraints) + 1
    row = report.constraints[-1]

    # Hand-computed per-draw fold over the same seed's draws, using the
    # sampler's own unconditioned draw primitive directly.
    rng = np.random.default_rng(0)
    applicable = 0
    satisfied = 0
    for _ in range(n):
        config, activity = _draw_config(space, rng, {})
        evals = instance_constraint_evals(space, config, activity)
        applicable_evals = [ce for ce in evals if ce.applicable]
        if applicable_evals:
            applicable += 1
            if all(ce.satisfied for ce in applicable_evals):
                satisfied += 1
    assert row.applicable == pytest.approx(applicable / n)
    assert row.satisfied == pytest.approx(satisfied / applicable if applicable else 0.0)


def test_activity_keys_exactly_space_params():
    space = _build_solver_portfolio()
    report = space.sampling_report(1000, seed=0)
    assert set(report.activity) == set(space.params)
    assert all(0.0 <= v <= 1.0 for v in report.activity.values())
    # workers is gated by use_ensemble, prior 1:1 -> P(active) ~ 0.5
    assert report.activity["workers"] == pytest.approx(0.5, abs=0.1)
    # workers[].timeout_s active only when workers is active AND that
    # instance was materialized (n_workers >= 1) -- strictly <= workers'.
    assert report.activity["workers[].timeout_s"] <= report.activity["workers"] + 1e-9


def test_solver_portfolio_budget_forbid_stays_fully_applicable():
    """Corpus reuse (PLAN.md M10.6: "Corpus: reuse solver_portfolio"): the
    fixture's own `.if_inactive(0)`-guarded budget forbid stays
    `applicable == 1.0` -- the naive (unguarded) form would not, by the
    same law as `test_unknown_swallowing_visible_without_guard` above."""
    space = _build_solver_portfolio()
    report = space.sampling_report(2000, seed=0)
    # Both fixture forbids -- the solver count and the guarded budget --
    # have no partial-eval-only Unknown source, so both stay fully
    # applicable across every draw.
    assert len(report.constraints) == 2
    assert all(r.applicable == 1.0 for r in report.constraints)


# ---------------------------------------------------------------------------
# Acceptance agreement with validate()
# ---------------------------------------------------------------------------


def test_acceptance_rate_agrees_with_validate():
    space = _build_delivery_routes()
    n = 500
    rng = np.random.default_rng(3)
    valid_count = 0
    for _ in range(n):
        config, _activity = _draw_config(space, rng, {})
        if space.is_feasible(unflatten(config, space)):
            valid_count += 1
    report = space.sampling_report(n, seed=3)
    assert report.acceptance_rate == pytest.approx(valid_count / n)
