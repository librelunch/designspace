"""Thermal controller: structs, charts, and nested lifts.

A multi-stage thermal controller, built from a PID sub-record that always
exists, a variable-length stage schedule where each stage is its own small
space carrying its own per-element constraint, and a fixed 2x3 gain grid.
Examples 01 to 04 used ``.choice()`` for hierarchy; this one uses the plain
**struct param**, a grouping that is unconditionally present and never a
discriminated variant.

Concepts introduced
-------------------
- ``ds.param("pid").space(...)``, the **struct param** in its inline form: an
  unconditionally-present namespace, present in every config and contributing
  no discriminator.
- ``.space(prebuilt_space)``, the form a repeated struct needs whenever an
  element carries its own constraint, since the inline form has nowhere to hang
  a ``.forbid``. Here it holds each stage's own setpoint ceiling.
- Struct-lift aggregates. ``.field(name)`` projects the lift to one column, and
  ``.min()``, ``.max()``, ``.sum()``, ``.length()`` and ``.distinct(*fields)``
  apply to the result.
- Nested and variadic ``.repeat(2, 3)``, NumPy-shape sugar for
  ``.repeat(3).repeat(2)``, together with the instance-path forms that address
  it: ``gain_grid[0][1]`` for nested indices, ``bias[-1]`` for a negative index
  resolved against the realized length, and ``stages[0].hold_min`` for an
  instance index followed by a dotted struct field.
- **Expression bounds**. In ``ds.param("cap").integer(1, ds.param("n_stages"))``
  a bound is itself an ``ArithExpr``. It desugars at resolution to the widest
  static envelope plus an ordinary bound-origin constraint, making it sugar
  over existing machinery and not a new bound kind.
- Charts made explicit: ``periodic=True`` for a half-open wraparound domain,
  ``.quantized(factor=...)`` for a geometric grid against ``step=`` for a
  linear one, and the three built-in prior families spelled out as
  ``.prior(ds.Log())``, ``.prior(ds.Logit())`` and ``.prior(ds.Power(p))``,
  with ``.log_scale()`` named as sugar for the first.
- Element ``.default()``, which is pre-lift and count-independent, against list
  ``.default()``, which is post-lift and static-count only. They sit on
  different parameters so both forms appear.
- ``.anchor(configs=...)`` and ``.meta(...)``.
- Introspection that only a hierarchical, variable-length space shows:
  ``.subspaces``, ``.is_hierarchical`` and ``.has_variable_length``.

Run with ``uv run python examples/06_thermal_controller.py``.
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
            # Expression bound: `cap`'s upper bound is a parameter reference
            # and not a literal.
            ds.param("cap").integer(1, ds.param("n_stages")),
            # A half-open periodic domain: hi == lo under wraparound, so hi
            # itself is not a legal value.
            ds.param("phase_rad").real(0.0, TWO_PI, periodic=True),
            # A geometric (multiplicative) grid via `factor=`, against
            # `.quantized(step=...)`'s linear one. `ds.Power(p)` biases the
            # continuous measure that the grid then snaps.
            ds.param("gain").real(1.0, 1024.0).quantized(factor=2.0).prior(ds.Power(2.0)),
            # Element default (pre-lift): count-independent, so it is legal
            # even though `bias`'s own length (3) is static here.
            ds.param("bias").real(-1.0, 1.0).default(0.0).repeat(3),
            # Nested and variadic lift of shape (2, 3), read outermost first.
            # `.repeat(2, 3)` desugars to `.repeat(3).repeat(2)`.
            ds.param("gain_grid").real(0.0, 1.0).default(0.0).repeat(2, 3),
        )
        # Aggregate feasibility over the struct lift: total scheduled dwell
        # time is capped. `.field()` projects to a scalar lift and `.sum()`
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
        # The anchor's `bias` entry shows the list shape a post-lift default
        # would take. A list default is legal only because `bias`'s count (3)
        # is static, and it is mutually exclusive with an element default on
        # the same parameter, which is why the two sit on different ones.
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


def show_summary(space: ds.Space) -> None:
    print(
        f"Thermal controller space: {space.n_params} parameters, "
        f"hierarchical={space.is_hierarchical}, "
        f"variable_length={space.has_variable_length}\n"
    )


def show_sampling(space: ds.Space) -> None:
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

    # A struct param has no namespace of its own in the flattened form.
    # `.subspaces` reports it, and only a hierarchical space has any.
    print(f"\n.subspaces: {list(space.subspaces)}")


def show_constraints(space: ds.Space) -> None:
    config = space.sample_one(seed=0)
    print("\nConstraints (nested/negative/mixed instance paths, struct-lift aggregates):")
    for ce in space.evaluate_constraints(config):
        c = ce.constraint
        tag = ", ".join(sorted(c.tags)) or "-"
        margin = f"{ce.margin:+.3f}" if ce.margin is not None else "  n/a "
        print(
            f"  {c.kind:10}[{tag:20}] applicable={ce.applicable!s:5} "
            f"satisfied={ce.satisfied!s:5} margin={margin}"
        )


def show_expression_bounds(space: ds.Space) -> None:
    # Expression bounds are sugar. `cap`'s declared upper bound is a parameter
    # reference, and it desugars to the same envelope-plus-constraint shape a
    # hand-written `.forbid(cap > n_stages)` would produce.
    config = space.sample_one(seed=0)
    print(
        f"\ncap's declared bound tracks n_stages: cap={config['cap']} <= "
        f"n_stages={config['n_stages']}: {config['cap'] <= config['n_stages']}"
    )


def show_defaults_and_anchors(space: ds.Space) -> None:
    # `stages`' element default (setpoint_c=20.0) applies per instance, so it
    # can only fill anything once the count is known.
    print(
        "\napply_defaults({})['stages'] is unavailable until n_stages is known; "
        "element defaults fill each instance once the count is set"
    )
    partial = space.apply_defaults({"n_stages": 2})
    print(f"  apply_defaults({{'n_stages': 2}})['stages'] = {partial.get('stages')}")
    print(f"  anchors: {list(space.anchors)}")


def main() -> None:
    space = build_space()
    show_summary(space)
    show_sampling(space)
    show_constraints(space)
    show_expression_bounds(space)
    show_defaults_and_anchors(space)


if __name__ == "__main__":
    main()
