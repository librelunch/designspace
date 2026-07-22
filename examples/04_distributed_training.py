"""Example 4 — Distributed Training: custom types, identity, and partial
configs.

A capstone example, gathering up what the first three deliberately left
out. The domain: configuring a data-parallel/pipeline-parallel training
run, where the *device interconnect topology* is not a value any built-in
type can express — it is a small graph, opaque to the library, wrapped in
a user-defined ``ParamType``.

Concepts introduced here
-------------------------
- ``.custom(param_type)``: the full protocol. ``DeviceTopology`` is a frozen
  dataclass — the canonical authoring template (``describe()`` = ``asdict(self)``,
  the registry factory is just ``cls(**d)``, so ``factory(x.describe()) == x``
  holds by construction) — with its own chainable, immutable config
  (``.with_max_degree(...)``): domain-specific fluent methods live on the
  *type* passed to ``.custom()``, not on a bespoke builder view.
- ``.prop(name)``: a declared, scalar-typed property of a custom value,
  usable in expressions — here driving a ``.repeat()`` count (the
  *canonical-ordering law*: the number of per-link bandwidth knobs always
  tracks the sampled topology's own edge count). A bool-declared prop is
  dual-typed, like a param reference itself — usable directly as a
  condition (``.require(x.prop("ok"))``, no ``== True`` needed).
- ``.require(...)``: the hard, positive-polarity verb — names the *desired*
  state directly (the earlier examples only used ``.forbid``/``.encourage``/
  ``.discourage``).
- ``.permutation(...)``: pipeline-stage assignment order.
- Identity and serialization: ``to_json()`` / ``Space.from_json(doc,
  custom_types=...)`` (a custom param needs a ``type_key -> factory``
  registry to reconstruct), ``fingerprint()`` equality, and
  ``ds.config_hash`` as a value's own stable key.
- Partial configs: ``apply_defaults``, then a scripted ``next_assignable``/
  ``is_complete``/``missing_params`` driver loop — the same incremental-fill
  pattern a wizard-style UI or a solver's ask-one-thing-at-a-time interface
  would use.
- ``.has_nongenerative_params`` and ``.cardinality()``, plus a second,
  *non-generative* custom type (no ``sample()``) — supplied, never
  searched, unless a ``.default()``/``.freeze()`` gives it a value.

Run it:  ``uv run python examples/04_distributed_training.py``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import designspace as ds


def _is_connected(n_devices: int, edges: list[tuple[int, int]]) -> bool:
    if n_devices <= 1:
        return True
    adjacency: dict[int, set[int]] = {i: set() for i in range(n_devices)}
    for i, j in edges:
        adjacency[i].add(j)
        adjacency[j].add(i)
    seen, frontier = {0}, [0]
    while frontier:
        node = frontier.pop()
        for neighbor in adjacency[node]:
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return len(seen) == n_devices


@dataclass(frozen=True)
class DeviceTopology:
    """Which device pairs share a direct high-bandwidth link. Opaque to
    core — no bounds, no chart — just the five required protocol methods
    plus the two optional ones (``sample``, ``properties``/``extract``)
    this type chooses to support.
    """

    n_devices: int = 5
    max_degree: int = 3

    def with_max_degree(self, max_degree: int) -> DeviceTopology:
        return replace(self, max_degree=max_degree)

    @property
    def type_key(self) -> str:
        return "device_topology"

    def sample(self, rng: Any) -> list[tuple[int, int]]:
        degree = [0] * self.n_devices
        edges: list[tuple[int, int]] = []
        for i in range(self.n_devices):
            for j in range(i + 1, self.n_devices):
                room = degree[i] < self.max_degree and degree[j] < self.max_degree
                if rng.random() < 0.6 and room:
                    edges.append((i, j))
                    degree[i] += 1
                    degree[j] += 1
        return edges

    def validate(self, value: Any) -> bool:
        if not isinstance(value, list):
            return False
        degree = [0] * self.n_devices
        seen: set[tuple[int, int]] = set()
        for item in value:
            if not (isinstance(item, tuple | list) and len(item) == 2):
                return False
            i, j = item
            if not (isinstance(i, int) and isinstance(j, int) and 0 <= i < j < self.n_devices):
                return False
            if (i, j) in seen:
                return False
            seen.add((i, j))
            degree[i] += 1
            degree[j] += 1
        return all(d <= self.max_degree for d in degree)

    def to_json(self, value: Any) -> Any:
        return [[i, j] for i, j in value]

    def from_json(self, data: Any) -> Any:
        return [(i, j) for i, j in data]

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    def properties(self) -> dict[str, type]:
        return {"n_links": int, "is_connected": bool}

    def extract(self, value: Any, prop: str) -> Any:
        if prop == "n_links":
            return len(value)
        if prop == "is_connected":
            return _is_connected(self.n_devices, [(i, j) for i, j in value])
        raise KeyError(prop)


def device_topology_factory(described: dict[str, Any]) -> DeviceTopology:
    return DeviceTopology(**described)


CUSTOM_TYPES: dict[str, Any] = {"device_topology": device_topology_factory}


@dataclass(frozen=True)
class FixedDeviceTopology:
    """A non-generative sibling: describes a topology's shape but declares
    no ``sample()`` — an ops-supplied interconnect, never searched."""

    n_devices: int = 5

    @property
    def type_key(self) -> str:
        return "fixed_device_topology"

    def validate(self, value: Any) -> bool:
        return isinstance(value, list) and all(
            isinstance(item, tuple | list) and len(item) == 2 for item in value
        )

    def to_json(self, value: Any) -> Any:
        return [[i, j] for i, j in value]

    def from_json(self, data: Any) -> Any:
        return [(i, j) for i, j in data]

    def describe(self) -> dict[str, Any]:
        return asdict(self)


STAGES = ("embed", "block_a", "block_b", "head")


def build_space() -> ds.Space:
    topology = DeviceTopology(n_devices=5).with_max_degree(3)
    return (
        ds.space(
            ds.param("topology").custom(topology),
            # A canonical-ordering law: the number of bandwidth knobs
            # always tracks the sampled topology's own edge count — no
            # separate "n_links" param to keep in sync by hand.
            ds.param("link_bandwidth_gbps")
            .real(10.0, 400.0)
            .log_scale()
            .repeat(ds.param("topology").prop("n_links")),
            ds.param("stage_order").permutation(STAGES),
            ds.param("micro_batch_size").integer(1, 64).default(8),
            ds.param("checkpointing").bool().default(False),
        )
        # The hard, positive-polarity verb: name the *desired* state
        # directly (the earlier examples only paired forbid with encourage/
        # discourage). A disconnected topology can't route gradients
        # between every device pair, so it is infeasible outright.
        .require(ds.param("topology").prop("is_connected"))
    )


def main() -> None:
    space = build_space()
    print(f"Distributed Training space: {space.n_params} parameters, "
          f"conditional={space.is_conditional}\n")

    # -- .custom() + .prop() ---------------------------------------------------
    print("--- Custom types and .prop() ---")
    config = space.sample_one(seed=0)
    print("A sampled configuration:")
    print(f"  topology            = {config['topology']!r}")
    print(f"  link_bandwidth_gbps = {[round(b, 1) for b in config['link_bandwidth_gbps']]}")
    print(f"  stage_order         = {config['stage_order']}")
    print(f"  micro_batch_size    = {config['micro_batch_size']}")
    print(f"  checkpointing       = {config['checkpointing']}")

    n_links = len(config["topology"])
    n_knobs = len(config["link_bandwidth_gbps"])
    print(f"\n.prop()-driven repeat: {n_knobs} bandwidth knob(s) == "
          f"{n_links} topology link(s): {n_knobs == n_links}")

    # -- .require() -------------------------------------------------------------
    print("\n--- .require() ---")
    disconnected = dict(config)
    disconnected["topology"] = [[0, 1], [2, 3]]  # two islands, device 4 stranded
    disconnected["link_bandwidth_gbps"] = config["link_bandwidth_gbps"][:2]
    print(f"  hand-built disconnected topology is_feasible: "
          f"{space.is_feasible(disconnected)}")
    for reason in space.infeasibility_reasons(disconnected):
        print(f"  reason: {reason}")

    # -- Identity and serialization ----------------------------------------------
    print("\n--- Identity and serialization ---")
    # Custom params serialize as `type_key` + `describe()`; reconstructing
    # the Space needs a `custom_types` registry mapping type_key -> factory.
    doc = space.to_json()
    restored = ds.Space.from_json(doc, custom_types=CUSTOM_TYPES)
    print(f"  to_json() -> from_json(custom_types=...): "
          f"fingerprint equal: {restored.fingerprint() == space.fingerprint()}")

    # A value's own stable key, independent of the space's fingerprint —
    # `(space.fingerprint(), config_hash(config, space))` is a globally
    # unique observation key.
    same_config_on_restored = restored.validate(config).valid
    print(f"  the same config validates against the restored space: "
          f"{same_config_on_restored}")
    print(f"  config_hash matches across the round-tripped space: "
          f"{ds.config_hash(config, space) == ds.config_hash(config, restored)}")

    # -- Partial configs ------------------------------------------------------
    print("\n--- Partial configs ---")
    defaulted = space.apply_defaults({})
    print(f"  apply_defaults({{}}) = {defaulted}")
    print(f"  missing_params: {space.missing_params(defaulted)}")

    # A scripted driver loop, revealing values from the config sampled
    # above one `next_assignable` step at a time — the incremental-fill
    # pattern a wizard-style UI or solver would use. A repeat()'s instances
    # only become individually assignable once its (here, prop-driven)
    # count is known; the canonical nested representation has no slot for
    # "list of the right length, some elements still missing," so a real
    # driver collects them together — here, in one step.
    partial: dict[str, Any] = dict(defaulted)
    step = 0
    while not space.is_complete(partial):
        step += 1
        path = space.next_assignable(partial)[0]
        if "[" in path:
            list_path = path[: path.index("[")]
            partial[list_path] = config[list_path]
            print(f"  step {step}: assign {list_path} "
                  f"(all {len(config[list_path])} link(s) at once)")
        else:
            partial[path] = config[path]
            print(f"  step {step}: assign {path} = {config[path]!r}")
    print(f"  is_complete: {space.is_complete(partial)}")

    # -- Introspection ----------------------------------------------------------
    print("\n--- Introspection ---")
    print(f"  has_nongenerative_params: {space.has_nongenerative_params}")
    print(f"  cardinality(): {space.cardinality()!r}  "
          "(None -- an unquantized real and an opaque custom both prevent an exact count)")

    # A custom type with no sample() is non-generative: it can only be
    # supplied, never searched, unless a .default()/.freeze() gives it one.
    fixed_space = ds.space(ds.param("topology").custom(FixedDeviceTopology(n_devices=5)))
    print(f"\n  a space with a sample()-less custom: "
          f"has_nongenerative_params={fixed_space.has_nongenerative_params}")
    try:
        fixed_space.sample_one(seed=0)
    except ds.SamplingError as e:
        print(f"  sample_one() raises SamplingError: {e}")
    provided = fixed_space.freeze(topology=[[0, 1], [1, 2]])
    print(f"  freeze(topology=[[0, 1], [1, 2]]).sample_one() = "
          f"{provided.sample_one(seed=0)}")


if __name__ == "__main__":
    main()
