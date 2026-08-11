# Progress

Current milestone: **M15 (open)**

One row per completed milestone: date and total test count at completion. This
file is the record that a milestone shipped; `PLAN.md` holds the protocol and
the work that has not. Update the "Current milestone" line with each row.
Decisions live in `DECISIONS.md`; this file does not index them.

From 2026-08-06 the test count is two numbers, `pytest -q` plus the doctest
gate, because those are two commit gates and two commands. Rows before that date
are single totals under the old arrangement. Both numbers are core's. The
`solvers` gate, added at M13.11, carries its own suite over the sibling package
under `packages/` and is counted in neither.

| Milestone | Completed | Tests |
|---|---|---|
| M0: Expression core | 2026-07-17 | 63 |
| M1: Builder, resolution skeleton, IR (flat scalar spaces) | 2026-07-17 | 126 |
| M2: Charts, Kleene, validation, sampler | 2026-07-17 | 259 |
| M3: Structure (choice, struct, subset, permutation, paths) | 2026-07-17 | 369 |
| M4: Lifts and aggregates | 2026-07-18 | 449 |
| M4.5: Faithfulness corrections | 2026-07-18 | 475 |
| M4.6: Build-layer view types | 2026-07-18 | 509 |
| M5: Expression bounds | 2026-07-19 | 550 |
| M6: Defaults and partial-config API | 2026-07-19 | 622 |
| M7: Identity and serialization (internal format-freeze checkpoint) | 2026-07-20 | 781 |
| M7.5: Post-freeze API additions (`require`, instance-path config utils) | 2026-07-21 | 800 |
| M7.6: Constraint API symmetrization (`encourage`/`discourage`, polarity accessors) | 2026-07-21 | 813 |
| M8: Structural operations and metaprogramming | 2026-07-22 | 925 |
| M9: Custom types (`.custom()`, `.prop()`, `from_json` registry, `.cardinality()`) | 2026-07-22 | 975 |
| M9.5: Container freeze completion (choice, subset, permutation, struct, list) | 2026-07-25 | 1017 |
| M10: DataFrame output (`space.sample()`, `polars` an optional extra) | 2026-07-26 | 1063 |
| M10.5: Expression and validation hygiene | 2026-07-30 | 1099 |
| M10.6: Sampling diagnostics (`sampling_report`) | 2026-07-30 | 1130 |
| M10.7: Traversal extraction and child index (`Space.coordinate_paths()`) | 2026-07-31 | 1189 |
| M10.8: `ds.value`, opaque derived quantities | 2026-07-31 | 1240 |
| M10.9: `unflatten`/`apply_defaults` static-count hygiene fix | 2026-07-31 | 1258 |
| M10.10: `ConstraintReport.violation_rate` | 2026-07-31 | 1265 |
| M11: Representation layer (`space.represent()`, the induced chart representation) | 2026-07-31 | 1362 |
| M12: Program types (`.symbolic()`, `.code()`) | 2026-08-01 | 1451 |
| M12.5: Repo and CI hygiene (`py.typed`, Python floor 3.12, `ruff format` gate) | 2026-08-03 | 1451 |
| M13: Public API documentation (NumPy docstrings, doctests, griffe gates; `__all__` 79 to 91) | 2026-08-04 | 2464 |
| M13.5: Documentation site (Sphinx, PyData theme, `designspace[docs]`; `__all__` 91 to 96) | 2026-08-04 | 2491 |
| M13.6: Executable tutorials and documentation prose (myst-nb, Tutorials and Design notes tabs) | 2026-08-05 | 2389 + 123 |
| M13.7: Design-document consolidation (`API.md` restructured, prose standards, four prose laws) | 2026-08-06 | 2447 + 123 |
| M13.8: Source and test prose (`src/` and `tests/` to the standard; prose laws widened; two new laws) | 2026-08-08 | 3156 + 123 |
| M13.9: User-facing text stands on its own (row citations out of messages and published docstrings; four new laws) | 2026-08-08 | 3462 + 123 |
| M13.10: Human-readable rendering (`__str__` on every public type, and `pretty(obj, space=None, ...)` | 2026-08-09 | 3820 + 126 |
| M13.11: Solver socket prototype (`designspace-solvers` under `packages/`, Optuna and cmaes bindings, a seventh gate) | 2026-08-10 | 3877 + 128 |
| M14: v0.1 release (MIT, release metadata, `CHANGELOG.md`, the release check, the documentation site, PyPI) | 2026-08-11 | 3897 + 128 |

## Out-of-band fixes

Bugfixes against already-shipped milestones, landed with their own conformance
laws. No milestone row.

| Date | Fix | Against |
|---|---|---|
| 2026-08-11 | The Optuna binding names each hard constraint's score and writes it onto the trial, so a per-element constraint is scored once per element where one ordered sequence changed length between trials; an inapplicable constraint is absent rather than scored zero, and one with no numeric distance reaches the sampler as its verdict rather than as feasible | M13.11 |
| 2026-08-11 | A definition's `type_kind` and its domain class are one fact with one home, so a definition where the two disagree is refused where assembled IR or a stored document enters, rather than failing later inside chart building without naming a parameter; the kind vocabulary is an exported union of literals | M1, M8, M11, M7 |
| 2026-08-10 | The partial-config surface takes a config in either form, so a driver loop can assign at the instance paths it reports; `flatten` refuses an already-flat config instead of dropping every lift and `ds.is_flat` reports that condition, `unflatten` reads a dynamic lift's length off its element keys, and `Space.param_def` resolves either path form to its definition. Extended to every config-taking method, validation and identity included, after `is_feasible` disagreed with `is_complete` about one configuration | M3, M4, M6, M7 |
| 2026-08-10 | An active lift is present whatever its count: a determined count of zero makes the container `active_unset` until its key holds `[]`, and `next_assignable` reports it, so the driver loop halts on a config that validates | M4, M6 |
| 2026-08-10 | `floor_to_grid` recovers a grid index with the same tolerance `build_grid_shape` floors with, so a multiplicative grid round-trips its own points instead of losing a whole cell; vectors byte-identical | M2, M5 |
| 2026-08-09 | The polars-free run selects on a `requires_polars` marker each test declares for itself, rather than on a list of ignored files and deselected node ids; it thereby regains 29 tests that list dropped, the missing-extra `ImportError` laws among them, and mypy resolves the two `TYPE_CHECKING` imports of the absent extra | M10, M12.5 |
| 2026-08-08 | The six gates moved into a `justfile`, their one definition, called by CI and by pre-commit and pre-push git hooks; devenv went native, pinned to the revision `flake.lock` carried | M12.5 |
| 2026-08-06 | Each commit gate became a command of its own, six rather than four; `core-only` CI job fixed for the polars-free install | M13, M13.5, M13.6 |
| 2026-08-06 | `build/` renamed to `builder/`, which had collided with pytest's default `norecursedirs` and cost the package all 83 of its doctests; test imports moved off private module paths | M1, M13, M2 |
| 2026-08-03 | Relocation rewrites a lift's domain-carried references (`ListDomain.count`, `element_constraints`); finalization audits both; a count's enclosing-scope reference is deferred like a condition | M3, M4, M10.5, M8 |
| 2026-08-03 | `.slice()`/`.freeze()` statically resolve what a fixed value determines: counts fold to a static `int`, always-true conditions to `None`; `.freeze()`'s fold gated on a single-value domain | M8 |
| 2026-08-03 | Immutability and copy-on-write swept over the exported surface: every exported dataclass frozen, read-only mapping views, every chainable op asserted to leave its receiver byte-identical | M0 to M12 |
| 2026-08-03 | Hardening pass 2: kind-by-surface matrix made permanent; transport handles the `ChartApply` node a representation emits, so `then` composes past one derived level; the round-trip law gains its tolerance and its authored-phenotype scope | M11 |
| 2026-08-03 | Hardening pass: reference-closure invariant over all four reference stores; a lifted choice's discriminator template now relocates; the container-element lift-depth boundary guarded on the compositional route | M3, M4 |
