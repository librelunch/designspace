# Simulated annealing

The simplest shape a design space takes: independent scalar parameters, one
conditional parameter, and two space-level rules. The space describes the
configuration surface of a simulated annealing metaheuristic, covering its
cooling schedule, its move operator and its acceptance rule.

Source: `examples/01_simulated_annealing.py`. Run it with
`uv run python examples/01_simulated_annealing.py`.

## Declaring the space

Five scalar types appear here. `real` and `integer` carry numeric bounds,
`categorical` is unordered and compared by equality only, `ordinal` is ordered
by declaration so `>= "boltzmann"` is meaningful, and `bool` gates the one
conditional parameter.

Two modifiers shape the coordinate system rather than the domain.
`.log_scale()` gives a temperature spanning orders of magnitude a
multiplicative geometry, so uniform sampling is uniform per decade.
`.quantized(step=)` snaps a continuous parameter to a linear grid.

The two rules use different verbs. `.forbid()` defines feasibility and the
reference sampler respects it, so no sampled config ever trips one.
`.encourage()` annotates: it is reported with a signed margin and never
enforced.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: build_space
```

## Sampling and the flattened view

`sample_one` draws one configuration from the declared measure. `is_feasible`
is parameter validity plus forbids, and nothing else. `ds.flatten` re-keys the
same config by instance path, which is the grammar DataFrame columns,
expression references and error messages all use.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: show_sampling
```

## Conditional activity

An inactive parameter is absent from the config, not present and null. Across a
batch of draws, `reheat_factor` appears only where `reheat` came out `True`.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: show_conditional_activity
```

## Declared constraints

`evaluate_constraints` returns both verbs. A declared constraint carries a
signed margin, where a positive value is slack.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: show_declared_constraints
```

## Reshaping a built space

`.freeze()` pins a parameter to one value and keeps it. The parameter is still
present in every config and its domain is narrowed to that single value, so a
submitted config cannot disagree with it.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: show_freeze
```

`.slice()` does the opposite: it removes the parameter and substitutes its
fixed value at every reference site. Here `reheat_factor`'s `.when(reheat)`
condition collapses to a constant, so it stays declared and can never be
sampled.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: show_slice
```

`.filter(tags=)` carves out a tagged subtree and `.extend()` adds a parameter
after the fact. Filtering emits a `UserWarning` here, because one forbid
references parameters outside the `schedule` subtree and the best-effort
default drops it. Passing `strict=True` raises instead.

```{literalinclude} ../../examples/01_simulated_annealing.py
:pyobject: show_filter_and_extend
```
