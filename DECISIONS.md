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

_Ledger tail._ D-1 through D-44 were resolved into `API.md` on and their entries removed here (preserved in git history); continue with D-50.
