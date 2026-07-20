"""Corpus: `firmware_buffers` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from firmware_buffers import TOTAL_HI, TOTAL_LO, build_space

from designspace.build._space import Space


def test_resolves():
    space = build_space()
    assert space.n_params == 4
    assert space.params["buf_a"].domain.hi == TOTAL_HI
    assert space.params["buf_b"].domain.hi == TOTAL_HI - 1
    assert space.params["buf_c"].domain.hi == TOTAL_HI - 2


def test_three_bound_origin_constraints():
    space = build_space()
    bound_constraints = [c for c in space.constraints if c.origin == "bound"]
    assert len(bound_constraints) == 3
    assert all(c.hard for c in bound_constraints)


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_every_sample_respects_the_chained_budget():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        assert TOTAL_LO <= cfg["total_ram"] <= TOTAL_HI
        assert 1 <= cfg["buf_a"] <= cfg["total_ram"]
        assert 1 <= cfg["buf_b"] <= cfg["total_ram"] - cfg["buf_a"]
        assert 0 <= cfg["buf_c"] <= cfg["buf_b"] - 1


def test_bound_origin_margin_is_remaining_headroom():
    space = build_space()
    cfg = {"total_ram": 8192, "buf_a": 2000, "buf_b": 1000, "buf_c": 0}
    result = space.validate(cfg)
    assert result.valid
    bound_evals = [ce for ce in result.constraint_evals if ce.constraint.origin == "bound"]
    assert len(bound_evals) == 3
    margins = sorted(ce.margin for ce in bound_evals)
    # buf_a <= total_ram (margin 6192), buf_b <= total_ram - buf_a (margin 5192),
    # buf_c <= buf_b - 1 (margin 999).
    assert margins == [999, 5192, 6192]


def test_overrun_is_infeasible():
    space = build_space()
    cfg = {"total_ram": 8192, "buf_a": 9000, "buf_b": 1000, "buf_c": 0}
    result = space.validate(cfg)
    assert not result.valid


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=2):
        assert restored.validate(cfg).valid
