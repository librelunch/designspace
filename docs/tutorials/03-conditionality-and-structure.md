---
file_format: mystnb
---

# Conditionality and structure

In a flat space every parameter is present in every configuration. Once the
structure of a configuration depends on the values drawn, three mechanisms
apply, and they are not interchangeable. This page assembles a genetic
algorithm from operators, each of which brings sub-parameters that exist only
when that operator is chosen.

## Conditional parameters

`.when(condition)` makes a parameter active only where the condition holds. An
inactive parameter is **absent** from the configuration, not present and null.

```{code-cell}
import designspace as ds

space = ds.space(
    ds.param("elitism").bool(),
    ds.param("elite_fraction").real(0.0, 0.3).when(ds.param("elitism")),
)
space.sample_one(seed=2)
```

```{code-cell}
space.sample_one(seed=0)
```

Conditionality is structural. Across a batch, the key appears exactly where the
flag is set:

```{code-cell}
[(c["elitism"], "elite_fraction" in c) for c in space.sample_dicts(6, seed=1)]
```

```{code-cell}
:tags: [remove-output]

assert all(
    ("elite_fraction" in c) == c["elitism"] for c in space.sample_dicts(200, seed=3)
)
```

## Alternatives

`.choice()` names variants, each with its own payload. A bare string is a
parameterless variant; a keyword argument carries a nested `ds.space(...)`.

```{code-cell}
space = ds.space(
    ds.param("population_size").integer(20, 500).quantized(step=10),
    ds.param("selection").choice(
        "roulette",
        tournament=ds.space(ds.param("tournament_size").integer(2, 10)),
        rank=ds.space(ds.param("rank_pressure").real(1.0, 2.0)),
    ).prior(weights=[1, 3, 2]),
    ds.param("crossover").choice(
        "one_point",
        "two_point",
        uniform=ds.space(ds.param("swap_prob").real(0.1, 0.9)),
    ),
)
config = space.sample_one(seed=0)
config
```

A choice nests one level further than a plain parameter: the variant name is
the key and its payload the value. `weights=` biases which variant is drawn.

## Reading a choice back

Indexing into that nesting couples the calling code to the convention. Three
helpers read it apart instead.

```{code-cell}
ds.variant(config, "selection")
```

```{code-cell}
ds.payload(config, "selection")
```

```{code-cell}
ds.destructure(config, "crossover")
```

`ds.payload` returns `None` for a bare variant, which is how a parameterless
variant is distinguished from one whose payload happens to be empty.

## Grouping without a discriminator

Where parameters are always active together and only need a namespace, a struct
groups them. `.space()` on a parameter adds no conditionality and introduces no
discriminator.

```{code-cell}
space = ds.space(
    ds.param("pid").space(
        ds.param("kp").real(0.1, 10.0).log_scale(),
        ds.param("ki").real(0.001, 0.999),
    ),
    ds.param("seed").integer(0, 100),
)
space.sample_one(seed=0)
```

Grouping *and* gating at the same time is a choice with one variant, and
writing it as one keeps the gate visible.

## What the space reports

A payload-bearing choice is what makes a space **hierarchical**. Each variant
relocates its descendants under a definition-path prefix, and `.subspaces` lists
those prefixes.

```{code-cell}
space = ds.space(
    ds.param("selection").choice(
        "roulette",
        tournament=ds.space(ds.param("tournament_size").integer(2, 10)),
    ),
    ds.param("mutation_rate").real(1e-4, 0.5).log_scale(),
    ds.param("adaptive").bool(),
    ds.param("decay").real(0.9, 0.999).when(ds.param("adaptive")),
)
space.is_conditional, space.is_hierarchical
```

```{code-cell}
sorted(space.subspaces)
```

Each entry describes which parameters live inside that region and under what
condition they are active:

```{code-cell}
info = space.subspaces["selection.tournament."]
info.kind, info.variant_name, info.member_paths
```

The flattened view shows how a payload is addressed by path:

```{code-cell}
config = space.sample_one(seed=5)
sorted(ds.flatten(config, space))
```

## The active subspace of one draw

`.active_subspace(config)` reports the parameters one concrete draw actually
used. Unchosen variants and inactive conditionals disappear from the returned
`Space` entirely.

```{code-cell}
active = space.active_subspace(config)
active.n_params, list(active.params)
```

```{code-cell}
:tags: [remove-output]

assert active.n_params <= space.n_params
assert set(active.params) <= set(space.params)
```

## Where to go next

[Constraints and feasibility](04-constraints-and-feasibility.md) adds rules
across parameters.
