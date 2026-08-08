---
file_format: mystnb
---

# Diagnostics and DataFrames

The previous pages look at one configuration at a time. This one looks at a
space in aggregate: what a batch of draws reports before the space is trusted,
and what a columnar view of those draws looks like. The running example is a
solver portfolio.

```{code-cell}
import designspace as ds

SOLVERS = ("cplex", "gurobi", "heuristic")

space = (
    ds.space(
        ds.param("enabled_solvers").subset(SOLVERS, min_size=1),
        ds.param("solver_mode").choice(
            "single",
            ensemble=ds.space(ds.param("n_workers").integer(2, 8)),
        ),
        ds.param("priority").ordinal("low", "normal", "high"),
        ds.param("warm_start").bool(),
        ds.param("warm_start_frac").real(0.05, 0.9).when(ds.param("warm_start")),
        ds.param("time_limit_s").integer(10, 3600),
        # A static count gives an Array column; a dynamic one gives a List.
        ds.param("weights").real(-1.0, 1.0).repeat(4),
        ds.param("n_checkpoints").integer(0, 3),
        ds.param("checkpoints").real(0.0, 1.0).repeat(ds.param("n_checkpoints")),
    )
    .encourage(
        ds.param("warm_start_frac") + ds.param("time_limit_s") / 3600.0 <= 1.0,
        tags=("budget-unguarded",),
    )
    .encourage(
        ds.param("warm_start_frac").if_inactive(0.0)
        + ds.param("time_limit_s") / 3600.0 <= 1.0,
        tags=("budget-guarded",),
    )
)
space.n_params
```

## Columnar output

`space.sample(n)` returns a `polars.DataFrame` and needs the `polars` extra.
`sample_dicts` and `sample_one` need no extra and are unaffected.

```{code-cell}
df = space.sample(6, seed=0)
df
```

The dtype table is visible in the schema. Scalars map to `Boolean`, `Float64`
and `Int64`; a choice becomes a `Utf8` discriminator plus one nullable `Struct`
per parameterized variant; a static-count lift becomes `Array(dtype, n)` and a
dynamic-count one becomes `List(dtype)`.

```{code-cell}
dict(df.schema)
```

An inactive parameter has no columnar analogue for the dict form's "absent", so
it becomes null:

```{code-cell}
df.select("warm_start", "warm_start_frac")
```

`reject_soft=True` additionally rejects declared violations. It is off by
default, since declared constraints do not affect feasibility.

```{code-cell}
space.sample(6, seed=0, reject_soft=True).height
```

## Sampling diagnostics

`sampling_report()` draws from the **unconditioned** measure, before any
rejection, and aggregates what happened. Drawing unconditioned is the point:
two pathologies are invisible once rejection has hidden them.

```{code-cell}
report = space.sampling_report(n=500, seed=0)
round(report.acceptance_rate, 3)
```

```{code-cell}
for row in report.constraints:
    tags = ", ".join(sorted(row.constraint.tags)) or "-"
    print(f"{row.constraint.kind:10} [{tags:18}] "
          f"applicable={row.applicable:.3f} satisfied={row.satisfied:.3f} "
          f"violation_rate={row.violation_rate:.3f}")
```

## Unknown-swallowing

A constraint that cannot be evaluated is *inapplicable*, and inapplicable means
**accepted**. That is the permissive direction, and it is silent.

The two budget constraints above are the same aggregate over the same draws,
differing only in the guard. The unguarded one goes Unknown wherever
`warm_start` is off; its `.if_inactive(0.0)` twin stays evaluable throughout.

```{code-cell}
{
    ", ".join(row.constraint.tags): round(row.applicable, 3)
    for row in report.constraints
}
```

```{code-cell}
:tags: [remove-output]

by_tag = {", ".join(r.constraint.tags): r for r in report.constraints}
assert by_tag["budget-guarded"].applicable == 1.0
assert by_tag["budget-unguarded"].applicable < 1.0
```

`applicable` is the only signal that this is happening. Nothing in `sample()`'s
output would report it.

```{code-cell}
round(report.activity["warm_start_frac"], 3)
```

`activity` gives the fraction of draws in which each parameter was active,
which is what the unguarded constraint's `applicable` is tracking.

## Funnels

Unknown-swallowing has a second consequence beyond a constraint quietly not
enforcing. A constraint that is inapplicable on part of the space biases the
conditioned measure *toward* that part, since rejection accepts those draws
unconditionally.

This is what `require` is defined to do: it conditions the declared measure.
The effect is not visible from the resulting sample, which is the reason the
report draws unconditioned.

## Reading the report correctly

`satisfied` is conditioned on **applicability**, not on all draws. A constraint
applicable in 1% of draws and always satisfied there reports `1.0`, not `0.01`.
The pair is read together: `applicable` says how often the question was asked,
`satisfied` how often the answer was yes.

`satisfied` is also raw, so it means opposite things for opposite verbs.
`violation_rate` folds the polarity in and always means the unhealthy fraction,
whichever verb produced the row.

## Bound tightening

The reference sampler can fold an already-assigned bound-origin coupling into
the draw instead of drawing and rejecting. For `sample()` that is unobservable,
since truncation and conditioning agree. For a *report* it is observable, which
is why it defaults to off: on a bound-coupled space it would collapse exactly
the rows most likely to carry a pathology.

```{code-cell}
tightened = space.sampling_report(n=500, seed=0, tighten_bounds=True)
round(report.acceptance_rate, 3), round(tightened.acceptance_rate, 3)
```

This space has no bound-origin coupling to tighten, so the two agree. The three
sampling entry points take no such flag at all, because tightening cannot change
the distribution they return.

## Comparing two configurations

```{code-cell}
a = space.sample_one(seed=0)
b = space.sample_one(seed=1)
[(d.param, d.old, d.new) for d in ds.config_diff(a, b, space)][:5]
```

## Where to go next

[Identity, serialization and solver hand-off](11-identity-and-solvers.md)
covers what a consumer stores and how it plugs in.
