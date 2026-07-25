"""Corpus: `sat_solver` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from sat_solver import build_space

from designspace.build._space import Space


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


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=3):
        assert restored.validate(cfg).valid


# -- freeze-ablation (M8, PLAN.md corpus table; DECISIONS.md D-40) ----------
#
# `build_space()` itself stays untouched (byte-identical known-answer
# vector) — these operate on a *derived* frozen space in-test.


def test_freeze_long_timeout_keeps_debug_feasible():
    space = build_space()
    frozen = space.freeze(timeout_s=120)
    for cfg in frozen.sample_dicts(100, seed=5):
        assert cfg["timeout_s"] == 120
    assert frozen.is_feasible({"solver": "dpll", "verbosity": "debug", "timeout_s": 120})


def test_freeze_short_timeout_ablates_debug_verbosity():
    # 30 < 60, so the still-active "debug requires timeout_s >= 60" forbid
    # now excludes "debug" entirely -- the sampler never draws it.
    space = build_space()
    frozen = space.freeze(timeout_s=30)
    for cfg in frozen.sample_dicts(100, seed=6):
        assert cfg["timeout_s"] == 30
        assert cfg["verbosity"] != "debug"
    assert not frozen.is_feasible({"solver": "dpll", "verbosity": "debug", "timeout_s": 30})


def test_freeze_verbosity_ablation_forces_long_timeout():
    space = build_space()
    frozen = space.freeze(verbosity="debug")
    for cfg in frozen.sample_dicts(100, seed=7):
        assert cfg["verbosity"] == "debug"
        assert cfg["timeout_s"] >= 60


# -- freeze-ablation: choice (M9.5, PLAN.md corpus table; DECISIONS.md D-50) --
#
# `build_space()` itself stays untouched -- these operate on a *derived*
# frozen space in-test (same D-40 discipline as the M8 freeze-ablation
# tests above, extended to this milestone's container-freeze completion).


def test_freeze_solver_to_bare_variant_prunes_cdcl_payload():
    space = build_space()
    frozen = space.freeze(solver="dpll")
    assert "solver.cdcl.restart_strategy" not in frozen.params
    assert frozen.n_params == 3  # solver, verbosity, timeout_s
    assert all(cfg["solver"] == "dpll" for cfg in frozen.sample_dicts(50, seed=8))


def test_freeze_solver_to_payload_variant_keeps_it_freely_sampled():
    space = build_space()
    frozen = space.freeze(solver="cdcl")
    assert "solver.cdcl.restart_strategy" in frozen.params
    configs = frozen.sample_dicts(50, seed=9)
    strategies = {cfg["solver"]["cdcl"]["restart_strategy"] for cfg in configs}
    assert strategies == {"luby", "geometric"}
