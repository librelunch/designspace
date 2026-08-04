# Structured values

Graphs, layouts, schedules, pipelines — anything whose value is a *structure*
rather than a number. There are three ways to declare one, and they trade the
same thing against each other: how much the library can see versus how much of
the structure's invariant you have to enforce yourself.

Pick by asking **where the invariant lives**.

| tier | shape | use when |
|---|---|---|
| 1 | parametric family — a choice over named structures | the structure is nameable |
| 2 | primitive decomposition — element lifts with per-element constraints | constraints are local to elements |
| 3 | custom type with a constructive sampler | invariants are global, or rejection is hostile |

```{note}
These tiers are unrelated to the white/grey/black tiers in
[predicate transparency](predicate-transparency.md). That one ranks how much of
a *predicate* the library can see; this one ranks how much of a *structure* you
hand over to a custom type.
```

## Tier 1 — a parametric family

When the structures worth searching have names, enumerate them. The space stays
entirely primitive: every parameter has a chart, a prior, and full introspection.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("topology").choice(
...         ring=ds.space(ds.param("size").integer(3, 12)),
...         star=ds.space(ds.param("leaves").integer(2, 10)),
...     ),
... )
>>> ds.variant(space.sample_one(seed=0), "topology")
'star'

```

This is the cheapest tier and the most under-used. "The structure is nameable"
is true far more often than it feels — a handful of named topologies usually
covers the space a modeller actually cares about.

## Tier 2 — primitive decomposition

When the structure is a collection of similar elements, lift a template over a
count. The count can itself be a parameter, which is what makes the structure
variable-length.

```pycon
>>> space = ds.space(
...     ds.param("n_layers").integer(1, 3),
...     ds.param("layer").space(
...         ds.param("units").integer(8, 64),
...     ).repeat(ds.param("n_layers")),
... )
>>> config = space.sample_one(seed=0)
>>> config
{'n_layers': 2, 'layer': [{'units': 23}, {'units': 10}]}

```

Elements get indexed instance paths, which is how a per-element constraint or an
error message names one:

```pycon
>>> sorted(ds.flatten(config, space))
['layer', 'layer[0].units', 'layer[1].units', 'n_layers']

```

Use this tier when the constraints you need are **local** — they talk about one
element, or about an element and its neighbour. A *static* count buys you more:
with the length known at resolution, you can machine-generate the unrolled
pairwise constraints rather than writing them out.

The limit is rejection. Dense combinatorial constraints over elements — pairwise
distinctness, conflict sets near a packing limit — collapse the acceptance rate,
and that is the signal to move to tier 3. See [rejection](rejection.md).

## Tier 3 — a custom type

When the invariant is **global** — connectivity, pairwise spacing, a feasibility
property no per-element rule expresses — stop trying to declare it and construct
it instead. A custom type carries its own sampler, so it produces valid values
by construction rather than by rejection.

The judgment this tier demands is **where to draw the ownership boundary**, and
the rule is: parameters coupled to the constructive invariant go *inside* the
type; independent payloads stay outside as primitive parameters.

That boundary matters because everything you move inside loses its chart and its
prior. A graph's edge set belongs inside — it is what the constructive sampler
exists to get right. A per-node learning rate does not: it is an independent
payload, and keeping it primitive keeps it log-scalable, introspectable, and
perturbable in u-space.

Align the two with a property-driven lift count:

```pycon
>>> class GraphType:
...     type_key = "graph"
...
...     def validate(self, value):
...         return len(value["nodes"]) >= 1
...
...     def to_json(self, value):
...         return value
...
...     def from_json(self, data):
...         return data
...
...     def describe(self):
...         return {"kind": "path"}
...
...     def sample(self, rng):
...         n = int(rng.integers(2, 5))
...         return {"nodes": list(range(n)),
...                 "edges": [[i, i + 1] for i in range(n - 1)]}
...
...     def properties(self):
...         return {"n_nodes": int}
...
...     def extract(self, value, prop):
...         return len(value["nodes"])
>>> space = ds.space(
...     ds.param("graph").custom(GraphType()),
...     ds.param("node_lr").real(1e-4, 1e-1).repeat(ds.param("graph").prop("n_nodes")),
... )
>>> config = space.sample_one(seed=0)
>>> len(config["graph"]["nodes"]) == len(config["node_lr"])
True

```

The connectivity invariant never appears as a constraint — `sample` simply
cannot produce a disconnected graph. That is what "constructive" buys, and it is
why this tier survives where rejection does not.

`.prop()` reads a named property off the custom value, and using it as a count
is what keeps the payload list exactly as long as the structure the type built.
A type whose values are aligned to this way must define a canonical ordering
stable under JSON round-trips — otherwise `node_lr[2]` means a different node
after a save and reload.

## The boundary that does not move

Value-dependent indexing (`islands[edges[k].src]`) and quantification over
dynamic ranges are permanently outside the expression language. Relational
semantics belong to tier 3 or to the consumer.

And prefer generative reparameterization over measure-zero constraints. A
simplex declared as "*n* reals that sum to 1" has probability zero of ever being
sampled; declared by stick-breaking it is primitive, chart-covered, and always
valid — with the manifold geometry riding in an `Encoding` rather than in a
constraint that rejection can never satisfy.

## One tension worth knowing about

A custom type that other parameters depend on through `.prop()` cannot later be
bridged away from `custom` with a `Representation` without dangling them. That
cuts directly against the tier-3 advice above, which steers exactly the
bridge-worthy structures toward carrying properties.

There is no resolution in the library — the tension is real and it belongs to
the modeller. If you expect to bridge a type later, either keep prop-driven
alignment out of the space, or supply a bridge whose target is another custom
type exposing the same properties.
