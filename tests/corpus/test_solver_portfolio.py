"""Corpus: `solver_portfolio` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from solver_portfolio import SOLVERS, TOTAL_TIMEOUT_BUDGET_S, build_space

from designspace.build._space import Space


def test_resolves():
    space = build_space()
    # 4 solver flags + use_ensemble + n_workers + workers + workers[].timeout_s
    assert space.n_params == 8


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_at_least_one_solver_enabled():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        assert any(cfg[f"use_{name}"] for name in SOLVERS)


def test_workers_absent_when_ensemble_disabled():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        if not cfg["use_ensemble"]:
            assert "workers" not in cfg


def test_active_empty_worker_pool_vs_inactive_lift():
    """The spec's own worked example, applied: `.if_inactive(0)` coalesces
    the *inactive* case to a concrete value, so both the inactive-lift and
    the active-empty-list branches end up with an applicable, satisfied
    (not-violated) forbid — but for different underlying reasons."""
    space = build_space()
    base = {
        "use_cplex": True,
        "use_gurobi": False,
        "use_glpk": False,
        "use_heuristic": False,
    }

    inactive = {**base, "use_ensemble": False, "n_workers": 0}
    active_empty = {**base, "use_ensemble": True, "n_workers": 0, "workers": []}

    for cfg in (inactive, active_empty):
        result = space.validate(cfg)
        assert result.valid
        budget_ce = next(ce for ce in result.constraint_evals if ce.constraint.expr.kind == "gt")
        assert budget_ce.applicable is True
        assert budget_ce.satisfied is False  # "> budget" not satisfied: not violated


def test_over_budget_active_pool_is_infeasible():
    space = build_space()
    workers = [{"timeout_s": 3600} for _ in range(3)]  # 10800s > 7200s budget
    cfg = {
        "use_cplex": True,
        "use_gurobi": False,
        "use_glpk": False,
        "use_heuristic": False,
        "use_ensemble": True,
        "n_workers": 3,
        "workers": workers,
    }
    result = space.validate(cfg)
    assert not result.valid
    assert sum(w["timeout_s"] for w in workers) > TOTAL_TIMEOUT_BUDGET_S


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=4):
        assert restored.validate(cfg).valid
