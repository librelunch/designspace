"""Corpus: `pump_configurator`, a scripted driver loop.

The loop runs over `next_assignable` and `remaining_domain`.
"""

from __future__ import annotations

from pump_configurator import build_space

from designspace import Space
from designspace.ir import (
    IntegerRemaining,
    PermutationRemaining,
    RealRemaining,
    SubsetRemaining,
    ValueRemaining,
)


def _pick_conservative_value(rd):
    """The most conservative legal value for each descriptor kind --
    exactly enough to keep this fixture's scripted loop landing on a
    feasible config despite `remaining_domain`'s soundness-not-completeness
    (the compound seal/certification forbid is never narrowed away)."""
    if isinstance(rd, RealRemaining):
        return rd.lo if rd.lo_inclusive else rd.lo + 1e-6
    if isinstance(rd, IntegerRemaining):
        return rd.lo
    if isinstance(rd, ValueRemaining):
        return rd.values[0]
    if isinstance(rd, SubsetRemaining):
        chosen = list(rd.forced_in)
        for item in rd.free:
            if len(chosen) >= rd.min_size:
                break
            chosen.append(item)
        return chosen
    if isinstance(rd, PermutationRemaining):
        return list(rd.items)
    raise TypeError(rd)  # pragma: no cover


def test_resolves():
    space = build_space()
    assert space.n_params == 6


def test_next_assignable_gates_bound_coupled_params_behind_their_dependency():
    """The coincidence law (`next_assignable == [] <=> is_complete`) can't
    catch an over-inclusive readiness filter -- a bound-coupled param must
    not be offered before the param its bound references is set."""
    space = build_space()
    na = space.next_assignable({})
    assert "impeller_diameter_mm" not in na  # gated behind flow_rate_lpm
    assert "max_pressure_bar" not in na  # gated behind num_stages
    assert "flow_rate_lpm" in na
    assert "num_stages" in na

    na_after_flow = space.next_assignable({"flow_rate_lpm": 150.0})
    assert "impeller_diameter_mm" in na_after_flow
    assert "max_pressure_bar" not in na_after_flow  # still gated behind num_stages


def test_scripted_driver_loop_reaches_a_valid_config():
    space = build_space()
    config: dict = {}
    steps = 0
    while not space.is_complete(config):
        steps += 1
        assert steps <= 20  # progress guarantee -- next_assignable must never stall
        ready = space.next_assignable(config)
        assert ready, "next_assignable must be non-empty while incomplete (coincidence law)"
        path = ready[0]
        rd = space.remaining_domain(path, config)
        assert rd is not None
        config[path] = _pick_conservative_value(rd)

    assert space.next_assignable(config) == []
    result = space.validate(config)
    assert result.valid, (config, result)


def test_remaining_domain_excludes_discontinued_seal():
    space = build_space()
    rd = space.remaining_domain("seal_type", {})
    assert rd is not None
    assert "packing" not in rd.values
    assert set(rd.values) == {"mechanical", "magnetic"}


def test_remaining_domain_soundness_over_many_valid_configs():
    """Every value a *feasible* config actually uses must lie within
    `remaining_domain`'s report at the point it was assignable -- run the
    driver loop from many different starting picks (via seeded sampling
    filtered to valid configs) and check the bound-coupled params."""
    space = build_space()
    checked = 0
    for cfg in space.sample_dicts(300, seed=0):
        if not space.validate(cfg).valid:
            continue
        checked += 1
        rd_impeller = space.remaining_domain(
            "impeller_diameter_mm", {"flow_rate_lpm": cfg["flow_rate_lpm"]}
        )
        assert rd_impeller is not None
        assert rd_impeller.lo <= cfg["impeller_diameter_mm"] <= rd_impeller.hi

        rd_pressure = space.remaining_domain("max_pressure_bar", {"num_stages": cfg["num_stages"]})
        assert rd_pressure is not None
        assert rd_pressure.lo <= cfg["max_pressure_bar"] <= rd_pressure.hi
    assert checked > 0


def test_bound_origin_and_forbid_reduce_together():
    space = build_space()
    rd = space.remaining_domain("impeller_diameter_mm", {"flow_rate_lpm": 150.0})
    assert rd is not None
    assert (rd.lo, rd.hi) == (20.0, 150.0)


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=1):
        assert restored.validate(cfg).valid
