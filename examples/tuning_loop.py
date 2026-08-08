"""A tuning loop over a design space.

Declare a space, draw candidates from it, score each against an objective, keep
the incumbent, and report the best configuration together with the key it
should be stored under.

Run with ``uv run python examples/tuning_loop.py``.
"""

from __future__ import annotations

import math
from typing import Any

import designspace as ds

N_CANDIDATES = 200
SEED = 0


def build_space() -> ds.Space:
    """The configuration surface of a gradient-descent training run."""
    return (
        ds.space(
            ds.param("optimizer").choice(
                adam=ds.space(ds.param("beta1").real(0.8, 0.999)),
                sgd=ds.space(ds.param("momentum").real(0.0, 0.99)),
            ),
            ds.param("lr").real(1e-5, 1.0).log_scale(),
            ds.param("weight_decay").real(1e-6, 1e-2).log_scale(),
            ds.param("batch_size").integer(16, 512).quantized(step=16),
            ds.param("warmup_steps").integer(0, 2000),
        )
        # A learning rate above 0.5 diverges in practice, so exclude it from the
        # space rather than relying on the objective to score it badly.
        .forbid(ds.param("lr") > 0.5)
        # Long warmups only pay off for large batches. Declared, so it is
        # reported with a margin and never affects what is drawn.
        .discourage(
            (ds.param("warmup_steps") > 1000) & (ds.param("batch_size") < 128),
            tags=("warmup-cost",),
        )
    )


def objective(config: dict[str, Any]) -> float:
    """Stand-in for a real evaluation. Lower is better.

    Shaped to have an interior optimum so the loop has something to find: it
    prefers a learning rate near 3e-3, a moderate batch size, and light decay.
    A real objective trains a model and returns its validation loss.
    """
    lr_penalty = (math.log10(config["lr"]) + 2.5) ** 2
    batch_penalty = (math.log2(config["batch_size"]) - 7.0) ** 2 / 8.0
    decay_penalty = math.log10(config["weight_decay"]) / 20.0
    warmup_penalty = config["warmup_steps"] / 20_000
    return lr_penalty + batch_penalty + decay_penalty + warmup_penalty


def search(space: ds.Space, n: int, seed: int) -> tuple[dict[str, Any], float]:
    """Score `n` draws and return the best configuration and its score."""
    best_config: dict[str, Any] | None = None
    best_score = math.inf
    for config in space.sample_dicts(n, seed=seed):
        score = objective(config)
        if score < best_score:
            best_config, best_score = config, score
    assert best_config is not None, "sample_dicts returned nothing"
    return best_config, best_score


def main() -> None:
    space = build_space()
    print(f"Space: {space.n_params} parameters, {len(space.constraints)} constraints")

    best, score = search(space, N_CANDIDATES, SEED)

    print(f"\nBest of {N_CANDIDATES} candidates (score {score:.4f}):")
    for path, value in ds.flatten(best, space).items():
        print(f"  {path:28} = {value!r}")

    # The declared constraint is reported, never enforced. A positive margin is
    # slack; a negative one means the discouraged state holds.
    for ce in space.evaluate_constraints(best):
        if not ce.constraint.hard:
            tags = ", ".join(sorted(ce.constraint.tags))
            print(f"\ndeclared [{tags}]: violated={ce.violated}")

    # Store results under this pair. The fingerprint identifies the space, the
    # config hash the point in it, so a result stays interpretable after the
    # space is edited.
    print("\nObservation key:")
    print(f"  space  {space.fingerprint()}")
    print(f"  config {ds.config_hash(best, space)}")


if __name__ == "__main__":
    main()
