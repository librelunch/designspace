# Implementation plan

`API.md` defines the target. This file defines the current route toward it. 
Keep exactly one milestone in progress. 


## Source of truth and conflict handling

1. **API.md is normative.** This plan sequences it; it never overrides it.
2. If the spec and this plan conflict, the spec wins. Record the conflict in `DECISIONS.md`.
3. If the spec is ambiguous or silent, do not invent silently: choose the least-surprising behavior consistent
   with the spec's Design Principles and Representation Model, implement it, and record the question, the options,
   and the choice in `DECISIONS.md` under the current milestone.
4. Never resolve an ambiguity by weakening a stated law (conformance laws, error table, Kleene table, chart formulas).
   Laws are frozen text.


## Working protocol

- **One milestone per branch/PR.** Do not start milestone N+1 while N's exit criteria fail.
- **Laws first.** At the start of each milestone, write that milestone's conformance-law tests (they will fail),
    then implement until green. Conformance tests are permanent — never delete or loosen one; a milestone may only add.
- **Track progress in `PROGRESS.md`:** one line per completed milestone with date, test count, and any DECISIONS entries created.
- **No dead scaffolding.** Do not stub future milestones' APIs. Unimplemented spec surface should not exist yet,
    so `from designspace import X` fails honestly.


## Global conventions

- Python ≥ 3.11. Layout: `src/designspace/`, tests in `tests/`.
- Tooling: `uv` for env, `ruff` (lint+format), `mypy --strict`, `pytest`, `hypothesis` for property tests.
- All public objects are **immutable** (`@dataclass(frozen=True)` or equivalent); builders return new objects. 
  No global mutable state; RNG passed explicitly.
- Exception taxonomy per spec: `DesignSpaceError` → `ResolutionError`, `SerializationError`, `SamplingError`; misuse
  guards raise plain `TypeError`. Every `ResolutionError` message names the offending definition path(s).
- Do not implement anything in the spec's **Out of Scope** list, even as "helpers": 
  no search operators, no distances, no tree generators, no algebraic expression normalization, no clamping anywhere.


## Freeze discipline (the version-bump protocol)

The JSON document and the fingerprint preimage share **one integer format version**, frozen at `1`
when M7 shipped. Every milestone after M7 works under this protocol:

1. **One counter, two surfaces.** `to_json`'s version and the preimage's version are the same
   number. `from_json` raises on an unknown one.
2. **Additive changes need no bump** during the pre-release span (M8–M12): a new `origin` value, a
   new expression node kind, a new entry in the non-serializable set — anything no shipped document
   or committed vector depends on. M7.5 (`require`) and M7.6 (`discourage`) set this precedent.
3. **Add, never replace, known-answer vectors.** A milestone that touches the format adds vectors
   for the new construct and must show **every pre-existing vector byte-identical**. This is the
   gate that actually enforces the freeze; the version integer alone would not.
4. **Any non-additive change bumps the integer** and requires user approval — it is a compatibility
   break, not an implementation detail.
5. **`rfc8785` is pinned exactly.** Bumping that pin is an act under this protocol, not a routine
   dependency update: a transitive change to number formatting would silently shift every committed
   digest.

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
  represent/       # M11 Encoding, Representation, transport, the induced chart representation
  program/         # M12 symbolic/code types
tests/
  unit/            # per-module
  conformance/     # the laws; known-answer vectors in tests/conformance/vectors/
  corpus/          # integration spaces (below), exercised end-to-end
```

## Integration corpus

Each fixture is a real space from the spec's design history. 
Add each at the milestone tagged; from then on it runs in every end-to-end suite
(resolve → sample 200 → validate all → round-trip once serialization exists).

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
| `mixture_stickbreaking` | representation morphism, mixed genotypes, custom→u-space bridge | M11 |
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
Corrects M2–M4 resolution behavior to match API.md after the spec was made
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
**Spec:** Defaults (entire section); Space — Partial Configs. M6 first folds the nailed-down normative text into API.md (the `RemainingDomain` type; three-valued activity; the one-unset-operand reducer; the `apply_defaults` cascade; `PartialEval`; `is_complete`/`next_assignable` + the coincidence law), then implements it.
**Build:**
- `ir/_results.py` — `PartialEval` + the `RemainingDomain` family (`RealRemaining`/`IntegerRemaining`/`ValueRemaining`/`SubsetRemaining`/`PermutationRemaining`); exported from `ir` and top-level.
- `eval/` — factor the topological activity walk (+ `_expand_lift_activity`) into one shared, classifier-parameterized helper; `compute_activity` (binary) and new `compute_activity_partial` (three-valued; pending-dependency rule; three-valued `IsActive`) are thin adapters.
- `defaults/` — `apply_defaults` cascade modeled on `sample/_sample.py::_draw_config` (fill-from-default replaces draw): topological walk, incremental activity, choice=variant / struct=field-wise / element-broadcast / `list_default` / lifted-descendant defaults; defaulted-count-param cascade; **fill-only output**; `has_complete_defaults`. Complete row-21 default validation for choice/subset/permutation and reject struct-level defaults (no new error row).
- `partial/` — `evaluate_partial`, `remaining_domain` (per-kind descriptor + the one-unset-operand reducer: bare-target, hard-only, origin polarity via `is_violated`, reusing `bound_origin_targets`), `param_activity`, `is_complete`, `missing_params`, `next_assignable`, public `topological_order`.
- `build/_space.py` — wire the nine methods (thin delegators; each calls `check_fully_resolved`).
**Gate:** idempotence + monotonicity (hypothesis); activity-respecting fill (the `turbo`/`chassis` case from the spec's history); completeness postcondition; element/list default exclusivity; the reducer guarantee tested positively *and* negatively (a two-unset-operand implication is documented as not propagated); three-valued activity **collapses to binary**; the driver-loop **coincidence** `next_assignable == [] ⟺ is_complete`; `remaining_domain` soundness. No new error-table rows (row 21 completed in code). Corpus: `pump_configurator` as a scripted driver loop.

### M7 — Identity and serialization
**Spec:** Identity and Serialization (entire section); Config Utilities (`config_hash`, `config_diff`).
**Build order within milestone:** canonical config encoding → `config_hash` → `config_diff` (variant-switch decomposition, positional repeat alignment) → `to_json`/`from_json` + version + non-serializable set + drop manifest → `fingerprint` (type tags, RFC 8785 — implement JCS in-repo or vendored, do not add a dependency without a DECISIONS entry — scopes, mark sentinel) **last**.
**Bound-origin preimage canonicalization (freeze-blocker from D-29(4)/M5).** The `fingerprint` step **must** canonicalize every bound-origin constraint (`origin == "bound"`) to its forbidden-state negation before hashing — a stored `x <= y` bound constraint enters the preimage as `x > y`, the shape a user `.forbid()` stores for the *same* feasibility. This is a provenance-specific canonical **encoding** (same category as "subsets sorted", "−0.0→0.0"), homed in the normalization pipeline, **not** algebraic expression rewriting. Rationale: M5 stores the *desired* predicate `x <= y` (for the `y − x` margin) and `eval/_constraint_eval.py::is_violated` keys feasibility off `origin`, which is excluded from the preimage; without this canonicalization a bound sugar and a user `.forbid(x <= y)` would have identical preimages but **opposite** feasible sets, breaking "equal fingerprints ⟹ identical valid-config sets". Also add the general guard: no preimage-excluded field (`origin`, `Constraint.params`, `dependency_graph`) may be feasibility-load-bearing.
**Gate:** the full Identity law block from the spec: sugar-equivalence pairs (log_scale/prior, implies, variadic repeat/chain, expression bounds/expansion), order-sensitivity, scope-monotonicity, round-trip law, mark distinctness, type-tag distinctness, float edges — plus **known-answer digest vectors** committed under `tests/conformance/vectors/` for every corpus fixture. Whole corpus round-trips. **Plus the bound-origin polarity law (D-29(4)):** a bound-sugar space and its `.forbid(x > y)` manual expansion are fingerprint-equal **and** feasibility-equal; a bound-sugar space and `.forbid(x <= y)` are fingerprint-**distinct** and feasibility-distinct. (Cross-ref: M4.5's deferred note already requires `fingerprint`/`to_json` to call `check_fully_resolved`.)
**Exit:** **freeze the wire format** (format-version integer `1`) — an internal checkpoint that anchors the freeze discipline (top of file) for every later milestone, **not** a public release. Public releases are deferred: the first is **v0.1 at M13**, and the format-version integer stays `1` across the whole pre-release span (M8–M12), which is exactly what the byte-identical KA-vector gates in M7.5/M8 enforce. Update `PROGRESS.md`.

### M7.5 — Post-freeze API additions
Implements the four API changes folded into `API.md` on 2026-07-21 (the discussion
additions — **not** D-30…D-37, which only clarified already-shipped M6/M7 behavior and
needed no new code). Sequenced **before M8** so structural ops (`slice`/`freeze`, which
substitute into constraint expressions) are built against the complete constraint model,
including `origin="require"`. Fractional-milestone precedent: M4.5/M4.6.

**Spec (already folded in):** Constraints §`.require` (+ Kleene polarity, margin);
Sampling §reject on forbids **and requires**; Config Utilities §instance-path
`variant`/`payload`/`destructure` and non-validating `config_hash`/`config_diff`
(+ `config_diff` plain-`==`); Partial Configs §`remaining_domain` empty/non-existent-path
`TypeError` and `require`-origin participation; Identity §feasible-predicate
(`origin` `bound`|`require`) preimage canonicalization; IR `Constraint.origin` gains
`"require"`.

**Build:**
- `build/_space.py` — new `.require(*conditions, tags=(), meta=None)`; `resolve/_constraints.py::add_constraints` gains an `origin` parameter (default `"user"`), `.require` passes `hard=True, origin="require"`.
- Generalize the four `origin == "bound"` special-cases to `origin in ("bound", "require")`: `identity/_ir_codec.py` (forbidden-state preimage canonicalization), `eval/_constraint_eval.py::is_violated` (feasible-iff-satisfied), `partial/_partial.py` (`remaining_domain` reduction + feasible-side polarity), `resolve/_bounds.py` (canonicalization gate). **Leave `dependency_graph`/`topological_order` bound-only** — `require`, like a forbid, builds no chart and imposes no assignment order (`resolve/_bounds.py:151`-style ordering is bound-specific).
- `config/_helpers.py::_get_by_path` — honor the path grammar's `[k]` indexing so `variant`/`payload`/`destructure` walk into lifted-choice elements (`pipeline[1]`); the bare list path raises a guiding misuse error naming the indexed form. Stays `Space`-free.
- `remaining_domain` empty/non-existent path already raises `TypeError` via `_lookup_param_shape` — add coverage, no code change.

**Freeze handling.** `require` adds the `origin="require"` value to the frozen format. Per the user-approved pre-release exemption (no shipped document/vector depends on the prior origin set) this is **additive with no version bump** — the format-version integer is unchanged. **Add — never replace —** known-answer digest vectors for a `require`-using space under `tests/conformance/vectors/`; confirm every existing corpus vector is byte-identical (no fixture uses `require`).

**Gate (conformance):** `require(e)` feasibility-, margin-, **and** fingerprint-equal to `forbid(~e)`, and fingerprint-**distinct** from the feasibility-opposite `forbid(e)`; `require` Kleene polarity (violated iff `e` definitely False; Unknown/True feasible); `require`-origin participates in `remaining_domain` identically to a bound (one-unset-operand reduction, soundness preserved); lifted-choice `variant`/`payload`/`destructure` by instance path with a message-content-tested misuse error on the bare list path; `remaining_domain` misuse `TypeError` on empty/non-existent path; new `require` KA vectors committed and **all prior conformance laws + all corpus vectors stay byte-identical**. **Not touched:** `to_json`/`from_json` names (rename rejected).

### M7.6 — Constraint API symmetrization (no runtime-value or format change)
User-directed API polish (fractional-milestone precedent: M4.5/M4.6/M7.5). Completes the
constraint verb set into a symmetric 2×2 and makes constraint polarity a first-class,
introspectable property, so consumers stop re-deriving it from `(origin, hard)`. **No format
version bump**: the rename is IR-identical and the one new `origin` value is additive. See **D-39**.

**Spec (folded in):** §Constraints (rename `constrain` → `encourage`; add `discourage`, the
soft complement `== encourage(~e)`; the *constraint quartet* + polarity-accessor paragraph);
§Sampling (`reject_soft` names the soft pair); §Identity (scope table; normalization step 1
extended so `discourage` canonicalizes to `Not(e)` like `require`); §IR (`Constraint.origin`
gains `"discourage"`; derived `Constraint.kind`/`feasible_when_satisfied` and
`ConstraintEval.violated`).

**Build:**
- `build/_space.py` — rename `.constrain` → `.encourage`; add `.discourage`
  (`add_constraints(hard=False, origin="discourage")`). `resolve/_constraints.py` — the
  `call` label maps `(origin, hard)` to the four verb names.
- `ir/_param.py` / `ir/_results.py` — derived properties: `Constraint.kind`
  (`forbid`|`require`|`encourage`|`discourage`|`bound`), `Constraint.feasible_when_satisfied`
  (False only for the bad-state verbs), `ConstraintEval.violated` (polarity-correct).
- `eval/_constraint_eval.py::is_violated` collapses to `return ce.violated`;
  `validate/_validate.py::infeasibility_reasons` labels by `kind`.
- `identity/_ir_codec.py::_canonicalize_polarity` (renamed from `_canonicalize_feasible_predicate`)
  — `origin in ("require","discourage")` negate whole-expression; `bound` op-flips.
- Rename `.constrain(` → `.encourage(` across corpus fixtures, examples, and tests (semantics
  preserved; conformance-law test names updated, never loosened). `examples/03` reads
  constraints via `kind`/`violated` and demonstrates `discourage`.

**Gate (conformance):** `kind`/`feasible_when_satisfied`/`violated` correct for all four verbs
+ bound; `discourage(e)` never affects feasibility, flagged iff satisfied, fingerprint-equal to
`encourage(~e)` and distinct from `encourage(e)`, absent from the `sampling` scope, rejected only
under `reject_soft`; new `discourage_demo` KA vector committed and **all prior conformance laws +
all corpus + `require_demo` vectors stay byte-identical**; `mypy --strict`, `ruff`, full `pytest`
green.

### M8 — Structural operations and metaprogramming
**Spec:** Space — Structural Operations (incl. anchor interactions, positional dict form); Space — Metaprogramming.
**Gate:** slice-substitution reaches conditions and constraint expressions incl. bound-origin **and require-origin** (envelope recompute test); select prefix-subtree brings variants; strict vs best-effort; `extend` identity with `ds.space()`; `map_params` coarsening example from the spec history; rebuilt spaces fingerprint-equal to equivalent hand-built ones. Corpus: `compiler_pipeline`; `sat_solver` gains freeze-ablation asserts.

### M9 — Custom types
**Spec:** Protocols §ParamType + contract laws; `.custom()` both forms; `.prop()`; registry in `from_json`; error rows 16, 23 (describe serializability); Space — Introspection `.has_nongenerative_params` and `.cardinality()` (deferred out of M8 — D-43 — since no non-generative param could exist before this milestone, and a custom type is the last `None`-yielding source `.cardinality()` needs to fully specify).
**Build:** alongside `.custom()`, `.has_nongenerative_params` (true iff any param is non-generative); `.cardinality()` (finite-config count over the structural product — `None` for infinite/continuous/unquantized-real and for a custom type with no finite `describe()`-derived domain). Also settles **freeze-on-custom**: a custom param's value is opaque, so `.freeze()` pins it via `require(p == value)` when the type supports `==`, otherwise it is out of scope like the M9.5 container kinds — no new machinery, reuses the `.freeze()` bool-pin mechanism.
**Gate:** `factory(x.describe()) ≡ x`; `extract` only-after-validate enforced in the evaluator; canonical-ordering law exercised by a prop-driven lift count; shorthand form correctly poisoned for `to_json`/`fingerprint` (raise + mark); `.cardinality()` exact count on a finite corpus fixture and `None` on `flat_hpo`-shaped continuous spaces; `.has_nongenerative_params` true only once a custom/program param exists. Corpus: `vi_family`.

### M9.5 — Container freeze completion
Completes `.freeze()` for the five kinds D-44 scoped out of M8 (choice, subset, permutation, struct, list), generalizing M8's constraint-pin mechanism (real/integer/categorical/ordinal domain-narrowing; bool `require`/`require(~·)` pin — see API.md, "Space — Structural Operations"). Fractional-milestone precedent: M4.5/M4.6/M7.5/M7.6.

**Directive:** fold the nailed-down container-freeze normative text into API.md's `.freeze` row as part of this milestone (the M6 fold-then-implement pattern), replacing the current forward reference.

**Build:**
- **subset** — per-item pins: `require(contains(p, i))` for each forced-in item, `require(~contains(p, i))` for each forced-out item (reuses `contains`, cf. `flow_chemistry`).
- **permutation** — per-position pins: `require(position_of(p, item) == k)` for the fixed arrangement (reuses `position_of`, cf. `job_shop`).
- **struct** — fans out to per-field `.freeze()` (fields are already scalar/combinatorial params; this kind needs no new mechanism, only dispatch).
- **choice** — discriminator pin `require(c == variant)` **plus** structural pruning of the non-selected variants' relocated descendant params, reusing `.select()`/`resolve/_relocate.py` machinery (the piece D-44 flagged as materially larger than value-fixing).
- **list** — per-element pinning plus fixing the count.

**Gate:** each container `.freeze()` is fingerprint-equal to its hand-written pin/prune expansion; a frozen space samples/validates to only the fixed value (or, for choice, only the fixed variant); all prior conformance laws + corpus + known-answer vectors stay byte-identical — freeze composes existing constructs (`require`, `.select()`-style pruning), so **no format-version bump**; the M8 `ResolutionError` for these five kinds is removed.

**Also consider (noted during M9's example work, not container-freeze-related — parked here as the next open milestone):** `Space — Partial Configs` has no public get/set-by-path pair for a *single* leaf on an already-nested config. `next_assignable()`/`missing_params()` hand back path-grammar strings, but the only existing accessor is `config/_helpers.py::_get_by_path` — private, read-only, and used solely to back `variant`/`payload`/`destructure`. A hand-rolled `next_assignable`-driven driver loop (see `examples/04_distributed_training.py`) therefore has to branch on path shape itself, and a naive `partial[path] = value` is silently wrong for any dotted/bracketed instance path once the space has struct/choice nesting (it writes a bogus top-level key instead of nesting) — the flat/nested duality only stays invisible in a fixture with no such nesting. A `ds.set_by_path`/`ds.get_by_path` pair (Config Utilities-shaped) would fix the scalar/struct/choice case cleanly. It would **not**, by itself, remove the lift-instance branch: a `.repeat()`'s elements have no representable "list of the right length, some elements still unset" state in the canonical nested config, so a driver must still bulk-assign a lift once any of its instance paths go ready — that's structural, not a missing-accessor gap.

### M10 — DataFrame output
**Spec:** Config Representation §DataFrame table incl. `Array`-per-static-level and lifted-choice encoding.
**Build:** `frame/`; `space.sample(n) -> pl.DataFrame` is new, gated behind the optional `designspace[polars]` extra rather than a core dependency (D-51 — a user-directed scope change from the milestone's original plan) — `polars` is imported lazily inside `Space.sample()` alone, raising a plain `ImportError` naming the extra when absent; `sample_dicts`/`sample_one` need no extra and are unaffected.
**Gate:** dtype table asserted per corpus fixture; null-for-inactive; column names == path grammar; a missing-polars `ImportError` naming the extra. **Exit:** internal pre-release checkpoint — **no public tag** (v0.1 ships at M13; an internal alpha such as `0.1.0aN` is optional, not required).

### M10.5 — Expression and validation hygiene
Eight fixes and additions in the resolver and the Kleene evaluator, all pre-existing and independent
of M11 — but M11 consumes items 3 and 5, so they land first rather than being duplicated.

**Priority: item 1.** It is the only confirmed contradiction of a stated law, it silently corrupts
driver-loop conclusions, and its cause is a documented deferral never picked up:
`eval/_kleene.py`'s M2-era docstring says "rule 5 becomes meaningful only once [a partial-config API]
exists", M6 shipped that API, nobody returned.

1. **`.if_inactive()` must discriminate Unknown provenance** (Kleene rule 5). On a config where a
   lift is *active* and only its elements are unset, `bufs.sum().if_inactive(0) <= 10` reports
   `satisfied=True, margin=10.0` while the unguarded form correctly reports `satisfied=None` — and
   the same space is infeasible once the elements land. Coalesce inactivity; propagate pending; also
   propagate emptiness (`max([])` over an *active* lift must not become the fallback).
2. **Static out-of-range index → resolution error** (row 29). `repeat(3)` with
   `require(y[7] > 0.99)` currently resolves clean and makes `is_feasible` true for everything.
   Dynamic counts keep the Unknown rule — it is right *because* lifts can be dynamic; the leak is
   applying it where the length is statically known.
3. **Nested and mixed instance indexing.** `g[0][1]` and `layers[2].act[1]` both fail today; the
   grammar parses them but `_is_declared`/`_resolve_entry` strip a single bracket group. Normalize
   progressively, retrying the base-lift fallback per level.
4. **Negative indexing** `x[-1]`, resolved against the realized length — the only way to name the
   last element of a dynamic lift. It references exactly that lift, so dependency analysis is
   untouched.
5. **Result-typed `.repeat()` counts.** `ds.param("m").sum()` over a bool lift is rejected (row 12)
   though the same aggregate type-checks and evaluates inside a constraint. Accept any
   integer-valued expression whose references resolve. Prerequisite for `Encoding.prop_expr`.
6. **Boolean operators over lift-valued operands** (row 29). `require(~ds.param("g[0]"))` on a
   `repeat(4,4)` resolves, then makes every config infeasible — the row is coerced by truthiness.
7. **`.choice()` payload type check** (row 29). A bare `ParamExpr` where a `Space` is expected
   raises `AttributeError` from `relocate_child`, because `Space.params` is a `Mapping` and
   `Expr.params` a `frozenset`. Reject with a path-named error, or auto-wrap.
8. **`space_from_ir` must validate anchors.** The builder's `.anchor()` raises row 22 on an
   out-of-domain anchor; the metaprogramming path accepts it silently. Row 22 is unconditional.

**Gate:** a conformance law per item, each asserting the *silent* pre-fix behavior (none of these
crashed); Kleene rule 5 gets the test it never had; all prior laws, corpus, and known-answer vectors
byte-identical; **no format bump**. **Plus one audit, which is why item 1 was reachable at all:**
rule 5 was stated in the Kleene prose but never named in §Conformance Laws, and laws-first testing
follows that list — so sweep the list against the Expressions/Kleene prose for other
stated-but-unnamed laws and name them.

### M10.6 — Sampling diagnostics
**Spec:** *Sampling diagnostics* beside the reference sampler; `SamplingReport`/`ConstraintReport` in
the IR results block.
**Build:** `sample/_diagnostics.py`; `.sampling_report(n=1000, seed=None) -> SamplingReport` drawing
through `_draw_one` with rejection bypassed, then `evaluate_constraint`/`compute_activity` per draw.
Aggregation only — no new evaluation semantics. It reports; it never repairs, reweights, or suggests.

It must draw the **unconditioned** measure: `sample()` returns the post-rejection distribution, in
which both pathologies it exists to expose are invisible. `satisfied` is conditioned on
**applicability**, not on all draws — otherwise "rarely relevant" and "usually violated" collapse
into one number, which is the distinction that matters.

**Gate:** on the funnel space (`repeat(ds.param("n"))` + `require(x[2] > 0.99)`) the report shows
`applicable ≈ 0.8` and `acceptance_rate ≈ 0.208`, matching the analytic values — the conditioned
measure concentrates 96% of accepted configs on `n ≤ 2`, which is correct-by-spec and must be
documented beside Kleene rule 4, not "fixed". On an optional-buffer space, `applicable ≈ 0.36` for a
naive aggregate versus `1.00` for its `.if_inactive(0)` form, the two differing only in that guard.
Seed-reproducible; never mutates; never rejects. Corpus: reuse `solver_portfolio`.

### M10.7 — Traversal extraction and child index
A pure refactor, so the gate is unusually strong: **every test, corpus fixture, and known-answer
vector byte-identical**, plus a fingerprint sweep over all fixtures.

The space-guided walk is written five times and M11 would make six. `_direct_children` lives private
in `config/_flatten.py` yet is imported by `config/_unflatten.py`, `identity/_config_encode.py`,
`frame/_rows.py`, `frame/_schema.py`, and `build/_space.py` — the last two through *local* imports to
break cycles. Four recursions share one skeleton with parallel `_*_choice` / `_*_list_element` helper
pairs, and the `"[]."`/`"[i]."` convention is re-derived across 13 modules. Extraction is literally
the spec's own principle for this layer.

Also index `_direct_children`, which full-scans `space.params` on every call, once per struct level:
on `k` structs × 8 fields it costs 1.29 µs/param at 45 params and **5.39 µs/param at 360** — 8× the
params for 33× the time. Struct *lifts* stay linear because the template dict is small regardless of
element count, so this is specifically a wide/nested-struct problem, invisible in flat and lift
benchmarks. Build a `dict[prefix, list[path]]` index eagerly at `_emit`; `Space` is frozen, so it is
safe to cache and safe to share.

**Implemented as lazy, not eager at `_emit`** — a deviation from the line above, decided during
implementation. `Space` is constructed at seven `src/` sites (`_emit`, `from_json`,
`space_from_ir`, `extend`, `freeze`, and two throwaway `skeleton = Space(params=..., conditions=())`
spaces in `ops/_structural.py` that feed straight into `flatten`) plus five `dataclasses.replace(
space, ...)` call sites; an eager build at `_emit` alone would leave the other eleven with no index.
Laziness (`Space._child_index`, `init=False, compare=False, repr=False`, built via
`object.__setattr__` on first `_direct_children` call) covers all twelve uniformly and costs nothing
for a space never traversed — routine implementation detail, not a DECISIONS.md-worthy gap.

**Abort criterion, decided up front:** if the unified driver needs more than four hooks, or forces a
consumer to pass flags it ignores, keep the copies and ship only the index. A bad abstraction over
five call sites is worse than the duplication. **The criterion fired**: the five walkers diverge on
seven axes (accumulator style, prefix arity, gate source, absent-child policy, choice shape, count
source, leaf work), not four — traversing three different structures (space alone; config-driven;
space-driven-with-two-side-tables) to emit four spec-mandated shapes. Only `_direct_children` and the
`"[]."`/`"[i]."`/`rindex("[")` path-construction idioms were extracted (the latter into
`paths/_grammar.py`'s `element_prefix`/`instance_prefix`/`strip_last_index`); the five recursion
bodies are untouched. `_INDEX_RE` (`validate/_validate.py`'s `_lookup_param_shape`,
`ops/_structural.py`'s `_definition_path_of`/`_governing_definition_path`) had been independently
compiled in both files — `import re` for no other purpose in either — so it moved to one shared
definition in `paths/_grammar.py` (a zero-risk dedup, no usage change). Its *usage* was deliberately
left unswapped for the canonical `definition_form()`: both call sites back public,
user-path-accepting surfaces (`.validate_param()`, `.remaining_domain()`, anchor/constraint-param
lookups) where a malformed path is a real, not merely hypothetical, input, and `definition_form()`
raises on one while the regex silently passes it through — an exception-type change on a public
misuse path, not a pure refactor. `tests/unit/test_traversal_refactor.py` confirms the two agree on
every well-formed corpus path (so the construction sweep lost nothing) and documents the boundary.

**Also here, because it is the same walk:** `Space.coordinate_paths()` (the fixed leaf layout, row
33) and `unflatten`'s static-count fallback. A solver adapter has to turn a genotype config into a
positional vector and back, and deriving which flat keys are coordinates rather than lift-length
bookkeeping means walking the `ListDomain` chain per bracket group — `x` is an outer count, `x[0]`
an inner count, `x[0][0]` a coordinate. Written by hand it fails *silently*: the round trip returns
a config that validates and differs. The layout is induced, not chosen (the order is already
`flatten`'s, which is already the DataFrame column order), so this is not the vectorization Out of
Scope excludes; the packing itself stays with the consumer.
**Gate:** `coordinate_paths()` round-trips through `unflatten` on every static, unconditional corpus
fixture; raises row 33 naming the offending param on a dynamic count and on a conditional param;
excludes lift-length entries at every nesting depth; order matches `flatten`'s and the DataFrame's.

### M10.8 — `ds.value`: opaque derived quantities
**Spec:** Expressions (`ds.value`, dual-typed like `.prop()`); Kleene rule 1's declared-operand rule;
the white/grey/black tier table under *Constraints*; the non-serializable set gains `fn`; rows 30.
**Build:** a `Value(ArithExpr, BoolExpr)` node carrying `fn`, operands, and `returns`, mirroring
`Prop` so evaluation, margins, and dual-typing reuse existing paths; evaluation in `eval/_kleene.py`
(Unknown if any referenced param is inactive, else `fn(*values)`); type checking beside `prop_type`;
`encode_expr` raising/marking it like any other callable.

Independently motivated — a physical constraint over ordinary reals currently forces the author to
wrap unrelated params in a sham custom type — and it is what lets M11's transport be total.

**Gate:** `returns=float` yields a real margin (parity with `prop("n") > 3 → 4.0`); `returns=bool` is
usable bare and yields `margin=None` that absorbs through Boolean composition (parity with
`prop("ok")`); `returns=int` drives a `.repeat()` count once M10.5 item 5 lands; non-scalar `returns`
is a row-30 error; an undeclared read raises because the value was never passed — asserted directly,
since that calling convention is the whole contract; `to_json`/`fingerprint` raise with the
closed-set message and `mark` yields `{"$opaque": true}`; `dependency_graph` includes the operands'
params. All prior vectors byte-identical.

### M11 — Representation layer
**Spec:** *The Representation Layer* (entire section); `Encoding` in Protocols; `Representation` in
the IR; the Representation conformance bullet; Solver Integration's three shapes; rows 31–32.
**Build:** `represent/` — `_protocol.py` (`Encoding`, `EncodingRule`, `hasattr` predicates mirroring
`custom/_protocol.py`), `_representation.py` (the frozen dataclass, `decode`, `encode`, `then`,
`check`), `_build.py` (dispatch → encodability and prop-dependency checks → targets → transport →
`meta/_meta.py::space_from_ir`), `_transport.py` (leaf substitution, projection resolution via
`_vector_base`, opaque synthesis), `_charts.py` (the induced representation and the chart node).
`Space.represent()`. `__init__.py` gains `Representation`, `Encoding`, `EncodingRule`, `ParamDef`,
`Chart`, and the domain types an `Encoding.target()` must construct; `Representation`'s constructor
is public — that *is* the supplied tier. Exporting `ParamDef` closes an M8 hole: `map_params`,
`param_from_def`, and `space_from_ir` have all taken it since M8 with no way for a user to annotate
their own callback.

Three things the implementation must not rediscover the hard way. **Rewrite expressions before
calling `space_from_ir`** — `check_expr_types` raises at construction for any surviving expression
whose operand changed kind. **`decode` must normalize instance paths to definition templates**
(`stops[0].dwell` → `stops[].dwell`) before looking up an encoding; getting this wrong makes
`delivery_routes` decode 0/200. **"Chart-bearing" is not `ParamDef.chart is not None`** — a scalar
lift's chart lives in `ListDomain.element_chart`, and the literal reading silently drops whole
vectors from the genotype.

**Gate:** the full Representation law block. Decode totality **200/200 on every corpus fixture** — a
measured baseline from a throwaway prototype, so anything less is a regression, not an unknown.
Feasibility agreement on `firmware_buffers`, the fixture where omitting transport costs 94% of the
budget (12/200 source-feasible while the target calls all 200 feasible). Path and arity preservation
over every fixture; `solver_portfolio`/`delivery_routes`/`memetic_pipeline` keep their count params
`integer`; rows 31–32 get message-content tests naming the path; the induced representation is
measure-preserving (fixed-seed KS on a log-scaled real, chi-square on integer and quantized params);
`src/` contains **zero** chosen encodings and **zero** structural morphisms (grep-asserted in CI —
the successor to "registry populated only in tests"); and a **supplied hierarchy-flattening
morphism, written entirely against the public surface**, passes `rep.check()` — the only honest test
that the supplied tier is expressive enough without core shipping it. Corpus:
`mixture_stickbreaking`. New known-answer vectors; every existing vector byte-identical;
format-version stays `1`. **Exit:** internal pre-release checkpoint — no public tag.

### M12 — Program types
**Spec:** `.symbolic()` / `.code()`; generative/non-generative sampling behavior; `Signature`, literals, `Primitive`.
**Gate:** `SamplingError` iff materialization required (default satisfies; freeze removes; inactive skips); literal domains carry charts; validators run on the AST/source; serialization poisoning matches M9's pattern. Corpus: `annealing_schedule`. **Exit:** internal pre-release checkpoint — **no public tag** (feature-complete for v0.1, which ships at M13 once docs land).

### M13 — Extras, docs; ship v0.1 (first public release)
`to_json_schema` (core, dependency-free); `[pydantic]` extra: `to_pydantic_model`; `to_dataclass() -> type` + `to_python_source()`; `from_callable` + `Annotated` domain literals as `designspace.contrib.signatures`. Guide pages: tier guidance for structured values, mechanism-choosing, rejection hostility, defaults-vs-anchors, solver-integration walkthrough — source material is the spec's Solver Integration section.

**User-facing docstring pass.** Rewrite docstrings across the **public/exported** surface — `Space` methods, `ds.*` functions, the public IR/result dataclasses, the builder view types, and the protocols — *for library users* (what it does + why + a runnable example), replacing today's absent or implementation/spec-facing docstrings. Private modules keep their spec-referencing maintainer docstrings (they document mechanism, not usage). Deferred to here deliberately: the public surface is not final until M12, so writing user docstrings once against the finished API avoids rewriting them as M8–M12 reshape it. **Enforced, not aspirational:** examples execute under `doctest` in CI, plus a docstring-coverage lint (ruff `D` rules or `interrogate`) scoped to `__init__`'s exports so the public surface cannot ship undocumented. Because **M13 is the first public release (v0.1)**, nothing ships publicly before it — the docstring pass is a **v0.1 release gate**, not a retrofit onto an already-released surface.

**Documentation site (Sphinx + PyData theme).** Build a rendered docs site under `docs/` with **Sphinx** and **`pydata-sphinx-theme`**, shipped as a `designspace[docs]` extra (dev/docs-only — **never core**; core stays `numpy`/`polars`/`rfc8785`). Extensions: `autodoc` + `autosummary` for an API reference generated from the M13 docstrings above; `napoleon` (NumPy/Google-style docstrings); `myst-parser` so guide pages are authored in Markdown, consistent with this repo's `.md` sources; `sphinx-copybutton`; `intersphinx` (python/numpy/polars); and doctest enforcement folded into the **existing `pytest` gate** — `pytest --doctest-modules` for the docstring examples plus `pytest --doctest-glob='*.md'` for guide pages authored as plain `>>>` blocks — so there is one runner and one gate. (Only if the guide pages adopt Sphinx `.. testcode::`/`.. doctest::` directives for richer setup/skip control do you need a directive-aware runner: the MyST-aware native `sphinx.ext.doctest` builder as a separate docs job, or `pytest-sphinx` to bring them under pytest — but `pytest-sphinx` targets rST directive syntax, so verify MyST-fence support before relying on it.) The guide pages listed above live here as MyST documents; **`API.md` stays the normative spec** — a separate maintainer artifact, not a user-docs page. Hosting (Read the Docs vs. GitHub Pages) is deferred; the buildable, doctest-clean site is the M13 deliverable.

**Exit — first public release.** With the full feature set (M0–M12), user docs, and public-surface docstrings all in place, tag **v0.1** and set `pyproject` `version = "0.1.0"`. The wire format — frozen since M7 and vector-tested byte-identical through M8–M12 — ships as format-version `1`, unchanged. This is the first artifact intended for public consumption; everything before M13 was a pre-release checkpoint.

---

## Definition of done (per milestone)

1. All new conformance laws green; all prior laws untouched and green.
2. Corpus fixtures for the milestone added and passing end-to-end.
3. Error-table rows introduced by the milestone each have a message-content test.
4. `mypy --strict`, `ruff`, full `pytest` green.
5. `PROGRESS.md` updated; `DECISIONS.md` entries for anything the spec left open.
6. Public `__init__.py` exports exactly the spec surface implemented so far — nothing speculative.
