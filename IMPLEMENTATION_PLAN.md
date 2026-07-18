# designspace — Implementation Plan (agent-executable)

This plan is written for an AI coding agent implementing `designspace` against **API_v3.md**. Read this file fully before writing code.

## Source of truth and conflict handling

1. **API_v3.md is normative.** This plan sequences it; it never overrides it.
2. If the spec and this plan conflict, the spec wins. Record the conflict in `DECISIONS.md`.
3. If the spec is ambiguous or silent, do not invent silently: choose the least-surprising behavior consistent with the spec's Design Principles and Representation Model, implement it, and record the question, the options, and the choice in `DECISIONS.md` under the current milestone.
4. Never resolve an ambiguity by weakening a stated law (conformance laws, error table, Kleene table, chart formulas). Laws are frozen text.

## Working protocol

- **One milestone per branch/PR.** Do not start milestone N+1 while N's exit criteria fail.
- **Laws first.** At the start of each milestone, write that milestone's conformance-law tests (they will fail), then implement until green. Conformance tests are permanent — never delete or loosen one; a milestone may only add.
- **Track progress in `PROGRESS.md`:** one line per completed milestone with date, test count, and any DECISIONS entries created.
- **No dead scaffolding.** Do not stub future milestones' APIs. Unimplemented spec surface should not exist yet, so `from designspace import X` fails honestly.
- **Every commit:** `ruff check`, `mypy --strict src/`, `pytest -q` all green.
- **Freeze discipline:** after M7 ships, the JSON format and fingerprint preimage are frozen. Any change to either requires bumping the shared format version integer and adding new known-answer vectors alongside (not replacing) the old ones. Do not bend the implementation to avoid a bump; bump deliberately and record it.

## Global conventions

- Python ≥ 3.11. Layout: `src/designspace/`, tests in `tests/`.
- Tooling: `uv` for env, `ruff` (lint+format), `mypy --strict`, `pytest`, `hypothesis` for property tests.
- **Dependencies:** `numpy` only, until M10 adds `polars`. `pydantic` only as the `[pydantic]` extra (M13), lazily imported. Nothing else without a DECISIONS entry.
- All public objects are **immutable** (`@dataclass(frozen=True)` or equivalent); builders return new objects. No global mutable state; RNG passed explicitly.
- Exception taxonomy per spec: `DesignSpaceError` → `ResolutionError`, `SerializationError`, `SamplingError`; misuse guards raise plain `TypeError`. Every `ResolutionError` message names the offending definition path(s).
- Do not implement anything in the spec's **Out of Scope** list, even as "helpers": no search operators, no distances, no tree generators, no algebraic expression normalization, no clamping anywhere.

## Module map (stable across milestones)

```
src/designspace/
  __init__.py      # public surface only; re-exports
  expr/            # M0  AST nodes, operators, guardrails, all_/any_/count
  build/           # M1  ds.param / ds.space builders, modifiers, layering
  ir/              # M1  ParamDef, Domain, Constraint, Condition, results
  resolve/         # M1+ pass pipeline, error table, desugaring; M5 envelopes
  charts/          # M2  chart families, integers, grids, periodic, truncation
  eval/            # M2  Kleene engine, activity, margins; M4 aggregates
  validate/        # M2  validate / is_feasible / evaluate_constraints
  sample/          # M2  reference sampler, rejection, retries
  paths/           # M3  grammar, parsing, scoping walk
  config/          # M3  flatten/unflatten/variant/payload/destructure; M7 hash/diff
  defaults/        # M6  apply_defaults cascade
  partial/         # M6  evaluate_partial, remaining_domain, next_assignable
  identity/        # M7  canonical encoding, config_hash, fingerprint
  serialize/       # M7  to_json/from_json, versioning
  ops/             # M8  slice/freeze/select/filter/extend/active_subspace
  meta/            # M8  space_from_ir, param_from_def, map_params, ...
  custom/          # M9  ParamType protocol, registry, prop()
  frame/           # M10 polars output
  represent/       # M11 ParamTransform traversal, Encoding, capability_report
  program/         # M12 symbolic/code types
tests/
  unit/            # per-module
  conformance/     # the laws; known-answer vectors in tests/conformance/vectors/
  corpus/          # integration spaces (below), exercised end-to-end
```

## Integration corpus

Each fixture is a real space from the spec's design history. Add each at the milestone tagged; from then on it runs in every end-to-end suite (resolve → sample 200 → validate all → round-trip once serialization exists).

| Fixture | Exercises | Added at |
|---|---|---|
| `flat_hpo` | reals/ints/categorical, log_scale, quantized, `when`, forbid margins | M2 |
| `greenhouse` | choice, nested values, defaults cascade | M3 (defaults asserts at M6) |
| `flow_chemistry` | subset inclusion priors, `contains`, `sum_over`, implications | M3 |
| `job_shop` | permutation, `position_of` | M3 |
| `sat_solver` | choice+ordinal, anchors, ordinal comparisons | M3 (freeze asserts at M8) |
| `wind_farm_grid` | subset + machine-generated pairwise forbids (static unrolling) | M3 |
| `delivery_routes` | struct lifts, instance paths, per-instance constraints, aggregates | M4 |
| `solver_portfolio` | bool+`count`, `if_inactive`, inactive-vs-empty | M4 |
| `memetic_pipeline` | lifted choice, `count_of`, list element forms | M4 |
| `firmware_buffers` | expression bounds, envelopes, bound-origin margins | M5 |
| `pump_configurator` | driver loop: `next_assignable` + `remaining_domain` | M6 |
| `compiler_pipeline` | registry-driven generation, `all_`, degenerate arities, map_params | M8 |
| `vi_family` | custom type, `describe` round-trip, `prop()` constraints | M9 |
| `mixture_stickbreaking` | transform pipeline, mixed genotypes | M11 |
| `annealing_schedule` | `.symbolic()` definition + validation (no generation) | M12 |

---

## Milestones

### M0 — Expression core
**Spec:** Expressions (construction only); guardrails.
**Build:** `expr/` — node types with `.kind`, `.children`, `.params`; comparison/arith/bool operators; `is_in`, `is_active`, `implies`; `ds.all_`/`ds.any_` with True/False literal nodes; `ds.count`; `if_inactive` node; `__bool__`/`__contains__` raising `TypeError` with guidance text. No evaluation, no resolution.
**Gate:** node construction round-trips (`children` reconstruction); guardrail tests (`and`, chained comparison, `in` all raise); `all_()`/`any_()` zero-arg literals; hashability/immutability property test.

### M1 — Builder, resolution skeleton, IR (flat scalar spaces)
**Spec:** Construction; Parameter Types (scalar rows only); Modifiers (identity-level; domain-level parsing without chart semantics); IR; Resolution steps 1–5, 7–8; error-table rows applicable to flat scalars; Degeneracy table (scalar rows); Errors/Concurrency.
**Build:** `build/`, `ir/`, `resolve/` as a real pass pipeline (collect → type-check → desugar → resolve refs → cycle-check → validate declarations → emit IR), each pass a function over an explicit intermediate. Duplicate-value checks with type-tagged equality; name-character rules; self-reference detection; duplicate-modifier rules (LWW vs accumulate).
**Gate:** every implemented error-table row has a test asserting error class *and* that the message contains the offending path; degenerate scalars resolve; declaration order preserved in `Space.params`.
**Not yet:** charts, sampling, choice/struct/lifts, expression bounds (reject with "not implemented" ResolutionError listing the construct).

### M2 — Charts, Kleene, validation, sampler (walking skeleton)
**Spec:** Charts (all subsections; *All charts are static*); Expressions §Three-valued semantics rules 1–5, 7; Constraints and Feasibility incl. margin table and Boolean composition; Sampling (dict output only); Validation.
**Build:** `charts/` (four families, integer floor over `[lo,hi+1)`, step/factor grids + tolerance + canonical value, periodic, external-prior truncation incl. support-containment path); `eval/` (activity along topological order, Kleene propagation, margin computation, `applicable`); `validate/`; `sample/` (`sample_one`, `sample` → `list[dict]` for now, forbid rejection, retry error naming dominant constraints, `seed: int | Generator`).
**Gate (conformance):** chart known-answer vectors (incl. subnormal log range); floor-integer exact uniformity (chi-square with fixed seed); quantized cell measure; Kleene truth table exhaustively; margin sign per form; composition preserves satisfaction invariant (hypothesis: random expression trees); `−0.0` handling; continuous-`==` warning. Corpus: `flat_hpo`.
**Risk note:** none — this milestone is large but mechanical. Ship it before touching structure.

### M3 — Structure: choice, struct, subset, permutation, paths
**Spec:** Parameter Types (structural + combinatorial); Config Representation (dict forms); Paths and Scoping; Config Utilities (`flatten`/`unflatten`/`variant`/`payload`/`destructure`); relevant expression methods (`contains`, `size`, `sum_over`, `position_of`); cascading deactivation; choice `.prior(weights=)`.
**Build:** `paths/` grammar (multi-index ready even though lifts land in M4), scoping walk (up-then-descend); nested self-contained choice values; variant-name validation on resolved names for all three syntaxes; subset Bernoulli+size-rejection sampling; permutation uniform shuffle.
**Gate:** relocatability law (space composed under a variant behaves identically to inline definition); `unflatten(flatten(c)) == c` (hypothesis over sampled configs); two same-named variants in one scope resolve; scoping shadowing tests. Corpus: `greenhouse`, `flow_chemistry`, `job_shop`, `sat_solver`, `wind_farm_grid`.

### M4 — Lifts and aggregates  ⚠ critical path
**Spec:** Modifiers §The lift (incl. variadic sugar, layer errors); vector aggregates incl. nested-lift leaf semantics; per-instance constraint instantiation; Kleene rule 6 (empty aggregates) and inactive-vs-empty projection; `if_inactive` evaluation; instance paths in expressions with out-of-range → Unknown.
**Build:** recursive `Domain` list levels; evaluator support for Unknown-carrying vectors; `ConstraintEval.instance_path`.
**Directive:** before implementing, write a short design note in `DECISIONS.md` for the evaluator's representation of vector values with Unknown elements (this interaction — Kleene × aggregates × instance paths — is the highest-complexity point in the codebase). Then write the full law set, then implement.
**Gate:** empty-aggregate values table; inactive-lift vs active-empty side-by-side test (the spec's worked example, verbatim); variadic/chain fingerprint-equality deferred to M7 but structural equality asserted now; per-instance instantiation counts; `is_sorted` depth-2 rejection. Corpus: `delivery_routes`, `solver_portfolio`, `memetic_pipeline`.

### M4.5 — Faithfulness corrections (no new feature surface)
Corrects M2–M4 resolution behavior to match API_v3.md after the spec was made
precise on points that the (now-cleared) `DECISIONS.md` had recorded as open.
Pure alignment: three resolution-time rejections that turn a previously-silent
Unknown-cascade or a wrong chart into a loud `ResolutionError`, plus one
conformance-law promotion. No public `__init__` additions; no milestone reorder.

**Spec (already folded in):** Charts §Power monotonicity domain (row 9);
Expressions §`.field()` struct-lift + declared-field requirement (row 6) and
ordinal non-member-literal rejection (row 18); Three-valued semantics §non-`count`
aggregates plain-propagate Unknown; Modifiers §repeat counts join the dependency
graph and cycle check (rows 7); extended/added error rows 6, 9, 11, 14, 18, 28.

**Build:**
- `charts/_builtin.py::check_power_domain` — reject a domain straddling 0
  (`lo < 0 < hi`) unless `p` is a positive odd integer, and the degenerate
  `lo^p == hi^p`; message names the param and the `(p, lo, hi)` violation.
- `resolve/_expr_checks.py` — a `.field()` check (new sibling of
  `_require_lift_domain`): reject unless the base lift's `element_kind == "space"`
  and `name` is a declared descendant field of the element; message names the bad
  field/base (row 6).
- `resolve/_expr_checks.py` (`check_expr_types`, ordinal branch) — reject an
  ordinal `Compare` whose literal operand is not a declared value (row 18).
- Promote D-19's aggregate plain-propagation tests from `tests/unit/` to
  `tests/conformance/` (they now assert a stated law).

*No new code for rows 11, 14, 28:* the incompatible-type modifier (row 11),
categorical ordering (row 14), and subset size-bound (row 28) rejections are
**already** enforced in code (added in M1/M3 via D-3/D-16); M4.5 only aligned
their spec wording. The only genuinely new rejections are Power (row 9), `.field()`
(row 6), and the ordinal non-member literal (row 18).

**Gate:** each new rejection has a message-content test naming the offending path
(rows 6, 9, 18); a new Charts conformance law — a valid `Power` chart is a
monotone bijection onto `[lo, hi]` (`from_unit(0)==lo`, `from_unit(1)==hi`,
strictly monotone), and every row-9 Power violation raises; the promoted aggregate
plain-propagation law. **These are additive loud-rejections** — every prior
conformance law and all nine corpus fixtures must stay green, confirming none
relied on the silent path.

**Deferred / tracked (folded here from cleared DECISIONS, revisit when a fixture
forces it):**
- Nested struct/choice lift at repeat depth > 1 (`grid[][].width`) stays rejected
  with a clear `ResolutionError` (the path grammar's `mask[][]` says what the
  correct deeper form looks like; nested *scalar* lifts are already fully general).
  Completing it — bracket-depth-general relocation/expansion — is strictly
  additive and blocks no law.
- The finalization pass `resolve/_pipeline.py::check_fully_resolved` (deferred
  row-6/7/14 over merged conditions) is currently wired into every terminal op
  that exists (validate ×3, sample ×2). **M7/M8 must also call it from
  `fingerprint()`, `to_json()`, and every introspection surface** — otherwise a
  space with a genuine typo could produce freeze-relevant output without ever
  triggering its R-error. Add this to the M7 gate.

### M4.6 — Build-layer view types (static typing; no runtime-value or IR change)
Splits the single builder `ParamExpr` into statically-typed view subclasses so the
fluent API offers only the methods valid at each step and a second type method is a
type error. **No observable value, JSON format, fingerprint, chart, or conformance
law changes**; the IR is untouched (`ParamDef.type_kind` stays a string). Pure
build-layer ergonomics.

**Spec (already folded in):** §Construction (`ds.param -> FreshParamExpr`); §Parameter
Types new *Builder view types* subsection (base `ParamExpr` with no type methods;
`FreshParamExpr` adds them; each type method narrows to `RealParamExpr` /
`IntegerParamExpr` / `BoolParamExpr` / `CategoricalParamExpr` / `OrdinalParamExpr` /
`SubsetParamExpr` / `PermutationParamExpr` / `ChoiceParamExpr` / `StructParamExpr`,
and `.repeat() -> ListParamExpr`; each view exposes only its valid modifiers/queries
and omits the type methods; `BoolParamExpr` is also a `BoolExpr`); §Space —
Metaprogramming forward note that `TypedParamExpr` (M8) will become the views' common
base. See **D-27**.

**Directive:** before implementing, write a design note in `DECISIONS.md` for the
builder-layer representation of a param's type once the class encodes it — how
`ParamExpr.type_kind` is derived from the view class and whether `type_calls` is
retired (its sole job, catching a second type method, the views now cover
structurally). This touches resolution's synthetic constructions; settle it on paper
first, then write the laws, then implement.

**Build:**
- `build/_paramexpr.py` / new `build/_views.py` — the view subclasses. Move the 9
  type methods off the base onto `FreshParamExpr`; put `.repeat()` on the typed
  views and `ListParamExpr` (a type is required before a lift), not on the base or
  `FreshParamExpr`; the base keeps modifiers, expression operators, and the
  aggregates. Each type method and `.repeat()` constructs its target view (a
  `_as(cls)` helper, since `dataclasses.replace()` returns `type(self)`); modifiers
  keep their view via `replace`. `ListParamExpr.repeat()` re-nests for `.repeat(2, 3)`.
- `__getattr__` on the typed views re-raises the path-named `ResolutionError` for a
  type-method name (preserving row 2's message on `.real(0,1).bool()`, not a bare
  `AttributeError`); a non-type-method miss stays a normal `AttributeError`.
- The construction trap sites, which must build the right class: `build/_functions.py`
  (`param()` returns `FreshParamExpr`), and resolution's internal `ParamExpr(...)`
  constructions at `resolve/_pipeline.py` (synthetic list element ~549/552, which
  today also *fabricates* `type_calls`; discriminator ref ~660) — these build base
  `ParamExpr`, which is fine, but must not depend on the removed fields.
- `__init__.py` exports exactly the view types implemented here; `param_from_def` /
  `TypedParamExpr` remain **M8** (not added now).

**Gate:** all prior conformance laws and all nine corpus fixtures stay green (this
change alters no value or format). Plus: a message-content test that **both**
`ds.param("x").real(0,1).bool()` (fluent) **and** a programmatically-built two-type
definition raise a **path-named `ResolutionError`** (row 2 preserved, never
downgraded to `AttributeError`); a static-typing negative check proving each view
omits the type methods and the wrong-type modifiers (e.g. a `type: ignore[attr-defined]`
round-trip on `.real(0,1).bool()` and `.categorical(...).log_scale()`);
`mypy --strict`, `ruff`, full `pytest` green.

**Deferred:** making `TypedParamExpr` the common base of the views (aligns
`param_from_def`) is left to **M8** to avoid introducing a metaprogramming-surface
name early; the views subclass `ParamExpr` directly until then (D-27).

### M5 — Expression bounds
**Spec:** Constraints §Expression bounds are sugar; error rows for uncomputable hulls; dependency-graph/topological-order entries for bound-origin constraints; Charts §tighten-not-reject (implement last, behind the conformance equivalence test).
**Build:** interval arithmetic over a **minimal** op set — `+`, `−`, `×` by constants and enveloped params; anything else is the uncomputable-hull error. `Constraint.origin`.
**Gate:** desugared space structurally identical to hand-written expansion; bound-origin margins; tighten-vs-reject distributional equivalence (fixed-seed KS test). Corpus: `firmware_buffers`.

### M6 — Defaults and partial-config API
**Spec:** Defaults (entire section); Space — Partial Configs.
**Build:** `defaults/` cascade along topological order; `partial/` with per-kind `RemainingDomain` descriptors and the one-unset-operand reducer (shared with M5's constraint machinery); `next_assignable`.
**Gate:** idempotence + monotonicity (hypothesis); activity-respecting fill (the `turbo`/`chassis` case from the spec's history); completeness postcondition; element/list default exclusivity; reducer guarantee tested positively *and* negatively (a two-unset-operand implication is documented as not propagated). Corpus: `pump_configurator` as a scripted driver loop.

### M7 — Identity and serialization  🔒 freeze; ship v0.1
**Spec:** Identity and Serialization (entire section); Config Utilities (`config_hash`, `config_diff`).
**Build order within milestone:** canonical config encoding → `config_hash` → `config_diff` (variant-switch decomposition, positional repeat alignment) → `to_json`/`from_json` + version + non-serializable set + drop manifest → `fingerprint` (type tags, RFC 8785 — implement JCS in-repo or vendored, do not add a dependency without a DECISIONS entry — scopes, mark sentinel) **last**.
**Gate:** the full Identity law block from the spec: sugar-equivalence pairs (log_scale/prior, implies, variadic repeat/chain, expression bounds/expansion), order-sensitivity, scope-monotonicity, round-trip law, mark distinctness, type-tag distinctness, float edges — plus **known-answer digest vectors** committed under `tests/conformance/vectors/` for every corpus fixture. Whole corpus round-trips.
**Exit:** tag `v0.1`. Update `PROGRESS.md`; from here the freeze discipline (top of file) applies.

### M8 — Structural operations and metaprogramming
**Spec:** Space — Structural Operations (incl. anchor interactions, positional dict form); Space — Metaprogramming.
**Gate:** slice-substitution reaches conditions and constraint expressions incl. bound-origin (envelope recompute test); select prefix-subtree brings variants; strict vs best-effort; `extend` identity with `ds.space()`; `map_params` coarsening example from the spec history; rebuilt spaces fingerprint-equal to equivalent hand-built ones. Corpus: `compiler_pipeline`; `sat_solver` gains freeze-ablation asserts.

### M9 — Custom types
**Spec:** Protocols §ParamType + contract laws; `.custom()` both forms; `.prop()`; registry in `from_json`; error rows 16, 23 (describe serializability).
**Gate:** `factory(x.describe()) ≡ x`; `extract` only-after-validate enforced in the evaluator; canonical-ordering law exercised by a prop-driven lift count; shorthand form correctly poisoned for `to_json`/`fingerprint` (raise + mark). Corpus: `vi_family`.

### M10 — DataFrame output; ship v0.2
**Spec:** Config Representation §DataFrame table incl. `Array`-per-static-level and lifted-choice encoding.
**Build:** `frame/`; `polars` becomes a core dependency here and not earlier; `sample(n)` return type switches to `pl.DataFrame` (`sample_dicts` retained as the M2 path).
**Gate:** dtype table asserted per corpus fixture; null-for-inactive; column names == path grammar. Exit: tag `v0.2`.

### M11 — Representation layer
**Spec:** Transforms and Encodings (entire section); `capability_report`.
**Gate:** children-first traversal order observable via a recording transform; transform→flatten pipeline on `mixture_stickbreaking` reproduces the spec's genotype recipe; `Encoding` registry populated only in tests, never in `src/`.

### M12 — Program types; ship v0.3
**Spec:** `.symbolic()` / `.code()`; generative/non-generative sampling behavior; `Signature`, literals, `Primitive`.
**Gate:** `SamplingError` iff materialization required (default satisfies; freeze removes; inactive skips); literal domains carry charts; validators run on the AST/source; serialization poisoning matches M9's pattern. Corpus: `annealing_schedule`.

### M13 — Extras and docs
`to_json_schema` (core, dependency-free); `[pydantic]` extra: `to_pydantic_model`; `to_dataclass() -> type` + `to_python_source()`; `from_callable` + `Annotated` domain literals as `designspace.contrib.signatures`. Guide pages: tier guidance for structured values, mechanism-choosing, rejection hostility, defaults-vs-anchors, solver-integration walkthrough — source material is the spec's Solver Integration section.

---

## Definition of done (per milestone)

1. All new conformance laws green; all prior laws untouched and green.
2. Corpus fixtures for the milestone added and passing end-to-end.
3. Error-table rows introduced by the milestone each have a message-content test.
4. `mypy --strict`, `ruff`, full `pytest` green.
5. `PROGRESS.md` updated; `DECISIONS.md` entries for anything the spec left open.
6. Public `__init__.py` exports exactly the spec surface implemented so far — nothing speculative.

## Bootstrapping (first session)

Create `CLAUDE.md` at repo root containing:

```markdown
# designspace
Implementing API_v3.md per IMPLEMENTATION_PLAN.md. Read both before any change.
- Spec (API_v3.md) is normative; plan sequences it; conflicts → DECISIONS.md.
- Current milestone: see PROGRESS.md. Work only within it.
- Laws-first: conformance tests before implementation; never weaken a law.
- Frozen after M7: JSON format + fingerprint preimage (version-bump protocol in plan).
- Commands: uv run pytest -q · uv run mypy --strict src/ · uv run ruff check
- Deps: numpy (core), polars (M10+), pydantic (extra only). Nothing else undocumented.
```

Then scaffold: `uv init`, module map directories, empty `PROGRESS.md`/`DECISIONS.md`, CI running the three commands, and begin M0.
