# Integrating a solver

designspace declares spaces. It does not search them, and it ships no operators,
no distances, and no adapters. Pointing a solver at a `Space` is therefore
something you or the solver author does, and it takes one of three shapes.

Which one applies depends on a fact about the solver, not about your space:
every solver defines the space it can work with. Base CMA-ES is ℝⁿ. Variants add
integers and categoricals. SMAC and irace add conditionals. Others work on
graphs.

## Shape 1: interpret the `Space` directly

A solver that understands the IR walks it: topological order → activity from
conditions → embed the active generative parameters in u-space through their
charts → propose → decode → check margins.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("opt").categorical("adam", "sgd"),
...     ds.param("lr").real(1e-4, 1e-1).prior(ds.Log()),
...     ds.param("mom").real(0.0, 0.99).when(ds.param("opt") == "sgd"),
... )
>>> space.topological_order
['opt', 'lr', 'mom']

```

### Charts are the part worth knowing about

Every generative scalar parameter resolves to a **chart**: a monotone map from
`[0, 1]` onto the domain. This is what gives a solver free, type-appropriate
perturbation: mutate in u-space, then decode through the chart.

```pycon
>>> lr = space.params["lr"].chart
>>> [round(lr.from_unit(u), 5) for u in (0.0, 0.5, 1.0)]
[0.0001, 0.00316, 0.1]

```

The midpoint is the geometric mean, not the arithmetic one, because the
parameter declared a log prior. A solver that perturbs in u-space gets
multiplicative noise on this parameter and additive noise on a linear one with
zero per-type code, and integer grids snap correctly on the way back.

The map runs both ways, so an existing configuration can be lifted into u-space
to seed a search:

```pycon
>>> round(lr.to_unit(0.001), 4)
0.3333

```

### Negotiation is ordinary introspection

There is no capability protocol to implement. The solver checks what it needs
and fails with **its own** message, since only it knows what it supports:

```pycon
>>> space.is_conditional, space.has_variable_length
(True, False)
>>> space.params["lr"].type_kind
'real'
>>> space.params["lr"].chart is not None
True

```

A solver that cannot handle conditionals reads `is_conditional` and says so
itself. The library does not raise on its behalf.

## Shape 2: convert to a foreign representation

ConfigSpace and its kin. Core ships no adapter and takes no dependency on one;
the public, bidirectional IR is the socket. Walk `params`, emit the foreign
declaration, and map back.

## Shape 3: bridge with a `Representation`

When the solver's genotype differs from your phenotype, `space.represent()`
produces a genotype `Space` plus a `decode`/`encode` pair:

```pycon
>>> rep = space.represent()
>>> sorted(rep.target.params)
['lr', 'mom', 'opt']

```

The important property is that `rep.target` is an **ordinary `Space`**. Shape 1
applies to it unchanged. That is the whole point. A bridge introduces no new
negotiation vocabulary; it only moves where shape 1 gets applied.

## Custom types negotiate per parameter

A `.custom()` parameter is an open world, and it offers two **independent**
channels.

**The generation ladder**, richest available rung wins:

1. a native adapter that recognizes the type's `type_key`;
2. a `Representation` whose target this solver can handle, with the geometry
   authored by the type author and the loss declared rather than silent;
3. opaque `sample(rng)`, enough for random search and resampling moves.

**The modeling channel**, orthogonal to generation: `properties()` featurizes
values for surrogates and reporting no matter which rung produced them, and
`to_json`/`config_hash` give observation identity. A type that is opaque to
generation can still be rich to modeling. The two channels are independent.

## Adapter conventions

Strategy-entangled operations are the only things genuinely forced into
adapters: crossover schemes, mutation policies, trust regions. When you write
one:

- key it by the same `type_key` used in serialization;
- give it the live `ParamType` instance and derive domain facts from it
  (`describe`, `validate`, `extract`) rather than re-declaring them;
- pass it a `Representation` rather than embedding one;
- scope it per *(capability, type)*. Scoping per *(solver, type)* multiplies
  adapters for no gain.

## Observation identity

Key results on the pair `(space.fingerprint(), ds.config_hash(config, space))`.

```pycon
>>> config = space.sample_one(seed=0)
>>> key = (space.fingerprint(), ds.config_hash(config, space))
>>> key[0].startswith("1:full:")
True

```

The fingerprint identifies the space, the config hash the point in it. Equal
fingerprints guarantee identical valid-config sets. Unequal ones guarantee
nothing, since identity is structural after desugaring rather than semantic.
