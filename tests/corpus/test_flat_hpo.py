"""Corpus: `flat_hpo` end-to-end (resolve -> sample 200 -> validate all).

Round-trip joins once serialization exists (M7).
"""

from __future__ import annotations

from flat_hpo import build_space


def test_resolves():
    space = build_space()
    assert space.n_params == 7


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_nesterov_only_present_for_sgd():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        if cfg["optimizer"] == "sgd":
            assert "nesterov" in cfg
        else:
            assert "nesterov" not in cfg


def test_forbid_margin_is_numeric_and_matches_lr():
    space = build_space()
    for cfg in space.sample_dicts(50, seed=2):
        evals = space.evaluate_constraints(cfg)
        forbid_eval = next(e for e in evals if e.constraint.hard)
        assert forbid_eval.applicable
        assert forbid_eval.margin == cfg["lr"] - 0.5


def test_quantized_params_are_on_grid():
    space = build_space()
    for cfg in space.sample_dicts(100, seed=3):
        assert cfg["batch_size"] % 16 == 0
