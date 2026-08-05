# Solver portfolio

The first six examples look at one config at a time. This one looks at the
space as a whole: what a batch of draws reports before the space is trusted,
and what the introspection surface reports without drawing anything at all.

Source: `examples/07_portfolio_observability.py`. Run it with
`uv run python examples/07_portfolio_observability.py`.

## Declaring the space

Two lifts differ in one respect that the DataFrame output makes visible.
`weights` has a literal count and `checkpoints` has a parameter-driven one.

```{literalinclude} ../../examples/07_portfolio_observability.py
:pyobject: build_space
```

## DataFrame output

`space.sample(n)` returns a `polars.DataFrame` and needs the `polars` extra;
`sample_dicts` and `sample_one` need no extra and are unaffected.

The dtype table appears here in full: `Boolean`, `Float64` and `Int64` for
scalars, a `Utf8` discriminator plus one nullable `Struct` per parameterized
choice variant, `Array(dtype, n)` for a static-count scalar lift against
`List(dtype)` for a dynamic-count one, and null for every inactive cell, since
the dict-config "absent" convention has no columnar analogue.

`reject_soft=True` additionally rejects declared violations. It is off by
default.

```{literalinclude} ../../examples/07_portfolio_observability.py
:pyobject: show_dataframe
```

## Sampling diagnostics

`sampling_report()` draws from the *unconditioned* measure, before rejection,
which is what keeps two pathologies visible that `sample()`'s output hides.

`ConstraintReport.satisfied` is a raw fraction and is not polarity-resolved.
Reading a table of mixed verbs by `satisfied` alone means re-deriving the flip
for every row. `violation_rate` is the polarity-resolved reading, the aggregate
analogue of `ConstraintEval.violated`, and means "unhealthy fraction"
regardless of which verb produced the row.

```{literalinclude} ../../examples/07_portfolio_observability.py
:pyobject: show_sampling_report
```

## Diffing two configurations

```{literalinclude} ../../examples/07_portfolio_observability.py
:pyobject: show_config_diff
```

## Introspection without sampling

`weights` carries no default anywhere, including on its own static-count lift.
The Defaults cascade leaves it implicit entirely, since `apply_defaults` emits
only default values. That matches a dynamic-count lift of the same shape, and
is not an error just because this count happens to be a literal.

```{literalinclude} ../../examples/07_portfolio_observability.py
:pyobject: show_introspection
```

## Fingerprint scopes

```{literalinclude} ../../examples/07_portfolio_observability.py
:pyobject: show_fingerprint_scopes
```
