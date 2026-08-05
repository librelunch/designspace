# Thermal controller

Examples 01 to 04 used `.choice()` for hierarchy. This one uses the plain
**struct param**, a grouping that is unconditionally present and never a
discriminated variant, alongside explicit charts and nested lifts.

Source: `examples/06_thermal_controller.py`. Run it with
`uv run python examples/06_thermal_controller.py`.

## Declaring the space

`ds.param("pid").space(...)` in its inline form is a namespace present in every
config, contributing no discriminator. `.space(prebuilt_space)` is the form a
repeated struct needs whenever an element carries its own constraint, since the
inline form has nowhere to hang a `.forbid`.

`.repeat(2, 3)` is NumPy-shape sugar for `.repeat(3).repeat(2)`, read outermost
first. Three instance-path forms address the result: `gain_grid[0][1]` for
nested indices, `bias[-1]` for a negative index resolved against the realized
length, and `stages[0].hold_min` for an instance index followed by a struct
field.

`ds.param("cap").integer(1, ds.param("n_stages"))` is an **expression bound**.
It desugars at resolution to the widest static envelope plus an ordinary
bound-origin constraint, so it is sugar over existing machinery and not a new
bound kind.

Three chart controls appear explicitly. `periodic=True` gives a half-open
wraparound domain where `hi` equals `lo` and is therefore not itself legal.
`.quantized(factor=)` gives a geometric grid, against `step=` for a linear one.
The three built-in prior families are spelled out as `ds.Log()`, `ds.Logit()`
and `ds.Power(p)`, with `.log_scale()` named as sugar for the first.

Element `.default()` is pre-lift and count-independent; list `.default()` is
post-lift and static-count only. The two are mutually exclusive on one
parameter, so they sit on different ones.

```{literalinclude} ../../examples/06_thermal_controller.py
:pyobject: build_space
```

## Sampling

A struct param has no namespace of its own in the flattened form. `.subspaces`
reports it, and only a hierarchical space has any.

```{literalinclude} ../../examples/06_thermal_controller.py
:pyobject: show_sampling
```

## Struct-lift aggregates and instance paths

`.field(name)` projects a struct lift to one column, after which `.min()`,
`.max()`, `.sum()`, `.length()` and `.distinct(*fields)` apply.

```{literalinclude} ../../examples/06_thermal_controller.py
:pyobject: show_constraints
```

## Expression bounds hold at runtime

```{literalinclude} ../../examples/06_thermal_controller.py
:pyobject: show_expression_bounds
```

## Defaults and anchors

An element default applies per instance, so it fills nothing until the count is
known.

```{literalinclude} ../../examples/06_thermal_controller.py
:pyobject: show_defaults_and_anchors
```
