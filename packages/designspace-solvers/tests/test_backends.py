"""Both bindings, driven end to end over the core package's corpus fixtures.

Every test here asserts the same three things of a real optimization run: that
each proposal is a complete configuration, that decoding a proposal and
validating it agree with the space, and that the observation key a tuning loop
records is stable. Those are the properties a consumer depends on, and they are
what a change to the representation would break first.

Feasibility is deliberately not asserted. A space with constraints has
infeasible corners, and a sampler is supposed to propose into them and learn;
a binding that could not produce an infeasible configuration would be
repairing proposals behind the solver's back.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from designspace_solvers import UnsupportedSpace, profile, rejections
from designspace_solvers.cmaes import Optimizer, _categorical_start, _layout
from designspace_solvers.optuna import constraint_values, suggest

import designspace as ds
from corpus.compiler_pipeline import build_space as build_compiler_pipeline
from corpus.flat_hpo import build_space as build_flat_hpo
from corpus.solver_portfolio import build_space as build_solver_portfolio


def _observation_key(space: ds.Space, config: dict[str, Any]) -> tuple[str, str]:
    return space.fingerprint(), ds.config_hash(config, space)


# -- Optuna, the define-by-run shape ---------------------------------------


@pytest.mark.parametrize(
    "build",
    [build_flat_hpo, build_solver_portfolio, build_compiler_pipeline],
    ids=["flat_hpo", "solver_portfolio", "compiler_pipeline"],
)
def test_optuna_proposes_only_complete_configurations(build: Any) -> None:
    """Every trial yields a configuration the space calls complete."""
    import optuna

    space = build()
    seen: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        config = suggest(trial, space)
        seen.append(config)
        return float(len(config))

    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    study.optimize(objective, n_trials=25)

    assert len(seen) == 25
    for config in seen:
        assert space.is_complete(config), f"incomplete: {config}"
        # Values only. A constraint may well be violated, and should be.
        assert not space.validate(config).param_errors


@pytest.mark.parametrize(
    "build",
    [build_flat_hpo, build_solver_portfolio, build_compiler_pipeline],
    ids=["flat_hpo", "solver_portfolio", "compiler_pipeline"],
)
def test_optuna_observation_key_is_stable(build: Any) -> None:
    """The key a tuning loop records does not change between reads."""
    import optuna

    space = build()
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=1))
    for _ in range(5):
        config = suggest(study.ask(), space)
        assert _observation_key(space, config) == _observation_key(space, config)


def test_optuna_omits_an_inactive_parameter() -> None:
    """An inactive parameter is absent, not filled with a stand-in."""
    import optuna

    space = ds.space(
        ds.param("use").bool(),
        ds.param("level").integer(1, 3).when(ds.param("use")),
    )
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    seen = [suggest(study.ask(), space) for _ in range(20)]

    assert any("level" not in config for config in seen), "never exercised the inactive branch"
    for config in seen:
        assert ("level" in config) == config["use"]


def test_optuna_fills_an_active_empty_lift() -> None:
    """A lift whose count is zero is active and empty, not absent.

    The assignment loop never announces this: with no element to assign it
    reports itself finished, and the key is never created. Validation calls the
    parameter missing, so the binding supplies the empty list that stands for
    an active list of length zero.
    """
    import optuna

    space = ds.space(
        ds.param("on").bool(),
        ds.param("n").integer(0, 3),
        ds.param("items")
        .space(ds.space(ds.param("v").integer(1, 9)))
        .repeat(ds.param("n"))
        .when(ds.param("on")),
    )
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    seen = [suggest(study.ask(), space) for _ in range(30)]

    empty = [c for c in seen if c["on"] and c["n"] == 0]
    assert empty, "never drew the active zero-length case"
    for config in empty:
        assert config["items"] == []
    for config in seen:
        assert not space.validate(config).param_errors, config
        # An inactive lift stays absent. Only an active one is filled.
        assert ("items" in config) == config["on"]


def test_optuna_keeps_a_quantized_parameter_on_its_grid() -> None:
    """A grid is respected because the value is decoded through the chart."""
    import optuna

    space = ds.space(
        ds.param("wd").real(1e-6, 1e-2).log_scale().quantized(factor=10),
        ds.param("batch").integer(16, 512).quantized(step=16),
    )
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    for _ in range(30):
        config = suggest(study.ask(), space)
        assert not space.validate(config).param_errors, config


def test_optuna_respects_a_declared_log_scale() -> None:
    """A log-scaled parameter stays inside its declared bounds."""
    import optuna

    space = ds.space(ds.param("lr").real(1e-5, 1e-1).log_scale())
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    values = [suggest(study.ask(), space)["lr"] for _ in range(50)]

    assert all(1e-5 <= v <= 1e-1 for v in values)
    # A log scale should spread across decades rather than pile up at the top,
    # which is what a linear suggestion over the same bounds would do.
    assert min(values) < 1e-3


def test_constraint_values_grade_distance_from_feasibility() -> None:
    """A hard constraint scores at most zero exactly when it is not violated."""
    space = ds.space(
        ds.param("a").integer(0, 10),
        ds.param("b").integer(0, 10),
    ).forbid(ds.param("a") > ds.param("b"))

    for a, b in [(1, 5), (5, 5), (6, 5), (9, 5)]:
        config = {"a": a, "b": b}
        (value,) = constraint_values(space, config)
        assert (value <= 0.0) == space.is_feasible(config)


def test_constraint_values_ignore_soft_constraints() -> None:
    """A preference does not make a configuration look infeasible."""
    space = ds.space(ds.param("a").integer(0, 10)).discourage(ds.param("a") > 5)
    assert constraint_values(space, {"a": 9}) == ()
    assert space.is_feasible({"a": 9})


# -- CMA-ES, the fixed-width shape -----------------------------------------


def test_cmaes_optimizes_a_mixed_space() -> None:
    """A run over continuous, integer and categorical parameters improves."""
    space = ds.space(
        ds.param("lr").real(1e-4, 1e-1).log_scale(),
        ds.param("depth").integer(1, 8),
        ds.param("act").categorical("relu", "tanh"),
    )

    def loss(config: dict[str, Any]) -> float:
        penalty = 0.0 if config["act"] == "tanh" else 1.0
        return abs(config["lr"] - 0.01) + abs(config["depth"] - 5) + penalty

    optimizer = Optimizer(space, seed=0)
    for _ in range(40):
        proposals = optimizer.ask()
        optimizer.tell([(p, loss(p.config)) for p in proposals])

    first = min(value for _, value in optimizer.history[: optimizer.population_size])
    best = min(value for _, value in optimizer.history)
    assert best < first, "the run did not improve on its first generation"

    for config, _ in optimizer.history:
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


def test_cmaes_decodes_every_kind_it_accepts() -> None:
    """Each accepted kind decodes to a value the space validates."""
    space = ds.space(
        ds.param("r").real(0.0, 1.0),
        ds.param("wide").integer(1, 10_000),
        ds.param("narrow").integer(1, 4),
        ds.param("gridded").integer(16, 512).quantized(step=16),
        ds.param("decades").real(1e-6, 1e-2).log_scale().quantized(factor=10),
        ds.param("o").ordinal("low", "mid", "high"),
        ds.param("c").categorical("x", "y", "z"),
        ds.param("flag").bool(),
        ds.param("items").subset(["a", "b", "c"]),
        ds.param("order").permutation(["p", "q", "r"]),
    )
    optimizer = Optimizer(space, seed=0)
    for proposal in optimizer.ask():
        config = proposal.config
        assert space.is_complete(config)
        assert not space.validate(config).param_errors
        assert sorted(config["order"]) == ["p", "q", "r"]
        assert set(config["items"]) <= {"a", "b", "c"}


def test_cmaes_refuses_a_conditional_space_by_name() -> None:
    """A flat solver names the parameter it cannot place rather than padding."""
    space = ds.space(
        ds.param("use").bool(),
        ds.param("level").integer(1, 3).when(ds.param("use")),
    )
    with pytest.raises(UnsupportedSpace) as caught:
        Optimizer(space)

    assert [r.path for r in caught.value.rejections] == ["level"]
    assert "level" in str(caught.value)


def test_cmaes_refuses_a_variable_length_space_by_name() -> None:
    """A variable-length list has no fixed width, and is refused as such."""
    space = build_solver_portfolio()
    with pytest.raises(UnsupportedSpace) as caught:
        Optimizer(space)

    assert "workers" in {r.path for r in caught.value.rejections}


def test_cmaes_starts_the_categorical_block_from_declared_weights() -> None:
    """`.prior(weights=...)` becomes the categorical distribution's starting point.

    Relative weights normalize; a bool reads `[False, True]`; a subset's
    weights are per-item inclusion probabilities, so each item becomes a row
    of `[excluded, included]`. Rows are padded to the widest variable.
    """
    space = ds.space(
        ds.param("act").categorical("relu", "tanh", "gelu").prior(weights=[6.0, 3.0, 1.0]),
        ds.param("flag").bool().prior(weights=[1.0, 3.0]),
        ds.param("items").subset(["a", "b"]).prior(weights=[0.25, 0.75]),
    )
    slots, _x_space, _z_space, c_space = _layout(space)
    start = _categorical_start(space, slots, c_space)

    assert start is not None
    np.testing.assert_allclose(
        start,
        [
            [0.6, 0.3, 0.1],
            [0.25, 0.75, 0.0],
            [0.75, 0.25, 0.0],
            [0.25, 0.75, 0.0],
        ],
    )


def test_cmaes_leaves_an_undeclared_categorical_uniform() -> None:
    """No weights means no starting point, which is the solver's own uniform."""
    space = ds.space(ds.param("act").categorical("relu", "tanh"), ds.param("d").integer(1, 4))
    slots, _x_space, _z_space, c_space = _layout(space)
    assert _categorical_start(space, slots, c_space) is None


def test_cmaes_ordinal_weights_do_not_reach_the_solver() -> None:
    """An ordinal sits in the integer block, which holds no distribution to seed."""
    space = ds.space(
        ds.param("o").ordinal("low", "mid", "high").prior(weights=[1.0, 1.0, 8.0]),
        ds.param("d").integer(1, 4),
    )
    slots, _x_space, _z_space, c_space = _layout(space)
    assert c_space == []
    assert _categorical_start(space, slots, c_space) is None


def test_cmaes_weighted_categorical_dominates_its_first_generation() -> None:
    """The declared weights are visible in what the solver proposes."""
    space = ds.space(
        ds.param("act").categorical("relu", "tanh").prior(weights=[19.0, 1.0]),
        ds.param("depth").integer(1, 8),
    )
    drawn = [p.config["act"] for seed in range(5) for p in Optimizer(space, seed=seed).ask()]
    assert drawn.count("relu") > 3 * drawn.count("tanh")


def test_cmaes_warm_starts_from_a_known_configuration() -> None:
    """A supplied mean puts the first generation near the configuration given."""
    space = ds.space(ds.param("x").real(-5.0, 5.0), ds.param("y").real(-5.0, 5.0))

    cold = Optimizer(space, seed=0, sigma=0.05)
    warm = Optimizer(space, seed=0, sigma=0.05, mean={"x": 4.5, "y": 4.5})

    cold_x = sum(p.config["x"] for p in cold.ask()) / cold.population_size
    warm_x = sum(p.config["x"] for p in warm.ask()) / warm.population_size
    assert warm_x > cold_x, "the warm start did not move the first generation"


# -- Negotiation, shared -----------------------------------------------------


def test_profile_reports_chart_availability_per_kind() -> None:
    """Only real and integer parameters carry a chart."""
    space = ds.space(
        ds.param("r").real(0.0, 1.0),
        ds.param("i").integer(0, 4),
        ds.param("o").ordinal("a", "b"),
        ds.param("c").categorical("x", "y"),
        ds.param("flag").bool(),
    )
    charted = {p.path for p in profile(space).params if p.has_chart}
    assert charted == {"r", "i"}


def test_rejections_report_every_reason_at_once() -> None:
    """A space outside the envelope is reported whole, not one fault per run."""
    space = ds.space(
        ds.param("a").categorical("x", "y"),
        ds.param("b").permutation(["p", "q"]),
        ds.param("c").real(0.0, 1.0),
    )
    found = rejections(space, kinds={"real"})
    assert [r.path for r in found] == ["a", "b"]
