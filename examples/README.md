# Examples

Two arcs, in one directory:

- **01–04** grow the *shape* of a space — flat, hierarchical (choice),
  variable-length (lifts), and custom-typed — in increasing complexity, the
  way a real design space usually grows.
- **05–08** hold the shape plain and grow what you *do* with a space
  instead — the full expression vocabulary, struct params and charts,
  DataFrame output and sampling diagnostics, and the surface a consumer
  (solver, wizard UI, driver loop) actually calls.

Each file is self-contained and runnable:

```console
uv run python examples/01_simulated_annealing.py
```

Every example is also exercised by `tests/test_examples.py` (`uv run pytest
tests/test_examples.py`), so a milestone that changes the public surface
gets caught here rather than letting these rot silently.

## Feature -> example index

Keyed by `API.md` section heading. A concept is introduced in exactly one
place; later examples use it freely without re-explaining.

| `API.md` section | Where it's shown |
|---|---|
| Parameter Types — Scalar (`real`/`integer`/`categorical`/`ordinal`/`bool`) | 01 |
| Parameter Types — Combinatorial (`subset`/`permutation`) | 03 (subset payload), 05 (`subset` queries, `permutation` queries), 08 (`PermutationRemaining`) |
| Parameter Types — Structural (`choice`, `.space(...)` struct) | 02 (choice), 06 (struct param, inline and prebuilt) |
| Parameter Types — Extension (`.custom(...)`) | 04 (full protocol), 08 (`sampler, validator` shorthand) |
| Modifiers and Layering (`.prior`, `.log_scale`, `.quantized`, `.default`, `.when`, `.tag`, `.meta`, the lift `.repeat`) | 01 (`.log_scale`, `.quantized(step=)`, `.when`), 03 (`.repeat(count)`, variadic sugar), 06 (nested/variadic `.repeat`, `periodic=True`, `.quantized(factor=)`, explicit `Log`/`Logit`/`Power`, element vs. list `.default`, `.meta`) |
| Paths and Scoping (path grammar, instance vs. definition paths) | 03 (instance paths into a lift), 06 (nested/negative/mixed instance paths) |
| Expressions — boolean vocabulary (`==`, `.is_in`, `.is_active`, `&`/`\|`/`~`, `.implies`, `ds.all_`/`ds.any_`/`ds.count`) | 01 (`.is_in`), 02 (`.implies`), 05 (`ds.all_`/`ds.any_`/`ds.count`, `.is_active`) |
| Expressions — arithmetic vocabulary (`.size`, `.sum_over`, `.position_of`, `.length`, `.prop`, `ds.value`, `.if_inactive`) | 04 (`.prop`), 05 (`.size`, `.sum_over`, `.position_of`, `.if_inactive`, `ds.value`), 06 (`.length`) |
| Expressions — vector aggregates (`.field`, `.sum`/`.min`/`.max`/`.count_of`/`.is_sorted`/`.distinct`) | 03 (`.count_of`, `.is_sorted`, plus `.sum`/`.min`/`.max`/`.distinct`/`.length`), 06 (`.field` projection over a struct lift) |
| Constraints and Feasibility (`.forbid`/`.require`/`.encourage`/`.discourage`, margins, `constraint.kind`/`ce.violated`) | 01 (`.forbid`/`.encourage`), 02 (feasibility vs. declared), 03 (all four verbs, polarity-agnostic reading), 04 (`.require`) |
| Charts (prior families, quantization, periodicity) | 01 (`.log_scale`, linear `.quantized`), 06 (`periodic=True`, geometric `.quantized(factor=)`, explicit `Log`/`Logit`/`Power`) |
| Sampling and Generativity (`sample`/`sample_one`/`sample_dicts`, `reject_soft`, non-generative params) | 01–04 (`sample_one`/`sample_dicts`), 04 (non-generative custom, `SamplingError`), 07 (`space.sample()` DataFrame, `reject_soft=True`) |
| Defaults (`.default`, `apply_defaults`, cascade) | 04 (`apply_defaults`, `missing_params`), 06 (element vs. list default, `.anchor` derived from complete defaults) |
| Sampling diagnostics (`sampling_report`, Unknown-swallowing, funnels, `tighten_bounds`) | 05 (unguarded vs. `.if_inactive()`-guarded aggregate), 07 (`sampling_report()`, `tighten_bounds`) |
| Space — Validation (`validate`, `validate_param`, `is_feasible`, `infeasibility_reasons`, `evaluate_constraints`) | 01–04 (progressively), 08 (`validate_param(..., context=...)`) |
| Space — Partial Configs (`evaluate_partial`, `remaining_domain`, `param_activity`, `next_assignable`, `is_complete`, `missing_params`) | 04 (driver-loop sugar), 08 (the full surface, all five `remaining_domain` descriptor kinds) |
| Space — Introspection (`.params`, `.constraints`, `.subspaces`, `.dependency_graph`, `.cardinality()`, ...) | 02 (`.subspaces`, `.is_hierarchical`), 04 (`.has_nongenerative_params`, `.cardinality()`), 07 (`dependency_graph`, `topological_order`, `param_constraints`/`param_conditions`, `is_finite`, `has_complete_defaults`) |
| Space — Structural Operations (`.freeze`/`.slice`/`.select`/`.filter`/`.extend`/`.active_subspace`) | 01 (`.freeze`/`.slice`/`.filter`/`.extend`), 02 (`.select`, `.active_subspace`) |
| Space — Metaprogramming (`ds.param_from_def`, `ds.space_from_ir`, `.map_params`, `.without_constraints`, the walkable `Expr.kind`/`.children`/`.params` triple) | 03 (`.map_params`, `.without_constraints`), 08 (`param_from_def`, `space_from_ir`, walking a constraint's expression tree, registry-driven generation with `ds.all_`) |
| Identity and Serialization (`to_json`/`from_json`, `fingerprint`, `config_hash`) | 04 (`to_json`/`from_json`, `fingerprint()` equality, `config_hash`), 04 & 07 (`fingerprint(scope=...)`), 08 (`fingerprint(on_unserializable="mark")`) |
| Config Utilities (`flatten`/`unflatten`, `config_hash`, `config_diff`, `variant`/`payload`/`destructure`, `coordinate_paths`) | 01 (`flatten`), 02 (`variant`/`payload`/`destructure`), 03 (`flatten`/`unflatten` round-trip), 07 (`config_diff`), 08 (`coordinate_paths`, its row-33 misuse error) |
| Config Representation (the dtype table) | 07 (`space.sample()` walking the table: `Boolean`/`Float64`/`Int64`/`Utf8` discriminator + `Struct`/`Array` vs. `List`/null-for-inactive); struct-lift and lifted-choice dict shapes in 03 and 06 |

## Not yet implemented

These appear in `API.md` but not in any example, because they aren't built
yet (see `PROGRESS.md`): `.represent()` / `Representation` / `Encoding` (the
Representation Layer, milestone M11), `.symbolic()` / `.code()` (Program
params, M12), `.to_json_schema()`.
