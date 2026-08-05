# Genetic algorithm

A step up from the flat space: the *structure* of the configuration depends on
the choices made. A genetic algorithm is assembled from operators, and each
operator brings sub-parameters that exist only when that operator is chosen.

Source: `examples/02_genetic_algorithm.py`. Run it with
`uv run python examples/02_genetic_algorithm.py`.

## Declaring the space

`.choice()` accepts two variant forms side by side. A bare string names a
parameterless variant; a keyword argument names one whose payload is a nested
`ds.space(...)`. `.prior(weights=)` biases which variant the sampler favors.

The discriminator is a parameter in its own right, so a constraint can compare
it by equality. `.implies(other)` desugars to `~expr | other` at resolution.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: build_space
```

## Hierarchy

A choice's payload-bearing variants are what make a space *hierarchical*. Each
relocates its own descendants under a definition-path prefix, and `.subspaces`
lists exactly those prefixes.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: show_hierarchy
```

## Sampling

Each draw activates a different set of sub-parameters, depending on the
operators and flags chosen.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: show_sampling
```

The summary line comes from a helper that reads a structured config apart with
`ds.destructure` and `ds.variant`:

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: describe
```

## Reading a choice back

`ds.variant` names the active branch and `ds.payload` returns its sub-config,
or `None` for a bare variant. `ds.destructure` returns both in one call.
Reading a choice this way rather than by indexing keeps the code independent of
the nesting convention.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: show_choice_readback
```

## Infeasibility and constraint polarity

`evaluate_constraints` returns forbids and declared constraints together, and
the two read at opposite polarity. A forbid's `satisfied` refers to its
*forbidden* predicate, so `satisfied=True` means the forbidden state holds and
the config is infeasible. This block therefore renders forbids as feasibility
and keeps the raw satisfied and margin pair for `.encourage()`, where a
positive margin means slack.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: show_infeasibility
```

Example 03 shows `constraint.kind` and `ConstraintEval.violated`, which fold
the polarity in and remove the need for the branch above.

## Selecting a subtree

`.select()` keeps a definition-path prefix subtree, so selecting a choice
brings its variants along and not just the bare discriminator. Three
constraints reference parameters outside the `selection` subtree, so the
best-effort default drops all three and warns.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: show_select
```

## The active subspace of one draw

`.active_subspace(config)` reports which parameters one concrete,
fully-materialized draw actually used. Inactive branches disappear from the
returned `Space` entirely.

```{literalinclude} ../../examples/02_genetic_algorithm.py
:pyobject: show_active_subspace
```
