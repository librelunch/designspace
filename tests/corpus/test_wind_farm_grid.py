"""Corpus: `wind_farm_grid` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from wind_farm_grid import ADJACENT_PAIRS, build_space

from designspace.build._space import Space


def test_resolves():
    space = build_space()
    assert space.n_params == 1
    assert len(space.constraints) == len(ADJACENT_PAIRS)
    assert all(c.hard for c in space.constraints)


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_no_adjacent_pair_both_selected():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        selected = set(cfg["turbines"])
        for a, b in ADJACENT_PAIRS:
            assert not (a in selected and b in selected)


def test_size_bounds_respected():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        assert 1 <= len(cfg["turbines"]) <= 4


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=3):
        assert restored.validate(cfg).valid
