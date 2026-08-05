---
file_format: mystnb
---

# Structural operations

A `Space` is immutable. Every operation on this page returns a new one, leaving
the receiver untouched, which is what makes it safe to derive several variants
from a single declaration. The running example is the simulated annealing space
from [declaring a space](01-declaring-a-space.md).

```{code-cell}
import designspace as ds

space = (
    ds.space(
        ds.param("initial_temp").real(1e-2, 1e3).log_scale().tag("schedule"),
        ds.param("min_temp").real(1e-4, 1.0).log_scale().tag("schedule"),
        ds.param("cooling_rate").real(0.80, 0.999).quantized(step=0.005).tag("schedule"),
        ds.param("steps_per_temp").integer(1, 500),
        ds.param("neighborhood").categorical("swap", "insert", "reverse").tag("operator"),
        ds.param("reheat").bool(),
        ds.param("reheat_factor").real(1.5, 5.0).when(ds.param("reheat")),
    )
    .forbid(ds.param("min_temp") >= ds.param("initial_temp"))
    # References `neighborhood` and `steps_per_temp`, neither of which carries
    # the "schedule" tag. That matters for `.filter()` below.
    .forbid(
        ds.param("neighborhood").is_in("insert", "reverse")
        & (ds.param("steps_per_temp") < 5),
    )
    .encourage(ds.param("cooling_rate") >= 0.95, tags=("slow-cooling",))
)
space.n_params
```

## Pinning a parameter

`.freeze()` narrows a parameter's domain to a single value and **keeps** the
parameter. It stays present in every configuration, so a submitted config can
never disagree with the pinned value.

```{code-cell}
tuned = space.freeze(initial_temp=50.0, cooling_rate=0.85)
tuned.n_params, tuned.params["initial_temp"].domain
```

```{code-cell}
[(c["initial_temp"], c["cooling_rate"]) for c in tuned.sample_dicts(3, seed=0)]
```

The receiver is unchanged:

```{code-cell}
:tags: [remove-output]

assert space.params["initial_temp"].domain == ds.RealDomain(1e-2, 1e3)
assert space.n_params == tuned.n_params
```

## Removing a parameter

`.slice()` does the opposite: it **removes** the parameter and substitutes its
fixed value at every reference site.

```{code-cell}
no_reheat = space.slice(reheat=False)
no_reheat.n_params, "reheat" in no_reheat.params
```

`reheat_factor` stays declared, but its `.when(reheat)` condition has collapsed
to a constant, so it can never be sampled:

```{code-cell}
:tags: [remove-output]

assert "reheat_factor" in no_reheat.params
assert all("reheat_factor" not in c for c in no_reheat.sample_dicts(50, seed=0))
```

Slicing a count is how a variable-length space is fixed to one layout:

```{code-cell}
variable = ds.space(
    ds.param("n").integer(1, 5),
    ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
)
fixed = variable.slice(n=3)
fixed.has_variable_length, len(fixed.sample_one(seed=0)["xs"])
```

## Carving out a subtree

`.select(*paths)` keeps a definition-path prefix subtree. `.filter(tags=)` keeps
the parameters carrying a tag.

```{code-cell}
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    schedule_only = space.filter(tags=("schedule",))
list(schedule_only.params)
```

That emitted a warning, because one constraint references parameters outside the
kept set:

```{code-cell}
str(caught[0].message)
```

Dropping the constraint is the best-effort default. `strict=True` raises
instead, for cases where silently losing a rule would be unacceptable:

```{code-cell}
try:
    space.filter(tags=("schedule",), strict=True)
except ds.ResolutionError as exc:
    print(exc)
```

## Adding after the fact

`.extend()` is additive and takes the same builders as `ds.space()`.

```{code-cell}
with_logging = space.extend(ds.param("log_every_n").integer(1, 100))
with_logging.n_params, space.n_params
```

## Rewriting every parameter

`.map_params(fn)` passes each resolved `ParamDef` through a function. It reaches
parameters wherever they live, including inside a lifted choice's variant
payloads, so the caller does not need to know each path in advance.

```{code-cell}
from dataclasses import replace


def coarsen(pd):
    if isinstance(pd.domain, ds.RealDomain) and pd.quantized is None:
        return replace(pd, quantized=ds.QuantizedSpec(step=0.05, factor=None))
    return pd


coarsened = space.map_params(coarsen)
[p for p, pd in coarsened.params.items()
 if space.params[p].quantized is None and pd.quantized is not None]
```

## Dropping constraints by tag

`.without_constraints(tags=)` removes declared constraints.

```{code-cell}
relaxed = space.without_constraints(tags=("slow-cooling",))
len(relaxed.constraints), len(space.constraints)
```

## Where to go next

[Partial configs and driver loops](09-partial-configs.md) fills a configuration
one parameter at a time.
