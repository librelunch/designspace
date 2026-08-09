# designspace

Declarative design spaces with a polars-like expression API.

A *design space* is the set of configurations a system can take: an algorithm,
a model, a process, or a physical assembly. A space is declared once, giving
the parameters, their domains, the condition under which each is active, and
the combinations that are legal. The resulting `Space` can then be sampled,
validated against, handed to a solver, serialized, or compared with another
space by fingerprint.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("optimizer").categorical("adam", "sgd"),
...     ds.param("lr").real(1e-4, 1e-1).prior(ds.Log()),
...     ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
... )
>>> print(space)
Space: 3 params, 1 conditional, 0 constraints
  optimizer  categorical  {'adam', 'sgd'}
  lr         real         [0.0001, 0.1]  log
  momentum   real         [0.0, 0.99]  when optimizer == 'sgd'
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

The user guide covers the library one topic at a time. The design notes take
the decisions a declaration forces and work through what each option costs. The
API reference is generated from the docstrings, so it is the same text `help()`
returns.

```{toctree}
:maxdepth: 2

user-guide/index
design-notes/index
reference
```

## Scope

designspace declares spaces and does not search them. It ships no search
operators, no distance functions, no tree generators, and no algebraic
normalization of expressions. No value is ever silently clamped: a value
outside its domain is an error, never a rounded input. These are deliberate
boundaries, and
[identity and solver hand-off](user-guide/11-identity-and-solvers.md) describes
where the library hands off to the consumer that does search.
