# Progress

Current milestone: **M10.5 (open)**.

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

One row per completed milestone: date, total test count at completion, IDs of any DECISIONS entries created during it. Update the "Current milestone" line when a milestone's exit criteria pass.

The "DECISIONS entries" column above is a **historical** record.
