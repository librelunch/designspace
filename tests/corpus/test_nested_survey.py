"""Corpus: `nested_survey`, end-to-end, over a relocated param-driven count.

The assertions that matter tie a realized list length to its count param's
value through each relocation route. Where relocation misses a count
expression, every such list comes back `[]` while the count param samples a
perfectly good positive integer, and nothing raises.
"""

from __future__ import annotations

from nested_survey import MAX_TOTAL_MINUTES, build_space

from designspace import Space


def test_resolves() -> None:
    space = build_space()
    assert set(space.params) == {
        "n_repeats",
        "core",
        "core.n_items",
        "core.items",
        "core.items[].difficulty",
        "core.items[].minutes",
        "mode",
        "mode.deep.n_probes",
        "mode.deep.probes",
        "mode.deep.reps",
    }
    # The count references must name the *relocated* params.
    assert space.dependency_graph["core.items"] == frozenset({"core.n_items"})
    assert space.dependency_graph["mode.deep.probes"] >= frozenset({"mode.deep.n_probes"})
    # ... and the cross-scope one still names the enclosing param.
    assert "n_repeats" in space.dependency_graph["mode.deep.reps"]


def test_realized_lengths_match_their_count_params() -> None:
    space = build_space()
    for config in space.sample_dicts(200, seed=0):
        core = config["core"]
        assert len(core["items"]) == core["n_items"]
        assert core["n_items"] >= 1  # never the silent zero-length collapse

        mode = config["mode"]
        if isinstance(mode, dict):
            deep = mode["deep"]
            assert len(deep["probes"]) == deep["n_probes"]
            assert len(deep["reps"]) == config["n_repeats"]


def test_per_item_constraint_still_bites_after_relocation() -> None:
    space = build_space()
    for config in space.sample_dicts(200, seed=1):
        for item in config["core"]["items"]:
            assert not (item["difficulty"] == 1 and item["minutes"] > 4)


def test_sample_and_validate_all() -> None:
    space = build_space()
    configs = space.sample_dicts(200, seed=2)
    assert len(configs) == 200
    for config in configs:
        result = space.validate(config)
        assert result.valid, (config, result.param_errors)


def test_violating_config_is_rejected() -> None:
    """The per-item forbid decides feasibility, after relocation as before."""
    space = build_space()
    config = {
        "n_repeats": 1,
        "core": {
            "n_items": 2,
            "items": [{"difficulty": 1, "minutes": 8}, {"difficulty": 3, "minutes": 2}],
        },
        "mode": "screening",
    }
    result = space.validate(config)
    assert result.valid is False
    violated = [e for e in result.constraint_evals if e.violated]
    assert [e.instance_path for e in violated] == ["core.items[0]"]


def test_soft_budget_is_reported_not_enforced() -> None:
    space = build_space()
    space_: Space = space
    reports = space_.sampling_report(n=200, seed=3)
    budget = [r for r in reports.constraints if "budget" in r.constraint.tags]
    assert len(budget) == 1
    # Applicable on every draw: the projection reads an always-active lift.
    assert budget[0].applicable == 1.0
    assert reports.acceptance_rate > 0.0
    assert MAX_TOTAL_MINUTES > 0
