# Program types

A tree or a source string is a genotype, and generating one is out of scope.
Core's job is therefore narrower than it looks: declare the space, validate
values against that declaration, and carry them through every existing surface
without ever generating or evaluating one.

Source: `examples/10_program_types.py`. Run it with
`uv run python examples/10_program_types.py`.

## Declaring the space

`.symbolic(signature, primitives, max_depth, ...)` declares a structured
expression tree with value shape `{"ast": <node>, "source": <str>}`, where
`"source"` is optional. `.code(signature, ...)` declares freeform source with
value shape `{"source": <str>}`, and its `description`, `constraints` and
`examples` are declared, serialized, fingerprinted metadata for a consumer's
own backend.

```{literalinclude} ../../examples/10_program_types.py
:pyobject: build_space
```

## Structural validation

Core checks the *structure* of a submitted tree: the vocabulary this parameter
declared, arity where a `ds.Primitive` declares one, variable names drawn from
`signature.args`, constants within a declared literal's bounds, and depth
within `max_depth`. It assigns no meaning to a bare primitive name and ships no
evaluator.

```{literalinclude} ../../examples/10_program_types.py
:pyobject: show_ast_validation
```

## Open vocabulary, checked arity

A bare string names a primitive with no arity attached, so it structurally
accepts any number of arguments. `ds.Primitive(name, arity, fn=None)` pins one,
as an exact int or a `(lo, hi)` range.

```{literalinclude} ../../examples/10_program_types.py
:pyobject: show_arity
```

## Generativity

`.code()` is always non-generative, since no `sampler=` form exists.
`.symbolic()` is non-generative unless `sampler=` is given. A `.default()`
satisfies `sample()`'s obligation either way, `freeze` does too, and a
parameter inactive for the draw never triggers it.

```{literalinclude} ../../examples/10_program_types.py
:pyobject: show_generativity
```

```{literalinclude} ../../examples/10_program_types.py
:pyobject: show_freeze_and_slice
```

## Identity and per-field opacity

Core never calls `Primitive.fn`. Like `validators` and `.symbolic()`'s
`sampler`, it rides the non-serializable set under raise, mark or drop,
degrading just that one field in place rather than the whole parameter.

```{literalinclude} ../../examples/10_program_types.py
:pyobject: show_identity
```
