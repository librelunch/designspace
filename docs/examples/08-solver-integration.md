# Pump configurator

The first seven examples build and inspect spaces. This one covers what a
*consumer* does with one: walking a config together one field at a time,
passing a positional vector in and out, and rebuilding a space from its own
resolved IR.

Source: `examples/08_solver_integration.py`. Run it with
`uv run python examples/08_solver_integration.py`.

## Declaring the space

The space is deliberately **fixed-layout**: every count is a literal and no
parameter carries a condition. That is the precondition `coordinate_paths()`
requires.

Two forbids differ in how far `remaining_domain` can reduce them. The first is
a single unset bare operand and reduces fully. The second is a conjunction
across two parameters, which `remaining_domain` leaves unreduced: it is sound,
meaning it never excludes a still-feasible value, but it is not complete.

```{literalinclude} ../../examples/08_solver_integration.py
:pyobject: build_space
```

## Positional vectors

`coordinate_paths()` returns the flat keys that are coordinates. Deriving that
set by hand fails *silently*, producing a config that still validates and
differs, because a hand-rolled filter cannot distinguish a coordinate from a
count-bookkeeping entry without walking the `ListDomain` chain.

The method is defined only where the layout does not depend on the config, so a
conditional space raises rather than returning a set that would be wrong for
some draws.

```{literalinclude} ../../examples/08_solver_integration.py
:pyobject: show_coordinate_paths
```

## The partial-config surface

`remaining_domain` returns one of five descriptor kinds, and this block calls
it once per kind. `validate_param(path, value, context=)` evaluates the
bound-origin coupling only once the parameter it depends on is in context;
without it the constraint is omitted as under-determined rather than guessed.

```{literalinclude} ../../examples/08_solver_integration.py
:pyobject: show_partial_configs
```

## Metaprogramming

`ds.param_from_def(pd)` turns a resolved `ParamDef` back into a builder
expression. Every `BoolExpr` and `ArithExpr` exposes a walkable
`.kind`/`.children`/`.params` triple, which is the facility a rewrite tool
builds on. `ds.space_from_ir(...)` reconstructs a fingerprint-equal space from
IR directly.

The generation loop at the end builds one bool flag per manufacturing step and
requires each against its own prerequisites via `ds.all_(*prereqs)`. A
prereq-free step uses the zero-operand identity, which the Degeneracy Table
defines as literal `True`.

```{literalinclude} ../../examples/08_solver_integration.py
:pyobject: show_metaprogramming
```

## The callback shorthand

`.custom(sampler=, validator=)` is generative but carries no structural
encoding, so it is not serializable. `to_json()` raises, and
`fingerprint(on_unserializable="mark")` succeeds where the default raises.

```{literalinclude} ../../examples/08_solver_integration.py
:pyobject: show_custom_shorthand
```
