"""Corpus: `annealing_schedule`, end-to-end.

Resolve, sample 200, validate all, round-trip, plus the program-type
surface this fixture was built for.
"""

from __future__ import annotations

from annealing_schedule import DEFAULT_ACCEPTANCE, DEFAULT_SCHEDULE, build_space

from designspace import Space


def test_resolves():
    space = build_space()
    assert space.n_params == 6


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_schedule_only_present_when_active():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        assert ("schedule" in cfg) == cfg["use_custom_schedule"]
        if "schedule" in cfg:
            assert cfg["schedule"] == DEFAULT_SCHEDULE


def test_acceptance_predicate_always_present_and_constant():
    space = build_space()
    for cfg in space.sample_dicts(50, seed=2):
        assert cfg["acceptance_predicate"] == DEFAULT_ACCEPTANCE


def test_min_temp_below_initial_temp_constraint_holds():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=3):
        assert cfg["min_temp"] < cfg["initial_temp"]


def test_has_nongenerative_params():
    assert build_space().has_nongenerative_params is True


def test_round_trips():
    space = build_space()
    doc = space.to_json()
    restored = Space.from_json(doc)
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
