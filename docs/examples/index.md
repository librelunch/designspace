# Examples

Ten runnable scripts, each self-contained. Every code block on the pages below
is extracted from the script it describes, so the two cannot drift apart.

```console
uv run python examples/01_simulated_annealing.py
```

`tests/test_examples.py` runs all ten to completion, which is what catches an
example rotting after a milestone changes the surface it demonstrates.

## Two arcs

Examples 01 to 04 grow the *shape* of a space, moving from flat through
hierarchical, variable-length and custom-typed, in the order a real design
space usually grows. Examples 05 to 10 hold the shape plain and grow what is
*done* with a space instead: the full expression vocabulary, struct parameters
and charts, DataFrame output and sampling diagnostics, the surface a consumer
calls, the bridge from a phenotype space to the genotype a solver optimizes
over, and the declaration of a tree or program genotype.

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} 01 Simulated annealing
:link: 01-simulated-annealing
:link-type: doc

A flat space. Scalar types, one conditional parameter, charts, and the
structural operations `.freeze`, `.slice`, `.filter` and `.extend`.
:::

:::{grid-item-card} 02 Genetic algorithm
:link: 02-genetic-algorithm
:link-type: doc

Hierarchy through `.choice()`. Variant payloads, `ds.variant`/`ds.payload`,
constraint polarity, `.select` and `.active_subspace`.
:::

:::{grid-item-card} 03 Memetic algorithm
:link: 03-memetic-algorithm
:link-type: doc

Variable-length pipelines. Lifted choices, vector aggregates, all four
constraint verbs, and `.map_params`.
:::

:::{grid-item-card} 04 Distributed training
:link: 04-distributed-training
:link-type: doc

Custom types. The full `ParamType` protocol, `.prop()`-driven counts,
serialization with a type registry, and the partial-config driver loop.
:::

:::{grid-item-card} 05 Flow chemistry
:link: 05-flow-chemistry
:link-type: doc

The expression vocabulary in one space, including subset and permutation
queries, `ds.value`, and Unknown-swallowing measured against its guard.
:::

:::{grid-item-card} 06 Thermal controller
:link: 06-thermal-controller
:link-type: doc

Struct parameters, nested lifts, explicit charts, expression bounds, and
element against list defaults.
:::

:::{grid-item-card} 07 Solver portfolio
:link: 07-portfolio-observability
:link-type: doc

A space in aggregate. DataFrame output and its dtype table,
`sampling_report()`, `config_diff`, and introspection without sampling.
:::

:::{grid-item-card} 08 Pump configurator
:link: 08-solver-integration
:link-type: doc

The consumer's surface. `coordinate_paths()`, all five `remaining_domain`
kinds, and metaprogramming over the IR.
:::

:::{grid-item-card} 09 Representation
:link: 09-representation
:link-type: doc

Genotype and phenotype. The induced chart representation, `rep.check()`,
mixed genotypes, and a supplied morphism.
:::

:::{grid-item-card} 10 Program types
:link: 10-program-types
:link-type: doc

`.symbolic()` and `.code()`. Structural AST validation, checked arity,
non-generative parameters, and per-field opacity.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

01-simulated-annealing
02-genetic-algorithm
03-memetic-algorithm
04-distributed-training
05-flow-chemistry
06-thermal-controller
07-portfolio-observability
08-solver-integration
09-representation
10-program-types
```

## Feature index

Keyed by `API.md` section heading. A concept is introduced in exactly one
place, and later examples use it without re-explaining it.

| `API.md` section | Where it appears |
|---|---|
| Parameter Types, Scalar (`real`/`integer`/`categorical`/`ordinal`/`bool`) | 01 |
| Parameter Types, Combinatorial (`subset`/`permutation`) | 03 (subset payload), 05 (`subset` and `permutation` queries), 08 (`PermutationRemaining`) |
| Parameter Types, Structural (`choice`, `.space(...)` struct) | 02 (choice), 06 (struct param, inline and prebuilt) |
| Parameter Types, Extension (`.custom(...)`) | 04 (full protocol), 08 (`sampler, validator` shorthand) |
| Parameter Types, Program (`.symbolic(...)`, `.code(...)`) | 10 |
| Modifiers and Layering (`.prior`, `.log_scale`, `.quantized`, `.default`, `.when`, `.tag`, `.meta`, the lift `.repeat`) | 01 (`.log_scale`, `.quantized(step=)`, `.when`), 03 (`.repeat(count)`, variadic sugar), 06 (nested and variadic `.repeat`, `periodic=True`, `.quantized(factor=)`, explicit `Log`/`Logit`/`Power`, element against list `.default`, `.meta`) |
| Paths and Scoping (path grammar, instance against definition paths) | 03 (instance paths into a lift), 06 (nested, negative and mixed instance paths) |
| Expressions, boolean vocabulary (`==`, `.is_in`, `.is_active`, `&`/`\|`/`~`, `.implies`, `ds.all_`/`ds.any_`/`ds.count`) | 01 (`.is_in`), 02 (`.implies`), 05 (`ds.all_`/`ds.any_`/`ds.count`, `.is_active`) |
| Expressions, arithmetic vocabulary (`.size`, `.sum_over`, `.position_of`, `.length`, `.prop`, `ds.value`, `.if_inactive`) | 04 (`.prop`), 05 (`.size`, `.sum_over`, `.position_of`, `.if_inactive`, `ds.value`), 06 (`.length`) |
| Expressions, vector aggregates (`.field`, `.sum`/`.min`/`.max`/`.count_of`/`.is_sorted`/`.distinct`) | 03 (`.count_of`, `.is_sorted`, plus `.sum`/`.min`/`.max`/`.distinct`/`.length`), 06 (`.field` projection over a struct lift) |
| Constraints and Feasibility (`.forbid`/`.require`/`.encourage`/`.discourage`, margins, `constraint.kind`/`ce.violated`) | 01 (`.forbid`/`.encourage`), 02 (feasibility against declared), 03 (all four verbs, read polarity-agnostically), 04 (`.require`) |
| Charts (prior families, quantization, periodicity) | 01 (`.log_scale`, linear `.quantized`), 06 (`periodic=True`, geometric `.quantized(factor=)`, explicit `Log`/`Logit`/`Power`) |
| Sampling and Generativity (`sample`/`sample_one`/`sample_dicts`, `reject_soft`, non-generative params) | 01 to 04 (`sample_one`/`sample_dicts`), 04 (non-generative custom, `SamplingError`), 07 (`space.sample()` DataFrame, `reject_soft=True`) |
| Defaults (`.default`, `apply_defaults`, cascade) | 04 (`apply_defaults`, `missing_params`), 06 (element against list default, `.anchor` derived from complete defaults) |
| Sampling diagnostics (`sampling_report`, Unknown-swallowing, funnels, `tighten_bounds`) | 05 (unguarded against `.if_inactive()`-guarded aggregate), 07 (`sampling_report()`, `tighten_bounds`) |
| Space, Validation (`validate`, `validate_param`, `is_feasible`, `infeasibility_reasons`, `evaluate_constraints`) | 01 to 04 (progressively), 08 (`validate_param(..., context=...)`) |
| Space, Partial Configs (`evaluate_partial`, `remaining_domain`, `param_activity`, `next_assignable`, `is_complete`, `missing_params`) | 04 (driver-loop sugar), 08 (the full surface, all five `remaining_domain` descriptor kinds) |
| Space, Introspection (`.params`, `.constraints`, `.subspaces`, `.dependency_graph`, `.cardinality()`) | 02 (`.subspaces`, `.is_hierarchical`), 04 (`.has_nongenerative_params`, `.cardinality()`), 07 (`dependency_graph`, `topological_order`, `param_constraints`/`param_conditions`, `is_finite`, `has_complete_defaults`) |
| Space, Structural Operations (`.freeze`/`.slice`/`.select`/`.filter`/`.extend`/`.active_subspace`) | 01 (`.freeze`/`.slice`/`.filter`/`.extend`), 02 (`.select`, `.active_subspace`) |
| Space, Metaprogramming (`ds.param_from_def`, `ds.space_from_ir`, `.map_params`, `.without_constraints`, the walkable `Expr.kind`/`.children`/`.params` triple) | 03 (`.map_params`, `.without_constraints`), 08 (`param_from_def`, `space_from_ir`, walking a constraint's expression tree, registry-driven generation with `ds.all_`) |
| Identity and Serialization (`to_json`/`from_json`, `fingerprint`, `config_hash`) | 04 (`to_json`/`from_json`, `fingerprint()` equality, `config_hash`), 04 and 07 (`fingerprint(scope=...)`), 08 (`fingerprint(on_unserializable="mark")`) |
| Config Utilities (`flatten`/`unflatten`, `config_hash`, `config_diff`, `variant`/`payload`/`destructure`, `coordinate_paths`) | 01 (`flatten`), 02 (`variant`/`payload`/`destructure`), 03 (`flatten`/`unflatten` round-trip), 07 (`config_diff`), 08 (`coordinate_paths` and its row-33 misuse error) |
| Config Representation (the dtype table) | 07 (`space.sample()` walking the table: the `Boolean`/`Float64`/`Int64`/`Utf8` discriminator, `Struct`/`Array` against `List`, null for inactive); struct-lift and lifted-choice dict shapes in 03 and 06 |
| The Representation Layer (`.represent()`, `Representation`, `Encoding`, `rep.check()`, the supplied tier) | 09 (induced chart representation, decode and encode, mixed genotypes via an explicit rule, a supplied hierarchy-flattening morphism) |

`Space.to_json_schema()` appears in `API.md` but in no example, because it is
not built yet. See `PROGRESS.md`.
