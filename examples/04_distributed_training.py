"""Distributed training: custom types, identity, and partial configs.

A capstone example, gathering up what the first three deliberately left out.
The domain is a data-parallel and pipeline-parallel training run, where the
*device interconnect topology* is not a value any built-in type can express.
It is a small graph, opaque to the library, wrapped in a user-defined
``ParamType``.

Concepts introduced
-------------------
- ``.custom(param_type)``, the full protocol. ``DeviceTopology`` is a frozen
  dataclass, which is the canonical authoring template: ``describe()`` returns
  ``asdict(self)`` and the registry factory is ``cls(**d)``, so
  ``factory(x.describe()) == x`` holds by construction. It carries its own
  chainable, immutable config (``.with_max_degree(...)``), since domain-specific
  fluent methods belong on the *type* passed to ``.custom()`` and not on a
  bespoke builder view.
- ``.prop(name)``, a declared, scalar-typed property of a custom value, usable
  in expressions. Here it drives a ``.repeat()`` count, giving the
  *canonical-ordering law*: the number of per-link bandwidth parameters always
  tracks the sampled topology's own edge count. A bool-declared prop is
  dual-typed, like a parameter reference itself, so it works directly as a
  condition (``.require(x.prop("ok"))``, with no ``== True``).
- ``.require(...)``, the hard, positive-polarity verb, naming the *desired*
  state directly. The earlier examples used only ``.forbid``, ``.encourage``
  and ``.discourage``.
- ``.permutation(...)`` for pipeline-stage assignment order.
- Identity and serialization: ``to_json()`` and ``Space.from_json(doc,
  custom_types=...)``, where a custom param needs a ``type_key -> factory``
  registry to reconstruct, plus ``fingerprint()`` equality and
  ``ds.config_hash`` as a value's own stable key.
- ``fingerprint(scope=...)``. ``"sampling"`` covers the feasible set, measure
  and chart geometry; ``"full"`` is document identity. A ``.meta()``-only
  change moves the second and not the first.
- Partial configs: ``apply_defaults``, then a scripted ``next_assignable``,
  ``is_complete`` and ``missing_params`` driver loop. This is the incremental
  fill pattern a wizard-style UI or a solver's ask-one-thing-at-a-time
  interface uses.
- ``.has_nongenerative_params`` and ``.cardinality()``, plus a second,
  *non-generative* custom type with no ``sample()``. Such a type is supplied
  and never searched, unless a ``.default()`` or ``.freeze()`` gives it a value.

Run with ``uv run python examples/04_distributed_training.py``.
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
    """Which device pairs share a direct high-bandwidth link.

    The value is opaque to core, with no bounds and no chart. The type supplies
    the five required protocol methods plus the two optional ones it chooses to
    support, ``sample`` and ``properties``/``extract``.
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
    """A non-generative sibling.

    It describes a topology's shape but declares no ``sample()``, so it models
    an ops-supplied interconnect that is never searched.
    """

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
            # A canonical-ordering law: the number of bandwidth parameters
            # always tracks the sampled topology's own edge count, so there is
            # no separate "n_links" parameter to keep in sync by hand.
            ds.param("link_bandwidth_gbps")
            .real(10.0, 400.0)
            .log_scale()
            .repeat(ds.param("topology").prop("n_links")),
            ds.param("stage_order").permutation(STAGES),
            ds.param("micro_batch_size").integer(1, 64).default(8),
            ds.param("checkpointing").bool().default(False),
        )
        # The hard, positive-polarity verb names the *desired* state directly.
        # The earlier examples paired forbid only with encourage and
        # discourage. A disconnected topology cannot route gradients between
        # every device pair, so it is infeasible outright.
        .require(ds.param("topology").prop("is_connected"))
    )


def show_summary(space: ds.Space) -> None:
    print(
        f"Distributed training space: {space.n_params} parameters, "
        f"conditional={space.is_conditional}\n"
    )


def show_custom_and_prop(space: ds.Space) -> None:
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
    print(
        f"\n.prop()-driven repeat: {n_knobs} bandwidth knob(s) == "
        f"{n_links} topology link(s): {n_knobs == n_links}"
    )


def show_require(space: ds.Space) -> None:
    print("\n--- .require() ---")
    config = space.sample_one(seed=0)
    disconnected = dict(config)
    disconnected["topology"] = [[0, 1], [2, 3]]  # two islands, device 4 stranded
    disconnected["link_bandwidth_gbps"] = config["link_bandwidth_gbps"][:2]
    print(f"  hand-built disconnected topology is_feasible: {space.is_feasible(disconnected)}")
    for reason in space.infeasibility_reasons(disconnected):
        print(f"  reason: {reason}")


def show_identity(space: ds.Space) -> None:
    print("\n--- Identity and serialization ---")
    config = space.sample_one(seed=0)

    # Custom params serialize as `type_key` plus `describe()`. Reconstructing
    # the Space needs a `custom_types` registry mapping type_key to factory.
    doc = space.to_json()
    restored = ds.Space.from_json(doc, custom_types=CUSTOM_TYPES)
    print(
        f"  to_json() -> from_json(custom_types=...): "
        f"fingerprint equal: {restored.fingerprint() == space.fingerprint()}"
    )

    # A value's own stable key, independent of the space's fingerprint. The
    # pair `(space.fingerprint(), config_hash(config, space))` is a globally
    # unique observation key.
    same_config_on_restored = restored.validate(config).valid
    print(f"  the same config validates against the restored space: {same_config_on_restored}")
    print(
        f"  config_hash matches across the round-tripped space: "
        f"{ds.config_hash(config, space) == ds.config_hash(config, restored)}"
    )

    # `scope="sampling"` identifies the feasible set, measure and chart
    # geometry only. `scope="full"`, the default, is full document identity. A
    # change touching only identity-level bookkeeping moves one and not the
    # other.
    tagged = space.meta(experiment="baseline")  # identity-level bookkeeping only
    print(
        f"  a .meta()-only change: sampling-scope fingerprint equal: "
        f"{space.fingerprint(scope='sampling') == tagged.fingerprint(scope='sampling')}"
    )
    print(
        f"  a .meta()-only change: full-scope fingerprint equal:     "
        f"{space.fingerprint(scope='full') == tagged.fingerprint(scope='full')}"
    )


def show_partial_configs(space: ds.Space) -> None:
    print("\n--- Partial configs ---")
    config = space.sample_one(seed=0)
    defaulted = space.apply_defaults({})
    print(f"  apply_defaults({{}}) = {defaulted}")
    print(f"  missing_params: {space.missing_params(defaulted)}")

    # A scripted driver loop, revealing values from the config sampled above
    # one `next_assignable` step at a time. This is the incremental fill
    # pattern a wizard-style UI or solver uses. A repeat()'s instances become
    # individually assignable only once its count is known, which here is
    # prop-driven; the canonical nested representation has no slot for "list of
    # the right length, some elements still missing", so a real driver collects
    # them together, as this loop does in one step.
    partial: dict[str, Any] = dict(defaulted)
    step = 0
    while not space.is_complete(partial):
        step += 1
        path = space.next_assignable(partial)[0]
        if "[" in path:
            list_path = path[: path.index("[")]
            partial[list_path] = config[list_path]
            print(
                f"  step {step}: assign {list_path} (all {len(config[list_path])} link(s) at once)"
            )
        else:
            partial[path] = config[path]
            print(f"  step {step}: assign {path} = {config[path]!r}")
    print(f"  is_complete: {space.is_complete(partial)}")


def show_introspection(space: ds.Space) -> None:
    print("\n--- Introspection ---")
    print(f"  has_nongenerative_params: {space.has_nongenerative_params}")
    print(
        f"  cardinality(): {space.cardinality()!r}  "
        "(None, because an unquantized real and an opaque custom both prevent "
        "an exact count)"
    )

    # A custom type with no sample() is non-generative. It can only be
    # supplied, never searched, unless a .default() or .freeze() gives it a
    # value.
    fixed_space = ds.space(ds.param("topology").custom(FixedDeviceTopology(n_devices=5)))
    print(
        f"\n  a space with a sample()-less custom: "
        f"has_nongenerative_params={fixed_space.has_nongenerative_params}"
    )
    try:
        fixed_space.sample_one(seed=0)
    except ds.SamplingError as e:
        print(f"  sample_one() raises SamplingError: {e}")
    provided = fixed_space.freeze(topology=[[0, 1], [1, 2]])
    print(f"  freeze(topology=[[0, 1], [1, 2]]).sample_one() = {provided.sample_one(seed=0)}")


def main() -> None:
    space = build_space()
    show_summary(space)
    show_custom_and_prop(space)
    show_require(space)
    show_identity(space)
    show_partial_configs(space)
    show_introspection(space)


if __name__ == "__main__":
    main()
