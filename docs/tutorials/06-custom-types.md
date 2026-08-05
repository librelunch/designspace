---
file_format: mystnb
---

# Custom types and properties

Some values are not expressible by any built-in type. A device interconnect
topology is a small graph: opaque to the library, but with invariants that
matter. `.custom()` wraps such a value in a user-defined type that owns its own
sampling, validation and serialization.

## The protocol

Five methods are required. `type_key` identifies the type in serialized form,
`validate` accepts or rejects a value, `to_json`/`from_json` move it across the
wire, and `describe` returns the type's own configuration.

A frozen dataclass is the canonical authoring template: `describe()` is
`asdict(self)` and the registry factory is `cls(**d)`, so
`factory(x.describe()) == x` holds by construction.

```{code-cell}
from dataclasses import asdict, dataclass
from typing import Any

import designspace as ds


def _is_connected(n_devices, edges):
    if n_devices <= 1:
        return True
    adjacency = {i: set() for i in range(n_devices)}
    for i, j in edges:
        adjacency[i].add(j)
        adjacency[j].add(i)
    seen, frontier = {0}, [0]
    while frontier:
        for neighbor in adjacency[frontier.pop()]:
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return len(seen) == n_devices


@dataclass(frozen=True)
class DeviceTopology:
    """Which device pairs share a direct high-bandwidth link."""

    n_devices: int = 5
    max_degree: int = 3

    @property
    def type_key(self):
        return "device_topology"

    def describe(self):
        return asdict(self)

    def validate(self, value):
        if not isinstance(value, list):
            return False
        degree = [0] * self.n_devices
        seen = set()
        for item in value:
            if not (isinstance(item, tuple | list) and len(item) == 2):
                return False
            i, j = item
            if not (isinstance(i, int) and isinstance(j, int)):
                return False
            if not 0 <= i < j < self.n_devices or (i, j) in seen:
                return False
            seen.add((i, j))
            degree[i] += 1
            degree[j] += 1
        return all(d <= self.max_degree for d in degree)

    def to_json(self, value):
        return [[i, j] for i, j in value]

    def from_json(self, data):
        return [(i, j) for i, j in data]

    def sample(self, rng):
        degree = [0] * self.n_devices
        edges = []
        for i in range(self.n_devices):
            for j in range(i + 1, self.n_devices):
                room = degree[i] < self.max_degree and degree[j] < self.max_degree
                if rng.random() < 0.6 and room:
                    edges.append((i, j))
                    degree[i] += 1
                    degree[j] += 1
        return edges

    def properties(self):
        return {"n_links": int, "is_connected": bool}

    def extract(self, value, prop):
        if prop == "n_links":
            return len(value)
        if prop == "is_connected":
            return _is_connected(self.n_devices, [(i, j) for i, j in value])
        raise KeyError(prop)


DeviceTopology().type_key
```

Two of those methods are optional. `sample(rng)` makes the type **generative**,
so the reference sampler can draw one. `properties()` and `extract()` declare
scalar facts about a value that expressions can read.

## Declaring and drawing

```{code-cell}
space = ds.space(
    ds.param("topology").custom(DeviceTopology(n_devices=5, max_degree=3)),
    ds.param("stage_order").permutation(("embed", "block_a", "block_b", "head")),
)
config = space.sample_one(seed=0)
config["topology"]
```

The value is whatever the type's `sample` returned. Core neither interprets nor
constrains its shape beyond calling `validate`.

```{code-cell}
space.validate(config).valid
```

```{code-cell}
space.validate_param("topology", [[0, 1], [0, 1]]).param_errors
```

## Properties in expressions

`.prop(name)` reads a declared property and returns something usable in an
expression. A bool-declared property is dual-typed, like a parameter reference
itself, so it works directly as a condition with no `== True`.

```{code-cell}
space = ds.space(
    ds.param("topology").custom(DeviceTopology(n_devices=5, max_degree=3)),
    ds.param("link_bandwidth_gbps")
    .real(10.0, 400.0)
    .log_scale()
    .repeat(ds.param("topology").prop("n_links")),
).require(ds.param("topology").prop("is_connected"))
config = space.sample_one(seed=0)
len(config["topology"]), len(config["link_bandwidth_gbps"])
```

Driving a `.repeat()` count with a property gives the canonical-ordering law:
the number of per-link parameters always tracks the sampled topology's own edge
count, with no separate `n_links` parameter to keep in sync.

```{code-cell}
:tags: [remove-output]

for c in space.sample_dicts(50, seed=1):
    assert len(c["link_bandwidth_gbps"]) == len(c["topology"])
    assert _is_connected(5, c["topology"])
```

A type aligned this way must define a canonical ordering that is stable under a
JSON round-trip. Without one, `link_bandwidth_gbps[2]` names a different link
after a save and reload.

The `require` on the connectivity property makes a disconnected topology
infeasible outright:

```{code-cell}
islands = dict(config, topology=[(0, 1), (2, 3)], link_bandwidth_gbps=[100.0, 200.0])
space.is_feasible(islands), space.infeasibility_reasons(islands)
```

## Non-generative types

A type with no `sample` can be supplied but never searched.

```{code-cell}
@dataclass(frozen=True)
class FixedTopology:
    n_devices: int = 5

    @property
    def type_key(self):
        return "fixed_topology"

    def describe(self):
        return asdict(self)

    def validate(self, value):
        return isinstance(value, list)

    def to_json(self, value):
        return [[i, j] for i, j in value]

    def from_json(self, data):
        return [(i, j) for i, j in data]


fixed = ds.space(ds.param("topology").custom(FixedTopology()))
fixed.has_nongenerative_params
```

```{code-cell}
try:
    fixed.sample_one(seed=0)
except ds.SamplingError as exc:
    print(exc)
```

A `.default()` or `.freeze()` supplies the missing value and satisfies
`sample()`'s obligation:

```{code-cell}
fixed.freeze(topology=[(0, 1), (1, 2)]).sample_one(seed=0)
```

An opaque value also blocks an exact count of the space:

```{code-cell}
fixed.cardinality()
```

## Where to go next

[Program types](07-program-types.md) covers the two built-in opaque types,
`.symbolic()` and `.code()`.
