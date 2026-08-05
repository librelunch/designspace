"""Genetic algorithm: choices, hierarchy, and cross-parameter rules.

A step up from the flat space of example 01: here the *structure* of the
configuration depends on the choices made. A genetic algorithm is assembled
from operators, one selection scheme, one crossover scheme and one mutation
policy, and each operator brings sub-parameters that exist only when that
operator is chosen.

Concepts introduced
-------------------
- ``.choice(...)`` variants: bare (parameterless) alongside parameterized ones
  whose payload is a nested ``ds.space(...)``. A chosen variant's parameters
  live under it and are absent otherwise.
- ``.prior(weights=...)``, biasing which variant the sampler favors.
- A cross-parameter ``.forbid(...)`` referencing a choice discriminator by
  equality (``ds.param("selection") == "tournament"``).
- ``.implies(other)``, a discriminator equality on one side of an implication,
  desugaring to ``~expr | other`` at resolution. It is used here inside an
  ``.encourage()``, whose declare-only rendering reads correctly at either
  polarity. A hard ``.require()`` needs the polarity-aware reading that
  example 03 introduces.
- Reading structured configs back with ``ds.variant``, ``ds.payload`` and
  ``ds.destructure``.
- ``infeasibility_reasons(...)`` and interpreting ``evaluate_constraints``,
  where a hard *forbid* and a declared *encourage* read at opposite polarity.
- ``.select(*paths)``: a definition-path prefix subtree of a built ``Space``.
  Selecting a choice brings its variants along.
- ``.active_subspace(config)``: the parameters active for one concrete,
  fully-materialized draw, with the conditional and choice structure collapsed
  to what that config uses.

Run with ``uv run python examples/02_genetic_algorithm.py``.
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
            # The crossover operator: two bare variants and one parameterized.
            ds.param("crossover").choice(
                "one_point",
                "two_point",
                uniform=ds.space(ds.param("swap_prob").real(0.1, 0.9)),
            ),
            # Mutation rate spans decades, so put it on a log scale.
            ds.param("mutation_rate").real(1e-4, 0.5).log_scale(),
            # Adaptive mutation adds a decay parameter, active only when enabled.
            ds.param("adaptive_mutation").bool(),
            ds.param("mutation_decay").real(0.90, 0.999).when(ds.param("adaptive_mutation")),
            # Elitism carries the fraction of the population preserved intact;
            # that fraction only exists when elitism is on.
            ds.param("elitism").bool(),
            ds.param("elite_fraction").real(0.0, 0.3).when(ds.param("elitism")),
        )
        # Feasibility: rank selection is O(n log n) per generation, so forbid
        # pairing it with a very large population. Note the discriminator
        # equality on a choice parameter.
        .forbid(
            (ds.param("population_size") > 400) & (ds.param("selection") == "rank"),
        )
        # A soft budget on mutation intensity, reported and never enforced.
        .encourage(
            ds.param("mutation_rate") <= 0.1,
            tags=("exploration-budget",),
        )
        # `.implies()`: rank selection has weak selective pressure, so this
        # prefers keeping elitism on to protect the best individual. That is a
        # preference, so `.encourage()` states it and `.require()` would not.
        .encourage(
            (ds.param("selection") == "rank").implies(ds.param("elitism")),
            tags=("rank-wants-elitism",),
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


def show_hierarchy(space: ds.Space) -> None:
    print(
        f"Genetic algorithm space: {space.n_params} parameters, "
        f"conditional={space.is_conditional}\n"
    )

    # A choice's payload-bearing variants are what make a space *hierarchical*.
    # Each relocates its own descendants under a definition-path prefix, and
    # `.subspaces` lists exactly those prefixes.
    print(f"is_hierarchical: {space.is_hierarchical}")
    print(f".subspaces: {list(space.subspaces)}\n")


def show_sampling(space: ds.Space) -> None:
    # A batch of draws. Each sampled config activates a different set of
    # sub-parameters depending on the operators and flags chosen.
    print("Eight sampled GA configurations:")
    for cfg in space.sample_dicts(8, seed=0):
        print(describe(cfg))


def show_choice_readback(space: ds.Space) -> None:
    # Reading structured values back out. `ds.variant` names the active branch;
    # `ds.payload` returns its sub-config, or None for a bare variant.
    print("\nInspecting one configuration's `selection` choice:")
    cfg = space.sample_one(seed=3)
    print(f"  raw value : {cfg['selection']!r}")
    print(f"  variant   : {ds.variant(cfg, 'selection')}")
    print(f"  payload   : {ds.payload(cfg, 'selection')}")


def show_infeasibility(space: ds.Space) -> None:
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

    # `evaluate_constraints` returns forbids and declared constraints together.
    # Mind the polarity: a forbid's `satisfied` refers to its *forbidden*
    # predicate, so `satisfied=True` means the forbidden state holds and the
    # config is infeasible. Forbids are therefore rendered as feasibility here,
    # and the raw satisfied/margin pair is kept only for `.encourage()`, where a
    # positive margin means slack.
    print("\nAll constraints on that config:")
    for ce in space.evaluate_constraints(bad):
        tag = ", ".join(sorted(ce.constraint.tags)) or "-"
        if ce.constraint.hard:
            if not ce.applicable:
                verdict = "inapplicable (Unknown)"
            elif ce.satisfied:
                verdict = "TRIPPED  -> infeasible"
            else:
                verdict = "clear    -> feasible"
            print(f"  forbid  [{tag:18}] {verdict}")
        else:
            margin = f"{ce.margin:+.4f}" if ce.margin is not None else "  n/a "
            print(f"  declare [{tag:18}] satisfied={ce.satisfied!s:5} margin={margin}")


def show_select(space: ds.Space) -> None:
    # Deploying a reduced variant that only ever uses the `selection` operator
    # family. `.select()` keeps the definition-path prefix subtree, so selecting
    # a choice brings its variants (tournament, rank) along and not just the
    # bare discriminator. This emits a UserWarning: the
    # `population_size > 400 & selection == "rank"` forbid, the
    # `mutation_rate <= 0.1` encourage and the `rank-wants-elitism` encourage
    # each reference at least one parameter outside the "selection" subtree, so
    # `.select()`'s best-effort default drops all three and warns. Pass
    # `strict=True` where silently losing a constraint would be unacceptable.
    selection_only = space.select("selection")
    print(f"\nselect('selection'): {list(selection_only.params)}")


def show_active_subspace(space: ds.Space) -> None:
    # Given one concrete, fully-materialized draw, which parameters did it
    # actually use? Inactive branches, meaning the unchosen crossover and
    # selection variants and mutation_decay/elite_fraction when their flags are
    # off, disappear from the returned Space entirely.
    cfg = space.sample_one(seed=5)
    active = space.active_subspace(cfg)
    print(f"\nactive_subspace(...) for one draw ({describe(cfg).strip()}):")
    print(f"  {active.n_params} of {space.n_params} declared params active: {list(active.params)}")


def main() -> None:
    space = build_space()
    show_hierarchy(space)
    show_sampling(space)
    show_choice_readback(space)
    show_infeasibility(space)
    print("\n--- Structural operations ---")
    show_select(space)
    show_active_subspace(space)


if __name__ == "__main__":
    main()
