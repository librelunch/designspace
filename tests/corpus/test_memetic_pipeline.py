"""Corpus: `memetic_pipeline` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from memetic_pipeline import MAX_OPS, MIN_OPS, build_space


def test_resolves():
    space = build_space()
    # n_ops, pipeline, pipeline[].mutation.rate, pipeline[].local_search.iters
    assert space.n_params == 4


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_length_within_declared_bounds():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        assert MIN_OPS <= len(cfg["pipeline"]) <= MAX_OPS
        assert cfg["n_ops"] == len(cfg["pipeline"])


def test_every_pipeline_has_at_least_one_local_search_step():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        n_local_search = sum(
            1 for op in cfg["pipeline"] if isinstance(op, dict) and "local_search" in op
        )
        assert n_local_search >= 1


def test_bare_and_parameterized_forms_coexist():
    space = build_space()
    saw_bare = False
    saw_parameterized = False
    for cfg in space.sample_dicts(50, seed=3):
        for op in cfg["pipeline"]:
            if isinstance(op, str):
                saw_bare = True
            else:
                saw_parameterized = True
    assert saw_bare
    assert saw_parameterized


def test_count_of_missing_local_search_is_infeasible():
    space = build_space()
    cfg = {"n_ops": 3, "pipeline": ["shuffle", "crossover", "shuffle"]}
    result = space.validate(cfg)
    assert not result.valid


def test_count_of_counts_variants_not_payload_equality():
    space = build_space()
    cfg = {
        "n_ops": 3,
        "pipeline": [
            {"local_search": {"iters": 5}},
            {"local_search": {"iters": 99}},
            "shuffle",
        ],
    }
    result = space.validate(cfg)
    assert result.valid
