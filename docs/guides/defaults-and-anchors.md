# Defaults and anchors

Two features associate values with a space, and they are easily confused. They
answer different questions:

- a **default** is a per-parameter fill value: what should this parameter be if
  nothing said otherwise?
- an **anchor** is a named whole configuration: what was the configuration that
  shipped?

## Filling a partial config

Defaults are declared per parameter and complete anything partial:

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("workers").integer(1, 16).default(4),
...     ds.param("batch").integer(8, 512).default(32),
... )
>>> space.apply_defaults({})
{'workers': 4, 'batch': 32}

```

Supplied values win and the rest are filled:

```pycon
>>> space.apply_defaults({"workers": 12})
{'workers': 12, 'batch': 32}

```

### Domain validation

A default outside its domain is an error at resolution. It is never moved
quietly to the nearest legal value:

```pycon
>>> ds.space(ds.param("w").integer(1, 16).default(99))
Traceback (most recent call last):
    ...
designspace.errors.ResolutionError: param 'w': default 99 is outside its domain

```

The check spans every kind: a choice default must name a declared variant, and a
subset or permutation default must be a legal one. A struct parameter admits no
default of its own, and its fields take defaults instead.

### Interaction with constraints

`apply_defaults` fills parameters and does not consult constraints, so its
output can be infeasible:

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

This is deliberate and matches how user-written forbids have always behaved:
they were never checked at fill time. A feasible completion requires filling and
then validating. The library does not guess which parameter to move.

## Anchors

An anchor is a reference point: the incumbent, last quarter's baseline, or the
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

`.anchors` returns a read-only view rather than the dict itself, as every public
accessor does. A `Space` is immutable, and handing out a mutable interior would
be a way around that. Wrapping the view in `dict()` produces an editable copy.

## Deriving anchors from defaults

The example above is the pattern to take away. Where a space already has
complete defaults, the anchor is **built from them** instead of restating the
same numbers:

```python
space.anchor(configs={"shipped": space.apply_defaults({})})
```

Defaults do **not** auto-create an anchor; the library does not invent a named
reference point that was not asked for. Deriving one is a single expression, and
it cannot drift out of sync the way a hand-copied dict does.

## Role conventions

The library has no notion of "incumbent", "baseline" or "champion". Anchor roles
are a `.meta()` convention, and no future version will bless one spelling of
them as API.
