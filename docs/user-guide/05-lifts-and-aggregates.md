---
file_format: mystnb
---

# Lifts and aggregates

A **lift** turns one parameter definition into a list of independent copies.
When the count is itself a parameter, the configuration's length becomes part of
what is searched. This page builds the operator pipeline of a memetic
algorithm, which interleaves evolutionary operators with local-search
refinement.

## Repeating a parameter

`.repeat(count)` takes a literal count or a parameter reference.

```{code-cell}
import designspace as ds

space = ds.space(
    ds.param("n_stages").integer(2, 4),
    ds.param("intensity").real(0.01, 5.0).log_scale().repeat(ds.param("n_stages")),
    ds.param("bias").real(-1.0, 1.0).repeat(3),
)
config = space.sample_one(seed=0)
config
```

`n_stages` is drawn first, because the count references it and so joins the
dependency graph:

```{code-cell}
space.topological_order
```

```{code-cell}
:tags: [remove-output]

for c in space.sample_dicts(50, seed=1):
    assert len(c["intensity"]) == c["n_stages"]
    assert len(c["bias"]) == 3
```

A literal count is *static* and a parameter-driven one is *dynamic*. The space
reports which it has:

```{code-cell}
space.has_variable_length
```

## Instance paths

Elements are addressed by index. That is what a per-element constraint or an
error message names.

```{code-cell}
sorted(ds.flatten(config, space))
```

Indices may be negative, resolved against the realized length:

```{code-cell}
space = space.encourage(ds.param("intensity[-1]") <= 0.5, tags=("gentle-finish",))
ce = space.evaluate_constraints(config)[-1]
ce.constraint.kind, ce.satisfied, round(ce.margin, 4)
```

## Aggregates over a scalar lift

An aggregate collapses the whole list to one value, so a rule can range over
elements without naming them.

```{code-cell}
space = ds.space(
    ds.param("n_stages").integer(3, 3),
    ds.param("intensity").real(0.01, 5.0).repeat(ds.param("n_stages")),
).require(
    ds.param("intensity").distinct(),
).encourage(
    ds.param("intensity").is_sorted(descending=True), tags=("cooling",),
).encourage(
    ds.param("intensity").sum() <= 8.0, tags=("budget",),
)
config = space.sample_one(seed=0)
[round(x, 3) for x in config["intensity"]]
```

```{code-cell}
[(ce.constraint.kind, ", ".join(ce.constraint.tags) or "-", ce.satisfied)
 for ce in space.evaluate_constraints(config)]
```

`.length()`, `.min()` and `.max()` complete the set:

```{code-cell}
probe = ds.space(
    ds.param("n").integer(2, 5),
    ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
).encourage(
    (ds.param("xs").max() <= 0.9) & (ds.param("xs").min() >= 0.1),
    tags=("range",),
).require(ds.param("xs").length() >= 2)
probe.sample_one(seed=3)["n"]
```

## Lifting a choice

Repeating a choice gives a heterogeneous list: bare strings and payload dicts
side by side.

```{code-cell}
op = ds.param("pipeline").choice(
    "shuffle",
    mutation=ds.space(ds.param("rate").real(0.01, 0.5)),
    local_search=ds.space(ds.param("iters").integer(1, 100)),
)
space = ds.space(
    ds.param("n_ops").integer(2, 5),
    op.repeat(ds.param("n_ops")),
).forbid(ds.param("pipeline").count_of("local_search") < 1)
config = space.sample_one(seed=0)
config["pipeline"]
```

`.count_of(variant)` counts matching variants across the lift, which is what
the forbid above uses to require at least one local-search step.

```{code-cell}
:tags: [remove-output]

for c in space.sample_dicts(100, seed=2):
    n_local = sum(
        1 for op in c["pipeline"] if isinstance(op, dict) and "local_search" in op
    )
    assert n_local >= 1
```

## Lifting a struct

A repeated struct gives a list of records. `.field(name)` projects it to one
column, after which the scalar aggregates apply.

```{code-cell}
stage = ds.space(
    ds.param("setpoint_c").real(15.0, 30.0),
    ds.param("hold_min").integer(5, 120),
)
space = ds.space(
    ds.param("n_stages").integer(2, 4),
    ds.param("stages").space(stage).repeat(ds.param("n_stages")),
).encourage(
    ds.param("stages").field("hold_min").sum() <= 200, tags=("dwell-budget",),
)
config = space.sample_one(seed=0)
config["stages"]
```

```{code-cell}
ce = space.evaluate_constraints(config)[0]
ce.satisfied, ce.margin
```

A mixed instance-then-field path addresses one field of one element:

```{code-cell}
sorted(ds.flatten(config, space))[:4]
```

## Nested lifts

`.repeat(2, 3)` is shape sugar for `.repeat(3).repeat(2)`, read outermost
first.

```{code-cell}
grid = ds.space(ds.param("gain_grid").real(0.0, 1.0).repeat(2, 3))
config = grid.sample_one(seed=0)
[[round(x, 3) for x in row] for row in config["gain_grid"]]
```

```{code-cell}
:tags: [remove-output]

assert len(config["gain_grid"]) == 2
assert all(len(row) == 3 for row in config["gain_grid"])
```

## Where to go next

[Custom types and properties](06-custom-types.md) covers values no built-in
type can express.
