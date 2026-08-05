---
file_format: mystnb
---

# Identity, serialization and solver hand-off

Two questions face any consumer storing results: which space produced this
number, and which point in it. This page answers both, then walks through the
three shapes a solver hand-off takes. The running example is a NAS-shaped
hyperparameter space.

```{code-cell}
import designspace as ds

space = ds.space(
    ds.param("lr").real(1e-5, 1.0).log_scale(),
    ds.param("weight_decay").real(1e-6, 1e-2).log_scale(),
    ds.param("n_layers").integer(1, 5),
    ds.param("width").integer(8, 256).log_scale().repeat(ds.param("n_layers")),
    ds.param("optimizer").categorical("adam", "sgd"),
).forbid(ds.param("lr") > 0.5)
space.n_params
```

## Serialization

`to_json` produces a plain dict, and `Space.from_json` reconstructs it.

```{code-cell}
doc = space.to_json()
sorted(doc)
```

```{code-cell}
doc["version"], len(doc["params"])
```

`version` is the shared format integer, frozen since the space format was
fixed. The parameter entries carry the resolved declaration:

```{code-cell}
doc["params"][0]
```

```{code-cell}
restored = ds.Space.from_json(doc)
restored.fingerprint() == space.fingerprint()
```

A custom parameter needs a `type_key` to factory registry to reconstruct, since
core cannot know how to rebuild a user-defined type:
`ds.Space.from_json(doc, custom_types={...})`.

## Fingerprints

A fingerprint identifies a space. Equal fingerprints guarantee identical
valid-configuration sets; unequal ones guarantee nothing, because identity is
structural after desugaring rather than semantic.

```{code-cell}
space.fingerprint()
```

Two scopes are available. `"full"`, the default, is document identity.
`"sampling"` covers only what fixes the feasible set, the measure and the chart
geometry, so a change to identity-level bookkeeping moves one and not the other.

```{code-cell}
tagged = space.meta(experiment="baseline")
(
    tagged.fingerprint(scope="sampling") == space.fingerprint(scope="sampling"),
    tagged.fingerprint(scope="full") == space.fingerprint(scope="full"),
)
```

## Observation identity

`ds.config_hash` is a configuration's own stable key. The pair
`(space.fingerprint(), config_hash(config, space))` identifies one observation
globally, and is what results should be keyed on.

```{code-cell}
config = space.sample_one(seed=0)
key = (space.fingerprint(), ds.config_hash(config, space))
key[1]
```

The hash follows the configuration across a round-trip of the space:

```{code-cell}
:tags: [remove-output]

assert ds.config_hash(config, space) == ds.config_hash(config, restored)
assert restored.validate(config).valid
```

## Shape 1: interpret the `Space` directly

A solver that understands the IR walks it. Topological order first, then
activity from conditions, then the charts.

```{code-cell}
space.topological_order
```

```{code-cell}
space.dependency_graph
```

Every generative scalar parameter carries a chart, which is what gives a solver
type-appropriate perturbation with no per-type code: mutate in `[0, 1]`, then
decode.

```{code-cell}
lr = space.params["lr"].chart
[round(lr.from_unit(u), 6) for u in (0.0, 0.5, 1.0)]
```

```{code-cell}
round(lr.to_unit(0.001), 4)
```

Capability negotiation is ordinary introspection. There is no protocol to
implement: the solver checks what it needs and fails with **its own** message,
since only it knows what it supports.

```{code-cell}
(
    space.is_conditional,
    space.has_variable_length,
    space.is_finite,
    space.has_nongenerative_params,
)
```

## Shape 2: convert to a foreign representation

Core ships no adapter for ConfigSpace or its kin, and takes no dependency on
one. The public, bidirectional IR is the socket: walk `params`, emit the foreign
declaration, and map back.

```{code-cell}
[(p, pd.type_kind) for p, pd in space.params.items()]
```

## Shape 3: bridge with a `Representation`

Where the solver's genotype differs from the declared phenotype,
`space.represent()` builds the **induced** chart representation, derived
mechanically from the charts already on the declaration.

```{code-cell}
rep = space.represent()
rep.encoded
```

`n_layers` is excluded and reported separately, because transport rewrites
conditions and constraints but never a count:

```{code-cell}
rep.excluded_by_prop
```

The target is an **ordinary `Space`** of unit-interval coordinates, so shape 1
applies to it unchanged. A bridge introduces no new vocabulary; it only moves
where shape 1 gets applied.

```{code-cell}
rep.target.params["lr"].domain
```

```{code-cell}
genotype = rep.target.sample_one(seed=0)
genotype
```

```{code-cell}
rep.decode(genotype)
```

Decoding is guaranteed **total**: every genotype the target calls valid decodes
to a phenotype the source calls valid.

```{code-cell}
:tags: [remove-output]

phenotype = rep.decode(genotype)
assert space.validate(phenotype).param_errors == ()
assert rep.target.is_feasible(genotype) == space.is_feasible(phenotype)
```

The reverse round-trip is not a law, because an integer chart is many-to-one:

```{code-cell}
rep.encode(rep.decode(genotype)) == genotype
```

`rep.check(n, seed)` runs the conformance laws as a tool. It covers decode
totality, feasibility agreement, and, where invertible, the one-directional
round-trip. It returns a report and never raises.

```{code-cell}
result = rep.check(n=200, seed=1)
result.ok, result.n, result.failures
```

## Where to go next

The [guides](../guides/index.md) cover the decisions behind these mechanisms,
and the [API reference](../reference.md) documents every exported name.
