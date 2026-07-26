# Decisions

This file is an interpretation log for genuine gaps in `API.md`. It is not a general ADR
diary, progress log, or place to justify divergence from a clear requirement.

When a question is resolved, update `API.md` so future work no longer depends on reading
the historical entry. Keep the entry here to preserve why the answer was chosen.

## Entry template

Copy this template for each genuine specification gap.

```markdown
## Q-0001 — Short title

- Status: Open | Resolved
- Date: YYYY-MM-DD
- Spec section: API.md §...
- Decided by: User | Agent | Pending

### Question

The exact question that the specification does not answer.

### Why the specification is insufficient

The conflicting readings or missing information that prevent a justified answer.

### Possibilities considered

1. **Possibility A.** Observable consequences and trade-offs.
2. **Possibility B.** Observable consequences and trade-offs.

### Answer

The selected interpretation, or `Pending` while the entry remains open.

### Reasoning

Why this answer best fits the stated scope and invariants.

### Specification update

The `API.md` section changed after resolution, or `Pending`.
```

---

## D-45 — `ParamType.type_key`, and how the optional capabilities (`sample`, `cardinality`, `properties`/`extract`) are typed

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Protocols (`ParamType`); §to_json / from_json; §Space — Introspection
- Decided by: User (capabilities model) + Agent (typing mechanism)

### Question

Two related gaps in the `ParamType` protocol block (API.md:708-717):

1. Serialization (`type_key` + `describe()`), the `from_json` registry, and `Capabilities.type_key` all require a `type_key` per custom param, but the protocol block never says where it comes from.
2. `sample`/`cardinality`/`properties`/`extract` are documented as optional capabilities a type may or may not implement, but Python's `typing.Protocol` has no clean way to mark a member "may or may not be present" — declaring them in the Protocol's static shape would force every author to stub unsupported ones.

### Why the specification is insufficient

`type_key` is used throughout (`API.md:608`, `730`, `891`, `983`) but never introduced as part of the contract. And the optional-capability paragraphs (this session's own design discussion, now folded into the protocol) don't specify a typing mechanism.

### Possibilities considered

1. **`type_key` required; optional capabilities duck-typed via `hasattr`, absent from the `ParamType` Protocol's static shape.** Mirrors the existing external-`Prior` protocol exactly (`ir/_priors.py`: only `.ppf()` is declared; `.cdf()` is `hasattr`-checked at each call site, never part of `Prior`'s shape — `charts/_external.py`). No sub-protocols, no `runtime_checkable` (unused elsewhere in this codebase).
2. **Nested capability sub-protocols** (`Generative`, `Cardinal`, ...), `@runtime_checkable`, `isinstance`-checked. More static precision, but new machinery this codebase doesn't otherwise use, and `runtime_checkable` only checks member *names*, not signatures — little real gain over `hasattr`.

### Answer

Possibility 1. `ParamType` declares only the five required members (`type_key`, `validate`, `to_json`, `from_json`, `describe`); `sample`/`cardinality`/`properties`+`extract` are checked via `hasattr` (`designspace.custom.is_generative`/`has_cardinality`/`has_properties`) wherever core needs them (sampler, `.cardinality()`, `.prop()` resolution).

### Reasoning

Exact match for an established, working precedent in the same codebase; zero new typing machinery; a type author is never forced to stub an unsupported capability with a `NotImplementedError` body just to satisfy a Protocol's shape.

### Specification update

Folded into API.md's `ParamType` protocol block.

---

## D-46 — A custom value's public (config-dict) representation is *phenotype* form, not native

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Config Representation; §Protocols (`ParamType`)
- Decided by: Agent

### Question

`ParamType.sample(rng) -> Any` returns a value of unconstrained type (e.g. a live graph object). `to_json(value)`/`from_json(data)` bridge it to/from a JSON-safe form. Every other kind's config-dict leaf *is* its domain value directly (a real's leaf is a bare `float`). What does a **custom** leaf hold — the native `sample()` output, or `to_json()`'s JSON-safe encoding? The choice determines what `validate`/`extract`/`.freeze()`/`.default()` receive as `value`, and how `config_hash`, `Space.to_json()`'s per-param `default`, and a `.freeze()` pin's embedded expression `Literal` all serialize a custom value.

### Why the specification is insufficient

API.md's own Config Representation table (API.md:684) shows `{"tree": <ParamType.to_json output>}` for a custom leaf — a direct textual claim that the *config* value is the `to_json()` output, not the native object. But the `ParamType` protocol's `validate`/`extract` signatures read most naturally as operating on the domain value itself (matching every other kind), and nothing states core must bridge through `from_json` before calling them.

### Possibilities considered

1. **Config/validate/freeze/default all hold the *native* value** (matching every other kind superficially). Fails immediately: `config_hash`/`fingerprint`'s existing generic value codec (`identity/_tags.py::encode_default_value`) can only serialize JSON-shaped dict/list/scalar trees — it cannot hash an arbitrary native object, and extending it per-type would require threading a `ParamType` through the config-encoding layer everywhere a leaf value is touched. A `.freeze()` pin's `Compare(eq, param, Literal(value))` has the identical problem — `Literal.value` must already be JSON-encodable.
2. **Config/validate/freeze/default all hold the *phenotype* (`to_json()`) form**; `to_json`/`from_json` are the only bridge, invoked by core exactly twice: right after `sample()` (native → phenotype, before storing in a config), and right before `validate`/`extract` (phenotype → native). This matches API.md's own table literally, and — because `to_json()`'s output is contractually JSON-serializable (row 23) — every existing generic codec (`encode_default_value`, the config/flatten/hash machinery) already handles it with **zero new per-type-aware code**, once `Literal`'s own codec is generalized from the scalar-only `tag_value` to the already-existing recursive `encode_default_value` (itself a backward-compatible, byte-identical-for-every-prior-literal change).

### Answer

Possibility 2.

### Reasoning

Directly evidenced by the spec's own illustrative table; the only design that requires no new serialization machinery (reuses `encode_default_value` uniformly for config leaves, `Space.to_json()` per-param defaults, and `.freeze()`'s pinned literal); and it gives "does this custom type support equality" a free, uniform answer — comparing two `to_json()` outputs structurally, with no `__eq__` requirement on the native value at all (feeds D-47).

### Specification update

Folded into API.md's `ParamType` protocol block and the Config Representation section.

---

## D-47 — Freeze-on-custom: mechanism, and why it also sets `default`

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Space — Structural Operations (`.freeze`'s per-kind mechanism); §Sampling and Generativity
- Decided by: Agent (mechanism follows directly from D-44/D-46; extends PLAN.md's M9 Build line, which named the mechanism but not this detail)

### Question

PLAN.md's M9 Build line says freeze-on-custom "pins it via `require(p == value)` when the type supports `==`, otherwise out of scope — no new machinery, reuses the `.freeze()` bool-pin mechanism." Two things that line leaves open: (a) what "supports `==`" means operationally, given D-46 (customs aren't required to implement native `__eq__`); (b) whether the pin *also* sets `default`, as the domain-narrowing kinds (real/integer/categorical/ordinal) do but bool does not.

### Why the specification is insufficient

Bool's pin (D-44's precedent) never sets `default`, but bool is *always* generative (chart-based `sample()` always exists), so it never needs one. A **non-generative** custom (M9's own new case, D-45) has no route to a value at `sample()` time except `.default()` — and API.md:427 states plainly that `.freeze()` must "remove" the non-generative `SamplingError` trigger. A bare require-pin (bool's mechanism) does not satisfy this: rejection-sampling a fresh `sample()` draw against a hard equality is fine for bool's 2-value domain but is not what a non-generative custom (no `sample()` at all) can even attempt.

### Possibilities considered

1. **Bare require-pin only** (bool's exact mechanism, no default). Fails the non-generative case outright — nothing left to materialize a value from.
2. **Require-pin + `default = value`.** Satisfies the non-generative case for free (the sampler's existing non-generative fallback — "materialize from `.default()` or raise" — already exists, D-45's `_materialize_scalar`) and costs nothing for the generative case (the reference sampler never consults `default` for a generative draw, matching every other kind), at the price of diverging slightly from bool's textual precedent.

### Answer

Possibility 2, and — per D-46 — "supports `==`" is realized as: **always true for the full protocol form** (comparing two values' `to_json()` output structurally is always well-defined, since `to_json()`'s output is contractually JSON-serializable) and **never true for the shorthand form** (no `to_json`, hence no comparable, embeddable literal) — `.freeze()` on a shorthand custom raises `ResolutionError` naming the param. `.slice()` is out of scope for a custom param entirely (a sliced value would need to substitute into a `.prop()` expression's operand, which `evaluate_arith`'s `Prop` handling does not support for a non-`ParamExpr` operand) — rejected with a clear `ResolutionError` rather than producing a space that fails unpredictably at evaluation.

### Reasoning

Setting `default` is what makes the freeze-removes-the-SamplingError guarantee (API.md:427) actually hold for the one kind whose freeze doesn't come from domain-narrowing; it is inert for the generative case, so it is a strict improvement over the bare-pin option with no downside. Gating "equality support" on the *protocol form* (not a native `__eq__`) is the only definition consistent with D-46's phenotype-form convention and requires no new author-facing requirement.

### Specification update

To be folded into API.md's `.freeze` row (currently a forward reference to M9.5's fold-in; this session's fold covers the custom case specifically, ahead of M9.5's five container kinds).

---

## D-48 — `.cardinality()`: the structural-product algorithm, and its scope on conditions

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Space — Introspection (`.cardinality()`)
- Decided by: Agent (PLAN.md's M9 Build line names the feature; this is the algorithm)

### Question

`.cardinality()` needs a concrete algorithm. The structural cases (real/integer/quantized grid, categorical/ordinal/bool, subset/permutation, choice/struct nesting, static-count list, custom) are enumerable in closed form. Params carrying a `.when()` condition are not, in general, without real CSP/enumeration machinery — explicitly out of scope everywhere else in the codebase (`is_finite`'s docstring: "no enumeration/CSP machinery yet").

### Why the specification is insufficient

API.md says only "finite-config count over the structural product... `None` if infinite/continuous/unquantized-real or not enumerable" — silent on exactly which conditional spaces count as "enumerable."

### Possibilities considered

1. **`None` whenever *any* param anywhere has a condition.** Sound, but this would make `.cardinality()` return `None` for essentially every choice- or struct-containing space (their descendants always carry a relocation-injected condition) — far too conservative to be useful, and contrary to "structural product" explicitly implying choice/struct nesting is meant to be handled.
2. **Recurse via each root param's own domain shape** (not a flat scan of `.params`) — a choice sums over variants (bare = 1, payload-bearing = product of the variant's own fields, recursively), a struct multiplies its fields, both handling their *own* relocation-injected condition implicitly (never inspecting it) since the recursion only ever visits a descendant through its actual structural parent. A descendant carrying an **independent** condition — one that is not exactly what structural injection alone would produce — is detected via structural (not identity) comparison of the canonical AST encoding (`identity/_tags.py::encode_expr`) against the injection that parent would produce, and makes the whole result `None`. A root param's own condition (never injected) always makes the result `None`.

### Answer

Possibility 2.

### Reasoning

Handles the common, spec-motivating case (struct/choice nesting — "structural product") exactly, with no CSP engine; remains sound (never over-counts) for the genuinely out-of-scope case (an independent `.when()` on a struct field or choice-variant field, or on a root param) by falling back to `None` rather than guessing. Matches PLAN.md's own "when tractable, else `None`" framing for the conditional case.

### Specification update

Folded into API.md's `.cardinality()` row.

---

## D-49 — `.prop()` dual-typed as `ArithExpr`/`BoolExpr`, matching bare-`ParamExpr` precedent

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Expressions (ArithExpr / `.prop()`); §Parameter Types (Builder view types, `BoolParamExpr`)
- Decided by: User (raised the ergonomics question) + Agent (precedent research and implementation)

### Question

`.prop()` originally returned a plain `ArithExpr`, so a bool-declared property needed an awkward `.prop("ok") == True` to be usable as a condition (`.require(...)`, `&`, `~`). Should `.prop()` instead be directly usable as a `BoolExpr` when the declared property type is `bool`, the way `BoolParamExpr` already is for a bool-typed param?

### Why the specification is insufficient

API.md's `.prop()` line only says "custom type property (scalar-typed)," under the `ArithExpr` heading — silent on whether a bool-declared prop gets the same "usable directly as a condition" treatment `BoolParamExpr` documents for bool params.

### Possibilities considered

1. **Leave `.prop()` `ArithExpr`-only.** Keeps the awkward `== True` idiom permanently.
2. **Make `Prop` dual-typed (`ArithExpr` **and** `BoolExpr`), with a new resolution-time check requiring bool-declared type for bare-boolean-position usage.** More precise than the existing bare-`ParamExpr` behavior, but inconsistent with it (asymmetric strictness) and requires new parent-context-tracking machinery `check_expr_types` doesn't otherwise have (it's a flat per-node walk, no parent pointers).
3. **Make `Prop` dual-typed, no new position-specific check.** Mirrors `ParamExpr(ArithExpr, BoolExpr, VectorExpr)` exactly — confirmed by direct inspection that the codebase already has *no* `type_kind == "bool"` gate anywhere for a bare `ParamExpr` used as a condition (`eval/_kleene.py::evaluate_bool`'s `ParamExpr` branch coerces via `bool(v)` unconditionally, and `check_expr_types` has no matching branch at all). Row 16's existing declared/scalar-type checks (`prop_type()`) still apply uniformly regardless of position, since they run on every `Prop` node the walk visits.

### Answer

Possibility 3. `Prop(ArithExpr, BoolExpr)`; `.prop()` returns the concrete `Prop` type (not the abstract `ArithExpr`) so mypy accepts it wherever `BoolExpr` is expected; `evaluate_bool` gained a `Prop` case reusing the existing `_evaluate_prop` helper, coercing via `bool(value)` — identical shape to the `ParamExpr` case immediately above it. `margin()` returns `None` for a bare `Prop` condition, matching a bare boolean param exactly (neither is `Compare`/`BoolOp`/`Not`-shaped).

### Reasoning

Exact match for an existing, real precedent — not a new inconsistency, and cheaper than inventing position-aware validation for one specific case while leaving the general one loose. `== True` usage remains fully valid and behaviorally identical (still builds the same `Compare` node via `ArithExpr.__eq__`), so this is strictly additive.

### Specification update

Folded into API.md's ArithExpr section (`.prop()`'s line).

---

## D-50 — `.freeze()`'s remaining five kinds (M9.5), and the unified variant-pruning rule

- Status: Resolved
- Date: 2026-07-25
- Spec section: API.md §Space — Structural Operations (`.freeze(values=None, **kw)`)
- Decided by: User (per-kind mechanism, confirmed ahead of implementation) + Agent (pruning-rule generalization and implementation details)

### Question

D-44 scoped choice/subset/permutation/struct/list out of `.freeze()`, flagging choice's structural pruning as "materially larger... better left to a future milestone." M9.5 closes this gap. The one genuinely open design question is choice's pruning: how does it generalize to a *lifted* choice (`.repeat()` of a `.choice()`, e.g. `memetic_pipeline`'s `pipeline`), where every instance shares one relocated `"[]."`-prefixed descendant template rather than having its own?

### Why the specification is insufficient

API.md's `.freeze()` row named the five container kinds only as a forward reference ("fixed by the same constraint-pin ... principle, generalized"); it never specified what "generalized" means once more than one instance of a choice discriminator can independently select a variant.

### Possibilities considered

1. **Never prune inside a list** (a future instance could always select any variant in principle). Correct but useless — defeats the point of pruning at all.
2. **Prune per-instance** (each frozen instance gets its own private view of reachable variants). Not implementable as stated: a lifted choice's variant descendants live at one shared `"[]."`-prefixed template (`resolve/_pipeline.py`'s list-handling branch calls `_relocate_choice_variants(f"{d.path}[]", f"{d.path}[].", ...)` once for the whole list, not once per instance) — there is no per-instance `ParamDef` to prune independently.
3. **Prune a variant iff it is selected by zero of the instances actually being frozen in this one `.freeze()` call**, computed once per list (aggregating across every instance in the given value), reusing exactly the top-level choice's own rule (there, "zero instances" trivially means "the one instance didn't pick it").

### Answer

Possibility 3, for both the top-level and lifted case, via one shared rule: compute the set of variants selected by *any* frozen instance of a given choice-or-list-of-choice param; prune every relocated descendant whose variant is not in that set. For a plain top-level choice there is exactly one instance, so this degenerates to "prune every variant except the one selected" (D-44's originally anticipated top-level behavior) with no special case in the implementation. For a lifted choice, `.freeze()` always receives the *complete* element list in one call (there is no partial-list freeze), so "every instance" is naturally already available in one place before any pruning decision is made — no cross-call state or multi-pass aggregation is needed.

`ChoiceDomain.variants` itself is left unnarrowed in both cases (nothing analogous to `lo == hi` exists for it — mirrors bool, which also has no domain-narrowing target); the semantic work is entirely carried by the `require` pin(s) plus the removal of now-permanently-unreachable descendant params. No `default` is set for choice: unlike custom (D-47), a choice param is always generative (weighted/chart-driven sampling), so no `SamplingError` guarantee is ever at stake, and a default would be a purely cosmetic addition with no corresponding need.

**Subset and permutation, by contrast, do get `default` set** (`default = value`, the same fixed list) — checked directly against the shipped code rather than assumed: `_narrow_or_pin`'s bool branch already sets `default` too (`replace(pd, default=value)`), so "every kind also gets `default`" is the actual, broader precedent — not "bool never sets it," which was an incorrect premise floated during implementation planning. Subset/permutation's own `.default()` validation (`resolve/_pipeline.py::_default_is_valid_subset`/`_default_is_valid_permutation`) accepts exactly the same full-list value shape `.freeze()` already validates via `validate/_validate.py::_domain_error_reason`'s existing `SubsetDomain`/`PermutationDomain` branches, so setting it costs nothing and matches the broader pattern.

**List sets `list_default` — except when its elements are choice-typed.** `list_default`'s own validation (`resolve/_pipeline.py::_validate_list_default_level`, run automatically during `space_from_ir`'s revalidation) treats it as a *complete nested-config value* — a payload-bearing variant there needs its full payload spelled out (`{"local_search": {"iters": 5}}`), not the bare discriminator string `.freeze()` itself accepts for a choice value (matching `_domain_error_reason`'s `ChoiceDomain` branch, which only ever checks the bare string). Since `.freeze()` on a list-of-choice is never given that payload, setting `list_default` to the bare-string sequence would fail this deeper validation — so it is left untouched for a choice-element list, mirroring choice's own no-`default` precedent one level up. Every other element kind's `list_default` is a complete, directly-checkable value (a flat scalar list, or a fully-specified struct/nested-list value), so it is set unconditionally there.

**A pre-existing keep-set bug, found and fixed during implementation.** `ops/_structural.py::_prune_to`'s (now `_apply_keep_set`'s) constraint-filter compared a constraint's `.params` paths directly against the pruning keep-set, which holds only *definition* paths. A per-instance `require`-pin on a `.repeat()` instance path (`"pipeline[0]"`) was therefore always misclassified as "referencing an excluded param" and silently dropped whenever a freeze call *also* triggered pruning (any choice or list-of-choice freeze) — the discriminator pins vanished, and the sampler could still legally draw a pruned variant's discriminator value with nothing left to reject it. Fixed by resolving each path to its *owning* `space.params` key first (`_governing_definition_path`, mirroring `validate/_validate.py::_lookup_param_shape`'s own three-way fallback: bare path, then `"[]"`-templated struct-lift form, then the direct-lift base with its trailing bracket stripped entirely — `_definition_path_of`'s blanket `"[]"`-substitution alone is wrong for a *direct* lift element, since `"pipeline[]"` is never a real key, only `"pipeline"` is). Applied to both the constraint filter and `_strip_anchor_keys`'s identical anchor-key check, which had the same latent gap.

The other four kinds' mechanisms: subset — a `require(contains(p,i))` / `require(~contains(p,i))` pin per declared item (reuses `Contains`); permutation — a `require(position_of(p,item)==k)` pin per position (reuses `PositionOf`); struct — pure fan-out, no new mechanism, recursing the same per-kind dispatch onto each given field's own path (subsumes nested struct/choice/list fields automatically); list — narrows `count` to the given value's literal length (raising if a pre-existing *literal* count doesn't match — the only place this is ever checked, since neither `validate()`'s lift-instance validation nor the list-default validator cross-check a literal count against a realized length) and (except for choice elements) sets `list_default`, then dispatches each element by `element_kind` — scalar/custom/bool via a per-instance `require(p[i]==v)` (uniform, including bool — no special-casing to avoid `Compare`; it is already proven safe via production use in choice-discriminator and custom pins), struct via the same fan-out rooted at the instance path, list via the same mechanism one level deeper (only the outermost `.repeat()` level's domain is ever narrowed; a nested level's own facts are a template shared across every outer row, not a per-instance fact).

### Reasoning

Possibility 3 is the only one of the three that is both implementable (no per-instance `ParamDef` exists to prune independently) and useful (it actually prunes dead structure whenever the given data supports it). It requires no new concept beyond what `.select()` already established for constraint/condition filtering and anchor strip/drop — `.freeze()`'s choice path reuses that machinery directly (factored out of `ops/_structural.py::_prune_to` into a shared `_apply_keep_set` helper) rather than reimplementing it, and it generalizes losslessly from the top-level case (one instance) to the lifted case (N instances) because both reduce to the identical "keep iff selected by at least one instance" test over the same relocated-path-prefix shape (a bare `"."`-prefix for a top-level choice, a `"[]."`-prefix for a lifted one — both produced by the same `resolve/_pipeline.py::_relocate_choice_variants`).

### Specification update

Folded into API.md's `.freeze` row (the `.freeze`'s per-kind mechanism paragraph, plus the anchors-under-structural-operations line noting choice's strip/drop exception), replacing the M9.5 forward reference.

---

## D-51 — `polars` as an optional extra (M10), and the missing-dependency error contract

- Status: Resolved
- Date: 2026-07-26
- Spec section: API.md §Dependencies; §Sampling and Generativity (`.sample()` signature)
- Decided by: User

### Question

Should `polars` be a hard core runtime dependency of `designspace` (as API.md's Dependencies section stated — "Core: `numpy`... `polars`..."), or an optional extra that only users of `.sample()`'s DataFrame output must install? If optional, what should `.sample()` do, and raise, when polars isn't installed?

### Why the specification is insufficient

This is not an ambiguity in API.md's text — the Dependencies section was unambiguous that polars was core. It is a deliberate, user-directed scope change to that already-clear text, recorded here per CLAUDE.md's rule that a decision changing the public dependency contract must be recorded even when directly instructed by the user, since it is not a routine implementation detail.

### Possibilities considered

1. **Keep polars core**, per the pre-M10 text. Simplest, but forces every consumer of `designspace` — including those who only need `sample_dicts()`/`sample_one()`/validation/serialization/structural ops — to install polars transitively, even though `sample_dicts` already exists specifically as a permanent, fully-functional no-polars sampling path (predates this milestone). Rejected per explicit user instruction.
2. **Optional `designspace[polars]` extra; `Space.sample()` lazily imports polars and raises a bare `ImportError` naming the extra when it's absent** — mirrors the Python ecosystem's own convention for optional dependencies (e.g. pandas' optional-engine imports) and the "name what's missing + name the remedy" messaging style API.md already uses for `capability_report()` ("param `topology`... has no unit embedding — register an adapter or use a sampling-based solver"). `sample_dicts`/`sample_one` are untouched — zero functional loss.
3. **Optional extra, but a new `DesignSpaceError` subclass** (e.g. `MissingDependencyError`) for the missing-polars case, keeping every raised error inside the library's own taxonomy. Rejected: the taxonomy (`ResolutionError`/`SamplingError`/`SerializationError`) is reserved for semantic findings about a *design space* — a missing package is an environment/packaging concern, not a design-space error, and inventing a subclass with exactly one call site and no reuse elsewhere in the error table adds public surface for no benefit over the standard-library convention.

### Answer

Possibility 2. `polars` moves from `Core:` to `Extras:` in API.md's Dependencies section (`designspace[polars]`, alongside the existing `designspace[pydantic]`). `Space.sample(n, seed=None, reject_soft=False)` is the only function in the library that imports polars, and it does so lazily inside the method body (`TYPE_CHECKING`-guarded at the module level so `mypy --strict` still checks the `pl.DataFrame` return type); a missing polars raises a plain `ImportError` reading `"space.sample() requires polars; install with `pip install designspace[polars]` (sample_dicts()/sample_one() work without it)"`.

### Reasoning

`sample_dicts`/`sample_one` already cover every sampling need without polars (a decision made before this milestone, not revisited here), so making polars optional costs the library nothing in capability — it only removes a forced transitive dependency for the (likely common) case of a consumer who never calls `.sample()`. A bare `ImportError` is the least-surprising choice for a Python user hitting a missing optional dependency and needs no addition to the exception taxonomy, which stays reserved for semantic design-space errors.

### Specification update

API.md's "Dependencies" section (moved `polars` from `Core:` to `Extras:`) and the `.sample()` signature line (parenthetical noting the extra); PLAN.md's M10 section (`**Build:**` line reworded from "polars becomes a core dependency" to describe the optional-extra wiring).

---

_Ledger tail._ D-1 through D-44 were resolved into `API.md` on and their entries removed here (preserved in git history); continue with D-52.
