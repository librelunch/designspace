# Flow chemistry

The first four examples grow the shape of a space. This one holds the shape
deliberately plain so the *constraints* can carry the example: every boolean
and arithmetic expression form the spec defines appears in one runnable space.

Source: `examples/05_flow_chemistry.py`. Run it with
`uv run python examples/05_flow_chemistry.py`.

## Declaring the space

Subset queries are `.contains(item)`, `.size()` and `.sum_over(mapping)`, the
last summing a literal dict of per-item weights over the included items.
Permutation queries are `.position_of(item)`, letting an ordering rule compare
two positions directly.

`ds.all_` and `ds.any_` fold a variadic AND and OR. `ds.count(*bool_exprs)`
reports how many of several conditions hold at once, as an arithmetic value, so
a cardinality rule can be written over parameters that are separate by
construction.

Two guards deal with parameters that may be inactive. `.is_active()` is total,
always True or False and never Unknown. `.if_inactive(fallback)` substitutes a
value so an aggregate stays evaluable. The space declares the same aggregate
both ways, which is what the diagnostics section below measures.

```{literalinclude} ../../examples/05_flow_chemistry.py
:pyobject: build_space
```

## An opaque derived quantity

`ds.value(fn, *operands, returns=type)` admits an ordinary Python function into
an expression. Without it, a physical model over unrelated reals would force
the author to wrap them in a sham custom type just to get a scalar function in.

`fn` is called with exactly the operand *values* and never the config, so the
reference set is exactly the operands' own references. That is what keeps
`dependency_graph` trustworthy.

```{literalinclude} ../../examples/05_flow_chemistry.py
:pyobject: _yield_fraction
```

## Reading every constraint

```{literalinclude} ../../examples/05_flow_chemistry.py
:pyobject: show_constraint_table
```

## Unknown-swallowing, measured

Kleene rule 4 makes a constraint referencing an inactive parameter
inapplicable rather than failing, so it is silently accepted. The unguarded and
guarded twins here are the identical aggregate over the identical draws, and
only the guard differs.

```{literalinclude} ../../examples/05_flow_chemistry.py
:pyobject: show_unknown_swallowing
```

## A construction-time guard

A non-scalar `returns=` is rejected when `ds.value` is constructed, not left to
resolution. It needs no `Space`, which is the point.

```{literalinclude} ../../examples/05_flow_chemistry.py
:pyobject: show_value_misuse
```
