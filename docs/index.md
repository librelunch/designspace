# designspace

Declarative algorithm design spaces with a polars-like expression API.

A *design space* is the set of configurations an algorithm can take. You declare
it once: the parameters, their domains, when each one is active, and what
combinations are legal. Then sample from it, validate against it, hand it to a
solver, or serialize it and compare it to one you built last month.

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

`momentum` is in the config because `optimizer` came out `"sgd"`. Draw a
configuration where it does not, and the parameter is absent rather than null.
Conditionality is structural, not a post-hoc mask.

```pycon
>>> adam = space.sample_one(seed=3)
>>> adam["optimizer"]
'adam'
>>> "momentum" in adam
False

```

## Where to go next

The **guides** are the place to start: each one takes a decision you will
actually face and walks through how the library expects you to make it. The
**API reference** is generated from the docstrings, so it is the same text
`help()` gives you.

```{toctree}
:maxdepth: 2

guides/index
reference
```

## What designspace does not do

It declares spaces; it does not search them. There are no search operators, no
distance functions, no tree generators, and no algebraic normalization of
expressions. Nothing is ever silently clamped: a value outside a domain is an
error, not a rounded-off input. Those are deliberate boundaries, and the
[solver integration guide](guides/solver-integration.md) explains where the
library hands off to the consumer that does search.
