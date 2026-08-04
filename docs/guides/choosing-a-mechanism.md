# Choosing a mechanism

Several spellings describe overlapping sets of configurations. They are **not**
interchangeable to the library: semantically overlapping encodings are
structurally distinct, and no normalization is attempted. Two spaces that admit
the same configurations will still fingerprint differently if you built them
differently.

So the choice is real, and it is worth making deliberately rather than by habit.

| you have | use |
|---|---|
| one or two parameters that only matter sometimes | `bool` + `.when()` |
| genuine alternatives, or alternatives with heavy payloads | `.choice()` |
| parameters that are always active together, and you want them namespaced | `.space()` (a struct) |
| a set of items where each *member* carries its own payload | bool-per-item + `.when()` + `ds.count()` |

## One or two dependents: bool plus `.when()`

When a flag gates a parameter or two, a bool is the whole mechanism.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("use_dropout").bool(),
...     ds.param("dropout_rate").real(0.0, 0.9).when(ds.param("use_dropout")),
... )
>>> on = space.sample_one(seed=2)
>>> on["use_dropout"], "dropout_rate" in on
(True, True)

```

An inactive parameter is **absent** from the config, not present-and-null:

```pycon
>>> off = space.sample_one(seed=0)
>>> off["use_dropout"], "dropout_rate" in off
(False, False)

```

This is the cheapest mechanism, and it stops paying once the gated group grows.
Three or four `.when()` calls all repeating the same condition is the signal to
reach for a choice.

## Alternatives: `.choice()`

A choice names variants and gives each its own payload. The discriminator is a
parameter in its own right, and the payload parameters live under it by path.

```pycon
>>> space = ds.space(
...     ds.param("optimizer").choice(
...         adam=ds.space(ds.param("beta1").real(0.8, 0.999)),
...         sgd=ds.space(ds.param("momentum").real(0.0, 0.99)),
...     ),
... )
>>> config = space.sample_one(seed=0)
>>> config
{'optimizer': {'sgd': {'momentum': 0.2670888466262316}}}

```

A config is a **nested** dict, and a choice nests one level further: the
variant name is the key, its payload the value. Read the two apart with
`ds.variant()` and `ds.payload()` rather than by indexing:

```pycon
>>> ds.variant(config, "optimizer")
'sgd'
>>> sorted(ds.payload(config, "optimizer"))
['momentum']

```

`ds.flatten()` gives the same config keyed by instance path, which is the view
the IR and every error message use:

```pycon
>>> sorted(ds.flatten(config, space))
['optimizer', 'optimizer.sgd.momentum']

```

Only the selected variant's parameters are present. Reach for this when the
alternatives are genuinely different things rather than one thing switched off.
`adam` and `sgd` do not share a `momentum`, and pretending they do with a
nullable parameter loses that.

## Pure grouping: `.space()`

When parameters are always active together and you only want a namespace, a
struct groups them without introducing a discriminator at all.

```pycon
>>> space = ds.space(
...     ds.param("net").space(
...         ds.param("depth").integer(1, 8),
...         ds.param("width").integer(16, 256),
...     ),
... )
>>> config = space.sample_one(seed=0)
>>> config
{'net': {'depth': 6, 'width': 81}}
>>> sorted(ds.flatten(config, space))
['net.depth', 'net.width']

```

A struct adds no conditionality. If you find yourself grouping *and* gating,
that is a choice with one variant, and writing it as one keeps the gate visible.

## Subset members with payloads

`.subset()` picks a set of items, but a subset member cannot carry parameters of
its own. When each selected item needs a payload, spell it as one bool per item
plus `.when()`, and recover "how many are on" with `ds.count()`.

```pycon
>>> space = ds.space(
...     ds.param("use_l1").bool(),
...     ds.param("use_l2").bool(),
...     ds.param("l1_weight").real(1e-5, 1e-1).when(ds.param("use_l1")),
...     ds.param("l2_weight").real(1e-5, 1e-1).when(ds.param("use_l2")),
... ).require(ds.count(ds.param("use_l1"), ds.param("use_l2")) >= 1)
>>> config = space.sample_one(seed=0)
>>> config["use_l1"] or config["use_l2"]
True

```

`ds.count()` counts how many of its boolean arguments hold, which is what lets a
cardinality rule ("at least one regularizer") be written over parameters that
are separate by construction.

If the members need *no* payload, use `.subset()` instead. It is one parameter
rather than *n*, and it gets a subset-shaped prior and chart for free.
