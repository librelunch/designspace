"""Example 2 — Genetic Algorithm: choices, hierarchy, and cross-parameter rules.

A step up from the flat space: here the *structure* of the configuration
depends on the choices made. A Genetic Algorithm is assembled from operators
— a selection scheme, a crossover scheme, a mutation policy — and each operator
brings its own sub-parameters that only exist when that operator is chosen.

Concepts introduced here
------------------------
- ``.choice(...)`` variants: bare (parameterless) alongside parameterized ones
  whose payload is a nested ``ds.space(...)``. A chosen variant's parameters
  live under it and are absent otherwise.
- ``.prior(weights=...)`` biasing which variant the sampler favors.
- A cross-parameter ``.forbid(...)`` referencing a choice discriminator by
  equality (``ds.param("selection") == "tournament"``).
- Reading structured configs back with ``ds.variant`` / ``ds.payload`` /
  ``ds.destructure``.
- ``infeasibility_reasons(...)`` and interpreting ``evaluate_constraints``
  (hard *forbid* vs. declared *constrain*).

Run it:  ``uv run python examples/02_genetic_algorithm.py``
"""

from __future__ import annotations

import designspace as ds


def build_space() -> ds.Space:
    return (
        ds.space(
            # Population size on a grid of 10.
            ds.param("population_size").integer(20, 500).quantized(step=10),
            # The selection operator. Three interchangeable variant forms:
            # a bare variant (`roulette`) has no payload; the others carry a
            # nested space. Weights bias the sampler toward tournament.
            ds.param("selection")
            .choice(
                "roulette",
                tournament=ds.space(ds.param("tournament_size").integer(2, 10)),
                rank=ds.space(ds.param("rank_pressure").real(1.0, 2.0)),
            )
            .prior(weights=[1, 3, 2]),
            # The crossover operator — two bare variants and one parameterized.
            ds.param("crossover").choice(
                "one_point",
                "two_point",
                uniform=ds.space(ds.param("swap_prob").real(0.1, 0.9)),
            ),
            # Mutation rate spans decades -> log scale.
            ds.param("mutation_rate").real(1e-4, 0.5).log_scale(),
            # Adaptive mutation adds a decay knob, active only when enabled.
            ds.param("adaptive_mutation").bool(),
            ds.param("mutation_decay")
            .real(0.90, 0.999)
            .when(ds.param("adaptive_mutation")),
            # Elitism carries the fraction of the population preserved intact;
            # that fraction only exists when elitism is on.
            ds.param("elitism").bool(),
            ds.param("elite_fraction")
            .real(0.0, 0.3)
            .when(ds.param("elitism")),
        )
        # Feasibility: rank selection is O(n log n) per generation, so forbid
        # pairing it with a very large population. Note the discriminator
        # equality on a choice parameter.
        .forbid(
            (ds.param("population_size") > 400) & (ds.param("selection") == "rank"),
        )
        # A soft budget on mutation intensity — reported, never enforced.
        .constrain(
            ds.param("mutation_rate") <= 0.1,
            tags=("exploration-budget",),
        )
    )


def describe(config: dict[str, object]) -> str:
    """A one-line human summary of a sampled GA configuration."""
    sel_name, sel_payload = ds.destructure(config, "selection")
    sel = sel_name if sel_payload is None else f"{sel_name}{tuple(sel_payload.values())}"
    parts = [
        f"pop={config['population_size']}",
        f"select={sel}",
        f"cross={ds.variant(config, 'crossover')}",
        f"mut={config['mutation_rate']:.1e}",
    ]
    if config.get("adaptive_mutation"):
        parts.append(f"decay={config['mutation_decay']:.3f}")
    if config.get("elitism"):
        parts.append(f"elite={config['elite_fraction']:.2f}")
    return "  " + ", ".join(parts)


def main() -> None:
    space = build_space()
    print(f"Genetic Algorithm space: {space.n_params} parameters, "
          f"conditional={space.is_conditional}\n")

    # A batch of draws. Each sampled config activates a different set of
    # sub-parameters depending on the operators and flags chosen.
    print("Eight sampled GA configurations:")
    for cfg in space.sample_dicts(8, seed=0):
        print(describe(cfg))

    # Reading structured values back out. `ds.variant` names the active
    # branch; `ds.payload` returns its sub-config (None for a bare variant).
    print("\nInspecting one configuration's `selection` choice:")
    cfg = space.sample_one(seed=3)
    print(f"  raw value : {cfg['selection']!r}")
    print(f"  variant   : {ds.variant(cfg, 'selection')}")
    print(f"  payload   : {ds.payload(cfg, 'selection')}")

    # A deliberately infeasible config: rank selection on a huge population.
    print("\nA config that trips the feasibility rule:")
    bad = {
        "population_size": 500,
        "selection": {"rank": {"rank_pressure": 1.5}},
        "crossover": "one_point",
        "mutation_rate": 0.01,
        "adaptive_mutation": False,
        "elitism": False,
    }
    print(f"  is_feasible: {space.is_feasible(bad)}")
    for reason in space.infeasibility_reasons(bad):
        print(f"  reason: {reason}")

    # Hard (forbid) and declared (constrain) constraints, side by side, with
    # the meaning of `satisfied` spelled out for each kind.
    print("\nAll constraints on that config:")
    for ce in space.evaluate_constraints(bad):
        kind = "forbid " if ce.constraint.hard else "declare"
        tag = ", ".join(sorted(ce.constraint.tags)) or "-"
        if ce.constraint.hard:
            note = "VIOLATED (infeasible)" if ce.satisfied else "clear"
        else:
            note = "holds" if ce.satisfied else "below threshold"
        margin = f"{ce.margin:+.4f}" if ce.margin is not None else "  n/a "
        print(f"  {kind} [{tag:18}] satisfied={ce.satisfied!s:5} "
              f"margin={margin}  -> {note}")


if __name__ == "__main__":
    main()
