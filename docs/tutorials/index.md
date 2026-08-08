# Tutorials

Eleven pages working through the library one topic at a time. Each is carried
by a concrete application, so the mechanism being introduced has something real
to act on.

The pages build on each other in order, but each declares its own space and can
be read on its own.

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} 01 Declaring a space
:link: 01-declaring-a-space
:link-type: doc

Scalar types, modifiers, priors and charts. What a resolved `ParamDef`
contains. Carried by a simulated annealing schedule.
:::

:::{grid-item-card} 02 Sampling and validation
:link: 02-sampling-and-validation
:link-type: doc

Drawing configurations, checking them, and the difference between a value being
in range and a configuration being feasible.
:::

:::{grid-item-card} 03 Conditionality and structure
:link: 03-conditionality-and-structure
:link-type: doc

`.when()`, `.choice()` and struct grouping, and how each changes the shape of a
configuration. Carried by a genetic algorithm's operators.
:::

:::{grid-item-card} 04 Constraints and feasibility
:link: 04-constraints-and-feasibility
:link-type: doc

The four verbs, margins, and reading a constraint report without re-deriving
polarity. Carried by a flow chemistry rig.
:::

:::{grid-item-card} 05 Lifts and aggregates
:link: 05-lifts-and-aggregates
:link-type: doc

`.repeat()` with static and parameter-driven counts, instance paths, and the
aggregates that range over a list. Carried by a memetic pipeline.
:::

:::{grid-item-card} 06 Custom types and properties
:link: 06-custom-types
:link-type: doc

The `ParamType` protocol, `.prop()`-driven counts, and non-generative types.
Carried by a device interconnect topology.
:::

:::{grid-item-card} 07 Program types
:link: 07-program-types
:link-type: doc

`.symbolic()` and `.code()`: structural AST validation, checked arity, and
per-field opacity.
:::

:::{grid-item-card} 08 Structural operations
:link: 08-structural-operations
:link-type: doc

`.freeze`, `.slice`, `.filter`, `.extend`, `.map_params` and
`.without_constraints`, all returning a new immutable `Space`.
:::

:::{grid-item-card} 09 Partial configs and driver loops
:link: 09-partial-configs
:link-type: doc

Defaults, `remaining_domain`'s five kinds, the incremental fill loop, and
positional vectors. Carried by a pump configurator.
:::

:::{grid-item-card} 10 Diagnostics and DataFrames
:link: 10-diagnostics-and-dataframes
:link-type: doc

`space.sample()` and its dtype table, `sampling_report()`, and the
Unknown-swallowing that a post-rejection sample hides.
:::

:::{grid-item-card} 11 Identity and solver hand-off
:link: 11-identity-and-solvers
:link-type: doc

Serialization, fingerprint scopes, observation identity, and the three shapes a
solver integration takes.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

01-declaring-a-space
02-sampling-and-validation
03-conditionality-and-structure
04-constraints-and-feasibility
05-lifts-and-aggregates
06-custom-types
07-program-types
08-structural-operations
09-partial-configs
10-diagnostics-and-dataframes
11-identity-and-solvers
```

## Feature index

Every concept the tutorials cover, and the page that introduces it. A concept
is introduced in exactly one place, and later pages use it without
re-explaining it.

| Concept | Page |
|---|---|
| Scalar parameters (`real`/`integer`/`categorical`/`ordinal`/`bool`) | 01 |
| Combinatorial parameters (`subset`/`permutation`) | 04 (queries), 09 (`SubsetRemaining`, `PermutationRemaining`) |
| Structural parameters (`choice`, `.space(...)` struct) | 03, 05 (lifted choice, struct lift) |
| Custom types (`.custom(...)`) | 06 |
| Program types (`.symbolic(...)`, `.code(...)`) | 07 |
| Modifiers and layering (`.prior`, `.log_scale`, `.quantized`, `.default`, `.when`, `.tag`, `.meta`) | 01 (priors, scales, grids, tags), 03 (`.when`), 09 (`.default`), 11 (`.meta`) |
| Paths and scoping (path grammar, instance against definition paths) | 02 (`flatten`), 03 (choice payload paths), 05 (instance and nested indices) |
| Boolean expressions (`==`, `.is_in`, `.is_active`, `&`/`\|`/`~`, `.implies`, `ds.all_`/`ds.any_`/`ds.count`) | 04 |
| Arithmetic expressions (`.size`, `.sum_over`, `.position_of`, `.length`, `.prop`, `.if_inactive`) | 04 (subset and permutation queries), 05 (`.length`), 06 (`.prop`), 10 (`.if_inactive`) |
| Vector aggregates (`.field`, `.sum`/`.min`/`.max`/`.count_of`/`.is_sorted`/`.distinct`) | 05 |
| Constraints and feasibility (the four verbs, margins, `constraint.kind`/`ce.violated`) | 04 |
| Charts (prior families, quantization, periodicity) | 01, 11 (a solver's use of them) |
| Sampling and generativity (`sample`/`sample_one`/`sample_dicts`, `reject_soft`, non-generative params) | 02, 06 (non-generative custom), 07 (non-generative program), 10 (`reject_soft`) |
| Defaults (`.default`, `apply_defaults`, cascade) | 09 |
| Sampling diagnostics (`sampling_report`, Unknown-swallowing, `tighten_bounds`) | 10 |
| Validation (`validate`, `validate_param`, `is_feasible`, `infeasibility_reasons`, `evaluate_constraints`) | 02, 04 (constraint evaluation), 09 (`validate_param` with context) |
| Partial configurations (`evaluate_partial`, `remaining_domain`, `param_activity`, `next_assignable`, `is_complete`, `missing_params`) | 09 |
| Introspection (`.params`, `.constraints`, `.subspaces`, `.dependency_graph`, `.cardinality()`) | 01, 03 (`.subspaces`), 06 (`.cardinality()`), 11 (`dependency_graph`, `topological_order`) |
| Structural operations (`.freeze`/`.slice`/`.select`/`.filter`/`.extend`/`.active_subspace`) | 08, 03 (`.active_subspace`) |
| Metaprogramming (`.map_params`, `.without_constraints`) | 08 |
| Identity and serialization (`to_json`/`from_json`, `fingerprint`, `config_hash`) | 11 |
| Configuration utilities (`flatten`/`unflatten`, `config_diff`, `variant`/`payload`/`destructure`, `coordinate_paths`) | 02 (`flatten`/`unflatten`), 03 (`variant`/`payload`/`destructure`), 09 (`coordinate_paths`), 10 (`config_diff`) |
| DataFrame representation (the dtype table) | 10 |
| The representation layer (`.represent()`, `Representation`, `rep.check()`) | 11 |

`Space.to_json_schema()` has no page of its own because it is not built yet.
