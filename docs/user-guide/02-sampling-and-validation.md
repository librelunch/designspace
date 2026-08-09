---
file_format: mystnb
---

# Sampling and validation

A declared space answers two questions: what configurations does it produce,
and is a given configuration one of them. This page continues with the
simulated annealing space from
[declaring a space](01-declaring-a-space.md).

```{code-cell}
import designspace as ds

space = ds.space(
    ds.param("initial_temp").real(1e-2, 1e3).log_scale(),
    ds.param("min_temp").real(1e-4, 1.0).log_scale(),
    ds.param("cooling_rate").real(0.80, 0.999).quantized(step=0.005),
    ds.param("steps_per_temp").integer(1, 500),
    ds.param("neighborhood").categorical("swap", "insert", "reverse"),
    ds.param("acceptance").ordinal("greedy", "boltzmann", "metropolis"),
).forbid(ds.param("min_temp") >= ds.param("initial_temp"))
print(space)
```

## One draw

`sample_one` returns a plain nested dict. The seed makes it reproducible.

```{code-cell}
config = space.sample_one(seed=0)
config
```

A config can be pretty-printed against its space using `pretty`, showing each
value beside the domain it satisfies.

```{code-cell}
print(ds.pretty(config, space))
```

`cooling_rate` lands on the declared grid, and the two temperatures respect the
forbid, because the sampler rejects any draw that trips a hard constraint.

```{code-cell}
config["min_temp"] < config["initial_temp"]
```

## Many draws

`sample_dicts` returns a list of the same shape.

```{code-cell}
batch = space.sample_dicts(5, seed=1)
[c["neighborhood"] for c in batch]
```

Since the forbid holds by construction, it holds across the whole batch:

```{code-cell}
:tags: [remove-output]

assert all(c["min_temp"] < c["initial_temp"] for c in space.sample_dicts(200, seed=2))
```

## Validation

`validate` checks a configuration against the space and returns a
`ValidationResult` rather than raising.

```{code-cell}
result = space.validate(config)
result.valid
```

A configuration outside a domain reports which parameter and why. Nothing is
clamped: an out-of-range value is an error, never a rounded input.

```{code-cell}
bad = dict(config, steps_per_temp=9999)
space.validate(bad).param_errors
```

`validate_param` checks a single value without needing a whole configuration:

```{code-cell}
space.validate_param("acceptance", "simulated").param_errors
```

## Feasibility

`validate` covers two separate things: whether each value is legal for its
parameter, and whether the constraints hold. `valid` is the conjunction, so it
is false if either fails, and the two halves of the result are what tell them
apart.

```{code-cell}
# Both values sit inside their own domains; it is the pair that is illegal.
infeasible = dict(config, initial_temp=0.05, min_temp=0.5)
result = space.validate(infeasible)
result.valid, result.param_errors
```

Every value is in range, so `param_errors` is empty; the forbid is what makes
`valid` false. `is_feasible` asks only the constraint half of that question:

```{code-cell}
space.is_feasible(infeasible)
```

```{code-cell}
:tags: [remove-output]

# A malformed config and a well-formed but infeasible one both report
# valid=False, and `param_errors` is what distinguishes them.
assert space.validate(infeasible).param_errors == ()
assert space.validate(bad).param_errors != ()
```

`infeasibility_reasons` names what failed:

```{code-cell}
space.infeasibility_reasons(infeasible)
```

## The flattened view

A configuration is nested, matching the declaration. `ds.flatten` re-keys it by
instance path, which is the grammar DataFrame columns, expression references and
error messages all use.

```{code-cell}
ds.flatten(config, space)
```

`ds.unflatten` reverses it exactly:

```{code-cell}
ds.unflatten(ds.flatten(config, space), space) == config
```

## Where to go next

[Conditionality and structure](03-conditionality-and-structure.md) makes the
set of parameters depend on the values drawn.
