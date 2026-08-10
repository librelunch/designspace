"""Tuning a conditional space with Optuna.

Declare a space whose parameters depend on one another, search it with an
Optuna study, and report the best feasible configuration together with the key
it should be stored under.

Run with ``uv run python packages/designspace-solvers/examples/optuna_hpo.py``.
"""

from __future__ import annotations

import math
from typing import Any

import optuna
from designspace_solvers.optuna import constraint_values, suggest

import designspace as ds

N_TRIALS = 60
SEED = 0


def build_space() -> ds.Space:
    """A training run whose optimizer brings its own parameters."""
    return ds.space(
        ds.param("optimizer").choice(
            adam=ds.space(ds.param("beta1").real(0.8, 0.999)),
            sgd=ds.space(
                ds.param("momentum").real(0.0, 0.99),
                ds.param("nesterov").bool(),
            ),
        ),
        ds.param("lr").real(1e-5, 1.0).log_scale(),
        ds.param("batch_size").integer(16, 512).quantized(step=16),
        ds.param("use_warmup").bool(),
        ds.param("warmup_steps").integer(1, 2000).when(ds.param("use_warmup")),
        # A long warmup at a large batch exceeds the step budget of the run.
        # Declared as a constraint rather than folded into the objective, so
        # the sampler learns the boundary from a margin.
    ).forbid(ds.param("batch_size") * ds.param("warmup_steps") > 250_000)


def objective_value(config: dict[str, Any]) -> float:
    """Stand-in for a real evaluation. Lower is better.

    Shaped to have an interior optimum so the search has something to find: it
    prefers a learning rate near 3e-3, a batch size near 128, and a warmup. A
    real objective trains a model and returns its validation loss.
    """
    loss = (math.log10(config["lr"]) + 2.5) ** 2
    loss += (math.log2(config["batch_size"]) - 7.0) ** 2 / 8.0
    loss -= 0.2 if config["use_warmup"] else 0.0
    loss += 0.1 if ds.variant(config, "optimizer") == "sgd" else 0.0
    return loss


def search(space: ds.Space, n_trials: int, seed: int) -> tuple[dict[str, Any], float]:
    """Run a study and return the best feasible configuration and its value.

    The configuration is kept on the trial as it is suggested. Optuna records
    the parameters it chose, which are one per suggestion rather than one per
    parameter of the space, so reading a configuration back out of a trial
    afterwards would mean reassembling it.
    """
    tried: dict[int, dict[str, Any]] = {}

    def objective(trial: optuna.Trial) -> float:
        config = suggest(trial, space)
        tried[trial.number] = config
        # Read by the sampler through `constraints_func` below. Storing them
        # here means each trial is scored exactly once.
        trial.set_user_attr("constraints", constraint_values(space, config))
        return objective_value(config)

    sampler = optuna.samplers.TPESampler(
        seed=seed,
        constraints_func=lambda trial: trial.user_attrs["constraints"],
    )
    study = optuna.create_study(sampler=sampler)
    study.optimize(objective, n_trials=n_trials)

    # A constraint informs the sampler; it does not filter the study, so the
    # feasible trials are selected here.
    number, value = min(
        (
            (trial.number, trial.value)
            for trial in study.trials
            if trial.value is not None
            and all(score <= 0.0 for score in trial.user_attrs["constraints"])
        ),
        key=lambda scored: scored[1],
    )
    return tried[number], value


def main() -> None:
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    space = build_space()
    print(space)

    best, value = search(space, N_TRIALS, SEED)

    print(f"\nBest feasible of {N_TRIALS} trials (value {value:.4f}):")
    print(ds.pretty(best, space))

    # An inactive parameter is absent rather than filled, so the report says
    # which of them the winning configuration never reached.
    inactive = [path for path, status in space.param_activity(best).items() if status == "inactive"]
    print(f"\nInactive in this configuration: {', '.join(inactive) or 'none'}")

    print("\nObservation key:")
    print(f"  space  {space.fingerprint()}")
    print(f"  config {ds.config_hash(best, space)}")


if __name__ == "__main__":
    main()
