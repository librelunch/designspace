"""Example 6 — Thermal Controller: structs, charts, and nested lifts.

A multi-stage thermal controller: a PID sub-record that always exists, a
variable-length stage schedule (each stage is its own little space, with its
own per-element constraint), and a fixed 2x3 gain grid. Where examples 1-4
used ``.choice()`` for hierarchy, this one uses the plain **struct param** —
grouping that is unconditionally present, never a discriminated variant.

Concepts introduced here
-------------------------
- ``ds.param("pid").space(...)`` — the **struct param**, inline form: an
  unconditionally-present namespace, present in every config, contributing
  no discriminator.
- ``.space(prebuilt_space)`` — the form a repeated struct needs whenever an
  element carries its own constraint (the inline form has nowhere to hang
  a ``.forbid``): here, each stage's own setpoint ceiling.
- Struct-lift aggregates: ``.field(name)`` projects the lift to one column,
  then ``.min()`` / ``.max()`` / ``.sum()`` / ``.length()`` /
  ``.distinct(*fields)``.
- Nested and variadic ``.repeat(2, 3)`` (numpy-shape sugar for
  ``.repeat(3).repeat(2)``), and the instance-path forms that address it:
  ``gain_grid[0][1]`` (nested indices), ``bias[-1]`` (negative, resolved
  against the realized length), and ``stages[0].hold_min`` (mixed: an
  instance index followed by a dotted struct field).
- **Expression bounds**: ``ds.param("cap").integer(1, ds.param("n_stages"))``
  — a bound may itself be an ``ArithExpr``; it desugars at resolution to the
  widest static envelope plus an ordinary bound-origin constraint, so it is
  sugar, not a new bound kind.
- Charts made explicit: ``periodic=True`` (a half-open wraparound domain),
  ``.quantized(factor=...)`` (a geometric grid, vs. ``step=`` for a linear
  one), and the three built-in prior families spelled out —
  ``.prior(ds.Log())``, ``.prior(ds.Logit())``, ``.prior(ds.Power(p))`` —
  with ``.log_scale()`` named as sugar for the first.
- Element ``.default()`` (pre-lift, count-independent) vs. list
  ``.default()`` (post-lift, static-count only) — used on different params
  so both forms appear.
- ``.anchor(configs=...)`` and ``.meta(...)``.
- Introspection that only a hierarchical, variable-length space shows:
  ``.subspaces``, ``.is_hierarchical``, ``.has_variable_length``.

Run it:  ``uv run python examples/06_thermal_controller.py``

See ``examples/README.md`` for the full feature -> example index.
"""

from __future__ import annotations

import designspace as ds

TWO_PI = 6.283185307179586


def build_space() -> ds.Space:
    # One stage of the schedule, as a prebuilt Space so it can carry its own
    # feasibility rule: a stage may not run above 28C.
    stage = ds.space(
        ds.param("setpoint_c").real(15.0, 30.0).default(20.0),  # element default
        ds.param("hold_min").integer(5, 120),
    ).forbid(
        ds.param("setpoint_c") > 28.0,
    )

    return (
        ds.space(
            # Inline struct param: always present, no discriminator.
            ds.param("pid").space(
                ds.param("kp").real(0.1, 10.0).log_scale(),  # sugar for .prior(ds.Log())
                ds.param("ki").real(0.001, 0.999).prior(ds.Logit()),
            ),
            ds.param("n_stages").integer(2, 4),
            # Prebuilt-Space struct lift: each stage instantiates `stage`,
            # including its own forbid, once per element.
            ds.param("stages").space(stage).repeat(ds.param("n_stages")),
            # Expression bound: `cap`'s upper bound is itself a param
            # reference, not a literal.
            ds.param("cap").integer(1, ds.param("n_stages")),
            # A half-open periodic domain: hi == lo under wraparound, so hi
            # itself is not a legal value.
            ds.param("phase_rad").real(0.0, TWO_PI, periodic=True),
            # A geometric (multiplicative) grid via `factor=`, as opposed to
            # `.quantized(step=...)`'s linear one; `ds.Power(p)` biases the
            # continuous measure the grid then snaps.
            ds.param("gain").real(1.0, 1024.0).quantized(factor=2.0).prior(ds.Power(2.0)),
            # Element default (pre-lift): count-independent, so it is legal
            # even though `bias`'s own length (3) is static here.
            ds.param("bias").real(-1.0, 1.0).default(0.0).repeat(3),
            # Nested + variadic lift: shape (2, 3), read outermost-first —
            # `.repeat(2, 3)` desugars to `.repeat(3).repeat(2)`.
            ds.param("gain_grid").real(0.0, 1.0).default(0.0).repeat(2, 3),
        )
        # Aggregate feasibility over the struct lift: total scheduled dwell
        # time is capped. `.field()` projects to a scalar lift; `.sum()`
        # flattens across every active instance.
        .encourage(
            ds.param("stages").field("hold_min").sum() <= 200,
            tags=("dwell-budget",),
        )
        .encourage(
            ds.param("stages").field("hold_min").max() <= 90,
            tags=("max-single-hold",),
        )
        .encourage(
            ds.param("stages").field("setpoint_c").min() >= 16.0,
            tags=("min-setpoint",),
        )
        .require(
            ds.param("stages").length() >= 2,
        )
        .encourage(
            ds.param("stages").distinct("setpoint_c"),
            tags=("distinct-setpoints",),
        )
        # Instance-path constraints: nested indices, negative indexing, and
        # a mixed instance-then-field path, all in the same space.
        .encourage(
            ds.param("gain_grid[0][1]") > 0.1,
            tags=("nested-index",),
        )
        .encourage(
            ds.param("bias[-1]") < 0.5,
            tags=("negative-index",),
        )
        .encourage(
            ds.param("stages[0].hold_min") > 10,
            tags=("mixed-index",),
        )
        # List default (post-lift), legal only because `bias`'s count (3)
        # is static -- mutually exclusive with an element default on the
        # same param, which is why it sits on a *different* one.
        .anchor(
            configs={
                "shipped": {
                    "pid": {"kp": 1.0, "ki": 0.1},
                    "n_stages": 2,
                    "stages": [
                        {"setpoint_c": 20.0, "hold_min": 10},
                        {"setpoint_c": 22.0, "hold_min": 15},
                    ],
                    "cap": 1,
                    "phase_rad": 0.0,
                    "gain": 1.0,
                    "bias": [0.0, 0.0, 0.0],
                    "gain_grid": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                },
            },
        )
        .meta(owner="controls", ticket="TC-9")
    )


def main() -> None:
    space = build_space()
    print(
        f"Thermal Controller space: {space.n_params} parameters, "
        f"hierarchical={space.is_hierarchical}, "
        f"variable_length={space.has_variable_length}\n"
    )

    config = space.sample_one(seed=0)
    print("A sampled configuration:")
    print(f"  pid        = {config['pid']!r}")
    print(f"  n_stages   = {config['n_stages']}, cap = {config['cap']}")
    for i, s in enumerate(config["stages"]):
        print(f"  stages[{i}]  = {s!r}")
    print(f"  phase_rad  = {config['phase_rad']:.4f}  (in [0, 2*pi))")
    print(f"  gain       = {config['gain']}  (on a factor=2.0 geometric grid)")
    print(f"  bias       = {[round(b, 3) for b in config['bias']]}")
    print(f"  gain_grid  = {[[round(x, 3) for x in row] for row in config['gain_grid']]}")

    # A struct param has no namespace of its own in the flattened form --
    # subspaces reports it, and only a hierarchical space has any.
    print(f"\n.subspaces: {list(space.subspaces)}")

    print("\nConstraints (nested/negative/mixed instance paths, struct-lift aggregates):")
    for ce in space.evaluate_constraints(config):
        c = ce.constraint
        tag = ", ".join(sorted(c.tags)) or "-"
        margin = f"{ce.margin:+.3f}" if ce.margin is not None else "  n/a "
        print(
            f"  {c.kind:10}[{tag:20}] applicable={ce.applicable!s:5} "
            f"satisfied={ce.satisfied!s:5} margin={margin}"
        )

    # Expression bounds are sugar: `cap`'s declared upper bound is a param
    # reference, but it desugars to the same envelope-plus-constraint shape
    # a hand-written `.forbid(cap > n_stages)` would produce.
    print(
        f"\ncap's declared bound tracks n_stages: cap={config['cap']} <= "
        f"n_stages={config['n_stages']}: {config['cap'] <= config['n_stages']}"
    )

    # Defaults: `stages`' element default (setpoint_c=20.0) applies
    # per-instance; the shipped anchor demonstrates the list-default shape
    # for a static-count lift (`bias`), derived rather than duplicated.
    print(
        "\napply_defaults({})['stages']: n/a until n_stages is known "
        "-- element defaults fill each instance once the count is set"
    )
    partial = space.apply_defaults({"n_stages": 2})
    print(f"  apply_defaults({{'n_stages': 2}})['stages'] = {partial.get('stages')}")
    print(f"  anchors: {list(space.anchors)}")


if __name__ == "__main__":
    main()
