---
file_format: mystnb
---

# Declaring a space

A design space is declared once and then queried. This page builds the
configuration surface of a simulated annealing metaheuristic, covering its
cooling schedule, its move operator and its acceptance rule, and shows what the
resulting `Space` reports about itself.

## Parameter types

`ds.param(name)` opens a declaration and the next call fixes the type. Five
scalar types cover most spaces.

```{code-cell}
import designspace as ds

space = ds.space(
    ds.param("initial_temp").real(1e-2, 1e3),
    ds.param("steps_per_temp").integer(1, 500),
    ds.param("neighborhood").categorical("swap", "insert", "reverse"),
    ds.param("acceptance").ordinal("greedy", "boltzmann", "metropolis"),
    ds.param("reheat").bool(),
)
list(space.params)
```

`real` and `integer` take numeric bounds. `categorical` is unordered and
compared by equality only; `ordinal` is ordered by declaration, which is what
makes a comparison such as `>= "boltzmann"` meaningful.

The space reports its own shape without being sampled:

```{code-cell}
space.n_params, space.is_conditional, space.is_finite
```

## Resolved parameters

`ds.space(...)` resolves the builders into `ParamDef` records. That resolved
form is the introspection surface, and it is what a solver walks.

```{code-cell}
space.params["acceptance"]
```

Each field is worth knowing. `type_kind` is the discriminator, `domain` holds
the declared values, and `chart` is the coordinate system covered below. The
rest carry the modifiers, which are all unset here.

```{code-cell}
space.params["acceptance"].domain
```

## Modifiers

Modifiers chain onto a typed parameter. Most of them change its coordinate
system rather than its domain.

`.log_scale()` gives a quantity spanning orders of magnitude a multiplicative
geometry, so uniform sampling is uniform per decade. `.quantized(step=)` snaps a
continuous parameter to a linear grid, and `.quantized(factor=)` to a geometric
one. `.tag()` labels a parameter for later filtering.

```{code-cell}
space = ds.space(
    ds.param("initial_temp").real(1e-2, 1e3).log_scale().tag("schedule"),
    ds.param("min_temp").real(1e-4, 1.0).log_scale().tag("schedule"),
    ds.param("cooling_rate").real(0.80, 0.999).quantized(step=0.005).tag("schedule"),
    ds.param("steps_per_temp").integer(1, 500),
    ds.param("neighborhood").categorical("swap", "insert", "reverse").tag("operator"),
    ds.param("acceptance").ordinal("greedy", "boltzmann", "metropolis").tag("operator"),
)
space.params["cooling_rate"].quantized
```

```{code-cell}
sorted(space.params["initial_temp"].tags)
```

## Charts

Every generative scalar parameter resolves to a **chart**, a monotone map from
`[0, 1]` onto the domain. The chart is what carries the prior, and it is what
gives a solver type-appropriate perturbation: mutate in `[0, 1]`, then decode.

```{code-cell}
temp = space.params["initial_temp"].chart
[round(temp.from_unit(u), 4) for u in (0.0, 0.25, 0.5, 0.75, 1.0)]
```

The midpoint is the geometric mean rather than the arithmetic one, because the
parameter declared a log scale. An unscaled parameter over the same bounds
splits the interval evenly instead:

```{code-cell}
linear = ds.space(ds.param("x").real(1e-2, 1e3)).params["x"].chart
[round(linear.from_unit(u), 4) for u in (0.0, 0.25, 0.5, 0.75, 1.0)]
```

The map runs both ways, so an existing configuration can be lifted back into
coordinate space to seed a search:

```{code-cell}
round(temp.to_unit(1.0), 6)
```

```{code-cell}
:tags: [remove-output]

# A log chart decodes its endpoints to within float error of the declared
# bounds rather than exactly, since it round-trips through log10.
assert abs(temp.from_unit(0.0) - 1e-2) < 1e-9
assert abs(temp.from_unit(1.0) - 1e3) < 1e-9
# The round-trip in the other direction is exact.
assert temp.to_unit(temp.from_unit(0.25)) == 0.25
```

## Priors

`.log_scale()` is sugar for `.prior(ds.Log())`. The three built-in families can
also be named directly, and `weights=` biases a discrete parameter.

```{code-cell}
priors = ds.space(
    ds.param("kp").real(0.1, 10.0).prior(ds.Log()),
    ds.param("ki").real(0.001, 0.999).prior(ds.Logit()),
    ds.param("gain").real(1.0, 1024.0).prior(ds.Power(2.0)),
    ds.param("mode").categorical("fast", "balanced", "thorough").prior(weights=[1, 3, 2]),
)
{name: pd.prior for name, pd in priors.params.items()}
```

A prior changes the chart, and therefore where uniform coordinate draws land:

```{code-cell}
{
    name: round(priors.params[name].chart.from_unit(0.5), 4)
    for name in ("kp", "ki", "gain")
}
```

## Where to go next

[Sampling and validation](02-sampling-and-validation.md) draws from this space
and checks configurations against it.
