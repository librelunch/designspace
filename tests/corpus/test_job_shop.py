"""Corpus: `job_shop` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

import pytest
from job_shop import JOBS, build_space

from designspace import Space
from designspace.errors import ResolutionError


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


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=3):
        assert restored.validate(cfg).valid


# -- freeze-ablation (M9.5, PLAN.md corpus table; DECISIONS.md D-50) --------
#
# `build_space()` itself stays untouched (byte-identical known-answer
# vector) — these operate on a *derived* frozen space in-test.


def test_freeze_schedule_to_a_fixed_deadline_satisfying_order():
    space = build_space()
    order = list(JOBS)  # job_a first, job_e last -- satisfies the deadline forbid
    frozen = space.freeze(schedule=order)
    for cfg in frozen.sample_dicts(50, seed=4):
        assert cfg["schedule"] == order


def test_freeze_schedule_to_a_deadline_violating_order_raises():
    # The deadline forbid references only "schedule" -- validate_param
    # (reused by freeze's own value check) already catches this at freeze
    # time, the same way an out-of-bounds real/integer freeze value does.
    violating = ["job_e", "job_a", "job_b", "job_c", "job_d"]  # job_a after job_e
    space = build_space()
    with pytest.raises(ResolutionError):
        space.freeze(schedule=violating)
