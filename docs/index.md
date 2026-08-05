# designspace

Declarative algorithm design spaces with a polars-like expression API.

A *design space* is the set of configurations an algorithm can take. A space is
declared once, giving the parameters, their domains, the condition under which
each is active, and the combinations that are legal. The resulting `Space` can
then be sampled, validated against, handed to a solver, serialized, or compared
with another space by fingerprint.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("optimizer").categorical("adam", "sgd"),
...     ds.param("lr").real(1e-4, 1e-1).prior(ds.Log()),
...     ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
... )
>>> config = space.sample_one(seed=0)
>>> config["optimizer"]
'sgd'
>>> "momentum" in config
True

```

`momentum` is present because `optimizer` came out `"sgd"`. In a draw where it
does not, the parameter is absent from the config, not present and null.
Conditionality is structural, not a mask applied afterwards.

```pycon
>>> adam = space.sample_one(seed=3)
>>> adam["optimizer"]
'adam'
>>> "momentum" in adam
False

```

## Contents

The tutorials cover the library one topic at a time, and every code block on
them is executed when the site is built, so the outputs shown are real. The
design notes take the decisions a declaration forces and work through what each
option costs. The API reference is generated from the docstrings, so it is the
same text `help()` returns.

```{toctree}
:maxdepth: 2

tutorials/index
design-notes/index
reference
```

## Scope

designspace declares spaces and does not search them. It ships no search
operators, no distance functions, no tree generators, and no algebraic
normalization of expressions. No value is ever silently clamped: a value
outside its domain is an error, never a rounded input. These are deliberate
boundaries, and the
[solver hand-off tutorial](tutorials/11-identity-and-solvers.md) describes where
the library hands off to the consumer that does search.
