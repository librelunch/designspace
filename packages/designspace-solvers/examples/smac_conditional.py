"""Tuning a conditional space with SMAC3, over the ConfigSpace translation.

Declare the same conditional space `optuna_hpo.py` searches, with a variant
choice, a conditional parameter and a hard constraint, search it with SMAC's
Bayesian-optimization facade instead, and report the best feasible
configuration together with the key it should be stored under.

The step-budget constraint is a product of two parameters, which has no
ConfigSpace forbidden-clause form; the translation reports it rather than
raising, so the objective penalizes it directly, the same way a caller
handles any constraint that does not reach the solver.

Run with ``uv run python packages/designspace-solvers/examples/smac_conditional.py``.
"""

from __future__ import annotations

import math
import tempfile
from typing import Any

from designspace_solvers.smac import Optimizer

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
        # The predicate multiplies two parameters together, which is outside
        # what a forbidden clause can express, so it is reported rather than
        # translated (see `main`, below).
    ).forbid(
        ds.param("batch_size") * ds.param("warmup_steps") > 250_000,
        tags=("step_budget",),
    )


def objective_value(space: ds.Space, config: dict[str, Any]) -> float:
    """Stand-in for a real evaluation. Lower is better.

    Shaped to have an interior optimum so the search has something to find: it
    prefers a learning rate near 3e-3, a batch size near 128, and a warmup. A
    real objective trains a model and returns its validation loss. The step
    budget carries no margin the search can see, so a violation is penalized
    directly instead.
    """
    loss = (math.log10(config["lr"]) + 2.5) ** 2
    loss += (math.log2(config["batch_size"]) - 7.0) ** 2 / 8.0
    loss -= 0.2 if config["use_warmup"] else 0.0
    loss += 0.1 if ds.variant(config, "optimizer") == "sgd" else 0.0
    if not space.is_feasible(config):
        loss += 10.0
    return loss


def search(space: ds.Space, n_trials: int, seed: int, output_directory: str) -> Optimizer:
    """Run SMAC over the translated space and return the optimizer, history and all."""
    optimizer = Optimizer(space, seed=seed, n_trials=n_trials, output_directory=output_directory)
    for _ in range(n_trials):
        proposal = optimizer.ask()
        optimizer.tell(proposal, objective_value(space, proposal.config))
    return optimizer


def main() -> None:
    space = build_space()
    print(space)

    with tempfile.TemporaryDirectory() as output_directory:
        optimizer = search(space, N_TRIALS, SEED, output_directory)

    feasible = [(c, v) for c, v in optimizer.history if space.is_feasible(c)]
    best, value = min(feasible, key=lambda pair: pair[1])

    print(f"\nBest feasible of {N_TRIALS} trials (value {value:.4f}):")
    print(ds.pretty(best, space))

    # An inactive parameter is absent rather than filled, so the report says
    # which of them the winning configuration never reached.
    inactive = [p for p, status in space.param_activity(best).items() if status == "inactive"]
    print(f"\nInactive in this configuration: {', '.join(inactive) or 'none'}")

    untranslated = [c.kind for c in optimizer.translation.untranslated_constraints]
    print(f"\nConstraint kinds SMAC never saw a margin for: {untranslated}")

    print("\nObservation key:")
    print(f"  space  {space.fingerprint()}")
    print(f"  config {ds.config_hash(best, space)}")


if __name__ == "__main__":
    main()
