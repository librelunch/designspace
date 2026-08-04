# Defaults and anchors

Two features that both associate values with a space, and are constantly
confused because of it. They answer different questions:

- a **default** is a per-parameter fill value — *what should this parameter be
  if nobody said?*
- an **anchor** is a named whole configuration — *what was the configuration we
  shipped?*

## Defaults fill a partial config

Declare them per parameter, then complete anything partial:

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("workers").integer(1, 16).default(4),
...     ds.param("batch").integer(8, 512).default(32),
... )
>>> space.apply_defaults({})
{'workers': 4, 'batch': 32}

```

Whatever you supply wins; the rest is filled:

```pycon
>>> space.apply_defaults({"workers": 12})
{'workers': 12, 'batch': 32}

```

### A default is never silently clamped

This is worth stating because so many libraries do the opposite. A default
outside its domain is an error at resolution, not a value quietly moved to the
nearest legal one:

```pycon
>>> ds.space(ds.param("w").integer(1, 16).default(99))
Traceback (most recent call last):
    ...
designspace.errors.ResolutionError: param 'w': default 99 is outside its domain

```

The check spans every kind: a choice default must name a declared variant, a
subset or permutation default must be a legal one. (A struct parameter admits no
default of its own — give defaults to its fields.)

### `apply_defaults` is constraint-blind

It fills parameters. It does not consult your constraints, so its output can be
infeasible:

```pycon
>>> space = ds.space(
...     ds.param("a").integer(0, 10).default(9),
...     ds.param("b").integer(0, 10).default(9),
... ).forbid(ds.param("a") + ds.param("b") > 10)
>>> filled = space.apply_defaults({})
>>> filled
{'a': 9, 'b': 9}
>>> space.validate(filled).valid
False

```

This is deliberate and it matches how user-written forbids have always behaved —
they were never checked at fill time. If you need a feasible completion, fill
and then `validate`; the library will not guess which parameter to move.

## Anchors name whole configs

An anchor is a reference point: the incumbent, last quarter's baseline, the
configuration a paper reported.

```pycon
>>> space = ds.space(
...     ds.param("workers").integer(1, 16).default(4),
...     ds.param("batch").integer(8, 512).default(32),
... )
>>> anchored = space.anchor(configs={"shipped": space.apply_defaults({})})
>>> dict(anchored.anchors)
{'shipped': {'workers': 4, 'batch': 32}}

```

`.anchors` hands back a read-only view rather than the dict itself — every
public accessor does, because a `Space` is immutable and handing out a mutable
interior would be a way around that. Wrap it in `dict()` when you want a copy
you can edit.

## Derive, do not duplicate

That example is the pattern worth taking away. When a space already has complete
defaults, **build the anchor from them** rather than writing the same numbers
twice:

```python
space.anchor(configs={"shipped": space.apply_defaults({})})
```

Defaults do **not** auto-create an anchor. The library will not invent a named
reference point you did not ask for — but deriving one is a single expression,
and it cannot drift out of sync the way a hand-copied dict does.

## Roles are a convention, not API

"Incumbent", "baseline", "champion" — the library has no notion of these. Anchor
roles are a `.meta()` convention. Keep them there rather than hoping a future
version will bless one spelling.
