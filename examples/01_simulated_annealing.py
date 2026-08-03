"""Example 1 — Simulated Annealing: a flat parameter space.

The simplest shape a design space takes: a handful of independent scalar
knobs, one conditional knob, and two space-level rules. This is the
configuration surface of a Simulated Annealing metaheuristic — its cooling
schedule, its move operator, and its acceptance rule.

Concepts introduced here
------------------------
- Scalar parameter types: ``real``, ``integer``, ``categorical``, ``ordinal``,
  ``bool``.
- Priors as coordinate systems: ``.log_scale()`` (multiplicative geometry for
  a temperature that spans orders of magnitude) and ``.quantized()`` (snap a
  continuous knob to a grid).
- A single conditional parameter via ``.when(...)`` — inactive parameters are
  simply *absent* from a config, never ``None``.
- ``.forbid(...)`` defines feasibility (the reference sampler respects it);
  ``.encourage(...)`` only annotates (it is reported, never enforced).
- ``.is_in(*values)`` — a forbid naming a set of move choices at once.
- Structural operations on an already-built ``Space``: ``.freeze(...)`` pins
  tuned knobs to a single value (kept, domain narrowed) after a search;
  ``.slice(...)`` removes a rejected knob entirely, substituting its value at
  every reference site; ``.filter(tags=...)`` carves out a tagged
  sub-space; ``.extend(...)`` adds a new knob after the fact.

This example (and 02-04) grows the *shape* of a space. Examples 05-08 hold
the shape plain and grow the *vocabulary* used on it instead — the full
expression language, charts, DataFrame output, sampling diagnostics, the
partial-config driver-loop surface, and metaprogramming.

Run it:  ``uv run python examples/01_simulated_annealing.py``
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
            # Whether to reheat on stagnation, and — only then — by how much.
            ds.param("reheat").bool(),
            ds.param("reheat_factor").real(1.5, 5.0).when(ds.param("reheat")),
        )
        # Feasibility: annealing must cool, so the stopping temperature has to
        # sit strictly below the starting one. A forbid rejects the bad region
        # outright — the sampler will never emit a config that trips it.
        .forbid(
            ds.param("min_temp") >= ds.param("initial_temp"),
        )
        # `.is_in()` names a set of values at once: insert/reverse moves
        # only pay off with a long enough inner loop, so forbid pairing
        # either with a very short one.
        .forbid(
            ds.param("neighborhood").is_in("insert", "reverse") & (ds.param("steps_per_temp") < 5),
        )
        # A soft preference, not a rule: flag schedules that cool aggressively.
        # Declared constraints never change feasibility or the sampler; they
        # ride along in ``evaluate_constraints`` with a signed margin so a
        # consumer can weigh them however it likes.
        .encourage(
            ds.param("cooling_rate") >= 0.95,
            tags=("slow-cooling",),
        )
    )


def main() -> None:
    space = build_space()
    print(
        f"Simulated Annealing space: {space.n_params} parameters, "
        f"conditional={space.is_conditional}\n"
    )

    # One reproducible draw from the declared measure.
    config = space.sample_one(seed=0)
    print("A sampled configuration:")
    for key, value in config.items():
        print(f"  {key:16} = {value!r}")

    # Feasibility is param-validity plus forbids — nothing else.
    print(f"\nis_feasible: {space.is_feasible(config)}")
    print(f"validate().valid: {space.validate(config).valid}")

    # The flat, path-keyed view (same grammar used everywhere: columns,
    # references, error messages).
    print("\nFlattened (path-keyed) view:")
    for key, value in ds.flatten(config, space).items():
        print(f"  {key:16} = {value!r}")

    # "Inactive means absent": draw until we see the reheat branch both on and
    # off, and note that reheat_factor only appears when reheat is True.
    print("\nConditional activity of `reheat_factor` across 8 draws:")
    for cfg in space.sample_dicts(8, seed=1):
        present = "reheat_factor" in cfg
        print(f"  reheat={cfg['reheat']!s:5} -> reheat_factor present: {present}")

    # The declared constraint, reported with its margin (positive = slack).
    print("\nDeclared constraints on the sampled config:")
    for ce in space.evaluate_constraints(config):
        if not ce.constraint.hard:  # skip the forbid; show the annotation
            tag = ", ".join(sorted(ce.constraint.tags))
            print(f"  [{tag}] satisfied={ce.satisfied} margin={ce.margin:+.4f}")

    # -- Structural operations: reshaping an already-built Space -------------
    print("\n--- Structural operations ---")

    # A search on this problem class found a good schedule -- pin it and keep
    # searching only the operator/acceptance knobs. Unlike .slice(), .freeze()
    # KEEPS the param (still present in every config) but narrows its domain
    # to that single value, so a submitted config can never disagree with it.
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

    # Reheating never paid off in practice -- remove it permanently. .slice()
    # REMOVES the param and substitutes its fixed value at every reference
    # site; reheat_factor's `.when(reheat)` condition collapses to a constant
    # (`False == False`), so it stays declared but can never be sampled.
    no_reheat = space.slice(reheat=False)
    still_absent = all("reheat_factor" not in c for c in no_reheat.sample_dicts(20, seed=3))
    print(
        f"\nslice(reheat=False): {no_reheat.n_params} params (down from {space.n_params}); "
        f"reheat_factor never sampled: {still_absent}"
    )

    # Just the cooling schedule, for a report that only discusses those knobs.
    # This *does* print a UserWarning: the `neighborhood`/`steps_per_temp`
    # forbid references params outside the "schedule" subtree, so `.filter()`'s
    # best-effort default drops it and warns rather than raising (`strict=True`
    # would raise instead) -- the same best-effort mechanism `.select()` uses,
    # covered in depth in `examples/02_genetic_algorithm.py`.
    schedule_only = space.filter(tags=("schedule",))
    print(f"\nfilter(tags=('schedule',)): {list(schedule_only.params)}")

    # A knob added after the fact. `.extend()` is additive; `ds.space()` (no
    # new params) would be the identity.
    with_logging = space.extend(ds.param("log_every_n").integer(1, 100))
    print(f"\nextend(log_every_n): {with_logging.n_params} params (was {space.n_params})")


if __name__ == "__main__":
    main()
