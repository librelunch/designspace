"""Racing a solver configuration over a set of instances, with irace.

irace owns the loop: a caller hands it a function that scores one configuration on one
instance rather than asking it for a configuration to score.

The space consists of a local-search solver whose strategy is a variant choice, with
the parameters of each strategy conditional on it. Two of its constraints have no
forbidden clause form. One compares two parameters, the other multiplies a parameter
by another, and irace parses conditions as R, so both reach the race as expressions.

Needs R 4.5 or later and the R package irace, version 4.4 or later. Install R, then
run ``Rscript -e "install.packages('irace', repos='https://cloud.r-project.org')"``.

Run with ``uv run python packages/designspace-solvers/examples/irace_racing.py``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from designspace_solvers.irace import Experiment, Scenario, run, translate

import designspace as ds

MAX_EXPERIMENTS = 1000
SEED = 0


@dataclass(frozen=True)
class Instance:
    """One problem to solve, as a race sees it.

    An instance reaches the target function unchanged, so it is whatever a
    caller wants: a file path, a loaded problem, or a description like this
    one.
    """

    name: str
    size: int
    ruggedness: float


INSTANCES = (
    Instance("smooth-40", 40, 0.05),
    Instance("smooth-90", 90, 0.20),
    Instance("mixed-60", 60, 0.40),
    Instance("mixed-120", 120, 0.60),
    Instance("rugged-50", 50, 0.80),
    Instance("rugged-100", 100, 0.95),
)


def build_space() -> ds.Space:
    """A local-search solver whose strategy brings its own parameters."""
    return (
        ds.space(
            ds.param("strategy").choice(
                annealing=ds.space(
                    ds.param("t_start").real(0.1, 100.0).log_scale(),
                    ds.param("t_end").real(1e-4, 1.0).log_scale(),
                    ds.param("cooling").ordinal("slow", "medium", "fast"),
                ),
                tabu=ds.space(
                    ds.param("tenure").integer(2, 50),
                    ds.param("aspiration").bool(),
                ),
            ),
            ds.param("restarts").integer(1, 20),
            ds.param("moves").subset(["swap", "insert", "reverse", "shift"], min_size=1),
            ds.param("perturb").real(0.0, 1.0),
        )
        # An annealing schedule that ends above where it starts is not a
        # schedule. The predicate compares two parameters, which a forbidden
        # clause has no form for and an R expression does.
        .forbid(
            ds.param("strategy.annealing.t_end") >= ds.param("strategy.annealing.t_start"),
            tags=("temperature_order",),
        )
        # Restarts multiply the work a perturbation costs, and the two
        # together have a budget the run has to stay inside.
        .forbid(
            ds.param("restarts") * ds.param("perturb") > 12.0,
            tags=("effort_budget",),
        )
    )


def solve(config: dict[str, Any], instance: Instance, seed: int) -> float:
    """Stand-in for running the configured solver on one instance.

    Returns the cost of the solution found, lower being better. A real target
    function runs the solver and returns what it scored; this one computes a
    cost with the shape a racing benchmark has. Which settings suit an
    instance depends on the instance, so a configuration that wins on one
    corner of the set gives ground on another, and the run is noisy, so one
    comparison decides nothing and racing has work to do.

    The seed comes from irace, which draws one per experiment. Reseeding from
    it is what makes a rerun of the same configuration and instance repeat.
    """
    rng = random.Random(seed)
    rugged = instance.ruggedness
    cost = float(instance.size)

    payload = ds.payload(config, "strategy")
    if ds.variant(config, "strategy") == "annealing":
        # Which strategy suits an instance is what the set disagrees about.
        # Annealing pays off above the midpoint of ruggedness and tabu below
        # it, by the same margin, so neither wins the set on its own.
        cost -= 0.5 * instance.size * (rugged - 0.5)
        # A wide temperature range searches more of the landscape.
        span = math.log10(payload["t_start"] / payload["t_end"])
        cost -= 0.05 * instance.size * span
        # Slow cooling escapes a local optimum and costs time doing it.
        slowness = 2 - ("slow", "medium", "fast").index(payload["cooling"])
        cost += 0.10 * instance.size * (1.0 - rugged) * slowness
        cost -= 0.10 * instance.size * rugged * slowness
    else:
        cost -= 0.5 * instance.size * (0.5 - rugged)
        # Tabu search wants a tenure scaled to the instance, and aspiration
        # earns its keep where the landscape is smooth enough to exploit.
        cost += 0.8 * abs(payload["tenure"] - instance.size / 6.0)
        cost -= 0.10 * instance.size if payload["aspiration"] and rugged < 0.5 else 0.0

    # More move types help on a rugged landscape and cost time everywhere.
    cost -= 3.0 * len(config["moves"]) * rugged
    cost += 1.2 * len(config["moves"])
    # Restarts have diminishing returns, and a mild perturbation beats none.
    cost -= 6.0 * math.log1p(config["restarts"])
    cost += 20.0 * (config["perturb"] - 0.2) ** 2

    return cost + rng.gauss(0.0, 0.06 * instance.size)


def report_translation(space: ds.Space) -> None:
    """Show what irace is handed, before a race is started.

    A translation holds no R objects, only the text of one, so it can be read
    on a machine with no R installed at all.
    """
    translation = translate(space)

    print("\nParameters, under the names irace resolves:")
    for spec in translation.params:
        transform = f" [{spec.transf}]" if spec.transf else ""
        condition = f"  | {spec.condition}" if spec.condition else ""
        print(f"  {spec.name:32s} {spec.type} {spec.domain}{transform}{condition}")

    print("\nForbidden, as R:")
    for expression in translation.forbidden:
        print(f"  {expression}")

    untranslated = [c.kind for c in translation.untranslated_constraints]
    print(f"\nConstraints irace never saw: {untranslated or 'none'}")


def race(space: ds.Space) -> list[dict[str, Any]]:
    """Hand irace the target function and let it drive."""
    scored = 0

    def evaluate(config: dict[str, Any], experiment: Experiment) -> float:
        nonlocal scored
        scored += 1
        return solve(config, experiment.instance, experiment.seed)

    elites = run(
        space,
        evaluate,
        Scenario(max_experiments=MAX_EXPERIMENTS, instances=INSTANCES, seed=SEED),
    )
    print(f"\nThe race scored {scored} configuration-instance pairs.")
    return elites


def main() -> None:
    space = build_space()
    print(space)
    report_translation(space)

    elites = race(space)

    print(f"\n{len(elites)} elite configurations survived the race. The best of them:")
    best = elites[0]
    print(ds.pretty(best, space))

    # An inactive parameter is absent rather than filled, so the report says
    # which of them the winning configuration never reached.
    inactive = [p for p, status in space.param_activity(best).items() if status == "inactive"]
    print(f"\nInactive in this configuration: {', '.join(inactive) or 'none'}")

    # Why the race spends its budget across a set rather than on one problem.
    # The elites are close on the whole set and pull apart across it, so which
    # one is best is a question the set answers and no single instance does.
    print("\nWhat each elite scores per instance, averaged over five seeds:")
    profiles = [
        [sum(solve(elite, instance, seed) for seed in range(5)) / 5.0 for instance in INSTANCES]
        for elite in elites
    ]
    for rank, profile in enumerate(profiles, start=1):
        summary = "  ".join(f"{i.name}={c:7.2f}" for i, c in zip(INSTANCES, profile, strict=True))
        print(f"  {rank}. {summary}")

    winners = [
        min(range(len(elites)), key=lambda rank: profiles[rank][column]) + 1
        for column in range(len(INSTANCES))
    ]
    print("\nBest elite on each instance:")
    for instance, rank in zip(INSTANCES, winners, strict=True):
        print(f"  {instance.name:12s} elite {rank}")

    print("\nObservation key:")
    print(f"  space  {space.fingerprint()}")
    print(f"  config {ds.config_hash(best, space)}")


if __name__ == "__main__":
    main()
