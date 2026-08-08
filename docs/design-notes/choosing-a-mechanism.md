# Choosing a mechanism

Several spellings describe overlapping sets of configurations. They are **not**
interchangeable to the library: semantically overlapping encodings are
structurally distinct, and no normalization is attempted. Two spaces that admit
the same configurations fingerprint differently if they were built differently,
so the choice is permanent in a way that a later refactor cannot undo.

| situation | mechanism |
|---|---|
| one or two parameters that only matter sometimes | `bool` + `.when()` |
| genuine alternatives, or alternatives with heavy payloads | `.choice()` |
| parameters that are always active together and want a namespace | `.space()` (a struct) |
| a set of items where each *member* carries its own payload | bool-per-item + `.when()` + `ds.count()` |

The [conditionality and structure](../user-guide/03-conditionality-and-structure.md)
page of the user guide shows each mechanism running. This page is about which
one to reach for, and what each costs.

## When a bool stops paying

A bool plus `.when()` costs the least of the four, and it stops paying once the
gated group grows. Three or four `.when()` calls repeating the same condition
are the signal to reach for a choice.

The cost of leaving it too late is structure rather than correctness. A reader
cannot tell from four independent conditions that they name one decision, and
neither can a solver. A choice makes that decision a parameter in its own right,
with its own prior.

## When alternatives are alternatives

Use a choice where the alternatives are different things rather than one thing
switched off. `adam` and `sgd` do not share a `momentum`, and a nullable
parameter spelling them as one loses that.

The test is whether the payloads would ever be compared. Parameters belonging to
different variants are never both present, so a constraint relating them can
only ever be vacuous.

## When grouping is only grouping

A struct adds no conditionality. Grouping *and* gating at the same time is a
choice with one variant, and writing it as one keeps the gate visible.

Reaching for a struct because the names are getting long is the right reason.
Reaching for it to express "these belong together" when they are also
conditionally present is how a gate ends up implicit.

## Subset members with payloads

`.subset()` picks a set of items, but a subset member cannot carry parameters of
its own. Where each selected item needs a payload, spell it as one bool per item
plus `.when()`, and recover "how many are on" with `ds.count()`.

```pycon
>>> import designspace as ds
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
cardinality rule such as "at least one regularizer" be written over parameters
that are separate by construction.

The cost is *n* parameters where a subset would be one, plus the loss of a
subset-shaped prior and chart. Where the members need no payload, `.subset()`
is the better trade.
