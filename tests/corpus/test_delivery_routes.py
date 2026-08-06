"""Corpus: `delivery_routes` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from delivery_routes import TOTAL_DWELL_BUDGET_MIN, build_space

from designspace import Space


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
    # The budget is a `.encourage()` (declared, not feasibility-affecting)
    # per API.md: ".encourage() ... never affects feasibility or the
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


# -- freeze-ablation: list-of-struct, dynamic count (M9.5, PLAN.md corpus
# table; DECISIONS.md D-50) --------------------------------------------------
#
# `build_space()` itself stays untouched -- these operate on a *derived*
# frozen space in-test. Wide integer ranges (location 0-9, dwell_min 5-30)
# make naive-rejection sampling of an exact multi-field pin unreliable
# within the sampler's fixed retry budget, so these check structure and a
# single deterministic `.validate()` call rather than `sample_dicts()`.


def test_freeze_stops_to_a_concrete_route():
    space = build_space()
    fixed = [{"location": 0, "dwell_min": 5}, {"location": 3, "dwell_min": 20}]
    frozen = space.freeze(stops=fixed)
    domain = frozen.params["stops"].domain
    assert domain.count == 2
    assert domain.list_default == fixed
    # "n_stops" drove "stops"'s count before freezing; freeze narrows only
    # the list it's given, leaving n_stops itself free and unpinned.
    assert frozen.params["n_stops"].domain.lo == 1
    assert frozen.params["n_stops"].domain.hi == 5
    assert frozen.validate({"n_stops": 2, "stops": fixed}).valid


def test_freeze_stops_rejects_a_config_violating_the_fixed_route():
    space = build_space()
    fixed = [{"location": 0, "dwell_min": 5}, {"location": 3, "dwell_min": 20}]
    frozen = space.freeze(stops=fixed)
    other = [{"location": 0, "dwell_min": 9}, {"location": 3, "dwell_min": 20}]
    assert not frozen.validate({"n_stops": 2, "stops": other}).valid


# -- DataFrame output (M10): dynamic-count struct lift -> List(Struct) -------


def test_dataframe_stops_is_dynamic_list_of_struct():
    import polars as pl

    space = build_space()
    df = space.sample(30, seed=7)
    dt = df.schema["stops"]
    assert isinstance(dt, pl.List)
    inner = dt.inner
    assert isinstance(inner, pl.Struct)
    assert {f.name for f in inner.fields} == {"location", "dwell_min"}

    dicts = space.sample_dicts(30, seed=7)
    for i in range(30):
        row_stops = df["stops"][i].to_list()
        dict_stops = dicts[i]["stops"]
        assert len(row_stops) == len(dict_stops) == df["n_stops"][i]
        for row_stop, dict_stop in zip(row_stops, dict_stops, strict=True):
            assert row_stop["location"] == dict_stop["location"]
            assert row_stop["dwell_min"] == dict_stop["dwell_min"]
