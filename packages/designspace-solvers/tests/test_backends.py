"""Every binding, driven end to end over the core package's corpus fixtures.

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

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from designspace_solvers import UnsupportedSpace, profile, rejections
from designspace_solvers.cmaes import Optimizer, _categorical_start, _layout
from designspace_solvers.configspace import translate
from designspace_solvers.optuna import constraint_values, set_constraints, suggest
from designspace_solvers.smac import Optimizer as SmacOptimizer

import designspace as ds
from corpus.compiler_pipeline import build_space as build_compiler_pipeline
from corpus.delivery_routes import build_space as build_delivery_routes
from corpus.flat_hpo import build_space as build_flat_hpo
from corpus.memetic_pipeline import build_space as build_memetic_pipeline
from corpus.solver_portfolio import build_space as build_solver_portfolio


def _observation_key(space: ds.Space, config: dict[str, Any]) -> tuple[str, str]:
    return space.fingerprint(), ds.config_hash(config, space)


# -- Optuna, the define-by-run shape ---------------------------------------


@pytest.mark.parametrize(
    "build",
    [build_flat_hpo, build_solver_portfolio, build_compiler_pipeline, build_memetic_pipeline],
    ids=["flat_hpo", "solver_portfolio", "compiler_pipeline", "memetic_pipeline"],
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
    [build_flat_hpo, build_solver_portfolio, build_compiler_pipeline, build_memetic_pipeline],
    ids=["flat_hpo", "solver_portfolio", "compiler_pipeline", "memetic_pipeline"],
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
        ((value,),) = (constraint_values(space, config).values(),)
        assert value is not None
        assert (value <= 0.0) == space.is_feasible(config)


def test_constraint_values_negate_a_require() -> None:
    """A `require` is feasible when satisfied, so its margin is negated.

    The polarity-opposite of the `forbid` above, over the same predicate and
    the same configurations, and it has to score the same way round.
    """
    space = ds.space(
        ds.param("a").integer(0, 10),
        ds.param("b").integer(0, 10),
    ).require(ds.param("a") <= ds.param("b"))

    for a, b in [(1, 5), (5, 5), (6, 5), (9, 5)]:
        config = {"a": a, "b": b}
        assert constraint_values(space, config) == {"require[0]": float(a - b)}
        assert (a - b <= 0.0) == space.is_feasible(config)


def test_constraint_values_ignore_soft_constraints() -> None:
    """A preference does not make a configuration look infeasible."""
    space = ds.space(ds.param("a").integer(0, 10)).discourage(ds.param("a") > 5)
    assert constraint_values(space, {"a": 9}) == {}
    assert space.is_feasible({"a": 9})


def test_constraint_values_omit_an_inapplicable_constraint() -> None:
    """A constraint over an inactive parameter is absent, not scored zero.

    Zero would say the configuration sits exactly on the boundary. Absence
    says the constraint never applied, which is what an inactive parameter
    makes true, and Optuna reads a constraint it was not told about as
    satisfied.
    """
    space = ds.space(
        ds.param("on").bool(),
        ds.param("n").integer(0, 10).when(ds.param("on")),
    ).forbid(ds.param("n") > 5, tags=("cap",))

    assert constraint_values(space, {"on": True, "n": 9}) == {"forbid[cap]": 4.0}
    assert constraint_values(space, {"on": False}) == {}


def test_constraint_values_leave_an_opaque_predicate_unmeasured() -> None:
    """An opaque predicate has a verdict and no distance, so it scores `None`."""
    space = ds.space(ds.param("n").integer(1, 20)).forbid(
        ds.value(lambda v: v % 2 == 0, ds.param("n"), returns=bool),
        tags=("even",),
    )

    assert constraint_values(space, {"n": 4}) == {"forbid[even]": None}
    assert constraint_values(space, {"n": 3}) == {"forbid[even]": None}


def test_set_constraints_writes_a_verdict_for_an_opaque_predicate() -> None:
    """An unmeasured constraint reaches the trial as its verdict.

    Writing zero would report a violated constraint as feasible, which is the
    one thing a constrained sampler must not be told.
    """
    import optuna

    space = ds.space(ds.param("n").integer(1, 20)).forbid(
        ds.value(lambda v: v % 2 == 0, ds.param("n"), returns=bool),
        tags=("even",),
    )
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))

    violated = study.ask()
    set_constraints(violated, space, {"n": 4})
    assert violated.constraints == {"forbid[even]": 1.0}
    assert not space.is_feasible({"n": 4})

    feasible = study.ask()
    set_constraints(feasible, space, {"n": 3})
    assert feasible.constraints == {"forbid[even]": -1.0}
    assert space.is_feasible({"n": 3})


def test_constraint_keys_are_named_by_tags() -> None:
    """Tags name a constraint; position names one that carries none.

    Positions count every hard constraint of the kind, tagged ones included,
    so naming one constraint never renumbers another.
    """
    space = (
        ds.space(*[ds.param(name).integer(0, 10) for name in "abcde"])
        .forbid(ds.param("a") > 8, tags=("budget",))
        .forbid(ds.param("b") > 8)
        .forbid(ds.param("c") > 8, tags=("memory", "latency"))
        .forbid(ds.param("d") > 8, tags=("budget",))
        .require(ds.param("e") <= 8)
    )
    config = dict.fromkeys("abcde", 0)

    assert sorted(constraint_values(space, config)) == [
        # Untagged, and second among the forbids.
        "forbid[1]",
        # Two constraints share the `budget` tag. Each keeps it and takes an
        # ordinal rather than one landing on the other's key.
        "forbid[budget.0]",
        "forbid[budget.1]",
        # Several tags read as labels rather than as one name, so all of them
        # are used, sorted.
        "forbid[latency,memory]",
        # A separate kind counts its own positions.
        "require[0]",
    ]


def test_constraint_keys_name_each_element_of_a_lift() -> None:
    """A per-element constraint is scored once per element, keyed by its path.

    The count follows the realized length, which is what a variable-length
    lift means and what a single ordered sequence of scores could not carry.
    """
    space = build_delivery_routes()

    for n_stops in (1, 3, 5):
        config = {
            "n_stops": n_stops,
            "stops": [{"location": i, "dwell_min": 20} for i in range(n_stops)],
        }
        keys = sorted(constraint_values(space, config))
        assert keys == ["forbid[0]"] + [f"forbid[0]@stops[{i}]" for i in range(n_stops)]


def test_constraint_keys_are_stable_across_trials() -> None:
    """One constraint keeps one key however the configuration changes.

    A key is derived from the space, so a constraint that goes inapplicable on
    one trial and applies on the next is scored under the same name both
    times, and the sampler reads a single series rather than two.
    """
    space = (
        ds.space(
            ds.param("on").bool(),
            ds.param("n").integer(0, 10).when(ds.param("on")),
            ds.param("m").integer(0, 10),
        )
        .forbid(ds.param("n") > 5, tags=("shared",))
        .forbid(ds.param("m") > 5, tags=("shared",))
    )

    off = constraint_values(space, {"on": False, "m": 9})
    on = constraint_values(space, {"on": True, "n": 9, "m": 9})

    assert off == {"forbid[shared.1]": 4.0}
    assert on == {"forbid[shared.0]": 4.0, "forbid[shared.1]": 4.0}
    assert off.keys() <= on.keys()


def test_set_constraints_reaches_the_sampler() -> None:
    """A constrained study runs on the current API and carries its scores.

    The deprecated `constraints_func` route would warn here, so its absence is
    asserted rather than assumed.
    """
    import optuna

    space = ds.space(
        ds.param("workers").integer(1, 16),
        ds.param("memory_gb").integer(1, 64),
    ).forbid(ds.param("workers") * ds.param("memory_gb") > 64, tags=("budget",))

    def objective(trial: optuna.Trial) -> float:
        config = suggest(trial, space)
        set_constraints(trial, space, config)
        return -float(config["workers"])

    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        study.optimize(objective, n_trials=25)

    assert all(sorted(trial.constraints) == ["forbid[budget]"] for trial in study.trials)
    feasible = [t for t in study.trials if all(v <= 0.0 for v in t.constraints.values())]
    assert feasible, "no feasible trial in a study whose space has feasible corners"
    for trial in feasible:
        assert trial.params["workers"] * trial.params["memory_gb"] <= 64


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


# -- ConfigSpace, the foreign-representation shape ---------------------------


@pytest.mark.parametrize(
    "build",
    [build_flat_hpo, build_compiler_pipeline],
    ids=["flat_hpo", "compiler_pipeline"],
)
def test_configspace_decodes_only_complete_configurations(build: Any) -> None:
    """Every sampled configuration decodes to one the space calls complete."""
    space = build()
    translation = translate(space)
    translation.config_space.seed(0)
    for _ in range(50):
        config = translation.decode(translation.config_space.sample_configuration())
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


@pytest.mark.parametrize(
    "build",
    [build_flat_hpo, build_compiler_pipeline],
    ids=["flat_hpo", "compiler_pipeline"],
)
def test_configspace_observation_key_is_stable(build: Any) -> None:
    """The key a tuning loop records does not change between reads."""
    space = build()
    translation = translate(space)
    translation.config_space.seed(1)
    for _ in range(20):
        config = translation.decode(translation.config_space.sample_configuration())
        assert _observation_key(space, config) == _observation_key(space, config)


def test_configspace_round_trips_encode_and_decode() -> None:
    """Encoding a decoded configuration and decoding it again is a no-op."""
    space = build_flat_hpo()
    translation = translate(space)
    translation.config_space.seed(2)
    for _ in range(30):
        config = translation.decode(translation.config_space.sample_configuration())
        again = translation.decode(translation.encode(config))
        assert again == config


def test_configspace_refuses_a_variable_length_space_by_name() -> None:
    """A `list` kind has no ConfigSpace counterpart, unrolling needing a fixed layout."""
    space = build_solver_portfolio()
    with pytest.raises(UnsupportedSpace) as caught:
        translate(space)
    assert "workers" in {r.path for r in caught.value.rejections}


# -- SMAC, ask and tell over the ConfigSpace translation ---------------------


def test_smac_optimizes_over_the_translation(tmp_path: Path) -> None:
    """A run over `flat_hpo` proposes only configurations the space validates."""
    space = build_flat_hpo()

    def loss(config: dict[str, Any]) -> float:
        return abs(config["lr"] - 0.01) + abs(config["n_layers"] - 4)

    optimizer = SmacOptimizer(space, seed=0, n_trials=12, output_directory=tmp_path)
    for _ in range(12):
        proposal = optimizer.ask()
        optimizer.tell(proposal, loss(proposal.config))

    assert len(optimizer.history) == 12
    for config, _ in optimizer.history:
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


def test_smac_observation_key_is_stable(tmp_path: Path) -> None:
    """The key a tuning loop records does not change between reads."""
    space = build_flat_hpo()
    optimizer = SmacOptimizer(space, seed=3, n_trials=8, output_directory=tmp_path)
    for _ in range(8):
        proposal = optimizer.ask()
        assert _observation_key(space, proposal.config) == _observation_key(space, proposal.config)
        optimizer.tell(proposal, 0.0)


def test_smac_observe_extends_history_without_asking(tmp_path: Path) -> None:
    """A reported configuration the optimizer never proposed warm starts the run."""
    space = ds.space(ds.param("x").real(0.0, 1.0))
    optimizer = SmacOptimizer(space, seed=0, n_trials=5, output_directory=tmp_path)
    optimizer.observe({"x": 0.5}, 0.0)
    assert optimizer.history == [({"x": 0.5}, 0.0)]


def test_smac_refuses_a_variable_length_space_by_name(tmp_path: Path) -> None:
    """SMAC refuses exactly what the ConfigSpace translation refuses."""
    space = build_solver_portfolio()
    with pytest.raises(UnsupportedSpace) as caught:
        SmacOptimizer(space, output_directory=tmp_path)
    assert "workers" in {r.path for r in caught.value.rejections}


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
