# User guide

Eleven pages working through the library one topic at a time. Each is carried
by a concrete application, so the mechanism being introduced has something real
to act on.

The pages build on each other in order, but each declares its own space and can
be read on its own. Every card lists the names its page introduces. A name is
introduced on exactly one page, and later pages use it without re-explaining
it.

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} 01 Declaring a space
:link: 01-declaring-a-space
:link-type: doc

Scalar types, modifiers, priors and charts. What a resolved `ParamDef`
contains. Carried by a simulated annealing schedule.
+++
`.real`, `.integer`, `.categorical`, `.ordinal`, `.bool`, `.prior`,
`.log_scale`, `.quantized`, `.tag`, `Chart`, `.params`, `.constraints`
:::

:::{grid-item-card} 02 Sampling and validation
:link: 02-sampling-and-validation
:link-type: doc

Drawing configurations, checking them, and the difference between a value being
in range and a configuration being feasible.
+++
`.sample_one`, `.sample_dicts`, `.validate`, `.is_feasible`,
`.infeasibility_reasons`, `ds.flatten`, `ds.unflatten`
:::

:::{grid-item-card} 03 Conditionality and structure
:link: 03-conditionality-and-structure
:link-type: doc

Conditional parameters, alternatives that carry payloads, and grouping without
a discriminator, and how each changes the shape of a configuration. Carried by
a genetic algorithm's operators.
+++
`.when`, `.choice`, `.space`, `ds.variant`, `ds.payload`, `ds.destructure`,
`.subspaces`, `.active_subspace`
:::

:::{grid-item-card} 04 Constraints and feasibility
:link: 04-constraints-and-feasibility
:link-type: doc

The four verbs, margins, and reading a constraint report without re-deriving
polarity. Boolean and arithmetic expressions, including queries over subsets
and permutations. Carried by a flow chemistry rig.
+++
`.subset`, `.permutation`, `.require`, `.forbid`, `.encourage`, `.discourage`,
`.is_in`, `.is_active`, `.implies`, `ds.all_`, `ds.any_`, `ds.count`, `.size`,
`.sum_over`, `.position_of`, `.evaluate_constraints`
:::

:::{grid-item-card} 05 Lifts and aggregates
:link: 05-lifts-and-aggregates
:link-type: doc

Repeating a parameter with static and parameter-driven counts, instance paths,
and the aggregates that range over a list. Carried by a memetic pipeline.
+++
`.repeat`, `.field`, `.sum`, `.min`, `.max`, `.count_of`, `.is_sorted`,
`.distinct`, `.length`
:::

:::{grid-item-card} 06 Custom types and properties
:link: 06-custom-types
:link-type: doc

The custom-type protocol, property-driven counts, and types that validate
without generating. Carried by a device interconnect topology.
+++
`.custom`, `ParamType`, `.prop`, `.cardinality`
:::

:::{grid-item-card} 07 Program types
:link: 07-program-types
:link-type: doc

The two built-in opaque types: structural AST validation, checked arity, and
per-field opacity.
+++
`.symbolic`, `.code`, `Signature`
:::

:::{grid-item-card} 08 Structural operations
:link: 08-structural-operations
:link-type: doc

Reshaping a space after it is built, by pinning a parameter, removing one,
carving out a subtree, adding to it, or rewriting every parameter. Each returns
a new immutable `Space`.
+++
`.freeze`, `.slice`, `.select`, `.filter`, `.extend`, `.map_params`,
`.without_constraints`
:::

:::{grid-item-card} 09 Partial configs and driver loops
:link: 09-partial-configs
:link-type: doc

Defaults and their cascade, the five kinds of remaining domain, the incremental
fill loop, and positional vectors. Carried by a pump configurator.
+++
`.default`, `.apply_defaults`, `.evaluate_partial`, `.remaining_domain`,
`.param_activity`, `.next_assignable`, `.is_complete`, `.missing_params`,
`.validate_param`, `.coordinate_paths`
:::

:::{grid-item-card} 10 Diagnostics and DataFrames
:link: 10-diagnostics-and-dataframes
:link-type: doc

Columnar output and the dtype each kind takes, sampling diagnostics, and the
Unknown-swallowing that a post-rejection sample hides.
+++
`.sample`, `.sampling_report`, `reject_soft`, `tighten_bounds`, `.if_inactive`,
`ds.config_diff`
:::

:::{grid-item-card} 11 Identity and solver hand-off
:link: 11-identity-and-solvers
:link-type: doc

Serialization, fingerprint scopes, observation identity, and the three shapes a
solver integration takes.
+++
`.to_json`, `.from_json`, `.fingerprint`, `ds.config_hash`, `.meta`,
`.dependency_graph`, `.topological_order`, `.represent`, `Representation`
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
