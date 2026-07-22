# Progress

Current milestone: **M9 — Custom types** (not started)

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

One row per completed milestone: date, total test count at completion, IDs of any DECISIONS entries created during it. Update the "Current milestone" line when a milestone's exit criteria pass.

The "DECISIONS entries" column above is a **historical** record. As of M5 those
entries (D-1 … D-29) were resolved into API.md (as normative spec text) or into
the plan, and `DECISIONS.md` was reset to an empty ledger for future use before M6
began. The original entries remain in this repo's git history. D-30 (M6) through
D-37 (M7) were folded into API.md on 2026-07-21 and `DECISIONS.md` reset again to
the empty ledger; those entries likewise remain in git history. Folded the same day
without new ledger entries (user-approved directly): four API changes — keeping
`to_json`/`from_json` (no rename), instance-path `variant`/`payload` on lifted
choices, the empty/non-existent-path `remaining_domain` `TypeError`, and the new
`space.require` (positive complement of `space.forbid`; spec only). These additions
were **implemented in M7.5** (2026-07-21, before M8): the `require` builder + origin-
parameterized `add_constraints`, the three feasible-predicate `origin ∈ {bound, require}`
generalizations (`is_violated`, `remaining_domain` reduction, fingerprint canonicalization),
instance-path `variant`/`payload`/`destructure`, and the additive `origin="require"` frozen-
format value with **no version bump** (format-version stays `1`; all corpus KA vectors
byte-identical; a new `require_demo` KA vector added). During M7.5 a genuine spec
inconsistency surfaced and was resolved with the user as **D-38** (`require` fingerprint
canonicalizes by whole-expression negation, matching `.forbid(~e)`; `require(x<=y) ≡
forbid(x>y)` is a *feasibility* equivalence, not a syntactic one).

**M7.6 — Constraint API symmetrization** (2026-07-21, before M8; user-directed):
renamed the soft verb `constrain` → `encourage` and added its bad-state complement
`discourage` (`== encourage(~e)`), completing the quartet hard `forbid`/`require` +
soft `encourage`/`discourage`; added derived polarity accessors `Constraint.kind`,
`Constraint.feasible_when_satisfied`, and `ConstraintEval.violated` (so
`is_violated` collapses to the property and `infeasibility_reasons` labels by
`kind`); `examples/03` reads constraints polarity-agnostically. The rename is
IR-identical (`encourage` == old `constrain`), so **no version bump** — all corpus +
`require_demo` KA vectors byte-identical; `discourage` adds the `origin="discourage"`
value additively with a new `discourage_demo` KA vector and canonicalizes to `Not(e)`
like `require`. Recorded as **D-39**.

**M8 — Structural operations and metaprogramming** (2026-07-22): built `ops/`
(`.slice`, `.freeze`, `.active_subspace`, `.select`, `.filter`, `.extend`) and
`meta/` (`param_from_def`, `space_from_ir`, `.map_params`, `.without_constraints`),
plus two prerequisites the ops needed: space-level `.anchor()`/`.meta()` (deferred
past M2 — **D-40**, kept out of the already-frozen `sat_solver` fixture; exercised
by a new `_anchor_demo` KA vector instead) and public `TypedParamExpr` (D-27's
promotion, now the base `param_from_def` returns — D-41 scopes it to
scalar/list kinds, raising for struct/choice, whose descendants live outside a
single `ParamDef`). `space_from_ir` re-validates an already-flat IR directly
(no builder round-trip — **D-42**), via new `resolve/` primitives
(`param_def_to_view`, `validate_param_defs`, `rebuild_charts`, `revalidate_space`)
shared with `serialize/_fromjson.py`. Added the "cheap read-only" introspection
accessors (`.subspaces`, `.dependency_graph`, `.param_constraints`,
`.param_conditions`, `.is_hierarchical`, `.has_variable_length`, `.is_finite` —
scope and shapes **D-43**; `.cardinality()`/`.capability_report()` deferred past
M8, `.has_nongenerative_params` deferred to M9). `.slice()` substitutes a fixed
value at every reference site (conditions, constraints of every origin including
bound and require) and recomputes affected bound-origin envelopes via
`resolve/_bounds.py`'s existing interval-hull machinery; `.freeze()` instead
narrows the frozen param's own domain to a single value (real/integer/
categorical/ordinal) or pins it via a hard `require` (bool) — chosen over
slice-style substitution by the user; choice/subset/permutation/struct/list are
out of scope for `.freeze()` in M8 (**D-44**). `select`/`filter` share prefix/
tag-based pruning (best-effort drop-with-warning by default, `strict=True`
raises); anchors conflicting with a frozen/sliced value raise (row 22), while
`select`/`filter` drop just the conflicting anchor key with the same warning.
New `compiler_pipeline` corpus fixture (registry-driven generation, `all_`,
degenerate arities, `map_params`); `sat_solver` gains `.freeze()`-ablation
asserts in its test file only (`build_space()` and its KA vector untouched).
No format-version bump — anchors/meta are additive, omitted from the preimage
when empty; every pre-M8 corpus + demo KA vector stays byte-identical.
