"""Corpus: `job_shop` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from job_shop import JOBS, build_space


def test_resolves():
    space = build_space()
    assert space.n_params == 1


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_schedule_is_a_full_permutation():
    space = build_space()
    for cfg in space.sample_dicts(100, seed=1):
        assert sorted(cfg["schedule"]) == sorted(JOBS)


def test_job_a_never_after_job_e():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=2):
        order = cfg["schedule"]
        assert order.index("job_a") <= order.index("job_e")
