"""Corpus: `sat_solver` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from sat_solver import build_space


def test_resolves():
    space = build_space()
    assert space.n_params == 4  # solver, solver.cdcl.restart_strategy, verbosity, timeout_s


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_debug_verbosity_requires_long_timeout():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        if cfg["verbosity"] == "debug":
            assert cfg["timeout_s"] >= 60


def test_cdcl_payload_only_present_for_cdcl():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        solver = cfg["solver"]
        if solver == "dpll":
            continue
        assert set(solver.keys()) == {"cdcl"}
        assert set(solver["cdcl"].keys()) == {"restart_strategy"}
