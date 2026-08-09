"""Corpus: `memetic_pipeline` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

import pytest
from memetic_pipeline import MAX_OPS, MIN_OPS, build_space

from designspace import Space


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


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=4):
        assert restored.validate(cfg).valid


# -- freeze-ablation: list-of-choice, the union pruning rule -----------------
#
# `build_space()` itself stays untouched -- these operate on a *derived*
# frozen space in-test.


def test_freeze_pipeline_prunes_the_variant_no_instance_selects():
    space = build_space()
    # Satisfies the fixture's own "at least one local_search" forbid.
    frozen = space.freeze(pipeline=["shuffle", "local_search", "crossover"])
    assert "pipeline[].mutation.rate" not in frozen.params
    assert "pipeline[].local_search.iters" in frozen.params
    assert frozen.params["pipeline"].domain.count == 3
    # n_ops (the count's original driver) stays free, unpinned.
    assert frozen.params["n_ops"].domain.lo == MIN_OPS
    assert frozen.params["n_ops"].domain.hi == MAX_OPS


def test_freeze_pipeline_union_rule_keeps_both_payload_variants_when_both_used():
    space = build_space()
    frozen = space.freeze(pipeline=["mutation", "local_search"])
    # Each instance selects only one payload-bearing variant, but the
    # union across the whole call uses both -- neither is pruned.
    assert "pipeline[].mutation.rate" in frozen.params
    assert "pipeline[].local_search.iters" in frozen.params
    for cfg in frozen.sample_dicts(30, seed=10):
        assert set(cfg["pipeline"][0]) == {"mutation"}
        assert set(cfg["pipeline"][1]) == {"local_search"}


# -- DataFrame output: a lifted choice gives List(Struct{variant, ...}) ------


@pytest.mark.requires_polars
def test_dataframe_pipeline_is_list_of_variant_struct():
    import polars as pl

    space = build_space()
    df = space.sample(40, seed=8)
    dt = df.schema["pipeline"]
    assert isinstance(dt, pl.List)
    inner = dt.inner
    assert isinstance(inner, pl.Struct)
    assert {f.name for f in inner.fields} == {"variant", "mutation", "local_search"}

    dicts = space.sample_dicts(40, seed=8)
    saw_bare = False
    saw_parameterized = False
    for i in range(40):
        row_ops = df["pipeline"][i].to_list()
        dict_ops = dicts[i]["pipeline"]
        assert len(row_ops) == len(dict_ops)
        for row_op, dict_op in zip(row_ops, dict_ops, strict=True):
            if isinstance(dict_op, str):
                saw_bare = True
                assert row_op["variant"] == dict_op
                assert row_op["mutation"] is None
                assert row_op["local_search"] is None
            else:
                saw_parameterized = True
                (variant_name, payload) = next(iter(dict_op.items()))
                assert row_op["variant"] == variant_name
                assert row_op[variant_name] == payload
                other = "mutation" if variant_name == "local_search" else "local_search"
                assert row_op[other] is None
    assert saw_bare
    assert saw_parameterized
