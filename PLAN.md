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

- **One milestone.** Do not start milestone N+1 while N's exit criteria fail.
- **Laws first.** At the start of each milestone, write that milestone's conformance-law tests (they will fail),
    then implement until green. Conformance tests are permanent — never delete or loosen one; a milestone may only add.
- **Track progress in `PROGRESS.md`:** one line per completed milestone with date, test count, and any DECISIONS entries created.
- **No dead scaffolding.** Do not stub future milestones' APIs. Unimplemented spec surface should not exist yet,
    so `from designspace import X` fails honestly.


## Global conventions

- Python ≥ 3.12
- Layout: `src/designspace/`, tests in `tests/`.
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
2. **Additive changes need no bump** during the pre-release span ("<0.1"): a new `origin` value, a
   new expression node kind, a new entry in the non-serializable set, anything no shipped document
   or committed vector depends on.
3. **Add, never replace, known-answer vectors.** A milestone that touches the format adds vectors
   for the new construct and must show **every pre-existing vector byte-identical**. This is the
   gate that actually enforces the freeze; the version integer alone would not.
4. **Any non-additive change bumps the integer** and requires user approval: it is a compatibility
   break, not an implementation detail.
5. **`rfc8785` is pinned exactly.** Bumping that pin is an act under this protocol, not a routine
   dependency update: a transitive change to number formatting would silently shift every committed
   digest.

## Module map (stable across milestones)

```
src/designspace/
  __init__.py      # public surface only; re-exports
  expr/            # M0  AST nodes, operators, guardrails, all_/any_/count
  builder/         # M1  ds.param / ds.space builders, modifiers, layering
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
  serialize/       # M7  to_json/from_json, versioning; M15 to_json_schema
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
**Build:** `builder/`, `ir/`, `resolve/` as a real pass pipeline (collect → type-check → desugar → resolve refs → cycle-check → validate declarations → emit IR), each pass a function over an explicit intermediate. Duplicate-value checks with type-tagged equality; name-character rules; self-reference detection; duplicate-modifier rules (LWW vs accumulate).
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
- `builder/_paramexpr.py` / new `builder/_views.py` — the view subclasses. Move the 9
  type methods off the base onto `FreshParamExpr`; put `.repeat()` on the typed
  views and `ListParamExpr` (a type is required before a lift), not on the base or
  `FreshParamExpr`; the base keeps modifiers, expression operators, and the
  aggregates. Each type method and `.repeat()` constructs its target view (a
  `_as(cls)` helper, since `dataclasses.replace()` returns `type(self)`); modifiers
  keep their view via `replace`. `ListParamExpr.repeat()` re-nests for `.repeat(2, 3)`.
- `__getattr__` on the typed views re-raises the path-named `ResolutionError` for a
  type-method name (preserving row 2's message on `.real(0,1).bool()`, not a bare
  `AttributeError`); a non-type-method miss stays a normal `AttributeError`.
- The construction trap sites, which must build the right class: `builder/_functions.py`
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
- `builder/_space.py` — wire the nine methods (thin delegators; each calls `check_fully_resolved`).
**Gate:** idempotence + monotonicity (hypothesis); activity-respecting fill (the `turbo`/`chassis` case from the spec's history); completeness postcondition; element/list default exclusivity; the reducer guarantee tested positively *and* negatively (a two-unset-operand implication is documented as not propagated); three-valued activity **collapses to binary**; the driver-loop **coincidence** `next_assignable == [] ⟺ is_complete`; `remaining_domain` soundness. No new error-table rows (row 21 completed in code). Corpus: `pump_configurator` as a scripted driver loop.

### M7 — Identity and serialization
**Spec:** Identity and Serialization (entire section); Config Utilities (`config_hash`, `config_diff`).
**Build order within milestone:** canonical config encoding → `config_hash` → `config_diff` (variant-switch decomposition, positional repeat alignment) → `to_json`/`from_json` + version + non-serializable set + drop manifest → `fingerprint` (type tags, RFC 8785 — implement JCS in-repo or vendored, do not add a dependency without a DECISIONS entry — scopes, mark sentinel) **last**.
**Bound-origin preimage canonicalization (freeze-blocker from D-29(4)/M5).** The `fingerprint` step **must** canonicalize every bound-origin constraint (`origin == "bound"`) to its forbidden-state negation before hashing — a stored `x <= y` bound constraint enters the preimage as `x > y`, the shape a user `.forbid()` stores for the *same* feasibility. This is a provenance-specific canonical **encoding** (same category as "subsets sorted", "−0.0→0.0"), homed in the normalization pipeline, **not** algebraic expression rewriting. Rationale: M5 stores the *desired* predicate `x <= y` (for the `y − x` margin) and `eval/_constraint_eval.py::is_violated` keys feasibility off `origin`, which is excluded from the preimage; without this canonicalization a bound sugar and a user `.forbid(x <= y)` would have identical preimages but **opposite** feasible sets, breaking "equal fingerprints ⟹ identical valid-config sets". Also add the general guard: no preimage-excluded field (`origin`, `Constraint.params`, `dependency_graph`) may be feasibility-load-bearing.
**Gate:** the full Identity law block from the spec: sugar-equivalence pairs (log_scale/prior, implies, variadic repeat/chain, expression bounds/expansion), order-sensitivity, scope-monotonicity, round-trip law, mark distinctness, type-tag distinctness, float edges — plus **known-answer digest vectors** committed under `tests/conformance/vectors/` for every corpus fixture. Whole corpus round-trips. **Plus the bound-origin polarity law (D-29(4)):** a bound-sugar space and its `.forbid(x > y)` manual expansion are fingerprint-equal **and** feasibility-equal; a bound-sugar space and `.forbid(x <= y)` are fingerprint-**distinct** and feasibility-distinct. (Cross-ref: M4.5's deferred note already requires `fingerprint`/`to_json` to call `check_fully_resolved`.)
**Exit:** **freeze the wire format** (format-version integer `1`) — an internal checkpoint that anchors the freeze discipline (top of file) for every later milestone, **not** a public release. Public releases are deferred: the first is **v0.1 at M14**, and the format-version integer stays `1` across the whole pre-release span (M8–M13.5), which is exactly what the byte-identical KA-vector gates in M7.5/M8 enforce. Update `PROGRESS.md`.

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
- `builder/_space.py` — new `.require(*conditions, tags=(), meta=None)`; `resolve/_constraints.py::add_constraints` gains an `origin` parameter (default `"user"`), `.require` passes `hard=True, origin="require"`.
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
- `builder/_space.py` — rename `.constrain` → `.encourage`; add `.discourage`
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
**Gate:** dtype table asserted per corpus fixture; null-for-inactive; column names == path grammar; a missing-polars `ImportError` naming the extra. **Exit:** internal pre-release checkpoint — **no public tag** (v0.1 ships at M14; an internal alpha such as `0.1.0aN` is optional, not required).

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
`frame/_rows.py`, `frame/_schema.py`, and `builder/_space.py` — the last two through *local* imports to
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

**As-built.** The plan's own gate text ("Unknown if any referenced param is inactive") turned out
to under-specify the guarded case (`ds.value(f, x.if_inactive(0), returns=float)` with `x`
inactive) — **D-76** resolves this to operand-*value*-driven Unknown (join provenance over what
the operands *evaluate to*, not a literal scan of their referenced params' activity), which is
what actually lets `.if_inactive()` compose inside an operand as the prose promises; `fn`'s own
exceptions propagate uncaught, deliberately unlike `Prop`'s defensive swallow (no equivalent
contract law licenses one here). "`encode_expr` raising/marking it like any other callable" needed
more than a new `isinstance` branch: `encode_expr` had no `EncodeContext`/site-description parameter
at all before this milestone (every prior opaque site lived in `encode_domain`/`encode_prior`, one
level up), so it gained `ctx`/`site` params threaded through every recursive call and every
caller (`encode_constraint`, `encode_condition`, `_encode_count`, `encode_param`'s condition) —
`EncodeContext`/`OnUnserializable`/`_OPAQUE_MARKER` relocated from `identity/_ir_codec.py` to
`identity/_tags.py` to avoid a cycle (`_ir_codec` already imports from `_tags`, never the
reverse), re-exported from `_ir_codec` so no existing import site changed. `on_unserializable=
"drop"` on an in-tree opaque leaf has no field to omit the way a whole prior/custom param does —
**D-77** degrades it to the same `mark` sentinel plus a manifest entry naming the site, D-47's
precedent extended to all three positions a `ds.value` can occupy (constraint, `.when()`
condition, dynamic repeat count). Row 30 gained a third clause beyond the two named here —
comparison type mismatch against the declared `returns`, strict and mirroring `.prop()` exactly
(**D-78**). `resolve/_relocate.py::rewrite_expr` also gained a `Prop` branch alongside `Value`'s:
`Prop`'s absence was a pre-existing latent `TypeError` for any `.prop()`-based condition on a
struct/choice payload field (surfacing, in particular, per-instance inside a `.repeat()`
struct-lift element, via `instantiate_element`'s call to the same function) — a routine
same-shape fix, not a DECISIONS.md-worthy gap, since it changes no behavior for any space that
resolved before. **Discovered while testing, then fixed as an immediate follow-up (user-directed,
same session):** `eval/_kleene.py::_resolve_param_domain`'s bracket-walk branch unconditionally
`return`ed `None` instead of the domain it had just walked — a one-line regression from M10.5,
when the function was generalized from single-bracket to multi-level/dotted instance paths. Two
live, previously-untested consequences: an ordinal comparison between two lift-element instance
paths (`g[0] > g[1]` on a repeated ordinal, or a chained scalar lift) silently used raw Python
value comparison instead of declaration position — a silent wrong answer, empirically confirmed
before the fix and now covered by `tests/conformance/test_kleene.py::
TestOrdinalOrderingByDeclarationPosition`'s three new lift-element cases; and `.prop()` against a
custom-typed lift element at an instance path (this milestone's own `.repeat()`-element scenario)
raised a bare, uncaught `AssertionError` rather than evaluating, now exercised end-to-end by
`test_opaque_values.py::TestRelocationInsideRepeatElement`. Also fixed: `evaluate_constraint`
(`eval/_constraint_eval.py`) and `_classify_constraint` (`partial/_partial.py`) each evaluated a
constraint's expression **twice** — once via `evaluate_bool` for satisfaction, once more via
`margin()`'s independent re-walk of the same `Compare` leaves — harmless for pure arithmetic but
meaning a `ds.value` `fn` was called twice per `evaluate_constraints`/`validate`/`is_feasible`
call. Both now share one call-scoped `value_cache` (identity-keyed on each `Value` node, threaded
through `evaluate_arith`/`evaluate_bool`/`margin()` alongside `status`), so `fn` runs exactly once
— including when the same `Value` object is referenced twice within one constraint. No output
changed for any existing test; `tests/conformance/test_opaque_values.py::TestCallingConvention`
gained three tests asserting the call count directly.

### M10.9 — `unflatten`/`apply_defaults` static-count hygiene fix
Not a specification gap — API.md already states the law unambiguously ("Defaults" > "Counts and
lifts": "otherwise the lift is left implicit"); this is a regression from M10.7's static-count
fallback contradicting it, discovered incidentally while writing `examples/` (unrelated task) and
fixed here as a standalone follow-up, user-directed, before M11 continues. No DECISIONS.md entry.

**The bug.** `apply_defaults({})` raised an uncaught `KeyError` instead of returning `{}` for a
literal-count (`.repeat(4)`), zero-default lift — e.g. `ds.space(ds.param("weights").real(-1.0,
1.0).repeat(4)).apply_defaults({})`. `_fill_list` (`defaults/_defaults.py`) correctly declines to
write anything when no element gets a default, but `apply_defaults`'s closing `unflatten(flat,
space)` call then hit M10.7's static-count fallback (`config/_unflatten.py`, D-75): absent a
bookkeeping key, a literal count was *always* assumed to mean "a full coordinate vector was
supplied, recover the length" — the fallback's one designed use case — and reconstruction was
attempted against elements that were never written. No existing test caught this: the analogous
`test_no_element_defaults_leaves_lift_implicit` covers only a *dynamic*-count lift, which sidesteps
the fallback entirely (`isinstance(count, int)` is false for an `ArithExpr`), so the literal-count
case was never exercised.

**Build:** `config/_unflatten.py` only. `_is_fully_static(domain)` — a new helper — decides whether
a lift's entire nested `.repeat()` chain is literal-int at every level (the identical boundary
`coordinate_paths()` itself draws for "fixed layout"; a struct/choice element is a recursion
boundary handled by its own independent `_unflatten_level` call, not inspected here). Gated on that,
the static-count-fallback branch in `_unflatten_level` now checks for at least one real leaf under
the list's own instance-path prefix before committing to reconstruct anything; finding none, it
omits the list — the same "omit if nothing present" convention already applied to a struct with no
present descendant, two branches above. A present bookkeeping key skips the check entirely
(unaffected); the fully-supplied coordinate-vector round trip (no bookkeeping keys anywhere, but
every leaf present) always finds its own first leaf and so is unaffected too.

**Deliberately not touched:** a *mixed* chain — a static outer count over a dynamic inner one, e.g.
`.repeat(ds.param("n")).repeat(2)` — still raises `KeyError` regardless of data, exactly as before
this fix (`tests/unit/test_config.py::TestUnflattenStaticCountFallback::
test_nested_dynamic_and_absent_count_still_raises_key_error`, pre-existing and unchanged). This is
M10.7's own documented, deliberate scope limit ("the nested level still raises `KeyError` … noted,
not changed"), not part of this bug: the inner count is never a literal the fallback can use, so
reconstruction is unrecoverable independent of whether any data is present. `_is_fully_static`
returning `False` for this shape is what keeps the two cases apart — an earlier version of this fix
(swallowing any `KeyError` on an absent-bookkeeping list, or checking leaf-presence unconditionally)
broke that test both times, which is why the gate below tests the boundary explicitly rather than
just the bug itself.

**Gate:** `tests/conformance/test_defaults.py::TestStaticCountLiftLeftImplicit` — written first,
confirmed failing against the unpatched code (three of four cases raised `KeyError`) before the fix
— covers a static-count scalar lift, a static-count struct lift, a nested fully-static lift
(`.repeat(2, 3)`), and a guard that genuinely-supplied static-lift values are never mistaken for
absence. All prior tests, corpus fixtures, and known-answer vectors byte-identical (1258 total,
`ruff`/`mypy --strict`/`pytest` all green) — including, specifically, the mixed-chain test above.
No format bump; no public surface change.

### M10.10 — `ConstraintReport.violation_rate`
A user-requested API addition, prompted by a genuine reading mistake against `examples/
07_portfolio_observability.py`'s own `sampling_report()` output: `ConstraintReport.satisfied` is a
raw fraction (a forbid/discourage names a *bad* state, so a high `satisfied` there is unhealthy —
the opposite of require/encourage/bound), and nothing on the type gives the polarity-resolved
reading `ConstraintEval.violated` already provides for a single evaluation. Not a specification gap
— `API.md`'s "Sampling diagnostics" section is silent on this, but adding a derived, read-only
property changes nothing it already says; no DECISIONS.md entry.

**Build:** `ir/_results.py` only. `ConstraintReport.violation_rate` — a `@property`, not a stored
field, mirroring `ConstraintEval.violated`'s own shape — `satisfied` directly for forbid/discourage
(`feasible_when_satisfied` false), `1 - satisfied` for require/encourage/bound. **`0.0` when
`applicable == 0.0`, for both polarities** — this is the one place a naive "just flip `satisfied`"
implementation goes wrong: mirroring `ConstraintEval.violated`'s "inapplicable is never violated"
(Kleene rule 4) and `satisfied`'s own "0.0 by convention, never `NaN`" default takes an explicit
early return, since the mechanical `1 - satisfied` would report a never-evaluated require/encourage
row as "always violated" (`1 - 0.0`) rather than "carries no information." A property, not a stored
field: purely additive to a frozen dataclass, no equality/repr/serialization impact (this type never
enters `to_json`/fingerprint).

**Gate:** `tests/conformance/test_sampling_diagnostics.py` — one test per verb kind confirming the
direction (`forbid`/`discourage`: `violation_rate == satisfied`; `require`/`encourage`:
`violation_rate == 1 - satisfied`), an impossible-`require` case asserting `violation_rate == 1.0`
directly (the motivating case — `satisfied == 0.0` read backwards without this), and a parametrized
`applicable == 0.0` case over both polarities asserting `violation_rate == 0.0` for each — written
first, confirmed failing (`AttributeError`) before the property existed. `examples/
07_portfolio_observability.py` updated to read `row.violation_rate` instead of the manual
`feasible_when_satisfied` check it had grown around this exact confusion. 1265 total,
`ruff`/`mypy --strict`/`pytest` all green. No format bump.

### M11 — Representation layer
A genotype is a `Space`: `space.represent(*rules) -> Representation`, a `Space → Space` morphism
carrying `decode`/`encode`, so a solver asks the genotype the same introspection questions it asks
any space. Landed as three individually-green commits (dispatch rules, induced encoding, transport,
and defaults/anchors settling all shipped before the corpus fixture and full law block, per the
user's own preference for reviewable diffs on a milestone this size).

**Build:** `represent/` — `_protocol.py` (`Encoding`, `EncodingRule`, `hasattr` predicates mirroring
`custom/_protocol.py`), `_representation.py` (the frozen `Representation` dataclass — `decode`/
`encode` are *stored callables*, not delegating methods, D-81 — `then`, `check`), `_charts.py` (the
induced chart representation: two encoding classes, not one flag, since "cannot encode" must be an
attribute's absence, decided per param by probing whether the source chart's `to_unit` actually
works), `_transport.py` (leaf-substitution-then-rewrite-then-opaque expression transport across all
four stores a condition/constraint can live in, plus the row-32 count/prop-read scans), `_build.py`
(dispatch → row 31/32 eligibility → per-param `target()` → transport → defaults/anchors settled by
encode-and-validate-or-drop → `meta/_meta.py::space_from_ir`). `Space.represent()`; `__init__.py`
gains `Representation`, `RepresentationCheck`/`RepresentationCheckFailure`, `Encoding`,
`EncodingRule`, `ParamDef`, `Chart`, `Expr`, and the `Domain` family (D-52) — `Representation`'s
constructor is public, which *is* the supplied tier.

Three things that would otherwise have been rediscovered the hard way, confirmed directly against
the corpus before the fuller law-block pass: rewriting expressions *before* calling
`space_from_ir` (`check_expr_types` raises at construction for any surviving expression whose
operand changed kind); `decode` normalizing instance paths to definition templates
(`stops[0].dwell` → `stops[].dwell`) before an encoding lookup; and "chart-bearing" never meaning
`ParamDef.chart is not None` (a scalar lift's chart lives in `ListDomain.element_chart`).

Two corrections earned along the way, neither found by reasoning about the spec in the abstract —
both found by running `represent()` against every corpus fixture and reading what broke. `_build.py`'s
dispatch has to know whether a count/prop-excluded match came from the induced rule (decline
silently — D-58's own criterion, nobody explicitly asked for that param) or a user-supplied rule
(raise row 32 — the user did ask), which the induced rule cannot decide itself (`EncodingRule` takes
only a `ParamDef`, no space-wide visibility). And `resolve/_bounds.py::bound_origin_targets` assumed
a bound-origin constraint's target-side operand is always a bare `ParamExpr` — an invariant
transport can now break on purpose (chart-wrapping it) without weakening the bound itself; relaxed
to skip rather than assert, since the tighten-not-reject optimization it feeds is best-effort by
nature and the constraint is still enforced through ordinary rejection sampling either way.

**Gate:** the full Representation law block, including decode totality and feasibility agreement
**200/200 on every corpus fixture** (measured directly, not assumed) plus `mixture_stickbreaking`;
path and arity preservation over every fixture, with `solver_portfolio`/`delivery_routes`/
`memetic_pipeline` keeping their count params `integer`; rows 31–32 message-content tests naming the
offending path; the induced representation's shape and measure-preservation (fixed-seed KS on a
log-scaled real, chi-square on an integer and a quantized param — hand-rolled, no scipy); the
round-trip laws, including the integer-chart many-to-one witness for why `encode(decode(g)) == g`
is explicitly not a law; `then`'s associativity and identity-unit, asserted extensionally; a
**supplied hierarchy-flattening morphism, written entirely against the public surface**
(`ds.space_from_ir`, `ds.flatten`/`ds.unflatten`), passing `rep.check()` — the only honest test that
the supplied tier is expressive enough without core shipping one; and a grep assertion that `src/`
contains **zero** chosen encodings and **zero** structural morphisms. Corpus: `mixture_stickbreaking`
(a consumer-authored stick-breaking `Encoding`, never in `src/`, bridging a custom mixture-weights
type to `k-1` independent unit coordinates — mixed genotypes, since an explicit rule never falls
back to the induced rule for what it misses). `examples/09_representation.py`. New known-answer
vectors (`mixture_stickbreaking`, `chart_apply_demo` — freezing the `ChartApply` codec via an
induced representation's target); every pre-M11 vector byte-identical; format-version stays `1`.
1362 total, `ruff`/`mypy --strict`/`pytest` all green. **Exit:** internal pre-release checkpoint —
no public tag.

### M12 — Program types
**Spec:** `.symbolic()` / `.code()`; generative/non-generative sampling behavior; `Signature`, literals, `Primitive`.
**Gate:** `SamplingError` iff materialization required (default satisfies; freeze removes; inactive skips); literal domains carry charts; validators run on the AST/source; serialization poisoning matches M9's pattern. Corpus: `annealing_schedule`. **Exit:** internal pre-release checkpoint — **no public tag** (the last core feature milestone — `to_json_schema` is deferred to M15/v0.2 at the user's direction, so v0.1 ships at M14 once M13's docs land).

**As-built.** API.md's own coverage of `.symbolic()` was two table rows, four support-type
signatures, one error row, one config example, and one DataFrame row — no AST grammar, no statement
of what core checks, no evaluator, no arity semantics for the built-in primitive list. Landed as
three individually-green stages (declaration/validation/generativity; identity/serialization/
freeze/slice; corpus/vectors/docs), mirroring M11's precedent for a milestone this size.

Three genuine gaps, resolved before implementation, one of them a deliberate change to a stated law:

- **D-83** — the AST is a core-defined, core-checked JSON node grammar (`{"op","args"}` /
  `{"var"}` / `{"const"}`), the only way `max_depth`/`primitives`/the literal types mean anything
  once tree *generation* is Out of Scope; core ships no evaluator (`Primitive.fn` and every
  primitive name are declared metadata a consumer's own interpreter uses, never called by core).
- **D-89** — core assigns no arity to a bare built-in string; arity is checked exactly where an
  author writes it, via `ds.Primitive`, whose `arity` was widened past API.md's literal `int` to
  `int | tuple[int, int | None]` so a variadic or unary-or-binary operator is declarable and
  checked rather than silently unchecked.
- **D-90** — *a user-directed change to a stated law, not a reinterpretation.* Once arity carries
  no built-in-name-level meaning, the fixed 15-name primitive list constrained nothing a
  `ds.Primitive` couldn't already extend past, and its own contents were an arbitrary, incomplete
  snapshot (no `sqrt`, `tan`, `floor`, `where`, no comparisons). The user chose to drop it: any
  non-empty string names a primitive at declaration time. Error row 15 is **rewritten in place**
  (the number stays; its content becomes the declaration-hygiene checks that survive — duplicate
  name, malformed arity, bad `max_depth`, bad literal bounds, bad signature arg name), not deleted.
  Vocabulary checking is *relocated*, not eliminated: a tree's `op` must still be a name the param
  declared, so `{"op":"cos"}` against `primitives=["cso"]` is still an invalid value — only the
  declaration-time membership fence is gone.

Four routine, low-risk implementation completions, each recorded (D-84 through D-88) rather than
left silent since each shapes the wire format: `.symbolic()`'s value is `{"ast", "source"}` with
`"source"` optional and never cross-checked against `"ast"` (no printer/parser exists); `.code()`'s
`description`/`constraints`/`examples` are declared, serialized, fingerprinted metadata for a
consumer's own backend, never interpreted by core; `Signature.args`/`.returns` normalize a Python
`type` to `type.__name__` at construction, keeping the type itself and the fingerprint preimage
canonical; `.freeze()`/`.slice()` on a program param reuse `_pin_custom`'s exact mechanism
(`require(p == value)` plus `default = value`) with **no shorthand exception** — a program value is
always a plain, comparable, serializable JSON dict, so `.slice()` (unlike on a custom param, whose
rejection is specifically about having no `.prop()` substitution target) needed no new code, only a
law. `validators`/`.symbolic()`'s `sampler`/`Primitive.fn` — the three sites M10.8's
`EncodeContext` docstring had already named and left unwired — ride raise/mark/drop **per field, in
place** (D-88), generalizing D-77's `ds.value` precedent from "one opaque leaf inside an expression
tree" to "one opaque field inside an otherwise-structural domain": unlike the `.custom(sampler,
validator)` shorthand, which poisons a domain with no structural content to lose, a
`.symbolic()`/`.code()` domain keeps `signature`/`primitives`' names and arities/`max_depth`/
`description`/`constraints`/`examples` fully serializable regardless of which opaque field, if any,
is present.

`frame/_schema.py`/`frame/_rows.py` (`Utf8`/JSON-string, M10-anticipated), `identity/_tags.py`'s
`EncodeContext` docstring (M10.8-anticipated), and `builder/_space.py::has_nongenerative_params`'s own
docstring (M9-anticipated) needed no correction, only activation — confirming the three-milestone
forward-anticipation held. One pre-existing gap *was* fixed alongside the new kinds, not merely
activated: `has_nongenerative_params` scanned `self.params` flat, which silently missed a
non-generative param living inside a direct (non-struct/-choice) `.repeat()` element — its facts sit
in `ListDomain.element_*`, never a separate `ParamDef` — a latent bug for the pre-existing custom-
element case, only surfaced because M12 needed the walk correct for `.code().repeat(n)` too.

`ops/_structural.py`, `partial/_partial.py`, `represent/_build.py`/`_charts.py`, and
`config/_flatten.py`/`_unflatten.py` needed **zero** code changes beyond the one `_pin_program`
dispatch branch: every other downstream surface's existing generic-scalar-leaf fallback already
covered the two new kinds correctly, confirmed by law rather than assumed (`remaining_domain`'s
path-named `TypeError`; `represent()`'s induced rule declining a chartless param; `.slice()`'s
generic substitution path). 1451 total (1362 at M11), `ruff`/`mypy --strict`/`pytest` all green.

### M12.5 — Repo and CI hygiene
**Spec:** none — no runtime, public-API, or wire-format change. A 2026-08-03 review found the
codebase itself sound (1451 green tests, no structural issues) but the packaging/CI/tooling
metadata around it inconsistent in ways that would otherwise leak into every milestone after this
one, so it is fixed first rather than folded into the next milestone.

**Build:** add `src/designspace/py.typed` (empty — PEP 561 marker; the package is `mypy --strict`
clean internally but today ships no type information to consumers) and confirm hatchling includes
it in the wheel. Resolve the four-way inconsistent Python floor (`pyproject` said `>=3.11`,
`.python-version`/`devenv.nix` said 3.14, `[tool.mypy] python_version` said 3.14, CI ran 3.12) by
raising the floor to `>=3.12` everywhere — 3.11 was never actually satisfiable, since numpy's own
shipped stubs use `type` statements requiring 3.12+, confirmed by `mypy --strict --python-version
3.12` passing clean against the current source with zero changes needed. CI gains a matrix over
3.12/3.13/3.14, plus a job installing **without** the dev group so the core-only (no-polars) path
is proven, not assumed. `PLAN.md` calls ruff "lint+format" but only `ruff check` was ever gated;
`ruff format --check` fails on 48 files today (11 `src/`, 37 `tests/`), all pure line-reflow under
the 100-char limit with zero semantic change (confirmed by diff) — reformat as its own
no-logic-touched commit, then add `ruff format --check` to CI and to `CLAUDE.md`'s commit-gate
block. Sweep the `PLAN.md` typo (25 occurrences across `src/`/`tests/`, including the package
`__init__` docstring, user-visible via `help(designspace)`). `.gitignore` gains `.idea/`.

**Gate:** all four commands (`ruff check`, `ruff format --check`, `mypy --strict src/`, `pytest -q`)
green on 3.12/3.13/3.14; the core-only CI job imports `designspace` and runs the non-frame suite;
test count unchanged at 1451, since nothing behavioral changes. **Exit:** internal — no public tag.

### M13 — Public API documentation
**Spec:** no new runtime surface. **User-facing docstring pass** across the public/exported
surface — `Space`'s 48 members, `ds.*` functions, the public IR/result dataclasses, the builder
view types, and the protocols — for library users (what it does, why, a runnable example),
replacing today's near-total absence (`Space` 5/48 documented, `ParamExpr` 0/25, zero `>>>`
examples in `src/`) or implementation/spec-facing docstrings. Private modules keep their
spec-referencing maintainer docstrings (they document mechanism, not usage). Deferred to here
deliberately: the public surface was not final until M12 (M12.5 touched only packaging/CI, no
runtime surface), so writing user docstrings once against the finished API avoids rewriting them
as M8–M12 reshaped it. `to_json_schema` is **not** part of this pass — the user chose to defer it
past v0.1, to M15, alongside the optional extras: its two real uses (schema-based
validation/autocomplete for a JSON config file edited outside Python; constraining an LLM's
structured output when it proposes a config) are both consumer integrations, useful but not
required for a v0.1 built around the Python API itself, and its output is deliberately shape-only —
it cannot express `.forbid()`/`.when()`/cross-param constraints, so it was never going to replace
`space.validate()` even at v0.1.

**Split from the documentation site (user-directed, 2026-08-04).** This entry originally carried
both the docstring pass and the Sphinx site. The site is now **M13.5**, so the docstring pass
stands as a self-contained deliverable that M14 can build on even if the site slips.

**Format: NumPy-style sections** (Parameters / Returns / Raises / Examples) on the public surface,
user-chosen. The repo has no prior convention — plain reflowed prose, zero section markers
anywhere — so this is additive, and private modules keep their existing prose untouched.
**Examples on every callable a user invokes** (the module-level functions, `Space`'s members, the
builder view methods; ~90–100 doctests). The IR/result dataclasses get prose but no example: theirs
would only echo a repr, and `repr(Space)` is a multi-line `mappingproxy` blob, unusable and brittle
as expected output.

**Enforced, not aspirational**, all folded into the existing `pytest` gate (`testpaths`/`addopts`,
so CLAUDE.md's four commit-gate commands are unchanged in number and wording):
1. **Coverage** — `tests/test_docs.py`, griffe-driven, over `ds.__all__` and every public member
   of every exported class.
2. **NumPy-section validity** — same file: griffe's `numpy` parser under a captured `griffe`
   logger, asserting zero WARNING records, plus the converse check griffe omits (every signature
   parameter appears in the `Parameters` section).
3. **Executable examples** — `--doctest-modules`, so every `>>>` block is a test.

**Correction to this entry's own prior recommendation (measured 2026-08-04): ruff `D` cannot
enforce coverage in this repo, and `interrogate` scopes badly.** `ruff check --select D1 src/`
reports **0** findings — every implementation module is `_private`, and ruff treats members of
private modules as non-public, so `D100`–`D107` never fire (confirmed by a controlled test: an
identical file named `pub.py` yields `D101`/`D102`, named `_priv.py` yields nothing). Ruff `D`
can only police the style of docstrings that already exist (493 findings today: 280 `D205`,
148 `D209`, 49 `D401`, plus `D400`/`D403`), which would force churn across 85 spec-facing private
docstrings this milestone otherwise never touches — the outcome the prior recommendation wanted
to avoid. `interrogate` works per *file*, so it cannot separate a public `Space.sample` from a
private helper living in the same `_space.py`. **`griffe` (dev group only, never core)** is the
only candidate that computes publicity from `__all__`, which is exactly the stated scoping; it
also cross-checks documented parameters against the real signature, the failure mode NumPy
sections invite. Ruff `D` is therefore **not** enabled. Recorded here rather than in
`DECISIONS.md`: this is a plan correction, not an `API.md` gap.

*Also measured:* a runtime `__doc__` coverage check would silently under-report, because
`@dataclass` synthesizes a `__doc__` from the signature — `ds.Space.__doc__` is a truthy
`"Space(params: ...)"` string though `Space` has no class docstring. Griffe reads source
statically and reports it correctly; the export gap is **38 of 79**, not the 22 a runtime scan
finds.

**Doctest determinism conventions** (forced by what the API returns): prefer discrete output
(`sample_one(seed=0)` on an integer/categorical param is exactly reproducible — numpy's PCG64
stream is stable — while a `log_scale` real's last ULP can move across platforms); never show a
bare digest from `fingerprint()`/`config_hash()`, show structure or use `+ELLIPSIS`; `ds` and `np`
are injected via a root `conftest.py`'s `doctest_namespace` rather than re-imported in 116
examples — paired with a `TYPE_CHECKING`-guarded `import designspace as ds` in each of the 18
modules that carry examples, since injection is invisible to a static analyser and an IDE would
otherwise report every `ds` as unresolved (verified against PyCharm's own inspections: 13
warnings in `builder/_functions.py` before, zero after). The guard never executes, so it changes no
behaviour; it costs one `# noqa: F401` per module, the narrowest available suppression, and
`mypy --strict` confirms the apparent self-import creates no cycle even from `ir/_chart.py`, a
leaf the package imports first. **One deliberate `+SKIP`:** `Space.sample()` returns a `pl.DataFrame` and the
`core-only` CI job installs without polars, so its example is skipped and the runnable coverage
lives on `sample_dicts`/`sample_one` (`tests/conformance/test_dataframe.py` already tests the
DataFrame path for real). The alternative — `--ignore`-ing `builder/_space.py` in that job — would
drop 40+ real doctests.

That same root `conftest.py` must carry `collect_ignore` for
`tests/typing/_row2_and_wrong_type_modifier.py`: it is a `mypy --strict` fixture that raises
`ResolutionError` at import by design, so `--doctest-modules` over `tests/` aborts the entire
collection without it.

**Gate:** the four commit gates green, with `pytest -q` now additionally proving every `>>>` block
executes and both griffe gates pass; each gate demonstrated to *bite* (delete a docstring → named
failure; rename a parameter without updating its `Parameters` block → griffe's "does not appear in
the function signature"; alter one character of expected output → doctest failure); the `core-only`
no-polars job stays green. No runtime, public-API, wire-format, or fingerprint change — every
known-answer vector byte-identical. **Exit:** internal — no public tag.

**Export closure (user-directed, resolved within the milestone).** What began as a flag — five
result types returned by public `Space` methods but absent from `__all__` — was settled by
computing the actual closure rather than working from the five that happened to be noticed: walk
every public callable's return and parameter annotations and every public attribute type,
transitively, and collect what is reachable but unexported. That found **thirteen**, and the
twelve exported bring `__all__` from 79 to 91.

Ten needed no judgment: `API.md`'s own IR block *declares* `Constraint`, `Condition`,
`ConstraintEval`, `ValidationResult`, `ParamError`, `ConstraintReport`, and `SamplingReport`
beside `ParamDef`/`PartialEval`/`ParamDiff`/`SubspaceInfo`, which were already exported, and
declares `class Prior(Protocol)` beside the already-exported `ParamType`/`Encoding`. `Weights`
and `PriorSpec` complete `ParamDef.prior`'s declared type alongside the exported
`Log`/`Logit`/`Power`. So this is not a surface *expansion* — it is the export list catching up
with what the spec already declares, which is the "exports exactly the spec surface" rule
working as intended rather than being bent.

Three were a genuine call, put to the user: `Count`, `Prop`, and `Value` are 3 of the 30 AST node
classes in `expr/_ast.py`, of which only the three bases were public, and `API.md` names none of
them. Resolved by splitting on whether an exported type can stand in. `Count` subclasses
`ArithExpr` alone and `API.md` already states `ds.count()`'s result *is* an `ArithExpr`, so its
annotation was **widened** to that and nothing exported. `Prop` and `Value` subclass **both**
`ArithExpr` and `BoolExpr`, and that duality is load-bearing, not incidental: it is what makes
`require(ds.value(f, x, returns=bool))` type-check, verified under `mypy --strict` before
deciding. No exported type expresses "both", so widening would have broken a spec'd use (the
tier table's "black" row) and export was the only option. Public AST classes: 3 of 30 → 5 of 30.

`_ElementSnapshot` is the one reachable type deliberately left private — underscore-named builder
state behind `ParamExpr.lift`, which this milestone's own `ParamExpr` docstring already directs
readers away from in favour of `ParamDef`. Re-running the closure scan after the change reports
it as the only remaining item, which is the check that the set is now complete rather than merely
larger.

Exporting put all twelve under this milestone's own gates, which is where the docstring work for
them came from — the gate demanded `Attributes` sections for eight types and a worked
implementation example for the `Prior` protocol, none of which existed. 2464 total.

**As-built.** Five laws, not four: griffe reports a `Protocol`'s members as ordinary methods, and a
`...` body has nothing to demonstrate, so protocol *members* are exempt from the example law and the
obligation moves to the protocol *class*, where an author can read a whole worked implementation at
once (`ParamType`, `Encoding`, `Chart` each carry one). Without that fifth law the exemption would
have silently dropped exactly the examples that matter most. Attribute coverage is by NumPy
`Attributes` section rather than one docstring per field, which is the idiomatic spelling and what
autodoc renders; `ClassVar` discriminators are exempt (the view types' `type_kind` — API.md already
says the views carry no state and never reach the IR), instance attributes are not.

**One silent gate hole found and closed, which is the reason the milestone earns its keep:** pytest's
default `norecursedirs` contains `build`, so `testpaths = ["tests", "src"]` collected **zero** of the
83 doctests in the builder package, then named `src/designspace/build/` — the package holding
`ds.param`, `ds.space`, and every `Space` method. `pytest -q` reported green the whole time. M13
closed it by restating `norecursedirs` in `pyproject.toml` without `build`. *(Superseded 2026-08-06:
the package was renamed to `builder/` and the restatement deleted, so pytest's defaults are correct
as they ship. A directory under `src/` named for build output would still be skipped.)*

Final counts: 116 doctests, 466 parametrized gate tests, 2400 total (1818 at M12.5). Every
known-answer vector byte-identical; no runtime, public-API, wire-format, or fingerprint change.
Each gate was demonstrated to bite before closing out — a deleted docstring, a renamed parameter
whose `Parameters` block was left stale (caught from *both* directions: griffe's "does not appear in
the function signature" and this milestone's own converse check), and a one-character change to an
expected output each produced a named failure. The `core-only` no-polars job passes with all
doctests running, confirming the single `+SKIP` on `Space.sample` is placed correctly.

### M13.5 — Documentation site (Sphinx + PyData theme)
Split out of M13 (user-directed, 2026-08-04) so the docstring pass could land on its own.
Consumes M13's docstrings; adds no runtime surface.

**Toolchain resolved (user-directed, 2026-08-04): stay on Sphinx; the docstring gates stay on
griffe.** The open question at the bottom of this entry was settled with a measurement rather than
an argument. Griffe and Sphinx do not compete for the same job and cannot conflict: griffe parses
source statically and never imports the package, autodoc imports the package and never reads
source; they share no config, no plugin bus, no state. Verified by installing the whole site stack
into the project environment and re-running M13's gates — `tests/test_docs.py` **519 passed,
unchanged**. Griffe stays a test-time gate over `__all__`; Sphinx is the build-time renderer.
Neither substitutes for the other. mkdocs was not blocked either (`mkdocstrings-python` 2.0.5
requires `griffelib>=2.0`, satisfied by the installed griffe 2.1.0), so Sphinx was chosen on the
merits above rather than by version accident.

**Build:** a rendered docs site under `docs/` with **Sphinx** and **`pydata-sphinx-theme`**,
shipped as a `designspace[docs]` extra (dev/docs-only — **never core**; core stays
`numpy`/`rfc8785`). Extensions: `autodoc` + `autosummary` for an API reference generated from
M13's docstrings; `napoleon` (M13 chose NumPy style); `myst-parser` so guide pages are authored
in Markdown, consistent with this repo's `.md` sources; `sphinx-copybutton`; `intersphinx`
(python/numpy/polars). Versions the probe build ran against: Sphinx 9.1.0, `pydata-sphinx-theme`
0.20.0, `myst-parser` 5.1.0. Doctest enforcement stays folded into the **existing `pytest` gate** —
M13 already wired `--doctest-modules`; this milestone adds `--doctest-glob='*.md'` for guide
pages authored as plain `>>>` blocks, one runner, one gate. (Only if the guide pages adopt Sphinx
`.. testcode::`/`.. doctest::` directives for richer setup/skip control does a directive-aware
runner become necessary: the MyST-aware native `sphinx.ext.doctest` builder as a separate docs
job, or `pytest-sphinx` — verify MyST-fence support before relying on it, since `pytest-sphinx`
targets rST directive syntax.) `.gitignore` gains `docs/_build/` and any autosummary stub
directory — today's `/build/` entry is root-anchored and would not cover them.

**Guide pages:** tier guidance for structured values, mechanism-choosing, rejection hostility,
defaults-vs-anchors, solver-integration walkthrough — source material is the spec's Solver
Integration section (`API.md` 1261–1290), which alone covers four of the five. Consider a sixth
on sampling diagnostics: `API.md`'s own §Sampling diagnostics is already written as guidance
prose (the two pathologies, why the unconditioned measure is the point). Note that three of these
draw on passages that are *unheaded paragraphs* inside larger spec sections — the white/grey/black
predicate tiers (383–391), rejection hostility (483), defaults-vs-anchors (511) — so the pages
must lift them out rather than map 1:1 onto headings; and that "tier" means three different things
in the spec (predicate tiers, structured-value tiers 1/2/3, representation derived/supplied),
which the pages must disambiguate. `examples/README.md`'s existing `API.md`-section → example
index is the navigation skeleton; `examples/01`–`10` each already carry a `Concepts introduced
here` block naming the surface they demonstrate.

Pages live under `docs/` as MyST documents; **`API.md` stays the normative spec** — a separate
maintainer artifact, not a user-docs page (its 25 fenced python blocks are signature listings,
not transcripts, and will not run as doctests). Hosting (Read the Docs vs. GitHub Pages) is
deferred; the buildable, doctest-clean site is the deliverable.

**Measured at this milestone's open** (throwaway probe site over all 90 exports, discarded
afterwards — no `docs/` tree was committed):

1. **Default warning level: 0 warnings, out of the box.** Napoleon accepts every NumPy section
   griffe accepts, so M13's docstrings need no reformatting and a "clean `make html`" gate would
   have started green and stayed uninformative. That is the reason for the stronger gate below.
2. **`nitpicky = True`: 768 warnings — every one a cross-reference, none a docstring-format
   complaint.** 720 of them are a single config line: the stock autosummary class template lists
   members in a summary table without documenting them, so every member reference dangles. A
   template emitting `.. autoclass::` with `:members:`/`:inherited-members:`/`:show-inheritance:`
   clears all 720.
3. **The residual 48 → 0**, by the ignore lists below plus one real docstring fix. The
   zero-warning configuration is proven, not projected.

**The one real defect, and why nitpicky earns its keep.** `src/designspace/expr/_ast.py:636` —
`Prop.children`'s docstring is `"""The operands: just the custom-typed parameter being read."""`.
Napoleon applies a `Type: description` heuristic to *property* docstrings, so Sphinx renders "The
operands" as the property's **type**. Griffe's numpy parser has no such heuristic, so M13's gate
passes it clean: this is precisely the class of defect an independent second reader catches and
the existing gate structurally cannot. A scan of the whole public surface found **exactly one**
property/attribute of that shape — the other 18 colon-bearing summaries sit on classes and
methods, where the heuristic does not apply — so the fix is one character (em dash for the colon),
confirmed to clear the warning. Do not generalize it into a docstring sweep.

**Ignore lists, each entry commented with its reason** (nitpicky is only honest if its exceptions
are named):

- **Private types reachable from public annotations** — `_ElementSnapshot` (16 refs),
  `_NumericParamExpr` (2). M13 already recorded `_ElementSnapshot` as the one deliberately-private
  reachable type; regex `designspace\..*\._.*`.
- **`MappingProxyType`** (10) — the read-only mapping views' annotation renders unqualified and
  cannot resolve to `types.MappingProxyType`.
- **`polars.DataFrame` / `pl.DataFrame`** — *not* fixable by the `intersphinx` entry this entry
  specifies, and this was measured rather than assumed: polars' published inventory carries 143
  `polars.DataFrame.*` **method** entries and **no `polars.DataFrame` class entry**, so the target
  does not exist upstream to link to.
- **The `{"raise", "mark", "drop"}` type fields** in `Space.to_json` / `Space.fingerprint` — this
  is the **canonical NumPy "one of" spelling** and the docstrings are correct; napoleon splits it
  per token and tries to resolve each fragment as a class. Ignored by regex rather than degrading
  correct docstrings to a bare `str`.
- **Five type aliases used in public signatures but absent from `__all__`** — `Seed`, `Config`,
  `OnUnserializable`, `FingerprintScope`, `FingerprintUnserializable`. See below.

**Resolved — the unexported aliases are now exported (user-directed, 2026-08-04).** M13's
export-closure walk covered classes reachable through annotations; it did not cover *aliases*, and
these five were that gap. Three routes were costed: **(a)** export them — a public-API change,
needing sign-off; **(b)** `nitpick_ignore`, docs-only and reversible; **(c)**
`autodoc_type_aliases` expansion, **tried and rejected** (it substitutes the alias text but emits
four `TypeAliasForwardRef` references of its own on union targets, trading five named warnings for
four anonymous ones). The user chose **(a)**. `__all__` 91 → 96, `API.md`'s Support Types section
gains a *Type aliases* block declaring all five, and each carries a PEP-258 attribute docstring
that the M13 gates now cover. Exporting also removed five ignore-list entries outright: the names
resolve for real rather than being silenced.

Exporting `Seed` forced a latent duplication into the open: it was defined **twice**, identically,
in `builder/_space.py` and `sample/_sample.py`, with `represent/` importing one and `frame/` +
`sample/_diagnostics.py` importing the other. Two `designspace.Seed` candidates cannot both be the
export, so the definition is now single, in `builder/_space.py` — the upstream module, since
`sample/_sample.py` imports it and not the reverse — and the three consumers import from there.
`mypy --strict`'s no-implicit-reexport rule is what surfaced the second and third consumers.

**Doctest wiring, and the hole not to repeat.** Measured: **no `.md` file in the repo contains a
single `>>>` line** — `API.md` included, whose 25 fenced python blocks are signature listings — so
`--doctest-glob='*.md'` collects zero tests today and cannot accidentally execute the spec even
under a bare `pytest .`. The corresponding trap is the opposite one: `testpaths` must gain
**`docs/`**, or the guide-page doctests collect to zero and the gate reports green while testing
nothing — the same shape as the `norecursedirs`/`build` hole M13 found and closed. Assert a
non-zero collected count for the guide pages rather than trusting a green run.

**Gate:** `sphinx-build` with **`nitpicky = True` and `-W`** clean over every name in `__all__`,
every ignore-list entry carrying a comment naming its reason; every `>>>` block in the guide pages
executing under the existing `pytest` gate, with a non-zero guide-page collection count asserted;
the four commit gates green. Each new gate demonstrated to *bite* before close-out (introduce a
dangling reference → named nitpick failure; break a guide-page example → doctest failure). No
runtime, wire-format, or fingerprint change — every known-answer vector byte-identical. The one
public-API change is the five exported aliases above, user-directed and declared in `API.md`.
**Exit:** internal — no public tag.

**As-built (2026-08-04).** 2492 tests, 1 skipped (1451 at M12.5, 2464 at M13). The site builds
clean under `-W` with `nitpicky = True`: 0 warnings over all 96 exports.

*A second spec-contradicting docstring, found while wiring the aliases.* `Space.fingerprint`'s
`Parameters` block documented **three** scopes — `{"full", "structure", "sampling"}` — and prose
about "whether two spaces agree on structure alone". `API.md`'s scope table declares **two**
columns, `FingerprintScope` is `Literal["full", "sampling"]`, and `_VALID_SCOPES` agrees. So the
docstring alone was wrong: it documented a scope that has never existed. Corrected to the two real
scopes. Neither M13's griffe gates nor Sphinx can catch this class of error — griffe checks that a
documented *parameter* exists, not that its documented *values* do — which is worth stating plainly
rather than implying the gates are exhaustive.

*What the site gate cost and where it lives.* `tests/test_docs_site.py`, so CLAUDE.md's four
commands stay four. Three laws: the API reference lists every name in `__all__`; every guide page
carries at least one `>>>`; the site builds clean. The build takes ~17s cold, so it is opt-in via
**`DESIGNSPACE_DOCS_BUILD`**, which a new `docs` CI job sets (and which also runs `sphinx-build`
directly). Keying it on the environment rather than on whether Sphinx imports is deliberate:
`uv run --extra docs` leaves Sphinx in the project environment, so an import-keyed guard would
switch the 17s on permanently as a side effect of having once built the docs, and a gate that
turns itself on unbidden is one people learn to route around. Set-but-extra-missing **fails**
rather than skipping — someone who asked for the build should hear that it could not run. The
second law is the deliberate answer to M13's
`norecursedirs` hole: a doctest gate that collects nothing reports green, so the pages are asserted
to *carry* tests rather than trusted to.

*Two Sphinx-specific findings.* `autodoc` resolves `.. autodata:: Config` against `designspace`,
where the alias is only imported, so it never finds the attribute docstring in the private module
that defines it — and for `Config = dict[str, Any]` it falls back to `dict.__doc__`, whose indented
signature lines are not valid RST (two ERRORs, two WARNINGs). PEP 695 `type` was probed and does
not help: `TypeAliasType.__doc__` is the generic "Type alias." text, not the author's. The five
aliases are therefore hand-documented in `reference.md` with `py:data` directives — which also
gives them real cross-reference targets — while the full prose stays on the definition where
griffe gates it. Separately, `myst_heading_anchors` does not make a cross-document
`page.md#heading` link resolve even though docutils emits the matching `id`; that one link was
rewritten to page level rather than pinned to a slug that the resolver disagrees about.

### M13.6 — Executable tutorials and documentation prose
Split out ahead of M14 (user-directed, 2026-08-05). Consumes M13.5's site; adds no runtime
surface and touches nothing under `src/`.

**Spec:** the site shipped at M13.5 with two entries, Guides and API reference. Neither shows a
reader what the library *returns*: the guides carry `pycon` doctests whose outputs are small and
hand-written, and the ten scripts under `examples/` were invisible from the site entirely. M13.6
adds a third top-level entry, **Tutorials**, which `pydata-sphinx-theme` renders as a header tab.
Eleven pages cover the surface one topic at a time, each carried by a concrete application, and
**every code block executes when the site is built** so the output beneath it is the value that
block actually returned. The former Guides tab becomes **Design notes**, cut to the five pages
that argue a trade-off rather than restate what a tutorial now shows. Separately, its prose is
rewritten from an essayistic, second-person register to that of the NumPy and SciPy user guides.

**Build:**

- `myst-nb` added to the `docs` extra, replacing `myst_parser` in `conf.py`'s `extensions`
  (myst-nb registers itself as the `.md` parser with `override=True` and calls myst-parser's setup
  internally; listing both raises a bare `ExtensionError`). Execution is opt-in per file: myst-nb
  treats a page as a notebook only when its front matter says `file_format: mystnb`, so the seven
  guides and the reference parse as plain MyST and never execute.
- `docs/tutorials/`: eleven topic-titled pages plus an index. Cells end in a bare expression,
  since that is what gets captured; state carries across cells within a page; every draw is
  seeded, because outputs regenerate on each build.
- `sphinx-design` for `{grid-item-card}` routing on the tutorials and guides indexes.
- `examples/` reduced from ten feature-tour scripts to one task-shaped driver,
  `examples/tuning_loop.py`.

**Gate:** the docs laws in `tests/test_docs_site.py` become five. The two M13.6 additions are
`test_tutorial_pages_exist` and **`test_tutorial_page_executes`**, which parses each page's
`{code-cell}` blocks and runs them in order in one namespace. That law is what makes a tutorial a
test rather than a demo: with outputs generated rather than written down, nothing compares them
against an expectation, so the pages carry `assert` statements for the claims their prose makes
and this runs them. It duplicates myst-nb's own execution deliberately, because myst-nb only runs
during the environment-gated build; this runs in ~0.4s per page on a plain `pytest -q`. It also
asserts the `file_format: mystnb` front matter, without which myst-nb renders the cells and
silently never executes them. Plus: the four commit gates pass; the site builds clean under `-W`
with `nitpicky = True`; the header carries Guides / Tutorials / API reference.

Register is deliberately **not** gated. Second-person counts, "rather than" counts and antithesis
counts are editorial judgment, and a threshold test over them would be brittle and would invite
gaming. The em-dash law is the exception only because it is objective.

**As-built (2026-08-05).** 2512 passed, 2 skipped (2513 passed, 1 skipped under
`DESIGNSPACE_DOCS_BUILD`); 2491 at M13.5. The site builds clean under `-W` with
`nitpicky = True` across 12 new tutorial pages, and 160 code cells execute and
render. Nav carries three tabs: Tutorials, Design notes, API reference.

*`literalinclude` was built first, and reading it back is what rejected it.* The first cut of this
milestone (commit `4dd795f`, kept in history) pulled code out of `examples/*.py` with
`{literalinclude}` and `:pyobject:`, which required splitting each script's `main()` into
`show_sampling(space)`-style step functions to give the directive an extraction unit. It met its
own acceptance criteria and was wrong anyway: a docs page rendered
`def show_sampling(space: ds.Space) -> None:` followed by `print(f"  {key:16} = {value!r}")`, when
what a reader wants is the expression and its result. And it showed no results at all, since a
`literalinclude` renders source. The lesson is that "no duplication" was the wrong thing to
optimize; the duplication `literalinclude` avoids is cheaper than the readability it costs.

*Why not doctest, which is already in the repo.* The guides' `pycon` blocks show real returned
values and are gated by `pytest -q`, so they were the obvious candidate. They require the expected
output to be written up front, which is impractical for a 500-draw `sampling_report` and
impossible to keep honest for a `polars.DataFrame` (`_space.py:1324` carries the repo's only
`# doctest: +SKIP` for exactly that reason). Generated output is the point of the change; the
`assert`-in-cell convention plus law 3 is what buys back the verification doctest gave for free.

*Executor choice.* `jupyter-sphinx` was rejected on maintenance grounds: last release 0.5.3 in
December 2023, 51 open issues, and its Sphinx-9 issue (#287) is a deprecation now and a removal in
Sphinx 11. `sphinx-gallery` was rejected on two counts: its text blocks are rST-only, with the
MyST request (#710) open since 2020 and explicitly unstaffed, and its gallery index is a hardcoded
thumbnail grid that would render as eleven identical grey `no_image.png` tiles for a library that
draws nothing. The `{grid-item-card}` index already built for revision 1 covers what a gallery
index would have provided.

*Three things measured rather than assumed.* A bare `Space` repr is 634 characters for two
parameters, so tutorial cells display targeted queries and never the space itself. polars ships
only `text-align` and `white-space` in its inline table CSS, and `pydata-sphinx-theme` already
carries `.dataframe` rules built on theme-aware variables, so the DataFrame renders correctly in
both themes with no override, contrary to the plan's budgeted one. And myst-nb writes executed
notebooks to `docs/jupyter_execute/`, which `ruff format` picks up because it formats `.ipynb` by
default; both that and `docs/.jupyter_cache/` are now gitignored.

*`jupyter_execute` also has to leave `exclude_patterns`, and the gate is what found it.* Those
notebooks land **inside the source directory**, so from the second build onward Sphinx reads them
back as source documents: eleven orphan-toctree warnings plus a broken xref each, all fatal under
`-W`. A first build passes and every later one fails, which is why an ad-hoc
`rm -rf docs/_build && sphinx-build` was green while `test_site_builds_clean` was red. Exactly the
class of failure M13.5 put the build inside `pytest` to catch.

*Guides became Design notes, and three of them were duplicates.* The tutorials
were written alongside a Guides tab, and the two overlapped badly enough that
the nav bar could not say which section answered which question. Measured at
heading level: `solver-integration`'s "Shape 1/2/3" headings were **verbatim
identical** to tutorial 11's, `sampling-diagnostics` matched four of tutorial
10's five, and `choosing-a-mechanism` matched three of tutorial 03's near word
for word. The first two were deleted after their genuinely unique sections moved
across (the custom-type generation ladder and adapter conventions into tutorial
11, Funnels into tutorial 10); `choosing-a-mechanism` and `defaults-and-anchors`
were cut down to the judgment they carry, the latter retitled `anchors` since
tutorial 09 now owns defaults. Guides 7 → 5, renamed **Design notes** because
the surviving pages all argue a trade-off rather than instruct: the tutorials
teach a mechanism and show what it returns, the design notes argue which
mechanism and what it costs. Nav is Tutorials / Design notes / API reference.

*The doctests caught two factual errors in prose during that edit.* `validate()`
covers domain legality **and** constraints, so a page claiming it checks only
domains was wrong twice over; `param_errors` is what separates a malformed
config from a well-formed infeasible one. And the "well-formed but infeasible"
example doubled `initial_temp` to trip a forbid, which pushed `min_temp` outside
its own `1e-4..1.0` domain and made the config malformed instead, quietly
demonstrating the opposite of the claim. Both surfaced because the assertions
run, which is the argument for law 3 restated.

*One em-dash survives in the built HTML, correctly.* Page 07 renders
`SerializationError: ... has no structural encoding — pass on_unserializable='mark' or 'drop'`,
which is `src/`'s own message. The gate covers authored prose under `docs/` and `examples/`, not
library output, and doctoring a displayed result to satisfy a prose rule would defeat the purpose
of showing real output.

### M14 — v0.1 release
**Spec:** no new runtime surface — release packaging only. `pyproject.toml` gains `version =
"0.1.0"`, `license`, `authors`, `classifiers`, `[project.urls]`; the `LICENSE` file lands here.
Real `README.md` (install, a short quickstart, feature summary, links to the docs site and
`API.md`, project status) replacing today's three-line stub. New `CHANGELOG.md`.

**Gate:** `uv build` emits a wheel containing `py.typed`; a clean-venv install of that wheel
imports `designspace` and type-checks correctly from a consumer's perspective (proving `py.typed`
took effect, not just that it's present in the archive). **Exit — first public release.** With the
full feature set (M0–M12), user docs (M13/M13.5), and release packaging all in place, tag **v0.1**. The
wire format — frozen since M7 and vector-tested byte-identical through M8–M13.5 — ships as
format-version `1`, unchanged. `to_json_schema` ships **without** v0.1 — deferred to M15 at the
user's direction (see M13 above) — so `API.md`'s Staging section, revised when M15 opens, is what
governs it until then. This is the first artifact intended for public consumption; everything
before M14 was a pre-release checkpoint.

### M15 — Optional extras and `to_json_schema` (v0.2, post-release)
**Spec:** `[pydantic]` extra: `to_pydantic_model`; `to_dataclass() -> type` + `to_python_source()`;
`from_callable` + `Annotated` domain literals as `designspace.contrib.signatures`; and
`Space.to_json_schema() -> dict` (API.md, "Identity and Serialization"), folded in here at the
user's direction rather than shipping at v0.1 as originally scoped (this file's M13 said
`to_json_schema` until 2026-08-03) — see M13's note above for why. Unlike the other three,
`to_json_schema` needs no optional dependency (it stays dependency-free per the spec's own
annotation); it is *build*-deferred here, not demoted to an install-time extra. `API.md`'s Staging
section is revised to say so when this milestone opens, since today it still states
`to_json_schema` "stays core" in a way that reads as required for the initial release.

**`API.md` currently underspecifies `to_json_schema`'s output contract** — a signature line and a
nine-word comment, no JSON Schema draft, no per-kind mapping, no statement on
conditions/constraints or opaque params. Resolve this with the user before writing code, and record
the answer in `DECISIONS.md` at that point. The other three extras are purely additive — new
methods, a new subpackage, new optional extras — with no IR/format/fingerprint impact, so no version
bump and no vector churn from them; `to_json_schema` likewise adds no wire format (a new method
only).

**Build:** the three extras as scoped in API.md's Staging section, plus `serialize/_jsonschema.py`
for `to_json_schema`, mirroring the domain walk already in `serialize/_tojson.py` and
`identity/_ir_codec.py`'s `encode_domain` rather than writing a third walker, wired onto `Space` via
a deferred import (matching the existing `builder/_space.py` pattern); new
`tests/conformance/test_json_schema.py`, laws-first per usual protocol. Carries forward M13's
documentation obligation explicitly: the docstring pass at M13 covers only what exists then, so
this milestone writes its own user-facing docstrings, under the same coverage lint, before merging.

**Gate:** the commit gates (CLAUDE.md) plus the docstring-coverage gates established at M13, all
green; pre-existing known-answer vectors byte-identical; every corpus fixture's
`to_json_schema()` output validates that fixture's own sampled configs; `examples/README.md`'s "Not
yet implemented" section (which currently names exactly `.to_json_schema()`) is deleted. **Exit:**
tag **v0.2**.

---

## Definition of done (per milestone)

1. All new conformance laws green; all prior laws untouched and green.
2. Corpus fixtures for the milestone added and passing end-to-end.
3. Error-table rows introduced by the milestone each have a message-content test.
4. `mypy --strict`, `ruff`, full `pytest` green.
5. `PROGRESS.md` updated; `DECISIONS.md` entries for anything the spec left open.
6. Public `__init__.py` exports exactly the spec surface implemented so far — nothing speculative.
