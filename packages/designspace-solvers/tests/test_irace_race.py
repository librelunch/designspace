"""A real race, against a real irace.

Everything here needs R and the irace package, which is why it is a gate of
its own rather than part of `gates-solvers`. It covers what no pure-Python
test can: whether irace accepts the names this binding places, parses the
conditions and forbidden expressions it generates, and compares an ordinal the
way the emitter assumed.

`translate` is asserted at a finer grain, and without R, in
`test_irace_translation.py`. What is left here is the round trip through irace
itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("rpy2")

from designspace_solvers.irace import Experiment, Scenario, run

import designspace as ds
from corpus.flat_hpo import build_space as build_flat_hpo
from corpus.job_shop import build_space as build_job_shop
from corpus.wind_farm_grid import build_space as build_wind_farm_grid

pytestmark = pytest.mark.requires_irace


@pytest.fixture(scope="module", autouse=True)
def _requires_irace() -> None:
    """Skip where R is installed but the irace package is not."""
    from rpy2.robjects.packages import importr

    try:
        importr("irace")
    except Exception as exc:
        pytest.skip(f"the R package irace is not available: {exc}")


#: irace sets its own floor on the budget from the number of parameters and
#: refuses to start below it. 200 clears the floor for every space raced here.
_BUDGET = 200


def _race(space: ds.Space, loss: Any, experiments: int = _BUDGET) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        seen.append(config)
        return loss(config)

    elites = run(space, evaluate, Scenario(max_experiments=experiments, seed=42))
    assert seen, "the race evaluated nothing"
    for config in seen:
        assert space.is_complete(config), f"incomplete: {config}"
        assert not space.validate(config).param_errors
    return elites


@pytest.mark.parametrize(
    "build",
    [build_flat_hpo, build_wind_farm_grid, build_job_shop],
    ids=["flat_hpo", "wind_farm_grid", "job_shop"],
)
def test_a_race_over_a_corpus_fixture_yields_configurations_the_space_validates(
    build: Any,
) -> None:
    """The names, conditions and forbidden expressions this binding generates
    are ones irace accepts. `wind_farm_grid` and `job_shop` place the bracketed
    item names the mangle exists for."""
    space = build()
    elites = _race(space, lambda config: float(len(ds.flatten(config, space))))
    assert elites
    for elite in elites:
        assert space.is_complete(elite)
        assert not space.validate(elite).param_errors


def test_a_race_finds_the_optimum_of_a_space_it_can_search() -> None:
    """Racing is not just accepted, it works: the elite is near the target."""
    space = ds.space(
        ds.param("lr").real(1e-4, 1e-1).log_scale(),
        ds.param("depth").integer(1, 12),
    )
    elites = _race(space, lambda c: abs(c["lr"] - 0.01) * 100 + abs(c["depth"] - 5))
    best = elites[0]
    assert abs(best["depth"] - 5) <= 2, best
    assert 1e-3 < best["lr"] < 1e-1, best


def test_a_condition_withholds_a_parameter_during_a_real_race() -> None:
    """A parameter its condition leaves inactive is absent from the
    configuration, not filled with a stand-in, all the way through irace."""
    space = ds.space(
        ds.param("warmup").bool(),
        ds.param("steps").integer(1, 100).when(ds.param("warmup")),
    )
    seen: list[dict[str, Any]] = []

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        seen.append(config)
        return float(config.get("steps", 0))

    run(space, evaluate, Scenario(max_experiments=_BUDGET, seed=7))
    assert {"steps" in config for config in seen} == {True, False}
    for config in seen:
        assert ("steps" in config) == config["warmup"], config


def test_an_ordinal_past_ten_levels_orders_numerically_not_lexicographically() -> None:
    """The trap an integer placement avoids. R reads `"10" >= "2"` as FALSE,
    so an ordinal placed as index strings would activate the wrong levels, and
    do so silently."""
    space = ds.space(
        ds.param("level").ordinal(*[str(i) for i in range(12)]),
        ds.param("tuned").real(0.0, 1.0).when(ds.param("level") >= "10"),
    )
    seen: list[dict[str, Any]] = []

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        seen.append(config)
        return float(config["level"])

    run(space, evaluate, Scenario(max_experiments=_BUDGET, seed=11))

    activated = {int(c["level"]) for c in seen if "tuned" in c}
    withheld = {int(c["level"]) for c in seen if "tuned" not in c}
    assert activated, "the condition never activated, so it was not exercised"
    assert activated <= {10, 11}, f"activated below the threshold: {sorted(activated)}"
    assert withheld and max(withheld) < 10, f"withheld at or above it: {sorted(withheld)}"


def test_a_conditional_ordinal_keeps_a_value_wherever_its_condition_holds() -> None:
    """irace draws each new configuration from an elite, and an elite that
    left this parameter inactive supplies no value for the model to centre on.
    Its ordinal sampler yields nothing there, so a race would hand back a
    configuration whose condition holds and whose level is missing, which is
    https://github.com/MLopez-Ibanez/irace/issues/94. Placed as an integer,
    the sampler falls back to a uniform draw over the domain.

    The budget is what makes this a test: the first iteration samples
    uniformly and only later ones sample from a model, so a short race never
    reaches the draw that fails.
    """
    space = ds.space(
        ds.param("use").bool(),
        ds.param("level").ordinal("low", "mid", "high").when(ds.param("use")),
        ds.param("x").real(0.0, 1.0),
    )
    seen: list[dict[str, Any]] = []

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        seen.append(config)
        return float(config["x"])

    run(space, evaluate, Scenario(max_experiments=400, seed=1))

    assert {"level" in config for config in seen} == {True, False}
    for config in seen:
        assert ("level" in config) == config["use"], config
        assert space.is_complete(config), config


def test_a_forbidden_expression_keeps_the_race_out_of_the_region() -> None:
    """An arithmetic constraint reaches irace as one expression, and irace
    honours it."""
    space = ds.space(
        ds.param("a").integer(1, 20),
        ds.param("b").integer(1, 20),
    ).forbid(ds.param("a") * ds.param("b") > 100)
    seen: list[dict[str, Any]] = []

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        seen.append(config)
        return float(-config["a"] * config["b"])

    run(space, evaluate, Scenario(max_experiments=_BUDGET, seed=3))
    assert seen
    for config in seen:
        assert config["a"] * config["b"] <= 100, config
        assert space.is_feasible(config), config


def test_a_race_writes_nothing_beside_the_caller() -> None:
    """Left to itself irace saves `irace.Rdata` into the working directory.
    Starting a race is not a request to write a file there."""
    space = ds.space(ds.param("x").real(0.0, 1.0))
    before = set(Path.cwd().iterdir())
    _race(space, lambda config: abs(config["x"] - 0.5))
    assert set(Path.cwd().iterdir()) == before


def test_a_log_file_is_written_where_one_is_asked_for(tmp_path: Path) -> None:
    """Suppressing the default does not remove the option."""
    space = ds.space(ds.param("x").real(0.0, 1.0))
    log = tmp_path / "race.Rdata"

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        return abs(config["x"] - 0.5)

    run(space, evaluate, Scenario(max_experiments=_BUDGET, seed=5, log_file=str(log)))
    assert log.exists()


def test_a_raising_target_function_stops_the_race_and_keeps_its_traceback() -> None:
    """irace's own channel for a failing target function stops the race. The
    Python exception is chained onto what R raises, so the cause survives."""
    space = ds.space(ds.param("x").real(0.0, 1.0))

    class Boom(Exception):
        pass

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        raise Boom("the target function failed")

    with pytest.raises(RuntimeError) as caught:
        run(space, evaluate, Scenario(max_experiments=_BUDGET, seed=0))
    assert isinstance(caught.value.__cause__, Boom)
