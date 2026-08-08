# Anchors

A **default** is a per-parameter fill value: what should this parameter be if
nothing said otherwise? An **anchor** is a named whole configuration: what was
the configuration that shipped?

The two are constantly confused because both associate values with a space. They
answer different questions, and only one of them is a reference point.

The [partial configs](../user-guide/09-partial-configs.md) page of the user
guide covers defaults and `apply_defaults` running. This page is about anchors,
and about the one place the two features meet.

## What an anchor is for

An anchor names a configuration worth returning to: the incumbent, last
quarter's baseline, or the configuration a paper reported. It travels with the
space, so a result reported months later can still say what it was measured
against.

```pycon
>>> import designspace as ds
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

Defaults do **not** auto-create an anchor. The library does not invent a named
reference point that was not asked for, because "the defaults" and "what
shipped" coincide only until the first time someone tunes a default.

Deriving one is a single expression, and it cannot drift out of sync the way a
hand-copied dict does. That is the whole argument for the pattern: the failure
mode it removes is a baseline that silently stops describing the baseline.

## An anchor is not validated into feasibility

`apply_defaults` fills parameters and does not consult constraints, so an anchor
derived from defaults inherits that. A space whose defaults are individually
legal can still have an infeasible combination:

```pycon
>>> conflicting = ds.space(
...     ds.param("a").integer(0, 10).default(9),
...     ds.param("b").integer(0, 10).default(9),
... ).forbid(ds.param("a") + ds.param("b") > 10)
>>> filled = conflicting.apply_defaults({})
>>> filled
{'a': 9, 'b': 9}
>>> result = conflicting.validate(filled)
>>> result.param_errors
()
>>> result.valid
False

```

Each default is legal on its own, so `param_errors` is empty. The forbid is what
makes the filled configuration invalid.

This is deliberate, and it matches how user-written forbids have always
behaved: they were never checked at fill time. Filling and checking are separate
steps, and the library does not guess which parameter to move. An anchor worth
trusting is one that was validated after it was derived.

## Role conventions

The library has no notion of "incumbent", "baseline" or "champion". Anchor roles
are a `.meta()` convention, and no future version will bless one spelling of
them as API.

That is a deliberate boundary rather than an omission. A role is a fact about a
team's process, and encoding process vocabulary in a frozen format would mean
carrying one project's workflow forever.
