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

## D-52 — `Encoding.target` returns `ParamDef`, and the consequent IR export

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer; §Protocols; §Space — Metaprogramming
- Decided by: User

### Question

`Encoding` is a protocol users implement, and three of its methods take a `ParamDef`. Should the protocol be stated at the IR level (`ParamDef` in, `ParamDef` out), which requires exporting `ParamDef` and several `Domain` classes from `designspace`, or at the builder level (`TypedParamExpr`), which exports nothing new?

### Why the specification is insufficient

API.md has never said which layer user-facing protocols bind to. `ParamType` (the other protocol users implement) touches no IR type, so it set no precedent.

### Possibilities considered

1. **Builder level.** `target()` returns a `TypedParamExpr` built with the already-exported view types (`ds.param(pd.path).real(0,1).repeat(3)`), and core converts. Exports nothing; gives builder-level domain validation free. But it needs a `def_from_param` inverse that does not exist (the un-exported half of `_emit`), and makes representation construction a builder round-trip rather than an IR rewrite.
2. **IR level, exporting `ParamDef`, `Chart`, and the domain classes an encoding must construct.** Direct, no new inverse, and the encoding reads `pd.chart`/`pd.domain` anyway.

### Answer

Possibility 2.

### Reasoning

The export is not new surface so much as an acknowledgement of surface that already exists: `Space.map_params(fn: Callable[[ParamDef], ParamDef])`, `ds.param_from_def(pd: ParamDef)`, and `ds.space_from_ir(params: ...ParamDef...)` have all been public since M8, and a user cannot type-annotate their own `map_params` callback without reaching into a non-`__all__` subpackage. M11 does not create that hole; it makes it unignorable, since `Encoding` has three methods taking the type. `ParamDef` is a frozen dataclass whose shape the frozen wire format already pins, so exporting it adds no compatibility surface beyond what `to_json` committed to at M7.

### Specification update

API.md §Protocols (`Encoding` in its IR-level shape); §The Representation Layer. `ParamDef`, `Chart`, and the domain classes join `__init__`'s exports at M11.

---

## D-53 — Path preservation, arity, and the two exclusions

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer
- Decided by: Agent

### Question

Which params may a derived representation encode, and what may the target look like?

### Why the specification is insufficient

The old text said only that "leaves may change shape", with no statement about paths, arity, or which params are eligible at all.

### Possibilities considered

1. **One source param → one target subtree** rooted at the same path. More expressive (heterogeneous targets), but gives up a checkable key-set law and is not closed under composition.
2. **One source param → one `ParamDef` at the same path.** Kind and shape may change; a lift is one key, so dimensionality is still unconstrained. Every canonical encoding — u-space, one-hot, stick-breaking, subset-as-bools, random keys, type bridges — is homogeneous and fits.

### Answer

Possibility 2, plus two eligibility rules. A param `p` is **encodable** iff no other key of `source.params` begins `f"{p}."` or `f"{p}[]."`, and **prop-excluded** if a `.repeat()` count or any `.prop()` reads it.

### Reasoning

The key-set law is only meaningful because `.params` is keyed by *definition* path: one-hot maps `algo` to a `ListDomain(count=3)` still keyed `algo`, with coordinates at instance paths that never enter `.params`. Verified against the shipped library — the key set is unchanged while the genotype dimension goes 1→3.

The encodability rule is forced by `_emit`, which relocates struct fields and choice payloads into separate flat entries that nothing reconnects. Without it a one-hot'd choice produces a *silently corrupt* target: `config/_flatten.py::_direct_children` takes the list branch and `algo.svm.C` becomes permanently unreachable, while `ops/_introspect.py::subspaces` keeps fabricating a variant condition from `ChoiceDomain`, and resolution does not catch it — `check_expr_types` type-checks `gt/lt/ge/le` but never `eq`. A *bare* choice has no descendants and stays encodable, which is right: it is semantically a categorical.

The prop exclusion generalizes what would otherwise be a count-only rule. On `vi_family`, `edge_weight`'s count is `Prop(topology, "n_edges")` and a constraint reads `topology.prop("is_connected")`; encoding `topology` dangles both, because `prop_type` requires a `CustomDomain`. Count dependencies are caught free, since `_list_count_deps` already walks `Prop`.

### Specification update

API.md §The Representation Layer ("Path and arity"); error table row 32.

---

## D-54 — Transport is total; nothing is dropped

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer ("Transport")
- Decided by: User

### Question

A condition or constraint over an encoded param no longer type-checks in the target. What happens to it?

### Why the specification is insufficient

The old representation layer was value-level only, so the question never arose.

### Possibilities considered

1. **Drop and report**, with a `strict=` flag to raise instead. Simple, but loses feasibility information and — for conditions — makes the target over-activate, which costs invertibility and makes the target's feasible set an *unsound* relaxation (it can reject configs the source accepts, when a transported constraint fires on a param the source considers inactive).
2. **Refuse to encode any param a condition or constraint mentions.** Sound but useless: bound-origin constraints reference nearly everything.
3. **Rewrite, three mechanisms deep, with an opaque fallback core synthesizes itself.**

### Answer

Possibility 3: leaf substitution via `decode_expr`, then optional per-node `rewrite`, then an opaque `ds.value` wrapper that core builds from `decode` and the source AST.

### Reasoning

Core can *always* synthesize the third rung — it knows the decode and the source expression — so transport is total and the drop case never arises. That removes `strict=`, the poison rule, and dropped conditions in one step; target activity therefore always matches source activity, which in turn removes both the invertibility loss and the relaxation unsoundness that dropping caused. What survives is a *quality* distinction, reported as `opaque_conditions`/`opaque_constraints`, since a structurally transported expression keeps margins and partial evaluation and an opaque one does not.

Two implementation facts this decision depends on, both verified against the shipped library. Expressions live in **four** stores, not two: a struct lift built from `ds.space(...).require(...)` leaves `Space.constraints` empty and puts the constraint on `ListDomain.element_constraints`, whose owning lift is itself non-encodable while carrying constraints over params that are encoded — left untouched it compares u-coordinates, and a genotype `{lo: 0.5, hi: 0.6}` is target-feasible while decoding to a source-infeasible `{lo: 50.5, hi: 15.85}`. And `Expr.params` **cannot drive the walk**: for `boxes.field("w").sum()` it reports `['boxes']`, never `boxes[].w`, so a `.params`-keyed walk passes the constraint through unchanged and the sum silently ranges `[0,3]` instead of `[3,300]`. `_vector_base` resolves the projection correctly and must be used.

### Specification update

API.md §The Representation Layer ("Transport"); the Representation conformance bullet.

---

## D-55 — Defaults and anchors under a representation

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer
- Decided by: Agent

### Question

`ParamDef.default` and `Space.anchors` hold phenotype values. What happens to them in a genotype target?

### Why the specification is insufficient

Silent; the question is new with the morphism.

### Answer

Encode them when the encoding supplies `encode`; otherwise drop and report. `represent()` validates the result itself rather than relying on the assembler.

### Reasoning

The assembler cannot be trusted here, and the failure modes differ by surface. Defaults get a *membership* check — carrying a phenotype default into a unit target raises row 21 loudly for a value outside `[0,1]` — but **not a semantic one**: a default of `1e-3` passes, because 0.001 lies inside `[0,1]`, and then decodes to ≈`1.007e-4`, silently meaning something else. Anchors get **no check at all** on the `space_from_ir` path, though the builder's `.anchor()` correctly raises row 22 — an asymmetry worth fixing on its own (M10.5 item 8) and worth not depending on meanwhile.

Anchors are also the concrete reason `invertible` is worth reporting rather than being an internal detail: anchors and historical observations are warm-start data, and seeding a solver with them *is* `rep.encode(config)`.

### Specification update

API.md §The Representation Layer ("Obligations"); PLAN.md M10.5 item 8.

---

## D-56 — Measure pushforward is a per-encoding declared capability

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer ("Obligations")
- Decided by: Agent

### Question

Should `decode(target.sample_one(seed))` be required to reproduce `source.sample_one()`'s distribution?

### Possibilities considered

1. **Universal law.** Clean, but it would forbid most useful encodings — one-hot under declared weights, naive stick-breaking, top-k subset repair are all non-preserving — and it is untestable in general for encodings core does not ship.
2. **Per-encoding, `hasattr`-declared**, with core guaranteeing it only where it can prove it.

### Answer

Possibility 2, following D-45's precedent for optional protocol members.

### Reasoning

A universal law conflates two contracts. `decode` totality is *structural*; measure equality is a *sampling* claim, and "sampling is declared measure, not search" — a solver proposing genotypes is not sampling the declared measure at all. Core can and does prove it for the induced chart representation, where `chart(u)` on `u ~ U[0,1]` *is* the declared measure; everywhere else the honest answer is that the encoding author knows and core does not.

### Specification update

API.md §The Representation Layer; §Protocols (`measure_preserving`).

---

## D-57 — Removing `transform`, `ParamTransform`, the `Encoding` registry, and `capability_report`

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer; §Protocols; §IR; §Conformance Laws; §Staging
- Decided by: User

### Question

The reworked layer supersedes four pieces of specified-but-unimplemented surface. Should they be removed outright?

### Why the specification is insufficient

Not a gap — a deliberate removal of stated surface, including one stated conformance law, recorded here because CLAUDE.md requires user approval before changing the public contract.

### Answer

Remove all four. `.transform`/`.inverse_transform` and `ParamTransform` are superseded by `Representation`; the `type_key`-keyed `Encoding` registry disappears because rules are plain callables; `capability_report()`/`Capabilities` are deleted. The Structure law "`transform`/`inverse_transform` round-trip when both leaf directions exist" is replaced by the Representation bullet, whose round-trip is deliberately **one-directional**.

### Reasoning

The value-level transform cannot answer the question the layer exists for — a solver needs the *space* it proposes from, not a dict-to-dict map. The registry existed only to key encodings by `type_key`; with `EncodingRule = Callable[[ParamDef], Encoding | None]` a consumer's dict is a three-line lambda, and "core never populates the registry" becomes trivially true because there is no registry.

`capability_report` deserves its own note: designspace cannot know what a solver supports, so the fail-fast message it was meant to produce belongs to the solver. Every fact it carried is already on the IR — `has_chart` is `pd.chart is not None`, `periodic` and `type_kind` are fields, `type_key` is on the domain's `ParamType`, `generative` is the existing `is_generative`. With `rep.target` an ordinary `Space`, negotiation is ordinary introspection. API.md's own Staging section already called it "sugar over introspection".

The replaced law is weaker in one direction by necessity: `encode(decode(g)) == g` cannot hold, because integer charts, quantized grids, one-hot ties, and random-key permutations are all many-to-one.

### Specification update

All four removed; §Conformance Laws Structure bullet rewritten and a Representation bullet added; §Staging drops `capability_report()`.

---

## D-58 — The induced chart representation's exact target

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer; §Charts
- Decided by: Agent

### Question

`space.represent()` with no rules is the induced representation. Which params does it touch, and what does each become?

### Answer

Every param carrying a chart **at its own level or at any element level of its `ListDomain` chain**, *excluding* any param a `.repeat()` count or `.prop()` reads. Each becomes `real(0,1)`, rewritten at the level the chart was found, with `periodic` mirrored.

### Reasoning

Three facts, each verified, each of which breaks a simpler formulation.

**"Chart-bearing" cannot mean `ParamDef.chart is not None`.** On a NAS-shaped space, charts live in three places: `n_layers` carries its own, `layers[].width` carries its own at a template key, and `dropout: real.repeat(3)` has **`chart is None`** with the chart in `ListDomain.element_chart`. The literal reading skips `dropout` entirely — dropping a three-real vector out of the genotype, the opposite of what anyone wants.

**Count-referenced params must be excluded.** `_check_count_type_node` raises row 12 unless a count's referenced param is `integer`; integers are chart-bearing, so the naive induced representation fails to *construct* on `solver_portfolio`, `delivery_routes`, `memetic_pipeline`, and API.md's own Quick Example. A count is load-bearing structure and is not droppable, and row 12 may not be weakened, so exclusion is the only remaining option.

**Periodic must be mirrored.** There is no `PeriodicChart`; `periodic` is a validation fact only, and the chart is a plain uniform, so `from_unit(1.0)` yields `hi` — which validates as **invalid**. Without the mirror, `decode` is not total.

Nested lifts and quantized elements need no special case: depth-2 lifts put the chart innermost and `rebuild_list_domain_charts` recurses correctly.

### Specification update

API.md §The Representation Layer ("The induced chart representation"); §Charts (Periodicity).

---

## D-59 — The `to_unit` asymmetry between integers and quantized reals

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Charts
- Decided by: Agent

### Question

`to_unit` returns a representative of a cell for both cell-valued kinds, but integers return the interval **midpoint** and quantized reals the **left edge**. Align them, or document?

### Why the specification is insufficient

API.md states the midpoint rule for integers and says nothing about quantized reals.

### Answer

Document the difference; do not align.

### Reasoning

Both satisfy `from_unit(to_unit(v)) == v`, which is the only law either owes, so neither is wrong. Aligning would move a shipped round-trip for no semantic gain, and `encode` should not inherit an undocumented asymmetry silently — naming it is the cheaper fix.

### Specification update

API.md §Charts ("All charts are static").

---

## D-60 — Structural morphisms are not core

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Out of Scope; §The Representation Layer ("Two tiers")
- Decided by: User

### Question

Should core ship a morphism that flattens a hierarchical space into a flat table (the ConfigSpace shape), relaxes conditions away for a fixed-dimension target, or pads a dynamic lift to fixed width?

### Answer

No. All three are writable as a *supplied* `Representation`; core ships none.

### Reasoning

designspace's IR **is** already the flattening — `_emit` relocates variant payloads to `optimizer.adam.beta1` gated on the discriminator, which is a flat param table plus conditions. So there is nothing to invent, and what blocks the derived tier is merely mechanical: designspace derives structure from path prefixes where ConfigSpace uses opaque flat names.

Shipping it anyway would make core endorse flattening as *the* answer to hierarchy, which contradicts both "no opinionated metrics" and the Representation Model's insistence that chosen genotypes come from consumers. Hierarchy is a modeling decision to be handled explicitly, not circumvented.

Relaxation and padding are additionally *chosen* rather than induced. Relaxation's `decode` needs no policy (it prunes by re-deriving source activity), but its `encode` must put something in the slot of a source-inactive param, and "inactive means absent" is a stated principle no filler respects — ConfigSpace uses NaN, SMAC imputes defaults, and core cannot pick. Padding needs a `max_count` and a convention that interacts with the element charts.

What core owes them instead: supplied-tier construction, `then`, `check()`, and a guide recipe.

### Specification update

API.md §Out of Scope (new bullet); §The Representation Layer ("Two tiers").

---

## D-61 — Two tiers, and which laws bind each

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer ("Two tiers")
- Decided by: User

### Question

If core does not ship structural morphisms, how does a consumer write one — and what does core guarantee about it?

### Answer

Two tiers. **Derived** (`space.represent(*rules)`) is built mechanically from per-param encodings and carries every law. **Supplied** (`Representation(...)` constructed directly) takes a target `Space` and both value maps from the user and carries **no structural guarantee, no arity or path law**. Core supplies the type, `then`, and `check()`.

### Reasoning

The escape hatch has to exist for D-60 to be tenable — refusing to ship flattening while also making it unwritable would just be a refusal. Every ingredient is already public (`ds.space_from_ir`, `flatten`/`unflatten`, `param_activity`), so the supplied tier costs core a constructor and a checker.

`check()` earns its place because a supplied morphism otherwise has no way to be shown sound, and core already owns every ingredient of the laws. It turns the conformance suite into a user-facing tool.

One clarification belongs in the spec because the name misleads: the arity law compares **definition-path keys**, so it does not constrain genotype dimensionality at all — a lift is one key.

### Specification update

API.md §The Representation Layer ("Two tiers", "Path and arity").

---

## D-62 — Decode totality is domain membership

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Conformance Laws (Representation)
- Decided by: Agent

### Question

"Every valid genotype decodes to a valid phenotype" — valid by which check?

### Answer

`source.validate(rep.decode(g)).param_errors == ()`, i.e. domain membership. **Not** `ValidationResult.valid`.

### Reasoning

`valid` folds in constraint feasibility. Stating the law with it would make the law false by construction wherever a constraint is opaque, since an opaque constraint is enforced through decode rather than mirrored structurally — measured directly: `param_errors == ()` while `valid is False`. Feasibility is a separate law with its own statement.

Two implementation notes the law depends on. `decode` must **normalize instance paths to definition templates** (`stops[0].dwell` → `stops[].dwell`) before looking up an encoding; without it `delivery_routes` decodes 0/200. And the law was validated before being written: a throwaway induced representation decodes **200/200** on `flat_hpo`, `firmware_buffers`, `delivery_routes`, `solver_portfolio`, `memetic_pipeline`, and `wind_farm_grid` — covering dynamic lifts, struct lifts, lifted choices, subsets, and expression-bounded params.

### Specification update

API.md §Conformance Laws (Representation bullet).

---

## D-63 — The repair obligation, and `prop_expr`

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §The Representation Layer ("Obligations"); §Protocols
- Decided by: Agent

### Question

What must an encoding do when the phenotype domain carries an invariant the genotype cannot express?

### Answer

`decode` must **repair**, or the genotype must be chosen so it cannot represent an invalid value. Separately, `Encoding.prop_expr` maps a phenotype property to a genotype expression, which is what lets a bridged custom type restore a `.prop()`-driven lift count.

### Reasoning

Encodings divide cleanly, and the division is measurable. Charts, stick-breaking, random keys, and argmax are surjective onto their domains by construction — random-key permutation decoding is 500/500 valid. A bool vector over `subset(4, min_size=2, max_size=3)` is **10/16**, and an adjacency matrix is not a connected graph. Where the missing invariant is part of the type's `validate`, the loss breaks *decode totality* — the one law that holds unconditionally — rather than merely costing feasibility, and it does so silently: the target samples happily and produces invalid phenotypes.

`prop_expr` is what makes a bridge buildable at all rather than merely conceivable. It also depends on a resolver fix: the `.repeat()` count check types *leaves*, so `sum(matrix)` is refused as a count even though the same aggregate type-checks and evaluates inside a constraint, is integer-valued, and statically references exactly its lift. That check becomes result-typed in M10.5.

### Specification update

API.md §The Representation Layer ("Obligations"); §Protocols (`prop_expr`); PLAN.md M10.5 item 5.

---

## D-64 — The chart-application expression node

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Expressions
- Decided by: User

### Question

Leaf substitution needs to express "apply this param's chart to a unit coordinate" inside a transported expression. How?

### Possibilities considered

1. **Desugar to arithmetic.** Works for uniform (`lo + u·(hi−lo)`) and power charts with today's operators, but log and logit need `exp` and integer/quantized need `floor` — so it covers a minority of cases.
2. **A node that applies the referenced param's own chart.** Wrong: in the target that param is `real(0,1)` with a *uniform* chart, not the source's.
3. **A node carrying the source chart's declaration** — domain, prior, quantization.

### Answer

Possibility 3, vector-polymorphic (element-wise over a lift or projection).

### Reasoning

The node is additive to a frozen format, so it needs justification beyond convenience: the chart is *already* a first-class core concept — static, per-param, serialized, named in "priors are coordinate systems" — so making it expressible exposes something that exists rather than inventing semantics. The spec it carries is exactly what `identity/_ir_codec.py::encode_param` already serializes, so the codec is reuse.

Vector-polymorphism is forced by the projection case: `sum(field(boxes,'w'))` must become `sum(chart(field(boxes,'w')))`, which only type-checks if the node maps element-wise.

Static analysis is unaffected (the node references exactly its operand) and bound envelopes get *easier*, since its hull is the source domain.

### Specification update

API.md §Expressions; §Out of Scope (the language is closed at chart + `ds.value`).

---

## D-65 — `ds.value`: one dual-typed opaque node

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Expressions; §Support Types; §Constraints
- Decided by: User

### Question

Constraints that no expression language should be expected to cover — a simulator's verdict, graph connectivity, a physical quantity computed by a real algorithm over several ordinary params — have no representation today. What should the escape hatch look like?

### Why the specification is insufficient

`forbid()` requires a `BoolExpr`, and the only opaque predicates are *per-param*: `ParamType.validate` and the `.custom(sampler, validator)` shorthand.

### Possibilities considered

1. **A boolean-only `ds.predicate`.** Simplest, but throws away margins for quantities that have them.
2. **Separate predicate and scalar nodes.** Two nodes where the codebase already has a dual-typed precedent.
3. **One dual-typed node with a declared `returns`**, modelled on `Prop`.

### Answer

Possibility 3. `ds.value(fn, *operands, returns=type)`, `returns ∈ {int, float, bool, str}`, operands passed positionally as expressions, `fn` called with exactly those values and never the config.

### Reasoning

`Prop` is already `class Prop(ArithExpr, BoolExpr)` with a declared scalar type, so one node reuses its evaluation, margin, and dual-typing paths, and `.prop()` becomes its ergonomic special case — *one custom param, named property* versus *any operands, arbitrary function*.

This is not a new capability class. `.prop()` is already **grey-box**: `prop("n") > 3` yields `margin = 4.0` (opaque extraction, structural comparison) while `prop("ok")` yields `None`. Arbitrary Python already decides feasibility today; it just has to be wrapped in a custom type and can only see one param. That disposes of the "escape hatch opens the floodgates" objection — the floodgate is open behind an awkward door — and the wart it removes is real: a physical constraint over ordinary reals currently forces the author to invent a sham `ParamType`.

Two design points earn their specificity. **Positional expression operands** keep `.if_inactive()` composable inside them, which matters because an opaque node otherwise has no escape hatch for an inactive operand. And **calling `fn` with exactly the operand values, never the config**, is what makes the reference set trustworthy: an undeclared read raises rather than reading silently. The asymmetry is worth documenting — under-declaring fails loudly, over-declaring weakens *silently*, since an ignored operand going inactive still makes the node Unknown and the constraint inapplicable.

### Specification update

API.md §Expressions (`ds.value`, Kleene rule 1); §Support Types; §Constraints (the white/grey/black table); §Identity (non-serializable set); error table row 30.

---

## D-66 — The expression language is closed at two nodes

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Out of Scope
- Decided by: User

### Question

Exact constraint transport is unbounded — one-hot wants `argmax`, log charts want `exp`, integers want `floor`, graphs want reachability. Where does the language stop growing?

### Answer

At chart application and `ds.value`. The pair is categorically exhaustive: anything structurally expressible goes through the language, anything else through the opaque leaf, and there is no third category.

### Reasoning

An earlier framing — "exactly one node, ever" — was an arbitrary line the first hard case would have argued against. This one has a reason behind it, which is what makes it holdable: the two nodes are not two features but two *kinds* of answer, and admitting the second removes the pressure that would otherwise produce a third, fourth, and fifth.

It also settles what a solver gets. Structurally transported constraints are white-box and keep margins and partial evaluation; opaque ones are correct but rejection-only. The reason to prefer the former is **not** solver consumption — with a grey-box objective nothing is handing constraints to a MIP or CP solver anyway, and constrained CMA-ES wants smooth constraints a mixed conditional space does not supply — but that margins, `evaluate_partial`, `remaining_domain` narrowing, and bound-origin tightening are all *designspace's own* machinery and all run on structure.

### Specification update

API.md §Out of Scope; §Constraints (white/grey/black); §Expressions.

---

## D-67 — `.if_inactive()` and the provenance of Unknown

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Expressions (Kleene rule 5)
- Decided by: Agent

### Question

`.if_inactive()` coalesces Unknown to a fallback. Unknown has three sources — inactivity, emptiness (`min`/`max` over an active empty lift), and, in partial evaluation, an unset operand. Which does it eat?

### Why the specification is insufficient

Rule 5 already answers half of it: "coalesces inactivity only and never eats pending". The implementation **contradicts** that, which is a bug rather than a decision. The *emptiness* half is a genuine gap — the spec is silent.

### Answer

Inactivity only. Pending and emptiness both propagate.

### Reasoning

The pending half is a shipped violation of a stated law, with a measurable consequence: on a config where a lift is *active* and only its elements are unset — no inactivity anywhere — `bufs.sum().if_inactive(0) <= 10` reports `satisfied=True, margin=10.0`, while the unguarded form correctly reports `satisfied=None` and the same space is infeasible once the elements land. A driver loop prunes on a false conclusion.

Its provenance is worth recording, because it is a process failure rather than a coding one. `eval/_kleene.py`'s M2-era module docstring says plainly: "M2 has no partial-config API yet (M6), so there is no separate 'pending' state to confuse it with (rule 5 becomes meaningful only once one exists)". M6 shipped that API; nobody returned. The comment predicted the exact bug.

Emptiness is decided the same way for consistency and for the method's name: an active empty lift is *active*, and silently turning an undefined `max([])` into the fallback is a poor default. An author who wants an empty lift to contribute a value can say so.

**Rule 5 had no conformance test.** It is stated in the Kleene prose but never named in the Conformance Laws list, which is what laws-first testing follows — `if_inactive` has tests (both M2-era) and the evaluable/pending partition has one, and the bug lived in the intersection neither reached. The Kleene law bullet now names Unknown provenance explicitly, and the list should be audited against the prose more broadly.

### Specification update

API.md §Expressions (rule 5 rewritten); §Conformance Laws (Kleene bullet gains the provenance law); PLAN.md M10.5 item 1.

---

## D-68 — Index expressions: negative admitted, `ArithExpr` refused, static out-of-range an error

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Expressions; §Out of Scope
- Decided by: User

### Question

Instance paths are legal in expressions and an out-of-range index makes the leaf inactive. Should negative indices be admitted? Arithmetic ones? And should a statically provable out-of-range index stay inactive?

### Answer

Negative indices are admitted. `ArithExpr` indices stay excluded. A statically provable out-of-range index becomes a resolution error.

### Reasoning

**Negative indexing** is not sugar. For a static count it is convenience; for a *dynamic* count it is the only way to name the last element, which is currently inexpressible and which the corpus already wants (`delivery_routes`' final stop, `memetic_pipeline`'s final op). It does not open the door the spec closes: `x[-1]` indexes by the lift's own realized length, so the expression still statically references exactly that lift and `dependency_graph`, `topological_order`, and the bound envelopes are untouched. Out-of-range already means inactive, so `x[-1]` on an empty lift falls out of existing semantics with no new rule.

**`ArithExpr` indexing** stays excluded, but the spec's stated reason was wrong. `x[n_layers - 1]` is not the relational join `islands[edges[k].src]` API.md cites. The real cost is **loss of static dependency analysis**: the referenced element is unknown until `k` is assigned, so the expression must conservatively reference the whole lift, degrading `remaining_domain`'s one-unset-operand reducer, `dependency_graph`, and the bound envelopes — machinery M5 and M6 already shipped and that laws depend on. For a static count the case is already expressible by unrolling, which is exactly what the metaprogramming surface exists for.

**Static out-of-range** is a silent no-op today: `repeat(3)` with `require(y[7] > 0.99)` resolves clean and makes `is_feasible` true for every config, because `_is_declared` only checks that the base lift exists. The Unknown rule itself is right, and for the stated reason — a lift can be dynamic, so there is generally no length to check against and an out-of-range leaf must not reject — but applying it where the length *is* statically known is a leak, not a policy.

A related gap surfaced while probing and is fixed alongside: nested and mixed instance indexing (`g[0][1]`, `layers[2].act[1]`) fails today because `_is_declared`/`_resolve_entry` strip a single bracket group, though the path grammar parses both.

### Specification update

API.md §Expressions; §Out of Scope (value-dependent-indexing bullet rewritten); error table row 29; PLAN.md M10.5 items 2–4.

---

## D-69 — Sampling diagnostics report the unconditioned measure

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Sampling and Generativity (Sampling diagnostics); §IR
- Decided by: User

### Question

Kleene rule 4 makes an unevaluable constraint *inapplicable*, i.e. accepted. That is permissive, and silent. Should the rule change, and if not, how does a user find out?

### Answer

The rule stays. Add `.sampling_report(n, seed)`, which draws the **unconditioned** measure and reports per-constraint applicability and satisfaction plus per-param activity. `satisfied` is conditioned on **applicability**, not on all draws.

### Reasoning

The rule is right: Unknown → violated would over-constrain every conditional space, and the language already ships both escape hatches — `is_active()` for reasoning about structure, `.if_inactive(v)` for coalescing a value. The gap is **observability, not semantics**. A textbook "total memory ≤ budget" over optional buffers silently stops enforcing across two thirds of its space: measured, `a + b + c <= 100` with `c` optional is applicable in **36%** of draws and reports `is_feasible → True` for `a + b = 128`, while the `.if_inactive(0)` form is applicable in 100% and correctly rejects.

It must draw the unconditioned measure, because `sample()` returns the post-rejection distribution — precisely the one in which this is invisible. The same surface exposes the dynamic-count funnel, which is *correct-by-spec* and must be documented rather than fixed: with `.repeat(ds.param("n"))` and `require(x[2] > 0.99)`, the constraint is inapplicable whenever `n ≤ 2`, so rejection accepts those draws unconditionally and **96.3%** of accepted configs concentrate on `n ≤ 2` (analytically `0.2/0.208`). Changing that would mean `require` no longer conditions the declared measure.

Conditioning `satisfied` on applicability is the one design detail that decides whether the report is useful: otherwise "rarely relevant" and "usually violated" collapse into the same number, and that is the distinction the whole surface exists to draw.

It reports; it never repairs, reweights, or suggests — which is what keeps it clear of the penalty-policy exclusion.

### Specification update

API.md §Sampling and Generativity (new subsection); §IR (`SamplingReport`, `ConstraintReport`); PLAN.md M10.6.

---

## D-70 — The fixed leaf layout: where config ↔ positional vector lives

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Config Utilities ("The fixed leaf layout")
- Decided by: User

### Question

A solver emits a positional container — CMA-ES a 1-D `ndarray`. Converting a genotype config to that container and back is somebody's job. Whose?

### Why the specification is insufficient

The spec covers phenotype ↔ genotype (`Representation`) and config ↔ flat dict (`flatten`/`unflatten`), but never flat dict ↔ ordered vector. Out of Scope excludes "vectorization", which reads as though the whole question were settled — but that bullet is about *chosen* genotypes, and a positional layout is not chosen.

### Possibilities considered

1. **Entirely the adapter's.** Core ships nothing; each adapter derives the layout from `flatten`.
2. **Entirely core's** — `to_vector`/`from_vector` on `Space`. Convenient, but commits core to dtype, shape, and batch conventions that belong to the solver, and drifts toward the vectorization the scope line excludes.
3. **Split: core owns the layout, the consumer owns the packing.**

### Answer

Possibility 3. `Space.coordinate_paths()` returns the ordered leaf instance paths excluding lift-length bookkeeping, and `unflatten` gains a static-count fallback so the reverse needs no bookkeeping re-injection. Packing into any particular container stays with the consumer.

### Reasoning

Possibility 1 was tested rather than assumed, and it fails. `flatten` interleaves structural bookkeeping with coordinates, and the two are not distinguishable by key shape: for `real.repeat(2,3)` it emits `x` as the outer count, `x[0]` as an *inner count*, and `x[0][0]` as a coordinate; for a struct lift, `a[0].b` is a count and `a[0].b[0]` a coordinate. Telling them apart means walking the `ListDomain` chain one bracket group at a time. A first attempt written directly against the public surface — by someone who had spent a session in this codebase — classified a scalar lift's elements as bookkeeping, because stripping the index maps an element to its owning lift, which *is* a list. The round trip returned a config that **validated** and was not the input. Silent, and exactly the failure mode this library already fails in too often.

Possibility 2 goes too far the other way: dtype, 1-D versus batch, and the solver's own conventions are not core's to guess, and shipping them would make the scope line meaningless.

The split holds because the layout is **induced**. Its order is `flatten`'s, which is already the DataFrame column order; which keys are coordinates is a structural fact about the space. Nothing is chosen, which is what distinguishes it from one-hot or padding.

Two conditions are kept deliberately separate because they fail differently. A **fixed layout** needs static counts and no conditions — either makes the key set config-dependent, so no positional layout exists at all, and both are errors rather than a silently config-specific answer. **Numeric packability** is a different question: `subset` and `permutation` leaves have a stable key but a variable-length list value, and `categorical`/`ordinal` are scalar but not numeric. Those still appear in `coordinate_paths()` — they are real coordinates — and a caller packing floats fails on them at the point of conversion, which is where the error means something. A genotype built for a real-vector solver satisfies both by construction; that is what makes it one.

### Specification update

API.md §Config Utilities (`coordinate_paths`, "The fixed leaf layout", the `unflatten` fallback); error table row 33; PLAN.md M10.7.

---

_Ledger tail._ D-1 through D-44 were resolved into `API.md` and their entries removed here (preserved in git history); continue with D-71.
