# Progress

Current milestone: **M13.5 (open)**

| Milestone | Completed | Tests | DECISIONS entries |
|---|---|---|---|
| M0 — Expression core | 2026-07-17 | 63 | D-1 |
| M1 — Builder, resolution skeleton, IR (flat scalar spaces) | 2026-07-17 | 126 | D-2, D-3 |
| M2 — Charts, Kleene, validation, sampler | 2026-07-17 | 259 | D-4, D-5, D-6, D-7, D-8, D-9, D-10 |
| M3 — Structure: choice, struct, subset, permutation, paths | 2026-07-17 | 369 | D-11, D-12, D-13, D-14, D-15, D-16, D-17 |
| M4 — Lifts and aggregates | 2026-07-18 | 449 | D-18, D-19, D-20, D-21, D-22, D-23, D-24, D-25 |
| M4.5 — Faithfulness corrections | 2026-07-18 | 475 | _none_ |
| M4.6 — Build-layer view types | 2026-07-18 | 509 | D-27, D-28 |
| M5 — Expression bounds | 2026-07-19 | 550 | D-29 |
| M6 — Defaults and partial-config API | 2026-07-19 | 622 | D-30 |
| M7 — Identity and serialization (internal format-freeze checkpoint) | 2026-07-20 | 781 | D-31, D-32, D-33, D-34, D-35, D-36, D-37 |
| M7.5 — Post-freeze API additions (`require`, instance-path config utils) | 2026-07-21 | 800 | D-38 |
| M7.6 — Constraint API symmetrization (`encourage`/`discourage`, polarity accessors) | 2026-07-21 | 813 | D-39 |
| M8 — Structural operations and metaprogramming | 2026-07-22 | 925 | D-40, D-41, D-42, D-43, D-44 |
| M9 — Custom types (`.custom()`, `.prop()`, `from_json` registry, `.has_nongenerative_params`, `.cardinality()`) | 2026-07-22 | 975 | D-45, D-46, D-47, D-48, D-49 |
| M9.5 — Container freeze completion (`.freeze()` for choice/subset/permutation/struct/list) | 2026-07-25 | 1017 | D-50 |
| M10 — DataFrame output (`space.sample() -> pl.DataFrame`, `polars` an optional extra) | 2026-07-26 | 1063 | D-51 |
| M10.5 — Expression and validation hygiene (Unknown provenance, instance-path indexing, repeat-count calculus, lift-valued-bool/choice-payload/anchor validation) | 2026-07-30 | 1099 | D-71, D-72 |
| M10.6 — Sampling diagnostics (`sampling_report`, `SamplingReport`/`ConstraintReport`) | 2026-07-30 | 1130 | D-73, D-74 |
| M10.7 — Traversal extraction and child index (`Space.coordinate_paths()`, `unflatten` static-count fallback) | 2026-07-31 | 1189 | D-75 |
| M10.8 — `ds.value`: opaque derived quantities | 2026-07-31 | 1240 | D-76, D-77, D-78 |
| M10.9 — `unflatten`/`apply_defaults` static-count hygiene fix | 2026-07-31 | 1258 | _none_ |
| M10.10 — `ConstraintReport.violation_rate` | 2026-07-31 | 1265 | _none_ |
| M11 — Representation layer (`space.represent()`, `Representation`, `Encoding`, the induced chart representation) | 2026-07-31 | 1362 | D-79, D-80, D-81, D-82 |
| M12 — Program types (`.symbolic()`, `.code()`) | 2026-08-01 | 1451 | D-83, D-84, D-85, D-86, D-87, D-88, D-89, D-90 |
| M12.5 — Repo and CI hygiene (`py.typed`, Python floor 3.12, `ruff format` gate, CI matrix, typo sweep) | 2026-08-03 | 1451 | _none_ |
| M13 — Public API documentation (NumPy-style docstrings + doctests over the exported surface; griffe-driven coverage/section gates; `__all__` closed over every type reachable from the public surface, 79 → 91) | 2026-08-04 | 2464 | _none_ |

One row per completed milestone: date, total test count at completion, IDs of any DECISIONS entries created during it. Update the "Current milestone" line when a milestone's exit criteria pass.

**Out-of-band fixes** (no milestone row — bugfixes against already-shipped milestones, landed with
their own conformance laws):

| Date | Fix | Against | Tests | DECISIONS |
|---|---|---|---|---|
| 2026-08-03 | Relocation now rewrites a lift's domain-carried references (`ListDomain.count`, `element_constraints`); finalization audits both; a count's enclosing-scope reference is deferred like a condition; `.select()` brings a lifted struct/choice's element templates | M3/M4 (relocation), M10.5 (finalization audit), M8 (`.select()`) | 1469 | D-91 |
| 2026-08-03 | `.slice()`/`.freeze()` statically resolve what a fixed value determines: counts fold to a static `int` (`.slice()` on a count param now works at all, and is the route to a fixed layout), always-true conditions fold to `None`; `.freeze()`'s fold gated on a single-value domain | M8 (structural ops) | 1487 | D-92 |
| 2026-08-03 | Immutability/copy-on-write swept over the exported surface: every exported dataclass frozen, read-only mapping views, and every chainable op asserted to leave its receiver byte-identical (the structural content of the thread-safety claim, previously asserted for expression nodes only) | M0–M12 (`Errors, Concurrency`) | 1818 | _none_ |
| 2026-08-03 | **Hardening pass 2.** Kind×surface matrix (22 kinds × 8 stated laws) made permanent; transport now handles the `ChartApply` node a representation emits, so a representation target can itself be represented and `then` composes past one derived level (it previously raised at a `# pragma: no cover` line); the round-trip law gains its tolerance and `rep.check()` now covers authored phenotypes (anchors, `apply_defaults({})`) | M11 (representation) | 1739 | D-94 |
| 2026-08-03 | **Hardening pass.** Reference-closure invariant over all four reference stores, swept across every corpus fixture and the 8×7 nesting grid; a lifted choice's discriminator template now relocates (it was never a `params` key, so nested lifted choices had never worked); D-24's boundary guarded on the compositional route too; new `nested_survey` corpus fixture covering a param-driven count in a relocated scope | M3/M4 (relocation), M4 (D-24 guard) | 1581 | D-93 |

The "DECISIONS entries" column above is a **historical** record: once an entry's answer is folded
into `API.md`, the entry itself is removed from the ledger and recovered from git history.