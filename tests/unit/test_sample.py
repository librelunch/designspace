"""M2 gate: `.sample_one()` / `.sample_dicts()` (API.md, "Sampling and
Generativity").

Row 26 (V): sampling retry exhaustion, naming the dominant constraint(s).
"""

from __future__ import annotations

import numpy as np
import pytest

import designspace as ds
from designspace.errors import SamplingError


class TestSampleOneBasics:
    def test_produces_a_value_per_active_param(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0),
            ds.param("n").integer(0, 10),
            ds.param("c").categorical("a", "b"),
            ds.param("flag").bool(),
        )
        cfg = space.sample_one(seed=0)
        assert set(cfg.keys()) == {"x", "n", "c", "flag"}
        assert 0.0 <= cfg["x"] <= 1.0
        assert 0 <= cfg["n"] <= 10
        assert cfg["c"] in ("a", "b")
        assert isinstance(cfg["flag"], bool)

    def test_inactive_param_is_absent(self):
        space = ds.space(
            ds.param("flag").bool().prior(weights=[1.0, 0.0]),  # always False
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        cfg = space.sample_one(seed=0)
        assert "x" not in cfg
        assert cfg["flag"] is False

    def test_seed_reproducibility(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("n").integer(0, 100))
        cfg1 = space.sample_one(seed=42)
        cfg2 = space.sample_one(seed=42)
        assert cfg1 == cfg2

    def test_generator_seed_accepted(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        rng = np.random.default_rng(1)
        cfg = space.sample_one(seed=rng)
        assert 0.0 <= cfg["x"] <= 1.0

    def test_sample_always_satisfies_forbids(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") > 0.5)
        for i in range(50):
            cfg = space.sample_one(seed=i)
            assert cfg["x"] <= 0.5

    def test_result_always_validates(self):
        space = ds.space(
            ds.param("x").real(1e-5, 1.0).log_scale(),
            ds.param("n").integer(1, 8),
        ).forbid(ds.param("n") > 6)
        for i in range(20):
            cfg = space.sample_one(seed=i)
            assert space.validate(cfg).valid


class TestSampleDicts:
    def test_returns_n_configs(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        batch = space.sample_dicts(10, seed=0)
        assert len(batch) == 10

    def test_reproducible_and_independent_draws(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        batch1 = space.sample_dicts(5, seed=0)
        batch2 = space.sample_dicts(5, seed=0)
        assert batch1 == batch2
        assert len({cfg["x"] for cfg in batch1}) == 5  # independent draws, not repeats


class TestRejectSoft:
    def test_reject_soft_false_ignores_declared_constraints(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).constrain(ds.param("x") <= 0.1)
        # With reject_soft=False (default), draws violating the declared
        # constraint are still accepted.
        draws = [space.sample_one(seed=i, reject_soft=False) for i in range(30)]
        assert any(cfg["x"] > 0.1 for cfg in draws)

    def test_reject_soft_true_also_rejects_declared_violations(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).constrain(ds.param("x") <= 0.5)
        for i in range(30):
            cfg = space.sample_one(seed=i, reject_soft=True)
            assert cfg["x"] <= 0.5


class TestRow26RetryExhaustion:
    def test_impossible_forbid_raises_sampling_error(self):
        # x is real(0, 1); forbidding x <= 1 forbids every possible draw.
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") <= 1.0)
        with pytest.raises(SamplingError):
            space.sample_one(seed=0)

    def test_retry_exhaustion_names_dominant_constraint(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") <= 1.0)
        with pytest.raises(SamplingError, match="le"):
            space.sample_one(seed=0)

    def test_unsatisfiable_subset_size_bounds_raise_sampling_error(self):
        # Every item independently included w.p. 0.5; requiring exactly the
        # full universe (min_size == max_size == len(items)) is reachable
        # but vanishingly unlikely for a large universe -- pin it to
        # something truly impossible instead: min_size > max_size is
        # already a resolution error, so use min_size == max_size == 1 with
        # weights forcing every item's inclusion probability to 0.
        space = ds.space(
            ds.param("s").subset(("a", "b"), min_size=1, max_size=1).prior(weights=[0.0, 0.0])
        )
        with pytest.raises(SamplingError):
            space.sample_one(seed=0)


class TestChoiceSubsetPermutationSampling:
    def test_choice_draws_a_declared_variant(self):
        space = ds.space(
            ds.param("algo").choice(
                "linear",
                svm=ds.space(ds.param("gamma").real(0.0, 1.0)),
            )
        )
        for i in range(30):
            cfg = space.sample_one(seed=i)
            value = cfg["algo"]
            assert value == "linear" or set(value.keys()) == {"svm"}

    def test_choice_weights_bias_the_draw(self):
        space = ds.space(ds.param("algo").choice("a", "b").prior(weights=[0.0, 1.0]))
        for i in range(20):
            cfg = space.sample_one(seed=i)
            assert cfg["algo"] == "b"

    def test_subset_respects_size_bounds(self):
        space = ds.space(ds.param("s").subset(("a", "b", "c", "d"), min_size=1, max_size=2))
        for i in range(50):
            cfg = space.sample_one(seed=i)
            assert 1 <= len(cfg["s"]) <= 2
            assert len(set(cfg["s"])) == len(cfg["s"])

    def test_permutation_is_a_full_reordering(self):
        space = ds.space(ds.param("p").permutation(("x", "y", "z")))
        for i in range(20):
            cfg = space.sample_one(seed=i)
            assert sorted(cfg["p"]) == ["x", "y", "z"]

    def test_struct_produces_no_flat_entry_of_its_own(self):
        space = ds.space(ds.param("layers").space(ds.param("width").integer(1, 10)))
        cfg = space.sample_one(seed=0)
        assert cfg == {"layers": {"width": cfg["layers"]["width"]}}
