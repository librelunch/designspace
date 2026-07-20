"""Corpus: `delivery_routes` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from delivery_routes import TOTAL_DWELL_BUDGET_MIN, build_space

from designspace.build._space import Space


def test_resolves():
    space = build_space()
    assert space.n_params == 4  # n_stops, stops, stops[].location, stops[].dwell_min
    assert len(space.params["stops"].domain.element_constraints) == 1
    assert len(space.constraints) == 2  # the aggregate budget + the root-level forbid


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_every_route_starts_at_the_depot():
    space = build_space()
    for cfg in space.sample_dicts(100, seed=1):
        assert cfg["stops"][0]["location"] == 0


def test_depot_stops_are_quick():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        for stop in cfg["stops"]:
            if stop["location"] == 0:
                assert stop["dwell_min"] <= 10


def test_total_dwell_within_budget_under_reject_soft():
    # The budget is a `.constrain()` (declared, not feasibility-affecting)
    # per API_v3.md: ".constrain() ... never affects feasibility or the
    # reference measure" — the default sampler may exceed it; only
    # `reject_soft=True` rejects on it.
    space = build_space()
    for cfg in space.sample_dicts(200, seed=3, reject_soft=True):
        assert sum(s["dwell_min"] for s in cfg["stops"]) <= TOTAL_DWELL_BUDGET_MIN


def test_default_sampling_does_not_reject_on_the_declared_budget():
    space = build_space()
    configs = space.sample_dicts(200, seed=4)
    assert any(
        sum(s["dwell_min"] for s in cfg["stops"]) > TOTAL_DWELL_BUDGET_MIN for cfg in configs
    )


def test_per_instance_constraint_violation_is_localized():
    space = build_space()
    cfg = {
        "n_stops": 2,
        "stops": [{"location": 0, "dwell_min": 20}, {"location": 5, "dwell_min": 10}],
    }
    result = space.validate(cfg)
    assert not result.valid
    instance_evals = [ce for ce in result.constraint_evals if ce.instance_path is not None]
    assert len(instance_evals) == 2
    violated = [ce for ce in instance_evals if ce.instance_path == "stops[0]"]
    assert len(violated) == 1
    assert violated[0].satisfied is True  # forbid's own predicate held: violated

    unviolated = [ce for ce in instance_evals if ce.instance_path == "stops[1]"]
    assert unviolated[0].satisfied is False


def test_out_of_range_instance_forbid_is_inapplicable_when_n_stops_is_zero_length_impossible():
    # n_stops has a lower bound of 1, so stops[0] is always in range —
    # confirm the root-level instance-path forbid still evaluates normally.
    space = build_space()
    result = space.validate({"n_stops": 1, "stops": [{"location": 0, "dwell_min": 5}]})
    assert result.valid


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=5):
        assert restored.validate(cfg).valid
