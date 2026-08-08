---
file_format: mystnb
---

# Partial configs and driver loops

A configuration does not have to arrive all at once. A wizard-style UI, or a
solver that asks one question at a time, builds one incrementally and needs to
know at each step what is still open and what is already determined. This page
uses a pump configurator, whose impeller diameter is bounded by the flow rate
that was actually assigned.

```{code-cell}
import designspace as ds

space = (
    ds.space(
        ds.param("flow_rate_lpm").real(100.0, 500.0),
        # An expression bound: the upper limit is a parameter reference.
        ds.param("impeller_diameter_mm").real(20.0, ds.param("flow_rate_lpm")),
        ds.param("num_stages").integer(1, 5),
        ds.param("seal_type").categorical("mechanical", "packing", "magnetic"),
        ds.param("certifications").subset(("CE", "UL", "ATEX"), min_size=0),
        ds.param("stage_order").permutation(("intake", "boost", "discharge")),
        ds.param("vibration_profile").real(0.0, 1.0).repeat(4),
    )
    .forbid(ds.param("seal_type") == "packing")
    .forbid(
        (ds.param("seal_type") == "magnetic")
        & ds.param("certifications").contains("ATEX"),
    )
)
space.n_params
```

## Defaults

A default is a per-parameter fill value. `apply_defaults` completes whatever is
missing and leaves supplied values alone.

```{code-cell}
defaulted = ds.space(
    ds.param("workers").integer(1, 16).default(4),
    ds.param("batch").integer(8, 512).default(32),
)
defaulted.apply_defaults({"workers": 12})
```

`apply_defaults` fills parameters and does not consult constraints, so its
output can be infeasible. That is deliberate: filling and validating are
separate steps, and the library does not guess which parameter to move.

```{code-cell}
conflicting = ds.space(
    ds.param("a").integer(0, 10).default(9),
    ds.param("b").integer(0, 10).default(9),
).forbid(ds.param("a") + ds.param("b") > 10)
filled = conflicting.apply_defaults({})
filled, conflicting.validate(filled).valid, conflicting.is_feasible(filled)
```

## What is open

`param_activity` classifies every parameter for a partial configuration.

```{code-cell}
space.param_activity({})
```

`evaluate_partial` reports how much is left and which constraints can already
be judged.

```{code-cell}
pe = space.evaluate_partial({"seal_type": "mechanical"})
pe.n_remaining, len(pe.evaluable_constraints), len(pe.pending_constraints)
```

## What values remain

`remaining_domain` narrows one parameter's domain given what is already
assigned. It returns one of five descriptor kinds.

```{code-cell}
space.remaining_domain("flow_rate_lpm", {})
```

The expression bound tightens once the parameter it references is known:

```{code-cell}
space.remaining_domain("impeller_diameter_mm", {"flow_rate_lpm": 300.0})
```

A forbid over a single unset operand reduces fully, so `packing` is already
excluded:

```{code-cell}
space.remaining_domain("seal_type", {})
```

The other two kinds:

```{code-cell}
space.remaining_domain("certifications", {"seal_type": "magnetic"})
```

```{code-cell}
space.remaining_domain("stage_order", {})
```

`remaining_domain` is **sound but not complete**: it never excludes a value that
is still feasible, but it does not reduce every constraint. The compound forbid
above is a conjunction across two parameters, which is not the single-unset-
operand shape it reduces, so `ATEX` is still listed as available.

## Validating one value in context

`validate_param` checks a value on its own. Where a constraint depends on
another parameter, it is omitted as under-determined rather than guessed:

```{code-cell}
space.validate_param("impeller_diameter_mm", 350.0).valid
```

Supplying the context evaluates it:

```{code-cell}
space.validate_param(
    "impeller_diameter_mm", 350.0, context={"flow_rate_lpm": 300.0}
).valid
```

## The driver loop

`next_assignable` names what can be assigned now, `is_complete` says when to
stop, and `missing_params` reports what is still absent.

```{code-cell}
target = space.sample_one(seed=0)
flat = ds.flatten(target, space)

partial = {}
steps = []
while not space.is_complete(partial):
    path = space.next_assignable(partial)[0]
    if "[" in path:
        # A lift's instances become assignable together, once the count is
        # known: the nested form has no slot for a partly-filled list.
        path = path[: path.index("[")]
        partial[path] = target[path]
    else:
        partial[path] = flat[path]
    steps.append(path)
steps
```

```{code-cell}
space.is_complete(partial), space.missing_params(partial), space.is_feasible(partial)
```

## Positional vectors

Where a space is **fixed-layout**, meaning every count is static and no
parameter carries a condition, `coordinate_paths()` gives the flat keys that are
coordinates, in a stable order.

```{code-cell}
paths = space.coordinate_paths()
paths
```

That is enough to pack a configuration into a vector and back:

```{code-cell}
vector = [flat[p] for p in paths]
restored = ds.unflatten(dict(zip(paths, vector, strict=True)), space)
restored == target
```

Deriving that key set by hand fails silently, because a hand-rolled filter
cannot tell a coordinate from a count-bookkeeping entry without walking the
`ListDomain` chain. The method is undefined where the layout depends on the
configuration, and says so rather than returning a set that would be wrong for
some draws:

```{code-cell}
conditional = ds.space(
    ds.param("flag").bool(),
    ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
)
try:
    conditional.coordinate_paths()
except ds.ResolutionError as exc:
    print(exc)
```

## Where to go next

[Diagnostics and DataFrames](10-diagnostics-and-dataframes.md) looks at a space
in aggregate rather than one configuration at a time.
