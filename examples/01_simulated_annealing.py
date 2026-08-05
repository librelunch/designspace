"""Simulated annealing: a flat parameter space.

The simplest shape a design space takes: independent scalar parameters, one
conditional parameter, and two space-level rules. The space below describes the
configuration surface of a simulated annealing metaheuristic, covering its
cooling schedule, its move operator, and its acceptance rule.

Concepts introduced
-------------------
- Scalar parameter types: ``real``, ``integer``, ``categorical``, ``ordinal``,
  ``bool``.
- Priors as coordinate systems. ``.log_scale()`` gives multiplicative geometry
  to a temperature spanning orders of magnitude; ``.quantized()`` snaps a
  continuous parameter to a grid.
- A conditional parameter via ``.when(...)``. Inactive parameters are absent
  from a config, never ``None``.
- ``.forbid(...)`` defines feasibility and the reference sampler respects it.
  ``.encourage(...)`` annotates only: it is reported, never enforced.
- ``.is_in(*values)``, a forbid naming a set of move choices at once.
- Structural operations on a built ``Space``. ``.freeze(...)`` pins a parameter
  to one value and keeps it, narrowing its domain. ``.slice(...)`` removes the
  parameter and substitutes its value at every reference site.
  ``.filter(tags=...)`` carves out a tagged subspace. ``.extend(...)`` adds a
  parameter after the fact.

Notes
-----
Examples 01 to 04 grow the shape of a space. Examples 05 to 10 hold the shape
plain and grow the vocabulary applied to it: the full expression language,
charts, DataFrame output, sampling diagnostics, the partial-config driver-loop
surface, and metaprogramming.

Run with ``uv run python examples/01_simulated_annealing.py``.
"""

from __future__ import annotations

import designspace as ds


def build_space() -> ds.Space:
    return (
        ds.space(
            # Temperatures span orders of magnitude, so search them in log
            # space: a solver perturbing the u-coordinate gets multiplicative
            # noise, and uniform sampling is uniform *per decade*.
            ds.param("initial_temp").real(1e-2, 1e3).log_scale().tag("schedule"),
            ds.param("min_temp").real(1e-4, 1.0).log_scale().tag("schedule"),
            # Geometric cooling factor, snapped to a 0.005 grid.
            ds.param("cooling_rate").real(0.80, 0.999).quantized(step=0.005).tag("schedule"),
            # Inner-loop length: how many moves at each temperature.
            ds.param("steps_per_temp").integer(1, 500),
            # The neighborhood move. Categorical: unordered, compared by
            # equality only.
            ds.param("neighborhood").categorical("swap", "insert", "reverse").tag("operator"),
            # The acceptance rule. Ordinal: ordered by declaration, so
            # comparisons like ``>= "boltzmann"`` are meaningful.
            ds.param("acceptance").ordinal("greedy", "boltzmann", "metropolis").tag("operator"),
            # Whether to reheat on stagnation, and if so by how much.
            ds.param("reheat").bool(),
            ds.param("reheat_factor").real(1.5, 5.0).when(ds.param("reheat")),
        )
        # Feasibility: annealing must cool, so the stopping temperature has to
        # sit strictly below the starting one. A forbid rejects the bad region
        # outright, and the sampler never emits a config that trips it.
        .forbid(
            ds.param("min_temp") >= ds.param("initial_temp"),
        )
        # `.is_in()` names a set of values at once: insert/reverse moves
        # only pay off with a long enough inner loop, so forbid pairing
        # either with a very short one.
        .forbid(
            ds.param("neighborhood").is_in("insert", "reverse") & (ds.param("steps_per_temp") < 5),
        )
        # A declared preference: flag schedules that cool aggressively.
        # Declared constraints never change feasibility or the sampler. They
        # ride along in ``evaluate_constraints`` with a signed margin, so a
        # consumer can weigh them as it sees fit.
        .encourage(
            ds.param("cooling_rate") >= 0.95,
            tags=("slow-cooling",),
        )
    )


def show_summary(space: ds.Space) -> None:
    print(
        f"Simulated annealing space: {space.n_params} parameters, "
        f"conditional={space.is_conditional}\n"
    )


def show_sampling(space: ds.Space) -> None:
    # One reproducible draw from the declared measure.
    config = space.sample_one(seed=0)
    print("A sampled configuration:")
    for key, value in config.items():
        print(f"  {key:16} = {value!r}")

    # Feasibility is parameter validity plus forbids, and nothing else.
    print(f"\nis_feasible: {space.is_feasible(config)}")
    print(f"validate().valid: {space.validate(config).valid}")

    # The flat, path-keyed view. The same grammar appears everywhere: DataFrame
    # columns, expression references, error messages.
    print("\nFlattened (path-keyed) view:")
    for key, value in ds.flatten(config, space).items():
        print(f"  {key:16} = {value!r}")


def show_conditional_activity(space: ds.Space) -> None:
    # Inactive means absent. Across a batch of draws, reheat_factor appears
    # only where reheat came out True.
    print("\nConditional activity of `reheat_factor` across 8 draws:")
    for cfg in space.sample_dicts(8, seed=1):
        present = "reheat_factor" in cfg
        print(f"  reheat={cfg['reheat']!s:5} -> reheat_factor present: {present}")


def show_declared_constraints(space: ds.Space) -> None:
    # The declared constraint, reported with its margin. A positive margin is
    # slack.
    config = space.sample_one(seed=0)
    print("\nDeclared constraints on the sampled config:")
    for ce in space.evaluate_constraints(config):
        if not ce.constraint.hard:  # skip the forbid; show the annotation
            tag = ", ".join(sorted(ce.constraint.tags))
            print(f"  [{tag}] satisfied={ce.satisfied} margin={ce.margin:+.4f}")


def show_freeze(space: ds.Space) -> None:
    # A search on this problem class found a good schedule. Pinning it leaves
    # only the operator and acceptance parameters to search. `.freeze()` keeps
    # the parameter, so it is still present in every config, and narrows its
    # domain to the single value; a submitted config can never disagree with
    # it. `.slice()` below does the opposite.
    tuned = space.freeze(initial_temp=50.0, cooling_rate=0.85)
    print(
        f"\nfreeze(initial_temp=50.0, cooling_rate=0.85): still {tuned.n_params} params "
        f"(kept, domain narrowed):"
    )
    for cfg in tuned.sample_dicts(8, seed=2):
        print(
            f"  initial_temp={cfg['initial_temp']}, cooling_rate={cfg['cooling_rate']}, "
            f"neighborhood={cfg['neighborhood']!r}"
        )


def show_slice(space: ds.Space) -> None:
    # Reheating never paid off in practice, so remove it permanently.
    # `.slice()` removes the parameter and substitutes its fixed value at every
    # reference site. `reheat_factor`'s `.when(reheat)` condition collapses to a
    # constant (`False == False`), so it stays declared and can never be
    # sampled.
    no_reheat = space.slice(reheat=False)
    still_absent = all("reheat_factor" not in c for c in no_reheat.sample_dicts(20, seed=3))
    print(
        f"\nslice(reheat=False): {no_reheat.n_params} params (down from {space.n_params}); "
        f"reheat_factor never sampled: {still_absent}"
    )


def show_filter_and_extend(space: ds.Space) -> None:
    # Just the cooling schedule, for a report that only discusses those
    # parameters. This emits a UserWarning: the neighborhood/steps_per_temp
    # forbid references parameters outside the "schedule" subtree, so
    # `.filter()`'s best-effort default drops it and warns. `strict=True` would
    # raise instead. `.select()` uses the same best-effort mechanism and
    # `examples/02_genetic_algorithm.py` covers it in depth.
    schedule_only = space.filter(tags=("schedule",))
    print(f"\nfilter(tags=('schedule',)): {list(schedule_only.params)}")

    # A parameter added after the fact. `.extend()` is additive; `ds.space()`
    # with no new parameters would be the identity.
    with_logging = space.extend(ds.param("log_every_n").integer(1, 100))
    print(f"\nextend(log_every_n): {with_logging.n_params} params (was {space.n_params})")


def main() -> None:
    space = build_space()
    show_summary(space)
    show_sampling(space)
    show_conditional_activity(space)
    show_declared_constraints(space)
    print("\n--- Structural operations ---")
    show_freeze(space)
    show_slice(space)
    show_filter_and_extend(space)


if __name__ == "__main__":
    main()
