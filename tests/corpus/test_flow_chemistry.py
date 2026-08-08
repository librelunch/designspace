"""Corpus: `flow_chemistry` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

import pytest
from flow_chemistry import build_space

from designspace import Space
from designspace.errors import ResolutionError


def test_resolves():
    space = build_space()
    assert space.n_params == 2


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_oxidizer_implies_acid():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        if "oxidizer" in cfg["reagents"]:
            assert "acid" in cfg["reagents"]


def test_catalyst_implies_high_temperature():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        if "catalyst" in cfg["reagents"]:
            assert cfg["temperature_c"] > 50.0


def test_budget_constraint_is_evaluated_not_enforced():
    space = build_space()
    configs = space.sample_dicts(200, seed=3)
    evals = [
        e
        for cfg in configs
        for e in space.evaluate_constraints(cfg)
        if "budget" in e.constraint.tags
    ]
    assert len(evals) == 200
    # encourage() never affects feasibility, even when violated.
    assert any(not e.satisfied for e in evals)
    assert all(space.validate(cfg).valid for cfg in configs)


def test_subset_size_bounds_respected():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=4):
        assert 1 <= len(cfg["reagents"]) <= 4


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=5):
        assert restored.validate(cfg).valid


# -- freeze-ablation ---------------------------------------------------------
#
# `build_space()` itself stays untouched (byte-identical known-answer
# vector); each operates on a derived frozen space, built in-test.


def test_freeze_reagents_to_a_fixed_membership():
    space = build_space()
    frozen = space.freeze(reagents=["acid", "oxidizer"])
    for cfg in frozen.sample_dicts(100, seed=6):
        assert sorted(cfg["reagents"]) == ["acid", "oxidizer"]


def test_freeze_reagents_without_acid_raises():
    # "oxidizer implies acid" is a hard forbid referencing only "reagents"
    # -- validate_param (reused by freeze's own value check) already
    # catches this at freeze time, the same way an out-of-bounds real/
    # integer freeze value already does (TestFreeze.test_invalid_value_raises).
    space = build_space()
    with pytest.raises(ResolutionError):
        space.freeze(reagents=["oxidizer"])
