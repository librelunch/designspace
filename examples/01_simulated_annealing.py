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
  ``.constrain(...)`` only annotates (it is reported, never enforced).

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
            ds.param("initial_temp").real(1e-2, 1e3).log_scale(),
            ds.param("min_temp").real(1e-4, 1.0).log_scale(),
            # Geometric cooling factor, snapped to a 0.005 grid.
            ds.param("cooling_rate").real(0.80, 0.999).quantized(step=0.005),
            # Inner-loop length: how many moves at each temperature.
            ds.param("steps_per_temp").integer(1, 500),
            # The neighborhood move. Categorical: unordered, compared by
            # equality only.
            ds.param("neighborhood").categorical("swap", "insert", "reverse"),
            # The acceptance rule. Ordinal: ordered by declaration, so
            # comparisons like ``>= "boltzmann"`` are meaningful.
            ds.param("acceptance").ordinal("greedy", "boltzmann", "metropolis"),
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
        # A soft preference, not a rule: flag schedules that cool aggressively.
        # Declared constraints never change feasibility or the sampler; they
        # ride along in ``evaluate_constraints`` with a signed margin so a
        # consumer can weigh them however it likes.
        .constrain(
            ds.param("cooling_rate") >= 0.95,
            tags=("slow-cooling",),
        )
    )


def main() -> None:
    space = build_space()
    print(f"Simulated Annealing space: {space.n_params} parameters, "
          f"conditional={space.is_conditional}\n")

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


if __name__ == "__main__":
    main()
