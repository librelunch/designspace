"""Searching a flat space with CMA-ES, warm started from a known configuration.

Draw a first incumbent from the space itself, hand it to the optimizer as a
starting point, and run generation by generation from there. Print what the run
found and what a conditional space is refused with.

Run with ``uv run python packages/designspace-solvers/examples/cmaes_warm_start.py``.
"""

from __future__ import annotations

import math
from typing import Any

from designspace_solvers import UnsupportedSpace
from designspace_solvers.cmaes import Optimizer

import designspace as ds

N_GENERATIONS = 30
N_DRAWS = 20
SIGMA = 0.2
SEED = 0


def build_space() -> ds.Space:
    """A signal filter, every parameter always active and every list fixed.

    A flat layout is what the optimizer needs. `.prior(weights=...)` on the
    window says where good values are expected before any evaluation, and
    starts the solver's categorical distribution there rather than uniform.
    """
    return ds.space(
        ds.param("cutoff_hz").real(1.0, 1e4).log_scale(),
        ds.param("order").integer(1, 12),
        ds.param("ripple_db").real(0.01, 3.0).quantized(step=0.01),
        ds.param("window").categorical("hann", "hamming", "blackman").prior(weights=[3, 2, 1]),
        ds.param("zero_phase").bool(),
    )


def loss(config: dict[str, Any]) -> float:
    """Stand-in for a real evaluation. Lower is better.

    Shaped to have an interior optimum: it prefers a cutoff near 300 Hz, an
    order near 6, light ripple, and a Blackman window, which the declared
    weights favour least.
    """
    value = (math.log10(config["cutoff_hz"]) - 2.5) ** 2
    value += abs(config["order"] - 6) / 4.0
    value += config["ripple_db"] / 3.0
    value += 0.0 if config["window"] == "blackman" else 0.4
    value -= 0.1 if config["zero_phase"] else 0.0
    return value


def incumbent(space: ds.Space, n: int, seed: int) -> tuple[dict[str, Any], float]:
    """The best of `n` draws from the space's own sampler."""
    scored = [(config, loss(config)) for config in space.sample_dicts(n, seed=seed)]
    return min(scored, key=lambda pair: pair[1])


def run(space: ds.Space, start: dict[str, Any]) -> Optimizer:
    """Optimize from `start` and return the optimizer, `history` and all."""
    optimizer = Optimizer(space, seed=SEED, sigma=SIGMA, mean=start)
    for _ in range(N_GENERATIONS):
        proposals = optimizer.ask()
        optimizer.tell([(proposal, loss(proposal.config)) for proposal in proposals])
    return optimizer


def show_refusal() -> None:
    """What the optimizer says when a space has no fixed layout."""
    conditional = ds.space(
        ds.param("resample").bool(),
        ds.param("target_hz").integer(8_000, 48_000).when(ds.param("resample")),
    )
    try:
        Optimizer(conditional)
    except UnsupportedSpace as refusal:
        print(refusal)


def main() -> None:
    space = build_space()
    print(space)

    start, start_value = incumbent(space, N_DRAWS, SEED)
    print(f"\nWarm start, best of {N_DRAWS} draws (loss {start_value:.4f}):")
    print(ds.pretty(start, space))

    optimizer = run(space, start)
    best, best_value = min(optimizer.history, key=lambda pair: pair[1])
    evaluations = len(optimizer.history)
    print(f"\nBest of {evaluations} evaluations over {N_GENERATIONS} generations", end="")
    print(f" (loss {best_value:.4f}):")
    print(ds.pretty(best, space))

    print("\nEvery proposal is a configuration the space validates:")
    print(f"  complete  {all(space.is_complete(config) for config, _ in optimizer.history)}")
    print(f"  valid     {all(space.validate(config).valid for config, _ in optimizer.history)}")

    print("\nObservation key:")
    print(f"  space  {space.fingerprint()}")
    print(f"  config {ds.config_hash(best, space)}")

    print("\nA space with no fixed layout is refused by path:")
    show_refusal()


if __name__ == "__main__":
    main()
