# Structured values

Graphs, layouts, schedules and pipelines are values whose content is a
*structure* rather than a number. Three mechanisms declare one, and they trade
off the same quantity: the more of the structure a custom type owns, the less
of it the library can see.

The question that selects one is **where the invariant lives**.

| mechanism | shape | applies when |
|---|---|---|
| parametric family | a choice over named structures | the structure is nameable |
| primitive decomposition | element lifts with per-element constraints | constraints are local to elements |
| custom type | a constructive sampler owns the value | invariants are global, or rejection is hostile |

## A parametric family

Where the structures of interest have names, enumerate them. The space
stays entirely primitive, so every parameter retains a chart, a prior, and full
introspection.

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

A parametric family costs the least of the three, and "the structure is
nameable" holds more often than it first appears. A handful of named topologies
usually covers the region a modeller cares about.

## Primitive decomposition

Where the structure is a collection of similar elements, lift a template over a
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

Primitive decomposition applies where the constraints needed are **local**,
meaning they talk about one element, or about an element and its neighbour. A
*static* count extends the reach: with the length known at resolution, the
unrolled pairwise constraints can be machine-generated instead of written out.

The limit is rejection. Dense combinatorial constraints over elements, such as
pairwise distinctness or conflict sets near a packing limit, collapse the
acceptance rate. That is the signal to move to a custom type; see
[rejection](rejection.md).

## A custom type

Where the invariant is **global**, covering connectivity, pairwise spacing, or a
feasibility property no per-element rule expresses, a custom type constructs the
value instead of declaring it. The type carries its own sampler, so every value
it returns is already valid.

The judgment a custom type demands is **where to draw the ownership boundary**.
The rule: parameters coupled to the constructive invariant go *inside* the
type, and independent payloads stay outside as primitive parameters.

That boundary matters because everything moved inside loses its chart and its
prior. A graph's edge set belongs inside, since getting it right is the whole
job of the constructive sampler. A per-node learning rate is an independent
payload, and keeping it primitive keeps it log-scalable, introspectable, and
perturbable in u-space.

A property-driven lift count aligns the two:

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

Because `sample` cannot construct a disconnected graph, connectivity never
appears as a constraint and never contributes to rejection. That is what
"constructive" means here, and why a custom type holds up where rejection does
not.

`.prop()` reads a named property off the custom value, and using it as a count
keeps the payload list exactly as long as the structure the type built. A type
aligned this way must define a canonical ordering that is stable under JSON
round-trips. Without one, `node_lr[2]` names a different node after a save and
reload.

## Limits of the expression language

Value-dependent indexing (`islands[edges[k].src]`) and quantification over
dynamic ranges are permanently outside the expression language. Relational
semantics belong to a custom type or to the consumer.

Generative reparameterization is preferable to a measure-zero constraint. A
simplex declared as "*n* reals that sum to 1" has probability zero of ever being
sampled. Declared by stick-breaking it is primitive, chart-covered, and always
valid, with the manifold geometry carried in an `Encoding` instead of in a
constraint that rejection can never satisfy.

## Custom types and representations

A custom type that other parameters depend on through `.prop()` cannot later be
bridged away from `custom` with a `Representation` without dangling them. That
cuts against the custom-type advice above, which steers exactly the
bridge-worthy structures toward carrying properties.

The library offers no resolution here; the tension belongs to the modeller.
Where a type is expected to be bridged later, either keep prop-driven alignment
out of the space, or supply a bridge whose target is another custom type
exposing the same properties.
