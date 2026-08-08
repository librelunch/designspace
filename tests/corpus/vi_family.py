"""`vi_family` corpus fixture.

Exercises a custom type through `.custom()`, in both `ParamType` forms
below; the `describe()` and factory round-trip, `GraphTopology` and
`FixedTopology` being frozen dataclasses, which is the canonical authoring
template API.md, "Protocols" gives, with `describe()` as `asdict(self)` and
the factory as `cls(**d)`, so that `factory(x.describe()) == x` holds by
construction; `.prop()` constraints over `n_edges` and `is_connected`; the
canonical-ordering law, through the prop-driven lift count
`.repeat(ds.param("topology").prop("n_edges"))`; and the corpus's one
non-generative param, `FixedTopology` supplying no `sample()`.

A topology here is a small undirected graph over `n_nodes` nodes,
represented natively as a sorted `list[tuple[int, int]]` of edges, and as a
phenotype as `list[list[int]]`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import pairwise
from typing import Any

import designspace as ds
from designspace import Space


def _is_connected(n_nodes: int, edges: list[tuple[int, int]]) -> bool:
    if n_nodes <= 1:
        return True
    adjacency: dict[int, set[int]] = {i: set() for i in range(n_nodes)}
    for i, j in edges:
        adjacency[i].add(j)
        adjacency[j].add(i)
    seen = {0}
    frontier = [0]
    while frontier:
        node = frontier.pop()
        for neighbor in adjacency[node]:
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return len(seen) == n_nodes


@dataclass(frozen=True)
class GraphTopology:
    """Generative full-protocol `ParamType`: a graph topology, constructed
    to respect `max_degree` and (optionally) connectivity. Chainable,
    immutable configuration through `dataclasses.replace`, which is the
    authoring template API.md, "Protocols" gives with its custom-type
    contract laws.
    """

    n_nodes: int = 4
    max_degree: int = 2
    connected: bool = True

    @property
    def type_key(self) -> str:
        return "graph_topology"

    def with_max_degree(self, max_degree: int) -> GraphTopology:
        return replace(self, max_degree=max_degree)

    def with_connected(self, connected: bool = True) -> GraphTopology:
        return replace(self, connected=connected)

    def sample(self, rng: Any) -> list[tuple[int, int]]:
        """A constructive draw, enforcing the global invariant inside the type.

        API.md, "Solver Integration" calls this the third tier, against
        reject-and-retry. A random-permutation path spanning tree guarantees
        connectivity with every degree at most 2, and is always
        constructible given `max_degree >= 2`. Extra edges are then layered
        on only where both endpoints have spare degree, so connectivity,
        once established, can only be added to and never broken by what
        follows.
        """
        degree = [0] * self.n_nodes
        edges: list[tuple[int, int]] = []
        if self.connected and self.n_nodes > 1:
            order = [int(k) for k in rng.permutation(self.n_nodes)]
            for a, b in pairwise(order):
                i, j = (a, b) if a < b else (b, a)
                edges.append((i, j))
                degree[i] += 1
                degree[j] += 1
        candidates = [
            (i, j)
            for i in range(self.n_nodes)
            for j in range(i + 1, self.n_nodes)
            if (i, j) not in edges
        ]
        for idx in rng.permutation(len(candidates)):
            i, j = candidates[int(idx)]
            if degree[i] < self.max_degree and degree[j] < self.max_degree:
                edges.append((i, j))
                degree[i] += 1
                degree[j] += 1
        edges.sort()
        return edges

    def validate(self, value: Any) -> bool:
        if not isinstance(value, list):
            return False
        degree = [0] * self.n_nodes
        seen: set[tuple[int, int]] = set()
        for item in value:
            if not (isinstance(item, tuple | list) and len(item) == 2):
                return False
            i, j = item
            if not (isinstance(i, int) and isinstance(j, int) and 0 <= i < j < self.n_nodes):
                return False
            if (i, j) in seen:
                return False
            seen.add((i, j))
            degree[i] += 1
            degree[j] += 1
        if any(d > self.max_degree for d in degree):
            return False
        return not self.connected or _is_connected(self.n_nodes, [(i, j) for i, j in value])

    def to_json(self, value: Any) -> Any:
        return [[i, j] for i, j in value]

    def from_json(self, data: Any) -> Any:
        return [(i, j) for i, j in data]

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    def properties(self) -> dict[str, type]:
        return {"n_edges": int, "is_connected": bool}

    def extract(self, value: Any, prop: str) -> Any:
        if prop == "n_edges":
            return len(value)
        if prop == "is_connected":
            return _is_connected(self.n_nodes, [(i, j) for i, j in value])
        raise KeyError(prop)


def graph_topology_factory(described: dict[str, Any]) -> GraphTopology:
    return GraphTopology(**described)


@dataclass(frozen=True)
class FixedTopology:
    """A non-generative sibling: a topology's shape, with no `sample()`.

    It is the corpus's non-generative param, so it exercises
    `has_nongenerative_params` and the `SamplingError` that fires unless a
    `.default()` or a `.freeze()` covers it, under API.md, "Sampling and
    Generativity". It is still full-protocol, and therefore serializable and
    freezable, through `to_json` and `from_json`.
    """

    n_nodes: int = 3

    @property
    def type_key(self) -> str:
        return "fixed_topology"

    def validate(self, value: Any) -> bool:
        if not isinstance(value, list):
            return False
        for item in value:
            if not (isinstance(item, tuple | list) and len(item) == 2):
                return False
            i, j = item
            if not (isinstance(i, int) and isinstance(j, int) and 0 <= i < j < self.n_nodes):
                return False
        return True

    def to_json(self, value: Any) -> Any:
        return [[i, j] for i, j in value]

    def from_json(self, data: Any) -> Any:
        return [(i, j) for i, j in data]

    def describe(self) -> dict[str, Any]:
        return asdict(self)


def fixed_topology_factory(described: dict[str, Any]) -> FixedTopology:
    return FixedTopology(**described)


CUSTOM_TYPES: dict[str, Any] = {
    "graph_topology": graph_topology_factory,
    "fixed_topology": fixed_topology_factory,
}


def build_space() -> Space:
    """The generative half: a topology plus a per-edge weight, aligned to
    the topology's realized edge count via the canonical-ordering law
    (`.repeat(ds.param("topology").prop("n_edges"))`)."""
    topology = GraphTopology(n_nodes=5, max_degree=3, connected=True)
    return ds.space(
        ds.param("topology").custom(topology),
        ds.param("edge_weight").real(0.0, 1.0).repeat(ds.param("topology").prop("n_edges")),
    ).require(ds.param("topology").prop("is_connected"))


def build_finite_space() -> Space:
    """A small, fully finite space, for `.cardinality()`'s exact-count gate.

    It pairs a fixed-cardinality custom, one declaring `cardinality()`, with
    plain finite params.
    """
    topology = FixedFamily(n_nodes=3)
    return ds.space(
        ds.param("family").custom(topology),
        ds.param("depth").integer(1, 3),
    )


@dataclass(frozen=True)
class FixedFamily:
    """A tiny generative custom declaring a `cardinality()`.

    Every edge subset over `n_nodes` nodes is a legal value, there being no
    connectivity or degree constraint, so the count is closed-form at
    `2 ** C(n_nodes, 2)`.
    """

    n_nodes: int = 3

    @property
    def type_key(self) -> str:
        return "fixed_family"

    def sample(self, rng: Any) -> list[tuple[int, int]]:
        candidates = [(i, j) for i in range(self.n_nodes) for j in range(i + 1, self.n_nodes)]
        mask = rng.random(len(candidates)) < 0.5
        return sorted(c for c, keep in zip(candidates, mask, strict=True) if keep)

    def validate(self, value: Any) -> bool:
        if not isinstance(value, list):
            return False
        n_max = self.n_nodes * (self.n_nodes - 1) // 2
        return len(value) <= n_max and all(
            isinstance(item, tuple | list) and len(item) == 2 for item in value
        )

    def to_json(self, value: Any) -> Any:
        return [[i, j] for i, j in value]

    def from_json(self, data: Any) -> Any:
        return [(i, j) for i, j in data]

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    def cardinality(self) -> int:
        n_edges_max = self.n_nodes * (self.n_nodes - 1) // 2
        return int(2**n_edges_max)


def fixed_family_factory(described: dict[str, Any]) -> FixedFamily:
    return FixedFamily(**described)


CUSTOM_TYPES["fixed_family"] = fixed_family_factory
