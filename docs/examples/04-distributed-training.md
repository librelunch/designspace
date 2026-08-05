# Distributed training

A capstone example, gathering up what the first three left out. The device
interconnect topology is a small graph that no built-in type can express, so it
is opaque to the library and wrapped in a user-defined `ParamType`.

Source: `examples/04_distributed_training.py`. Run it with
`uv run python examples/04_distributed_training.py`.

## The custom type

A frozen dataclass is the canonical authoring template. `describe()` returns
`asdict(self)` and the registry factory is `cls(**d)`, so
`factory(x.describe()) == x` holds by construction. Domain-specific fluent
methods such as `.with_max_degree(...)` belong on the type itself rather than
on a bespoke builder view.

Five protocol methods are required (`type_key`, `validate`, `to_json`,
`from_json`, `describe`). This type also supplies the two optional ones,
`sample` for generativity and `properties`/`extract` for declared properties.

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: DeviceTopology
```

Reconstructing a space containing a custom parameter needs a `type_key` to
factory registry:

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: device_topology_factory
```

## Declaring the space

`.prop(name)` reads a declared, scalar-typed property off a custom value and
returns something usable in expressions. Driving a `.repeat()` count with it
gives the canonical-ordering law: the number of per-link bandwidth parameters
always tracks the sampled topology's own edge count, with no separate `n_links`
parameter to keep in sync.

A bool-declared prop is dual-typed, like a parameter reference itself, so
`.require(x.prop("is_connected"))` needs no `== True`.

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: build_space
```

## Sampling and property alignment

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: show_custom_and_prop
```

## The positive hard verb

`.require()` names the *desired* state directly. The earlier examples paired
`.forbid()` only with `.encourage()` and `.discourage()`.

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: show_require
```

## Identity and serialization

`fingerprint(scope="sampling")` identifies the feasible set, measure and chart
geometry. `scope="full"`, the default, is document identity. A change touching
only identity-level bookkeeping moves the second and not the first.

`ds.config_hash(config, space)` is a value's own stable key, so the pair
`(space.fingerprint(), config_hash(config, space))` identifies one observation
globally.

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: show_identity
```

## The partial-config driver loop

`apply_defaults` fills what defaults cover, then `next_assignable`,
`is_complete` and `missing_params` drive an incremental fill. This is the
pattern a wizard-style UI or a solver's ask-one-thing-at-a-time interface uses.

A lift's instances become individually assignable only once its count is known,
which here is prop-driven. The canonical nested representation has no slot for
"list of the right length, some elements still missing", so a driver collects
them together.

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: show_partial_configs
```

## Non-generative custom types

A custom type with no `sample()` can only be supplied, never searched, unless a
`.default()` or `.freeze()` gives it a value.

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: FixedDeviceTopology
```

```{literalinclude} ../../examples/04_distributed_training.py
:pyobject: show_introspection
```
