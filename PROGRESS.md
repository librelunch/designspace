# Progress

Current milestone: **M14 (open)**

One row per completed milestone: date and total test count at completion. A
milestone's section is deleted from `PLAN.md` when its exit criteria pass, so
this file is the record that it shipped. Update the "Current milestone" line at
the same time. Decisions live in `DECISIONS.md`; this file does not index them.

From 2026-08-06 the test count is two numbers, `pytest -q` plus the doctest
gate, because those are two commit gates and two commands (see `CLAUDE.md`).
Rows before that date are single totals under the old arrangement.

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

## Out-of-band fixes

Bugfixes against already-shipped milestones, landed with their own conformance
laws. No milestone row.

| Date | Fix | Against |
|---|---|---|
| 2026-08-08 | The six gates moved into a `justfile`, their one definition, called by CI and by pre-commit and pre-push git hooks; devenv went native, pinned to the revision `flake.lock` carried | M12.5 |
| 2026-08-06 | Each commit gate became a command of its own, six rather than four; `core-only` CI job fixed for the polars-free install | M13, M13.5, M13.6 |
| 2026-08-06 | `build/` renamed to `builder/`, which had collided with pytest's default `norecursedirs` and cost the package all 83 of its doctests; test imports moved off private module paths | M1, M13, M2 |
| 2026-08-03 | Relocation rewrites a lift's domain-carried references (`ListDomain.count`, `element_constraints`); finalization audits both; a count's enclosing-scope reference is deferred like a condition | M3, M4, M10.5, M8 |
| 2026-08-03 | `.slice()`/`.freeze()` statically resolve what a fixed value determines: counts fold to a static `int`, always-true conditions to `None`; `.freeze()`'s fold gated on a single-value domain | M8 |
| 2026-08-03 | Immutability and copy-on-write swept over the exported surface: every exported dataclass frozen, read-only mapping views, every chainable op asserted to leave its receiver byte-identical | M0 to M12 |
| 2026-08-03 | Hardening pass 2: kind-by-surface matrix made permanent; transport handles the `ChartApply` node a representation emits, so `then` composes past one derived level; the round-trip law gains its tolerance and its authored-phenotype scope | M11 |
| 2026-08-03 | Hardening pass: reference-closure invariant over all four reference stores; a lifted choice's discriminator template now relocates; the container-element lift-depth boundary guarded on the compositional route | M3, M4 |
