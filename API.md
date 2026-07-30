# designspace specification

A Python library for declaratively defining (algorithm) design spaces using a chainable, polars-like expression API.

The library separates **space definition** (what a valid configuration looks like) from **search strategy** (how to explore it).

```python
import designspace as ds
```

---

## Representation Model

Configs are **phenotypes**: values in domain units, legible to the expert who wrote the space. A permutation of job names, a temperature in °C, a Cholesky factor — never an index vector or a bitstring.

A **genotype is a `Space`**, and a **`Representation`** is the `Space → Space` morphism between them, carrying a value-level pair. **Charts** are the canonical genotype for generative primitives, *induced* from phenotype declarations (bounds + prior) rather than chosen; every other genotype is an **Encoding** supplied by a consumer or type author. **Operators act on genotypes** — mutation, crossover, neighborhoods, distances, kernels — and are therefore out of scope by construction.

Everything below is a consequence of this split.

## Design Principles

**Everything is data, and everything is constructible.** Constraints, conditions, choice topology, and dependency structure are inspectable ASTs. The IR is bidirectional: spaces can be rebuilt from rewritten IR.

**No opinionated metrics.** Distance, encoding, and vectorization are consumer-specific. The library provides the morphism machinery and sockets; consumers supply semantics.

**Priors are coordinate systems.** Every generative param resolves to a *chart*: a monotone map `[0,1] → domain` defining both sampling and solver geometry. There is no separate transform concept for priors.

**Inactive means absent.** A param that is not active does not appear in a config dict. Never `None`, never `NaN`. (Columnar containers necessarily use `null`; the principle governs dict configs.)

**Sampling is declared measure, not search.** The reference sampler interprets the priors the expert declared. It is not an optimizer and ships no search operators.

---

## Quick Example

```python
space = ds.space(
    ds.param("optimizer").choice(
        "sgd",
        adam=ds.space(
            ds.param("beta1").real(0.5, 0.999),
            ds.param("beta2").real(0.9, 0.9999),
        ),
    ),
    ds.param("lr").real(1e-5, 1.0).log_scale(),
    ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
    ds.param("n_layers").integer(1, 8),
    ds.param("layers").space(
        ds.param("width").integer(16, 1024).log_scale(),
        ds.param("activation").categorical("relu", "gelu", "silu"),
    ).repeat(ds.param("n_layers")),
).forbid(
    ds.param("lr") > 0.1,
).encourage(
    ds.param("layers").field("width").sum() <= 4096,
    tags=("budget",),
)

config = space.sample_one(seed=0)
result = space.validate(config)
df = space.sample(1000, seed=0)
```

---

## Construction

| Function | Returns | Purpose |
|---|---|---|
| `ds.param(name)` | `FreshParamExpr` | Define or reference a parameter |
| `ds.space(*exprs)` | `Space` | Collect params into a space |

`FreshParamExpr` is a `ParamExpr` carrying the type methods; each type method narrows to a type-specific view (see *Builder view types* under Parameter Types). `ParamExpr` remains the base type of every param object.

Names may not contain `.`, `[`, or `]` (reserved by the path grammar). Declaration order is **significant**: it is preserved through composition, aligns `.prior(weights=...)`, and enters `fingerprint()`.

---

## Parameter Types

Each `ds.param(name)` in definition position takes **exactly one** type method. This is enforced two ways: the builder view types (below) make a second type method a static type error, and resolution rejects any definition that carries more than one type however it was built (error table row 2).

### Builder view types

The builder is statically typed so that an IDE offers only the methods valid at each step, and choosing a second type is caught before resolution.

- `ParamExpr` is the **base** type. It is an `ArithExpr`/`BoolExpr`/`VectorExpr` (usable in reference position) and carries the identity-, domain-, and lift-level modifiers, but **no** type methods. `isinstance(x, ParamExpr)` holds for every param object, in reference or definition position.
- `ds.param(name)` returns a **`FreshParamExpr`** — a `ParamExpr` that additionally carries the type methods. It is the only object on which a type is chosen.
- Each type method returns a **type-specific view**, a subclass of `ParamExpr`: `.real → RealParamExpr`, `.integer → IntegerParamExpr`, `.bool → BoolParamExpr`, `.categorical → CategoricalParamExpr`, `.ordinal → OrdinalParamExpr`, `.subset → SubsetParamExpr`, `.permutation → PermutationParamExpr`, `.choice → ChoiceParamExpr`, `.space → StructParamExpr`. `.repeat()`, available on any typed view (a type is required before a lift), returns a **`ListParamExpr`**, which itself re-offers `.repeat()` for nested lifts. Two kinds of method are genuinely narrowed onto the views and **omitted** from the views to which they do not apply: the **type methods** (removed from every view — so `ds.param("x").real(0, 1).bool()` is a static type error), and the **domain-level modifiers** `.log_scale()`/`.quantized()` (present only on `RealParamExpr`/`IntegerParamExpr` — so `ds.param("x").categorical(...).log_scale()` is a static type error). The **query and aggregate methods** — `.contains()`/`.size()`/`.sum_over()`/`.position_of()`, `.field()`, `.length()`, and the vector aggregates (`.sum()`/`.min()`/`.max()`/`.count_of()`/`.is_sorted()`/`.distinct()`) — are **not** narrowed: they live on the base `ParamExpr` (which *is* a `VectorExpr`, per above), because they are used in *reference* position, where the object is always the `FreshParamExpr` returned by `ds.param(name)`, never a definition-position view. Their type-correctness is a *runtime* law — a `.contains()` on a permutation, a `.field()` on a non-struct lift, or `is_sorted` past depth 1 raise at resolution (rows 18, 6, 24) — not a static view restriction. `BoolParamExpr` is additionally a `BoolExpr` (a boolean param is usable directly as a condition).

The view types are a **build-layer** convenience: they add no state beyond `ParamExpr`, have no serialized footprint, and do not appear in the IR — `ParamDef.type_kind` remains a string (see IR), and resolution and every downstream layer read `ParamDef`, unaffected. Choosing a second type still raises the path-named resolution error (row 2) for any definition that reaches resolution, so the law holds for programmatically-constructed definitions as well as fluent ones.

### Scalar

| Method | Value | Notes |
|---|---|---|
| `.real(lo, hi, periodic=False)` | `float` | Bounds inclusive; `lo == hi` legal (constant); `lo > hi` is a resolution error. Bounds accept `ArithExpr` — sugar; see *Expression bounds are sugar*. `periodic=True` makes the domain half-open `[lo, hi)` with `hi ≡ lo`; `hi` itself is then invalid. |
| `.integer(lo, hi)` | `int` | Bounds inclusive. Bounds accept `ArithExpr` — sugar; see *Expression bounds are sugar*. |
| `.categorical(*values)` | `Any` | Unordered. Only `==`, `!=`, `.is_in()`. Mixed types allowed; declared values must be distinct (type-tagged equality) and may not share a string image. |
| `.ordinal(*values)` | `Any` | Ordered by declaration position. Comparison yes, arithmetic no. Values must be distinct. Single-value ordinals are legal (constant). |
| `.bool()` | `bool` | Usable directly as `BoolExpr`. Strict — `1` and `"true"` are invalid. |

### Combinatorial

| Method | Value | Notes |
|---|---|---|
| `.subset(items, min_size=0, max_size=None)` | `list` | Set semantics: order irrelevant, no duplicates. Items must be distinct. |
| `.permutation(items)` | `list` | All items, any order. Items must be distinct. `.prior()` unsupported; sampling is uniform shuffle. Constraints via `.position_of()`. |

### Structural

| Method | Value | Notes |
|---|---|---|
| `.choice(*bare, *tuples, **keyword)` | see below | ≥1 variant (single variant = constant discriminator). Variant names are unique **within the choice** and obey the name-character rules regardless of syntactic route (bare, tuple, keyword, or `**splat`). |
| `.space(*exprs)` / `.space(prebuilt: Space)` | `dict` | Struct-valued param: unconditionally-present grouping under a namespace. Per-element constraints on repeated structs require the prebuilt-`Space` form (the inline form has nowhere to hang a `.forbid`). |

Choice accepts three interchangeable variant forms:

```python
ds.param("algo").choice(
    "linear",                                                  # bare: parameterless
    ("svm-rbf", ds.space(ds.param("gamma").real(1e-5, 10.0))), # tuple: arbitrary name (path-safe chars only)
    ("fast", None),                                            # tuple + None: same as bare
    mlp=ds.space(ds.param("depth").integer(1, 5)),             # keyword: identifiers only
)
```

Choice values are **self-contained** and nested under the param:

```python
{"algo": "linear"}                          # bare variant: plain string
{"algo": {"svm-rbf": {"gamma": 0.1}}}       # parameterized variant: single-key dict
```

Variant names never occupy the parent scope; two choices in one scope may both declare a variant `"fast"`.

### Program

| Method | Value | Notes |
|---|---|---|
| `.symbolic(signature, primitives, max_depth, validators=None, sampler=None)` | `{"ast", "source"}` | Structured expression trees. Variables auto-derived from `signature.args`. **Non-generative** (no reference sampler; tree genomes are genotypes — solver territory). `sampler=` opts in a generator (non-serializable). `validators` are callables over the AST. |
| `.code(signature, description="", constraints=None, examples=None, validators=None)` | `{"source": str}` | Freeform source. **Non-generative.** `validators` are callables over the source string. |

### Extension

| Method | Notes |
|---|---|
| `.custom(param_type: ParamType)` | Full protocol. Serializable, constraint-integrated via `.prop()`. |
| `.custom(sampler, validator)` | Callback shorthand. **Not serializable.** |

---

## Modifiers and Layering

Modifiers are chainable and immutable — each returns a new expression. They belong to two layers:

**Domain-level** — describe the element's domain and measure:

| Modifier | Applies to | Notes |
|---|---|---|
| `.prior(dist)` | real, integer | Any object satisfying `Prior` (see Charts). |
| `.prior(weights=[...])` | categorical, ordinal, bool, **choice** | Non-negative, not all zero, aligned to declaration order. Bool: `[False_w, True_w]`. |
| `.prior(weights=[...])` | subset | **Independent inclusion probabilities in `[0,1]`** per item. Absent `.prior()`, each item defaults to `0.5` (the maximum-entropy Bernoulli). Sampling: independent Bernoullis + rejection on size bounds; realized marginals under active size bounds deliberately differ from the declared values. |
| `.log_scale()` | real, integer | Sugar for `.prior(ds.Log())`; participates in prior last-write-wins. Requires `lo > 0`. |
| `.quantized(step=None, factor=None, include_hi=False)` | real, integer | Linear grid `lo, lo+step, …` or geometric grid `lo, lo·f, lo·f², …` (`factor > 1`); exactly one of `step`/`factor`. See Charts for measure and tolerance. |
| `.default(value)` | all | **Element default** when applied before a lift. Validated against the domain at resolution. |

**Identity-level** — describe the param as a whole; they bind to the outer param regardless of position, but writing them before a `.repeat()` when they concern the list is a resolution error rather than a silent rebind:

| Modifier | Notes |
|---|---|
| `.when(condition)` | Multiple calls ANDed. Presence semantics (see Expressions). |
| `.tag(*tags)` | Accumulates. Empty string rejected. |
| `.meta(mapping=None, **kwargs)` | Merges; last-write-wins per key. Values may be any JSON-serializable value — scalars, lists, or nested dicts (matching error row 23); each scalar leaf is type-tagged recursively in the fingerprint, the same codec as `default`. Constraint-level `meta=` (on `.forbid`/`.require`/`.encourage`/`.discourage`) follows the identical rule. |
| `.default(value)` | **List default** when applied after a lift: legal only for static counts; length must match; mutually exclusive with element defaults on the same param. |

**The lift.** `.repeat(count)` closes the element definition: everything left of it defines the element; everything right applies to the list.

```python
ds.param("dropout").real(0.0, 0.6).log_scale().repeat(4)          # List(Float64)
ds.param("layers").space(...).repeat(ds.param("n_layers"))        # List(Struct)
ds.param("mask").bool().repeat(8).repeat(8)                       # List(List(Boolean)) — legal
ds.param("grid").real(0.0, 1.0).repeat(2, 3)                      # variadic sugar: shape (2, 3)
ds.param("pipeline").choice(...).repeat(n)                        # heterogeneous list — legal
```

- `count: int | ArithExpr`, resolution-checked to be integer-typed (row 12) against a **closed, resolution-time calculus** (D-72): int literals, integer params, `ds.count`/`.size()`/`.length()`/`.position_of()`/`.count_of()` (always int by construction — a match- or occurrence-count is int regardless of what it counts), a declared-`int` `.prop()`, `.sum()` over an integer- **or** bool-leaved lift (`sum([True, False])` is `int`), `.min()`/`.max()` over an **integer**-leaved lift only (`min([True, False])` is `bool`, not `int` — the one deliberate asymmetry), a literal-valued `.sum_over()` mapping, `+ - * %` over two int-valued operands, `**` with a non-negative literal integer exponent, and `.if_inactive()` when both branches are int-valued; division and anything outside this set is row 12. A negative evaluated count is a validation error; `0` yields `[]`. Counts, unlike bounds, remain runtime-evaluated — lists are structure, not charts. A count that references another param nonetheless joins the dependency graph and cycle check (that param must be assigned before the list can be materialized), exactly as a condition does.
- **Variadic sugar.** `.repeat(*counts)` reads as a numpy shape — first count outermost — and desugars to chained lifts in reverse order: `.repeat(2, 3)` ≡ `.repeat(3).repeat(2)`, fingerprint-equal by the sugar-equivalence law. Any count may be an `ArithExpr` per axis. The chain retains one capability the sugar elides: per-level list modifiers between lifts (`.repeat(8).default([...]).repeat(8)`).
- Element values are the element type's self-contained value (scalars, dicts, choice values).
- Constraints declared inside a repeated element `Space` are **instantiated per element**: introspection lists them once under definition paths (`edges[].…`); evaluation reports one `ConstraintEval` per instance path.

**Duplicate modifiers.** Value-bearing (`prior`, `default`, `quantized`) — last-write-wins within a layer. Accumulating (`tag`, `meta`, `when`) — stack.

---

## Paths and Scoping

One grammar, used everywhere — references, `flatten` keys, DataFrame columns, `validate_param` names, diffs, error messages:

```
path     := segment ("." segment)*
segment  := name ("[" i "]")*        # instance path
          | name ("[]")*             # definition path
```

Segments are param names, variant names, and struct-param names. `name[i]` addresses a repeat element (**instance path**), with one index per lift level for nested lifts (`mask[2][3]`); `i` may be **negative**, resolved against the lift's realized length (`name[-1]` is the last element). `name[]` denotes the element schema (**definition path** — used by introspection; illegal in expressions), likewise repeated per level (`mask[][]`).

**Scoping rule (the only one):** resolve the first segment by walking **up** to the innermost scope where it binds, then descend through the remaining segments. A bare name is the one-segment case. Shadowing behaves like lexical closures. Cross-scope constraints are declared at the common ancestor. Composed spaces are therefore *relocatable*: nesting a space under a variant or struct never rewrites its internal references.

```python
ds.space(
    ds.param("global_flag").bool(),
    ds.param("algo").choice(
        svm=ds.space(
            ds.param("C").real(1e-3, 1e3),
            ds.param("gamma").real(1e-5, 10).when(ds.param("global_flag")),  # up
        ),
    ),
).forbid(
    ds.param("algo.svm.C") > 100,   # down from root: param → variant → param
)
```

---

## Expressions

`BoolExpr` and `ArithExpr` are walkable ASTs exposing `.kind: str`, `.params: frozenset[str]`, `.children: tuple`. **`Expr`** names their common base, for signatures that accept or return either (`Encoding.decode_expr`, `Encoding.rewrite`).

**BoolExpr** — for `.when()` and the constraint verbs (`.forbid()`/`.require()`/`.encourage()`/`.discourage()`):

```python
ds.param("x") == != > < >= <= (value | expr)
ds.param("x").is_in(*values)
ds.param("x").is_active()               # total: always True/False
ds.param("s").contains(item)            # subset only (invalid on permutation)
ds.param("flag")                        # bool param, directly
expr & expr    expr | expr    ~expr
expr.implies(other)                     # dedicated Implies node; desugars to ~expr | other at resolution
ds.all_(*exprs)   ds.any_(*exprs)       # variadic; zero args = literal True / False
ds.count(*bool_exprs) <op> value        # number of True operands (ArithExpr)
```

**ArithExpr** — for the constraint verbs, expression bounds, and repeat counts. Comparisons yield `BoolExpr`:

```python
ds.param("x") + - * / ** % (expr | literal)
ds.param("s").size()                    # subset cardinality
ds.param("s").sum_over(mapping)         # subset: Σ mapping[item] over included items;
                                        #   mapping stored literally in the AST; keys ⊆ item universe;
                                        #   an included item absent from the mapping contributes 0
ds.param("p").position_of(item)         # permutation index; item must be a member
ds.param("r").length()                  # lift length
ds.param("c").prop(name)                # custom type property (scalar-typed)
ds.value(fn, *operands, returns=type)   # opaque derived quantity (scalar-typed)
expr.if_inactive(fallback)              # inactive → fallback; unset stays pending
```

**`ds.value`** generalizes `.prop()` from *one custom param, named property* to *any operands,
arbitrary function*, and is dual-typed the same way — `returns` is one of `int|float|bool|str`
(row 16's scalar restriction applies identically), and a `bool`-returning value is usable bare as a
condition. Operands are ordinary expressions, passed positionally, so `.if_inactive()` and any other
coercion compose inside them; `fn` is called with **exactly those operand values and never the
config**, which is what makes the reference set trustworthy — a function reading something it was
not given raises rather than reading it silently. The referenced params are the union of the
operands' own references, so `dependency_graph`, ordering, and cycle detection are unaffected.
`returns=float` keeps margins (`ds.value(deflection, …) <= 0.005` reports `0.005 − deflection`);
`returns=int` may drive a `.repeat()` count. Note the asymmetry when choosing operands:
under-declaring fails loudly, while **over-declaring weakens silently** — an operand the function
ignores still makes the whole node Unknown when it goes inactive, and Unknown constraints are
inapplicable. `fn` is opaque, so a space using `ds.value` is not serializable (see
*Identity and Serialization*).

**Chart application** is the one other opaque-free leaf: a node applying a param's chart to a unit
coordinate, emitted by a representation when it substitutes a decode into a transported expression
(see *The Representation Layer*). It carries the **source** chart's declaration — domain, prior,
quantization — because the param it reads in the genotype is an ordinary `real(0,1)` whose own chart
is uniform. It is vector-polymorphic: applied to a lift or a projection it maps element-wise. These
two are the *only* nodes the expression language will grow. Anything structurally expressible goes
through the language; anything else goes through `ds.value`. There is no third category.

`.prop()` is dual-typed like a bare param reference itself (see *Builder view types*, `BoolParamExpr`): a bool-declared prop is usable directly as a condition — `.require(ds.param("c").prop("ok"))`, `&`/`|`/`~`, `.implies()` — with no `== True` needed, coercing via `bool(value)` at evaluation exactly like any other bare `BoolExpr` leaf (row 16's undeclared-property/non-scalar-type checks still apply uniformly to this position; a non-bool-declared prop used bare is not separately rejected, matching the same convention).

**Vector expressions and aggregates.** A scalar lift *is* a vector expression; `.field(name)` projects a struct lift into one. The aggregate namespace lives on vector expressions only:

```python
.sum()  .min()  .max()
.count_of(*values)          # equality-comparable elements; on lifted choices, counts variants
.is_sorted(descending=False)
.distinct()                 # scalar lift: pairwise-distinct elements
.distinct(*fields)          # struct lift: distinct field tuples
```

**Nested lifts.** Numeric and equality aggregates (`sum`, `min`, `max`, `count_of`, `distinct`) operate over the **leaves**, flattened across all levels; `.field()` on nested struct lifts projects leaves shape-preservingly, and its aggregates likewise flatten. `is_sorted` is restricted to depth 1 (deeper is a resolution error — a grid has no canonical order). Kleene and the empty-aggregate rules apply unchanged to the leaf set. Per-axis constraints need no axis machinery — give the axis a scope and use per-instance instantiation:

```python
ds.param("rows").space(
    ds.param("cells").real(0.0, 1.0).repeat(8),   # row-scope forbid on
).repeat(8)                                        # ds.param("cells").sum() → per row
```

Instance paths are legal in expressions: `ds.param("stops[0].dwell_min") < 10`, at any nesting the grammar admits (`g[0][1]`, `layers[2].act[1]`). **Negative indices are admitted**, resolved against the lift's own realized length — for a *dynamic* count `x[-1]` is the only way to name the last element — and they still reference exactly that lift, so `dependency_graph`, `topological_order`, and the bound envelopes are untouched. An out-of-range index makes the leaf inactive (→ Unknown) wherever the length is a *runtime* fact (a dynamic count), distinct from a *structural* error caught at resolution: against a **static** count the length is known at resolution, so an out-of-range index — `repeat(3)` with `y[7]` — is a resolution error (row 29), not a silently inapplicable constraint. An `ArithExpr` index is excluded entirely (see *Out of Scope*). `.field(name)` requires a struct lift whose element declares `name`; projecting an undeclared field, or `.field()` on a non-struct lift, is a resolution error (a nonexistent definition path — row 6), not a silent Unknown. Ordinals: comparison only; two ordinal *params* compare only if they declare identical value sequences; comparing an ordinal against a literal that is not one of its declared values is a resolution error (row 18). Categoricals: `==`, `!=`, `.is_in()` only.

**Runtime equality.** `==`, `!=`, and `.is_in()` compare `bool` by type-tagged identity against everything else (so `True ≠ 1` — bool is strict), `int` and `float` numerically against each other (`1 == 1.0`), and every other pair (strings and other `Any`-typed categorical/ordinal values) by exact type match. This runtime rule is deliberately distinct from declaration-time distinctness (rows 3–4) and fingerprint canonicalization, which type-tag uniformly; a categorical that declares both `1` and `1.0` as distinct variants therefore cannot be told apart by a runtime `==`.

**Guardrails.** `__bool__` and `__contains__` on expressions raise informative `TypeError`s, so `expr1 and expr2`, `0 < ds.param("x") < 1`, and `v in ds.param("s")` fail loudly instead of silently miscompiling.

### Three-valued semantics

Expressions evaluate in Kleene logic; **Unknown** arises only from inactivity.

1. **Leaves.** Any predicate or arithmetic term over an *inactive* param is Unknown. `is_active()` is the sole total predicate. Projection over an *inactive* lift is Unknown — distinct from an *active empty* list (below). A `ds.value(...)` node is Unknown iff any param its operands reference is inactive — its function is never called in that case, so an opaque leaf obeys the same rule as a transparent one.
2. **Propagation.**

| a | b | `a & b` | `a \| b` |   | a | `~a` |
|---|---|---|---|---|---|---|
| T | T | T | T |   | T | F |
| T | U | U | T |   | U | U |
| T | F | F | T |   | F | T |
| U | U | U | U |
| U | F | F | U |
| F | F | F | F |

Comparisons and arithmetic with an Unknown operand are Unknown. Range-tracking is specific to `ds.count`, which tracks `[t, t + u]` (True count, Unknown count) and is Unknown iff the comparison outcome differs across that range. Every *other* aggregate (`sum`, `min`, `max`, `count_of`, `is_sorted`, `distinct`) containing any Unknown element is itself Unknown — plain propagation, no range computed: a non-empty vector is treated as an ordered collection of operands, and one Unknown operand makes the whole Unknown, exactly as for ordinary arithmetic. (`count_of` resembles `ds.count` but is a distinct construct over a vector and does not range-track.)

3. **Coercion at `.when()`:** Unknown → False. Deactivation therefore cascades along `topological_order`.
4. **Coercion at the constraint verbs on complete configs:** Unknown → **inapplicable** — not violated, `margin = None`, `ConstraintEval.applicable = False`.
5. **Unknown has a provenance, and `.if_inactive()` discriminates on it.** Unknown arises from three sources: *inactivity* (rule 1), *emptiness* (`min`/`max` over an active empty lift, rule 6), and — in partial evaluation only — an *unset* operand, which makes a constraint **pending** rather than Unknown. `.if_inactive(fallback)` coalesces **inactivity alone**: it never eats pending, and it never eats emptiness. Both restrictions matter and both fail silently if ignored — eating pending makes a driver loop conclude a constraint is satisfied while the values that will violate it are still unassigned; eating emptiness turns an undefined `max([])` into the fallback while the lift is *active*, which the method's own name disclaims. An author who wants an empty lift to contribute a value writes it explicitly rather than relying on the inactivity guard. A node combining more than one Unknown-valued operand (`a & b` with `a` inactive and `b` pending) keeps the **strongest** provenance — `inactive < pending < permanent` — so `.if_inactive()` still refuses to coalesce whenever *any* contributing operand was pending or a structurally malformed value (which itself carries permanent provenance, D-71).
6. **Empty aggregates** (active lift, zero elements): `sum → 0`, `count_of → 0`, `distinct → True`, `is_sorted → True`; `min`/`max` → **Unknown** (containing constraint goes inapplicable rather than erroring).

Side-by-side, because this is the most confusable pair in the semantics:

```python
# use_aux = False  → aux_layers inactive → .field("w").sum() is Unknown → constraint inapplicable
# use_aux = True, n_aux count yields []  → sum() == 0 → constraint applies and is satisfied
```

7. **Bound couplings are constraints, so they follow rule 4.** Expression bounds desugar to bound-origin constraints (see *Expression bounds are sugar*); when the referenced param is inactive while the target is active, the coupling is simply inapplicable and the target ranges over its envelope. An author wanting strict coupling writes it explicitly: `.when(ds.param("y").is_active())`.

---

## Constraints and Feasibility

Chainable on `Space`, each returning a new `Space`:

| Method | Purpose |
|---|---|
| `.forbid(*conditions, tags=(), meta=None)` | Defines **feasibility** — violating configs are invalid and rejected by the reference sampler. The argument names the **forbidden (bad)** state |
| `.require(*conditions, tags=(), meta=None)` | Defines **feasibility** via the **required (good)** state — feasible iff the predicate is satisfied; the polarity-inverse of `.forbid`. Sugar-equivalent to `.forbid(~condition)` in feasibility, margin, and fingerprint |
| `.encourage(*conditions, tags=(), meta=None)` | Declares an evaluated, annotated predicate naming a **desired (good)** state — reported with a margin, but **never** affects feasibility or the reference measure |
| `.discourage(*conditions, tags=(), meta=None)` | Declares an evaluated, annotated predicate naming an **undesirable (bad)** state — the soft complement of `.encourage` (`== encourage(~condition)`); reported, never affects feasibility |
| `.anchor(configs: dict[str, dict])` | Named reference configs, validated at resolution |
| `.meta(mapping=None, **kwargs)` | Space-level metadata (objectives, cost models, anchor-role conventions) |

**The constraint quartet.** The four predicate verbs are two polarity pairs on two axes — **hard** (`forbid`/`require`, affect feasibility) vs. **soft** (`encourage`/`discourage`, declared and reported, never affect feasibility), crossed with the **polarity** of the stored predicate: a `forbid`/`discourage` names a *bad* state (the good outcome is *not* satisfying it), a `require`/`encourage` a *good* state. Each is the polarity-inverse of its partner (`require(e) == forbid(~e)`, `discourage(e) == encourage(~e)`). Every verb produces a `Constraint`; read its category and polarity through the derived accessors rather than the storage — `Constraint.kind` (`"forbid"`|`"require"`|`"encourage"`|`"discourage"`|`"bound"`), `Constraint.feasible_when_satisfied` (the polarity — `False` only for the bad-state verbs), and `ConstraintEval.violated` (polarity-correct: an inapplicable eval is never violated; otherwise violated iff `satisfied` differs from the desired polarity).

Feasibility is defined by param validity plus forbids **and requires** only (a `require` is a forbid of the negated condition — see below). `validate().valid`, `is_feasible()`, and `infeasibility_reasons()` never consider the soft `.encourage()`/`.discourage()` declarations; those appear in `constraint_evals` with margins so nothing is hidden. Core stores `tags` and `meta` on constraints and never interprets them — penalty shapes, weights, priorities, and relaxation orders are consumer policy attached via `meta`. A directional preference with no threshold ("minimize capex") is not a constraint — no predicate, no margin — and belongs in space-level `.meta()` as an objective declaration.

**`require` — the positive complement.** `space.require(e)` declares that feasible configs must *satisfy* `e`, sparing the user the mental inversion `.forbid` demands. It carries `origin="require"` and stores the **desired (feasible)** predicate `e` — the same *feasible-iff-satisfied* convention a bound-origin constraint uses — so introspection and `infeasibility_reasons` read in the user's own terms and the reported `margin` is `margin(e)` directly (positive is slack). Three-valued: `require(e)` is **violated iff `e` is definitely False**; an Unknown or True `e` is feasible (Unknown ⇒ inapplicable, `margin = None`), exactly `forbid(~e)`'s Kleene behavior. It is therefore feasibility-, margin-, **and** fingerprint-equal to `.forbid(~e)`: the fingerprint preimage canonicalizes every polarity-opposite constraint (`origin` `bound`, `require`, or `discourage`) to its baseline-polarity (negated) form, so `origin` stays semantics-neutral (see *Identity — Normalization pipeline*). The `require` origin is additive to the frozen format; no shipped document or known-answer vector depends on the prior origin set, so it introduces no format-version bump.

**`discourage` — the soft complement of `encourage`.** `space.discourage(e)` declares that `e` names an *undesirable* state, the soft sibling of `.forbid` exactly as `.encourage` is the soft sibling of `.require`. It carries `origin="discourage"`, stores the bad-state predicate `e`, is **flagged as a violation iff `e` is satisfied** (mirroring `.forbid`'s Kleene polarity), and — being soft — **never affects feasibility** (it is dropped from the `sampling` fingerprint scope, and only `sample(..., reject_soft=True)` rejects on it). It is fingerprint-equal to `.encourage(~e)` and fingerprint-distinct from `.encourage(e)`: its preimage canonicalizes to `Not(e)` for the same reason `require` does — to keep the excluded `origin` from becoming semantics-load-bearing. Like `require`, the `discourage` origin is additive to the frozen format with no version bump.

**White, grey, and black box.** A predicate's transparency decides how much of the library's own machinery can act on it, and the tiers are worth naming because the cost is invisible at the call site:

| tier | form | margins | `remaining_domain` narrowing | tighten-not-reject |
|---|---|---|---|---|
| white | expression over param values | yes | yes | yes (bound-origin) |
| grey | opaque scalar, structural comparison — `prop("n") > 3`, `ds.value(f, …, returns=float) <= c` | yes | no | no |
| black | opaque predicate — `ds.value(f, …, returns=bool)` | no (`None`) | no | no |

The reason to prefer a transparent form is **not** solver consumption — a solver facing a black-box objective is not handing constraints to a MIP or CP solver anyway — but that margins, `evaluate_partial`, `remaining_domain`, and bound-origin tightening are all *designspace's* machinery and all run on structure. A grey predicate is often available where a black one is reached for by habit: a physical quantity has a numeric value, and exposing it as `returns=float` under a comparison keeps the margin that a `returns=bool` wrapper throws away.

### Margins

`ConstraintEval.margin` is the signed distance to the boundary in the constraint's own units: positive is slack, negative is violation magnitude, zero is on the boundary.

| Form | Margin |
|---|---|
| `a <= b` / `a < b` | `b − a` |
| `a >= b` / `a > b` | `a − b` |
| `a == b` | `−abs(a − b)` |
| `a != b` | `abs(a − b)` — note: violated ⇒ 0; never negative |
| non-numeric leaf (e.g. categorical `==`) | `None` |
| `p & q` | `min(margin(p), margin(q))` |
| `p \| q` | `max(margin(p), margin(q))` |
| `~p` | `−margin(p)` |

`None` absorbs through composition. The composition rules preserve the satisfaction invariant (`&` holds iff min ≥ 0, etc.), so composite geometric constraints (e.g. exclusion zones) keep usable margins.

**Continuous-equality warning.** An `==` constraint over purely continuous, unquantized operands is measure-zero under sampling; resolution emits a warning pointing at generative reparameterization (see Solver Integration) or `.custom()`. *Purely* qualifies the whole comparison: the warning fires only when no operand is discrete-typed (categorical / ordinal / bool / integer / quantized) and at least one is an unquantized real — a discrete operand anywhere suppresses it.

### Expression bounds are sugar

`ds.param("x").integer(1, ds.param("y"))` desugars at resolution to `ds.param("x").integer(1, env_hi)` plus the implicit hard constraint `ds.param("x") <= ds.param("y")` — there is exactly one encoding of a bound coupling, and the bound syntax is notation for it. The envelope is the interval-arithmetic hull of the bound expression over the referenced params' (already-enveloped) domains, computed along the dependency DAG: a **hi**-bound's envelope is the hull's **supremum**, a **lo**-bound's its **infimum** — the chart must cover the widest value any legal assignment of the dependencies could produce (charts are static; the bound-origin constraint narrows the domain back down per config). A dependency need **not** be a literal — it may be any real/integer param carrying its own prior, quantization, or bounds, and envelopes chain along the DAG. A bound expression with no computable hull is a resolution error (row 20), with the stated workaround being exactly the desugared form written by hand.

- **Computable op set.** The envelope engine is **minimal**: `+` and `−` over any enveloped sub-expressions, and `*` with one **syntactically literal** operand (chained literal scaling like `y * 2 * 3` is fine). `/`, `**`, `%`, `*` of two non-literal operands, and any vector/count/field operator have no computable interval hull and are row 20 — the workaround is the manual expansion (a hand-computed literal envelope plus a `.forbid()` in forbidden-state form). A bound on a param *inside* a `.repeat()` element is not yet supported; express it as a per-element `.forbid()` via the prebuilt-`Space` form.
- **Scope.** Bound expressions resolve **eagerly** in the declaring scope and tolerate no enclosing-scope up-reference (unlike `.when()` conditions — see *Resolution timing*): the chart is built during this scope's resolution, before any enclosing scope merges, so an up-reference could not yet resolve. Cross-scope bound couplings use the same route as cross-scope constraints — write them by hand at the common ancestor.
- **Provenance and polarity.** The implicit constraint carries `origin="bound"` (vs. `"user"`) so errors can say "`x` exceeds its declared bound `y`" and introspection can distinguish. It stores the **desired** predicate `x <= y` (which is what yields the `y − x` margin below) — deliberately **not** `.forbid()`'s "the argument names the *forbidden* state" convention; feasibility is evaluated as *feasible-iff-satisfied*, the opposite of a user forbid. The hand-written *feasibility*-equivalent is therefore `.forbid(ds.param("x") > ds.param("y"))` — the forbidden-state spelling — not `.forbid(x <= y)`, which would invert feasibility. `origin` is derived provenance, excluded from the fingerprint preimage; so that fingerprint-equality still tracks feasibility (equal fingerprints must mean equal valid-config sets), the preimage encodes a bound-origin constraint in its **forbidden-state (negated) form**, making the sugar fingerprint-equal to its `.forbid(x > y)` manual expansion (see *Normalization pipeline*). This upholds the invariant that **no preimage-excluded field may be feasibility-load-bearing**.
- **Ordering.** Bound-origin constraints, unlike user constraints, enter `dependency_graph` and `topological_order`, preserving assign-`y`-before-`x` ordering.
- **Margins for free.** The coupling yields a `y − x` margin, which the old per-config-chart encoding never had. (This is precisely why the stored predicate is the *desired* `x <= y` and not the forbidden `x > y`; see *Provenance and polarity*.)
- **Inclusivity.** Bounds are inclusive; strict orderings (Wolfe's `c1 < c2`) need an explicit strict constraint or an epsilon.
- **Scaled measures** ("Beta scaled to `[0, y]`") are not truncations and are not expressible as bounds; use generative reparameterization — encode `frac ∈ [0,1]` with the prior and let the consumer derive `x = frac·y`.

---

## Charts

Every generative scalar param resolves to a **chart**: a monotone map `[0,1] → domain`. Sampling is `chart(u)`; solver geometry is u-space; integers and quantization are the same mechanism.

### Built-in prior families

Bounds-aware and parameterless; resolution composes them with `[lo, hi]`:

| Prior | `chart(u)` | Requires |
|---|---|---|
| Uniform (default) | `lo + u·(hi − lo)` | — |
| `ds.Log()` | `exp(log lo + u·(log hi − log lo))` | `lo > 0` |
| `ds.Logit()` | `σ(logit(lo) + u·(logit(hi) − logit(lo)))` | `0 < lo ≤ hi < 1` |
| `ds.Power(p)` | `(lo^p + u·(hi^p − lo^p))^(1/p)` | `p ≠ 0`; `tᵖ` monotone on `[lo, hi]` — `lo ≥ 0` unless `p` is a positive odd integer, and `lo > 0` when `p < 0` |

The `Requires` column is the operative rule (`p ≠ 0`; `lo ≥ 0` unless `p` is a positive odd integer; `lo > 0` when `p < 0`); it guarantees the closed-form (signed-root) chart is a strictly increasing bijection onto `[lo, hi]`. Monotonicity of `tᵖ` is necessary but not the test — the rule is stricter, because the signed-root formula does not recover `[lo, hi]` on every monotone domain. It rejects (row 9): a domain straddling 0 (`lo < 0 < hi`, non-odd-integer `p`) — including the degenerate `lo^p == hi^p` (`Power(2)` over `[-a, a]`) and the domain-incomplete `Power(2)` over `[-2, 3]` (which would map onto `[2, 3]`) — and an all-negative even-`p` domain (`Power(2)` over `[-4, -2]`), which is monotone yet unrecoverable by the formula.

Each has a closed-form inverse, so `to_unit(value)` always exists for built-ins. `lo == hi` yields the constant chart (still generative); `to_unit` at that degenerate point is unspecified and returns `0.0` — nothing observable depends on it, since `from_unit` returns the single legal value for every `u`.

### External priors

Any object satisfying `Prior` (`.ppf(q)` required, `.cdf(value)` optional). At resolution: if `ppf(0)` and `ppf(1)` are finite and inside `[lo, hi]`, the support is contained and `ppf` is used directly (`cdf` then only gates inverse mapping, surfaced as `invertible` in introspection). Otherwise the chart is the truncation `ppf(cdf(lo) + u·(cdf(hi) − cdf(lo)))` and a missing `cdf` is an error. **Silent clipping of tail mass onto the bounds is forbidden** — the same rule as default clamping.

### Integers

The continuous chart is built over `[lo, hi + 1)` and the emitted value is `floor(chart(u))`. Uniform prior ⇒ exactly uniform over `{lo..hi}`; `Log()` ⇒ standard log-uniform integers with no endpoint bias. The inverse is interval-valued: value `k` owns `[chart⁻¹(k), chart⁻¹(k+1))`; `to_unit(k)` returns the interval midpoint, and the interval itself is exposed for solvers.

### Quantization

Grid `g_k = lo + k·step` (or `g_k = lo·factor^k`); chart built over the extension `[g_0, g_K + cell)`; emitted value = greatest grid point ≤ the continuous draw. Consequences: uniform prior ⇒ equiprobable grid points; any prior ⇒ each point's probability is the prior measure of its cell; an integer param *is* a quantized real with `step=1`. `include_hi=True` appends `hi` as a final grid point whose own cell width follows the same local-spacing formula as a grid point one step further out (`step`, or `hi·(factor − 1)`). Degenerate `step ≥ hi − lo` (geometric analogue: `factor ≥ hi / lo`) yields the single-point grid `{lo}` (plus `hi` if included); `step ≤ 0` or non-finite is a resolution error.

**Grid membership and canonicalization.** Validation recovers `k = round((v − lo)/step)`; valid iff `0 ≤ k ≤ K` and `|v − (lo + k·step)| ≤ tol` (default `rtol=1e-9`, overridable). `config_hash` canonicalizes to `lo + k·step` computed exactly this way. Canonicalization is context-free — all grids, like all charts, are static.

### Periodicity

`periodic=True` reals: canonical domain `[lo, hi)`, chart maps `[0,1) → [lo, hi)`, `hi` invalid — so hashing is canonical by construction. The flag is on `ParamDef` for solvers to read and apply wraparound moves and periodic kernels, and a representation must **mirror it onto the genotype**: `from_unit(1.0)` yields `hi`, which is not a domain member, so an unmirrored unit target would decode outside the source domain.

### All charts are static

Every chart is built once, at resolution, over the param's (envelope) bounds — expression bounds having been desugared first (see *Expression bounds are sugar*). Chart-family requirements (`Log()` needs `lo > 0`, `Logit()` needs `(0,1)`, `Power(p)`'s monotonicity domain) are checked against the *declared* envelope bounds `(lo, hi)`, which do not move under quantization or the integer extension — even though the continuous chart math is built over a wider bound (`hi + 1` for integers, the grid extension for quantized). `ParamDef.chart` is a plain attribute. The genotype→phenotype map therefore never depends on other genes — u-space coordinates are comparable across configs.

**`to_unit` is what makes a representation invertible.** It exists for every closed-form family, and for an external prior only when that prior supplies `cdf` — a `Prior` with `ppf` alone yields a chart that decodes but cannot encode, so any representation touching it is not invertible. For the two cell-valued kinds the returned representative differs and the difference is deliberate: an **integer**'s `to_unit(k)` is the interval **midpoint** (above), while a **quantized** real's is the cell's **left edge**, `to_unit(g_k) = (g_k − lo) / (g_K + cell − lo)`. Both satisfy `from_unit(to_unit(v)) == v`, which is the only law either owes; the asymmetry is documented rather than aligned so neither existing round-trip moves.

The reference sampler *may* recognize a bound-origin constraint whose referenced params are already assigned and draw from the correspondingly tightened chart instead of rejecting — observably identical, because truncation is conditioning (tightening an external prior to a sub-interval needs `cdf`; absent that, rejection). This is a **best-effort** optimization (`may`), layered on top of the hard bound-origin constraint that always sits in `space.constraints`: it applies only to the closed-form families (Uniform/`Log()`/`Logit()`/`Power(p)`) over a non-quantized real/integer. External priors without `cdf`, quantized grids, and any dependency not yet assigned at draw time fall through unchanged to rejection. Correctness needs only that tightening never fire where truncation ≠ conditioning — completeness of the tightened-family list is not required, since every un-tightened case rejects and rejection is always sound.

---

## Sampling and Generativity

```python
.sample(n, seed=None, reject_soft=False) -> pl.DataFrame   # requires the `polars` extra
.sample_one(seed=None, reject_soft=False) -> dict
.sampling_report(n=1000, seed=None, tighten_bounds=False) -> SamplingReport   # diagnostics; see below
```

`seed: int | numpy.random.Generator | None`. The reference sampler is an interpreter of declared measure: walk `topological_order`, decide activity, draw active generative params through their charts (weights for categorical/ordinal/bool/choice; Bernoulli-plus-size-rejection for subsets; uniform shuffle for permutations; `sample(rng)` for customs), reject on **forbids** and **requires** only (a `require` is a forbid of the negated condition). `reject_soft=True` additionally rejects soft-constraint (`.encourage()`/`.discourage()`) violations — rejection on a user-declared predicate, off by default. Default max retries 10,000 with an informative error naming the constraints that dominated rejection.

**Rejection hostility.** Dense combinatorial forbids (pairwise `distinct`, conflict sets near packing limits) collapse rejection acceptance. The remedy is constructive: enforce the invariant inside a `.custom()` sampler or reparameterize (see Solver Integration, tiers). The retry-exhaustion error links here.

**Generative vs. non-generative.** Every param is generative except `.code()`/`.symbolic()` (without `sampler=`) and a full-protocol `.custom(param_type)` whose `param_type` declares no `sample()` (the shorthand `.custom(sampler, validator)` is always generative — a sampler is required). `sample()` raises a `SamplingError` naming the offending params **iff** it must materialize a value for a non-generative param — a `.default()` satisfies it, `freeze`/`slice` removes it, and a param inactive for the draw in progress never triggers it.

Sampling always produces explicit values and **ignores defaults** — measure bias is the prior's job, not the default's.

---

## Defaults

`.default()` semantics were unified in v3 around a cascade:

- A **choice default names a variant** (a string). A struct param or activated variant payload fills **field-wise** from its members' own defaults; a struct carries no own default value. If a config already supplies a choice's variant, partial input wins — that variant's payload is filled from its own members' defaults.
- **Element defaults** (pre-lift) are count-independent and legal under dynamic counts. **List defaults** (post-lift) are legal only for static counts, must match the length, and are mutually exclusive with element defaults on the same param. A **default declared on a param inside a lifted struct/choice** (a `[]`-template field) fills into each materialized instance the same way.

```python
.apply_defaults(config) -> dict
.has_complete_defaults -> bool
```

`apply_defaults` is a **partial-evaluation operator**: idempotent, monotone (never overwrites, never removes), activity-respecting. It walks `topological_order`, recomputing activity as it fills, and fills only params whose activity resolves to *active* given the config so far (so a filled default triggers downstream defaults in one pass); params of *inactive* or *unknown* activity are left untouched. Partial input wins field-wise: the fill merges into the leaf representation and never replaces a supplied value or subtree.

**Counts and lifts.** A param used as a repeat count is filled from its own default like any other, and since `topological_order` places a count param before its list, that default determines the list length before materialization. A count is **determined** when it is a static integer, evaluates to a definite integer over the config, or is Unknown *solely because a referenced param is inactive* — in which case it is **0** and the lift is the complete value `[]`. `apply_defaults` emits **only default values**: it materializes a lift (its count and filled instance leaves) iff the count is determined and either the count is 0 or at least one instance leaf receives a default; otherwise the lift is left implicit. `is_complete`/`missing_params` re-derive the count from the config, so completeness is exact regardless.

Postcondition: the result is complete iff every param active under the filled config has a default or was supplied — `apply_defaults` does not guarantee completeness; check `is_complete`. `has_complete_defaults` is `is_complete(apply_defaults({}))`.

Defaults validate against their (static) domain at resolution — **never a silent clamp** (cross-reference: the prior tail-clipping ban). This check spans every kind: a choice default must name a declared variant, a subset/permutation default must be a valid subset/ordering, and a struct param admits no own default (error row 21). `apply_defaults` is constraint-blind: its output may violate forbids — bound-origin couplings included — which `validate` reports; this matches user forbids, which were never checked at fill time.

**Defaults vs. anchors.** Defaults are per-param fill values for completion; anchors are named whole configs for reference. When a space has complete defaults, derive rather than duplicate: `.anchor(configs={"shipped": space.apply_defaults({})})`. Defaults do not auto-create an anchor. Anchor roles (incumbent, baseline) are a `.meta()` convention, not API.

### Sampling diagnostics

`.sampling_report(n=1000, seed=None, tighten_bounds=False) -> SamplingReport` draws `n` configs from the **unconditioned** measure — before rejection — and aggregates what happened. It reports; it never repairs, reweights, or suggests.

Drawing *unconditioned* is the whole point. `sample()` returns the post-rejection distribution, in which the two pathologies worth finding are invisible:

- **Unknown-swallowing.** Kleene rule 4 makes an unevaluable constraint *inapplicable*, i.e. accepted — the permissive direction, and silent. A constraint aggregating over optional params (`a + b + c <= budget` with `c` conditional) quietly stops enforcing wherever `c` is inactive; `ConstraintReport.applicable` is the only signal. The fix is usually `.if_inactive()`, but nothing prompts a user to reach for it.
- **Funnels.** A constraint that is inapplicable on part of the space biases the conditioned measure toward that part, since rejection accepts those draws unconditionally. This is correct — `require` conditions the declared measure — but it is not visible from the resulting sample.

`satisfied` is conditioned on **applicability**, not on all draws: a constraint applicable in 1% of draws and always satisfied there reports `1.0`, not `0.01`. Collapsing those would erase the distinction the surface exists to draw. When `applicable == 0.0` (never Kleene-defined across all `n` draws), `satisfied` reports `0.0` by convention — not `NaN`, so a frozen report always equals itself — and carries no information; `applicable` is the number to read.

**Tightening is opt-in and off by default (D-74).** The reference sampler's best-effort tighten-not-reject optimization (*All charts are static*) folds an already-assigned bound-origin coupling into the draw itself, which is observably identical to rejection *after* rejection — but drawn unconditioned, it would silently launder the report's own subject: on a bound-coupled space it collapses exactly the `ConstraintReport` rows most likely to carry the pathology to `satisfied ≈ 1.0`. `tighten_bounds=False` (default) draws every config against the full declared envelope, so `acceptance_rate` reads as "how much of the declared measure the hard constraints cut away" and bound-origin rows show their real satisfaction fractions. `tighten_bounds=True` draws the way the reference sampler actually does, answering "how much does tightening save me" directly. The three sampling entry points (`sample`/`sample_one`/`sample_dicts`) take no such flag — tightening cannot change their returned distribution (truncation ≡ conditioning), so a flag there would be a performance knob wearing a semantic one's signature.

**Per-instance folding (D-73).** A per-element constraint (`ListDomain.element_constraints`, instantiated once per active lift instance) contributes one `ConstraintReport` row, keyed by its template `Constraint`, folded **per draw**: `applicable` is the fraction of draws where at least one instance eval was Kleene-defined; `satisfied` is the fraction of *those* draws where every applicable instance was satisfied. A draw materializing zero instances (the lift inactive, or active and empty) counts as inapplicable for that row. `SamplingReport.activity` keys are exactly `set(space.params)`, including `"[]"`-templated definition paths from inside a lifted struct/choice; a template key's value uses the identical per-draw fold — the fraction of draws in which at least one of its instances was active. Every row and every key therefore shares one denominator, `n`, and stays comparable to `acceptance_rate` and to each other.

---

## Space — Validation

```python
.validate(config) -> ValidationResult
.validate_param(path, value, context=None) -> ValidationResult   # instance paths supported
.is_feasible(config) -> bool
.infeasibility_reasons(config) -> list[str]
.evaluate_constraints(config) -> list[ConstraintEval]
```

Relations: `is_feasible(c) == validate(c).valid`, both defined by param errors plus hard constraints; `evaluate_constraints` reports every constraint (hard and declared) with `applicable` and `margin`. `context` enables evaluating constraints that reference other params (bound-origin couplings included); without it, `validate_param` reports those as unevaluated rather than guessing — concretely, an under-determined constraint (one referencing a param absent from `context`) is **omitted** from `validate_param`'s `constraint_evals` rather than appearing with a placeholder: `ConstraintEval` has no "pending on missing context" state, and reusing `applicable=False` would conflate it with a genuine Kleene-Unknown. `validate` and `config_hash` operate on this space's own **phenotype** configs. A genotype is not a transformed view of one: it is a config of its own target `Space` and takes that space's identity (`target.fingerprint()`, `config_hash(g, target)`) — see *The Representation Layer*.

---

## Space — Partial Configs

```python
.evaluate_partial(config) -> PartialEval
.remaining_domain(path, config) -> RemainingDomain | None
.param_activity(config) -> dict[str, "active" | "inactive" | "unknown"]
.is_complete(config) -> bool
.missing_params(config) -> list[str]
.topological_order -> list[str]              # definition paths
.next_assignable(config) -> list[str]        # instance paths: active, unset, dependency-ready
```

`topological_order` gives an assignment order where every condition and bound-origin constraint references only already-assigned params; follow it and any interruption point is a well-defined partial config. It lists definition paths, omitting lift descendant templates. `next_assignable` is the derived driver-loop sugar.

**Three-valued activity.** `param_activity` classifies each param `active` (its condition is `True`, or it has none), `inactive` (`False`), or `unknown` — Kleene-Unknown **and** at least one param the condition references is itself `active`-unset or `unknown` (a still-resolvable dependency). A condition left Unknown *solely* by inactive operands is `inactive`, by the same cascading deactivation a full config applies. So `unknown` means "undetermined but resolvable," a param is `unknown` only if a param it gates on is `active`-unset or `unknown`, and collapsing `unknown` to `inactive` reproduces the full-config activity. (`is_active(p)` inside a condition follows the same three values — determined for a determined `p`, `Unknown` for an `unknown` one.)

**Status, completeness, order.** `evaluate_partial` reports each param's `param_status` — `set` (active and present), `active_unset` (active and absent), `inactive`, or `unknown` — with `evaluable_constraints` (a `ConstraintEval` for every constraint of determined value, including those settled inapplicable by inactivity alone), `pending_constraints` (still Kleene-Unknown on an `active_unset`/`unknown` operand), and `n_remaining` (the number of `active_unset` params — a lower bound while any lift count is still undetermined). `is_complete(config)` holds iff no param is `active_unset` or `unknown`; `missing_params` lists the `active_unset` instance paths in `topological_order`. A lift contributes instance statuses only when its count is **determined** (per the Defaults count rule; an inactive count-dependency yields the complete `[]`); an **undetermined** count (a pending count-dependency) contributes none — the count param's own status carries incompleteness. A list container is `set`/`unknown`/`inactive`, never `active_unset` — `set` once its count is determined and its instances present, `unknown` while its count is still pending, `inactive` when its condition is false. A **struct container** likewise collapses `active → set` (it has no own value, so `active_unset` cannot apply).

`next_assignable` lists the `active_unset` params every one of whose referenced params (condition, bound-origin bound, repeat count) is `set` or `inactive`. **This coincides with completeness: `next_assignable(config) == []` iff `is_complete(config)`** — following `topological_order`, the first param that is not `set`/`inactive` is always `active_unset` with all references settled, so a driver loop assigning `next_assignable` halts exactly at completeness. You assign a lift's count param and its instance leaves, never the container.

`remaining_domain` returns a per-kind descriptor — `RealRemaining`/`IntegerRemaining` (interval, grid-intersected if quantized), `ValueRemaining` (still-legal values for bool/categorical/ordinal/choice), `SubsetRemaining` (items forced-in / forced-out / free), `PermutationRemaining` (declared items, unreduced) — or `None` if the param is inactive. It starts from the declared domain and intersects the narrowing of every **hard** constraint (forbid, bound-origin, or require; the soft `.encourage()`/`.discourage()` excluded) that, after substituting all other operands from the config, leaves the param as the sole unset **bare** operand of a comparison — the feasible side by origin (a bound or require stores the feasible predicate; a forbid stores its negation). **Guarantee level:** declared bounds ∩ constraints reducible with exactly one unset bare operand — bound-origin couplings included, so bound tightening falls out of the same rule. A param buried in arithmetic, two unset operands, or an unsupported operator is not reduced; full propagation across multi-param constraints is CSP solving — consumer territory. The descriptor is **sound, not complete**: it never excludes a still-feasible value, though it may admit values an unreduced coupling would forbid. `remaining_domain` on a struct/list container path — or an empty or otherwise non-existent param path — is a misuse `TypeError`: it names no leaf param, and `None` is reserved for an inactive param and must not be overloaded to mean "no such param."

---

## Space — Introspection

```python
.params -> dict[str, ParamDef]               # keyed by definition path
.conditions -> list[Condition]
.constraints -> list[Constraint]
.anchors -> dict[str, dict]
.subspaces -> dict[str, SubspaceInfo]        # struct and variant subspaces by prefix
.dependency_graph -> dict[str, frozenset[str]]

.param_constraints(path) -> list[Constraint]
.param_conditions(path) -> list[Condition]

.n_params -> int
.is_conditional -> bool
.is_hierarchical -> bool
.has_variable_length -> bool
.has_nongenerative_params -> bool            # replaces has_code_params
.has_complete_defaults -> bool
.is_finite -> bool
.cardinality() -> int | None                 # None if infinite or not enumerable
.fingerprint(scope="full", on_unserializable="raise") -> str
.represent(*rules: EncodingRule) -> Representation      # see The Representation Layer
```

`cardinality()` is the finite-config count over the structural product: closed-form per kind — integer range, quantized-real grid, categorical/ordinal/bool value count, subset (Σ over size bounds), permutation (`n!`), choice (Σ over variants — bare contributes 1, payload-bearing the product of the variant's own fields), struct (Π over fields), static-count list (`element_count ** count`), custom (the type's own `cardinality()` if it declares one, else `None`) — recursing through each param's own domain shape, never a flat scan, so a choice/struct's own relocation-injected activation condition is handled implicitly by the variant-sum/field-product formula, needing no CSP/enumeration machinery for that case. An **unquantized real, a dynamic-count list, or a custom with no declared `cardinality()`** makes the whole result `None`. A param carrying its own **independent** condition — one referencing anything beyond what its struct/choice nesting alone would inject, or any condition at all on a root (non-nested) param — also makes the result `None`: general conditional enumeration is out of scope; this is sound (never over-counts), just conservative.

`dependency_graph` maps each definition path to the params it depends on via conditions, constraints, and repeat counts (bound-origin constraints and repeat counts included; only conditions, bound-origin constraints, and repeat counts impose assignment order — a runtime-evaluated count is not a bound, but it must still be assigned before its list). A plain constraint has no distinguished target, so it couples every param it mentions **symmetrically** — each mentioned path's entry gains every other mentioned path. Every key of `.params` gets an entry, lift-descendant templates (`"[]"`) included, matching `.params`'s own unfiltered transparency.

`param_conditions(path)` returns the **union**: every condition whose `target == path`, plus every condition that merely *references* `path` in its expression. `param_constraints(path)` returns every constraint that references `path` (a constraint has no target to distinguish).

---

## Space — Structural Operations

Each returns a new `Space`. Path arguments accept both keyword form and a positional `dict[str, Any]` (required when paths contain `.` or `[]`).

| Method | Semantics |
|---|---|
| `.slice(values=None, **kw)` | Remove params; **substitute** the value at every reference site — conditions and constraint expressions, bound-origin included (envelopes recompute on re-resolution) — then re-resolve |
| `.freeze(values=None, **kw)` | Fix values, keep params in output; conditions resolve statically |
| `.active_subspace(config)` | Subspace of params active for this config |
| `.select(*paths, strict=False)` | Definition-path **prefix subtree** (selecting a choice brings its variants). Best-effort: constraints referencing excluded params dropped with a warning; `strict=True` raises |
| `.filter(tags=..., mode="any", strict=False)` | Same best-effort semantics |
| `.extend(*exprs)` | Additive — inherits params, conditions, constraints, anchors, meta. `ds.space()` is the identity |

**Anchors under structural operations:** `freeze`/`slice` re-validate anchors; a conflict with a frozen/sliced value is a resolution error. `select`/`filter` drop conflicting anchor keys with the same warning mechanism. `extend` keeps anchors and re-validates. **Exception:** a choice `.freeze()` that structurally prunes non-selected variants (below) uses `select`/`filter`'s strip/drop mechanism instead of the hard-fail every other freeze kind uses — pruning removes params, so the "unchanged shape" assumption behind the hard-fail doesn't hold.

**`.freeze`'s per-kind mechanism.** Real/integer/categorical/ordinal narrow the param's own domain to the single fixed value (`lo == hi` is already a legal degenerate domain — Degeneracy Table) and set `default` to it, dropping any prior. Bool has no domain to narrow, so it is pinned instead via a hard `require`/`require(~·)` constraint on the param — this is deliberately visible in `.constraints` and the fingerprint (fingerprint-equal to a hand-written `.require(b)`), not a silent domain fact. A **custom** param is likewise opaque to domain-narrowing: a full-protocol `.custom(param_type)` is pinned via `require(p == value)` — comparing structurally on `to_json()` output, which every full-protocol type supports for free, needing no native `__eq__` — **and** `default` is set to the fixed (phenotype) value, so a non-generative custom's `sample()`-time `SamplingError` is satisfied too (real/integer/categorical/ordinal already get this from domain-narrowing alone; bool never needs it, being always generative). The `.custom(sampler, validator)` shorthand has no comparable, serializable value and is not freezable — a path-named resolution error.

A **subset** is fixed by a per-item `require`: `require(contains(p, i))` for every declared item present in the fixed value, `require(~contains(p, i))` for every declared item absent from it — no domain narrowing (`SubsetDomain` has no single-value representation) — and `default` is set to the fixed value, matching the domain-narrowing kinds. A **permutation** is fixed the same way: a per-position `require(position_of(p, item) == k)` for each `k`, with `default` likewise set. A **struct** has no value of its own to fix — `.freeze()` fans out to a per-field `.freeze()` call at each given field's own fully-qualified path (a partial dict fixes only the given fields; the same dispatch composes recursively when a field is itself a struct, choice, subset, permutation, or list) — no struct-level `default`.

A **choice** is fixed by a discriminator pin `require(c == variant)` plus structural pruning: a variant's already-relocated descendant params are dropped iff **no instance being frozen in this call selects it** — for a plain choice (one instance) this reduces to "every variant but the chosen one," the originally-anticipated behavior; for a lifted choice (below) the same rule aggregates over every element in one pass, so a variant selected by at least one element survives for all of them. `ChoiceDomain.variants` itself is never narrowed (nothing analogous to `lo == hi` exists for it — mirrors bool) and no `default` is set (choice sampling is always generative; the pin alone fully determines it). Pinning a payload field alongside the discriminator needs no separate sugar — give both paths in the same `.freeze()` call (`freeze(algo="svm-rbf", **{"algo.svm-rbf.gamma": 0.1})`).

A **list** (`.repeat()`) is fixed by narrowing its own `count` to the literal length of the given value (dropping any prior `int`/expression count, mirroring real/integer's "drop any prior" narrowing) and setting `list_default` to the given value — except when its elements are choice-typed, where a bare discriminator selection is not a complete nested-config value for a payload-bearing variant, so `list_default` is left alone, mirroring choice's own no-`default` precedent. Each element is then pinned per its own kind: a scalar/custom/bool element by a per-instance `require(p[i] == value[i])`; a struct element by the same field fan-out rooted at `p[i]`; a nested list element by the same mechanism one level deeper (only the outermost `.repeat()` level's own domain is ever narrowed — a nested level's element facts are a template shared across every outer row, not a per-instance fact); and a lifted-choice element by a per-instance discriminator `require`, with variant pruning computed **once per list** over the union of variants selected by *any* of its instances, exactly the rule above generalized from one instance to many.

`.slice()` does not support a custom param (no substitution target for a `.prop()` expression's operand) — a path-named resolution error.

---

## Space — Metaprogramming

The IR is bidirectional:

```python
ds.param_from_def(pd: ParamDef) -> TypedParamExpr
ds.space_from_ir(params, conditions, constraints, anchors=None, meta=None) -> Space

.map_params(fn: Callable[[ParamDef], ParamDef]) -> Space     # sugar
.without_constraints(tags=...) -> Space                       # sugar
```

`TypedParamExpr` is the type-specific builder view for `pd`'s type (see *Builder view types*); when this surface lands (M8) it becomes the common base of those views. Until then the views subclass `ParamExpr` directly.

`param_from_def` inverts every scalar kind (real/integer/bool/categorical/ordinal/subset/permutation) and any list thereof, fingerprint-equal to the original. A struct or choice `ParamDef` (or a `"list"` `ParamDef` repeating one) has no single-`ParamDef` inverse — its descendants live as separate flat entries the lone `ParamDef` carries no reference to — so `param_from_def` **raises `TypeError`** for these, naming `space_from_ir` as the tool that reconstructs them from the full flat IR (where every descendant already exists as its own entry).

Resolution re-validates whatever comes in. Expressions are values — rewrites reattach existing `BoolExpr` objects; `.kind`/`.children` walking covers expression-level rewrites. `ds.all_`/`ds.any_` provide fold identities for generated constraint sets. Degenerate arities produced by generators are legal with defined semantics (see Degeneracy Table). A space-valued param (searching a catalog of inner spaces) needs no new machinery: a `.custom()` type with `fingerprint()` as value identity.

---

## The Representation Layer

A genotype **is a `Space`**. A representation is a `Space → Space` morphism carrying a value-level
pair, so a solver can ask the genotype the same questions it would ask any space — kinds, bounds,
conditionality, cardinality, fingerprint — instead of reverse-engineering structure from transformed
dicts.

```python
.represent(*rules: EncodingRule) -> Representation
```

`EncodingRule = Callable[[ParamDef], Encoding | None]`. Rules are tried in argument order per param;
the first non-`None` wins (**union dispatch**, not composition). `Encoding` is a per-param arrow
(see *Protocols*); `Representation` is the whole-space morphism (see *IR*).

### Two tiers

**Derived** — `space.represent(*rules)` builds the target mechanically from per-param `Encoding`s.
Path-preserving and arity-1, so the laws below are guaranteed by construction.

**Supplied** — `Representation(source=…, target=…, decode=…, encode=None)` constructed directly: the
consumer supplies the target `Space` (via `ds.space_from_ir`) and both value maps. Core supplies the
type, `then`, and `check()`; **no structural guarantee, no arity or path law**. This is where
morphisms core has no opinion about live — hierarchy flattening, foreign-format export, fixed-width
padding, imputation policies. A derived representation *is* a supplied one; both compose through
`then`. Soundness of a supplied morphism is the author's obligation, verified by `check()`, never
enforced.

`rep.check(n=200, seed=None)` samples the target, decodes, and asserts the conformance laws — the
suite as a tool, since a supplied morphism has no other way to be shown sound.

### Path and arity (derived only)

One source param maps to **one `ParamDef` at the same path**; kind and shape may change. Hence
`set(target.params) == set(source.params)` over *definition-path* keys — and a lift is a single key,
so genotype **dimensionality is unconstrained**: one-hot maps `algo` to a `list` of `real` still
keyed `algo`, its coordinates at instance paths `algo[0]…`.

A param `p` is **encodable** iff no other key of `source.params` begins `f"{p}."` or `f"{p}[]."` —
an encoding owns its whole subtree, and structs, payload-bearing choice discriminators, and
struct/choice lifts have descendants relocated into separate flat entries that nothing reconnects.
A *bare* choice has no descendants and is encodable, which is right: it is semantically a
categorical. Additionally, a param is **prop-excluded** if a `.repeat()` count or any `.prop()`
reads it — encoding it away from `custom` would dangle both. Violations are resolution errors.

### The induced chart representation

`space.represent()` with no rules. It touches exactly the params that carry a chart **at their own
level or at any element level of their `ListDomain` chain** — a scalar lift's chart lives in
`ListDomain.element_chart`, not on the `ParamDef`, and omitting those would drop whole vectors from
the genotype — **excluding** any param a count or `.prop()` reads. Each becomes `real(0, 1)`,
rewritten at the level the chart was found, with `periodic` mirrored onto the target (a periodic
real's `from_unit(1.0)` equals `hi`, which is *not* a domain member, so without the mirror `decode`
would not be total). Everything else is left alone — subset, permutation, categorical, bool, and
custom have no chart, and that is exactly what a solver needs to be told.

This is the only representation core ships. It is *induced*, not chosen: the chart is the coordinate
system the declaration already fixed. Every chosen genotype — one-hot, stick-breaking, random keys,
type bridges — is supplied by a consumer or a type author.

### Transport

Conditions and constraints are rewritten, never dropped. Three mechanisms, preferred in order:

1. **Leaf substitution** (`decode_expr`) — substitute the decode *into* the expression rather than
   restructuring it: `forbid(x + y > 10)` becomes `forbid(chart_x(x) + chart_y(y) > 10)`. Structure
   is untouched and multi-param nodes work, each leaf wrapping independently.
2. **Node rewriting** (`rewrite`) — optional, for solver-visible structure where substitution
   cannot reach: one-hot turning `algo == "adam"` into `(algo[1] > algo[0]) & (algo[1] > algo[2])`.
3. **Opaque transport** — core wraps the source expression as a `ds.value(...)` returning `bool`
   whose function decodes its operands and evaluates the source expression. Core can always do this,
   knowing both `decode` and the source AST, so **transport is total**.

Because nothing is dropped, target activity always matches source activity, and **feasibility
agreement holds by construction**. What differs is *quality*, reported as `opaque_conditions` /
`opaque_constraints`: structurally transported expressions keep margins and partial evaluation,
opaque ones do not (see *Constraints* on the white/grey/black tiers). Expressions are rewritten in
all four stores they inhabit — `Space.conditions`, each `ParamDef.condition`, `Space.constraints`,
and `ListDomain.element_constraints`. A projection (`p.field("w").sum()`) reads the lift's
*descendant*, not the lift its `params` set names, and must be rewritten at the projection node.

### Obligations

`decode` must be **total**: every config valid in `target` decodes to one valid in `source`.
Encodings divide by whether this is free. Charts, stick-breaking, random keys, and argmax are
surjective onto their domains by construction. A bool vector over a size-bounded subset, or an
adjacency matrix over a connectivity-constrained graph, is not — an invariant carried by the type's
`validate` that no genotype constraint can express means `decode` must **repair**, or the genotype
must be chosen so it cannot represent an invalid value. The failure is silent otherwise: the target
samples happily and produces invalid phenotypes.

`encode` is optional; `rep.invertible` is true when every applied encoding supplies it. It is what
warm-starting needs — anchors and historical observations are phenotypes, and seeding a solver with
them is `rep.encode(config)`. `measure_preserving` is likewise per-encoding and declared, never
assumed; core proves it only for the induced representation, where `chart(u)` on `u ~ U[0,1]` *is*
the declared measure.

**Defaults and anchors are phenotype values.** `ParamDef.default` and `Space.anchors` hold values in
source units, so only `encode` can carry them into a genotype target. Where the applied encoding
supplies it, `represent()` encodes them and **validates the result itself** rather than trusting the
assembler; where it does not, they are dropped and reported (`dropped_defaults`,
`dropped_anchors`). A default drops per param; an **anchor drops whole**, since a config missing an
active param is not a valid anchor. The drop is not a corner case — an `Encoding` need not supply
`encode` at all, and even the induced representation cannot encode a param whose external `Prior`
offers `ppf` without `cdf` (that chart decodes but cannot encode; see *Charts*). Carrying an
unencoded phenotype value across is the failure this prevents: a `1e-3` default lands inside a unit
target's `[0,1]` and passes the domain check while meaning something else entirely.

Operators never live on `ParamType`: neighborhoods and distances are properties of a genotype, and
the same phenotype admits many.

---

## Identity and Serialization

### to_json / from_json

```python
.to_json(on_unserializable="raise") -> dict
Space.from_json(data, custom_types=None) -> Space        # classmethod
.to_json_schema() -> dict                                 # oneOf per choice; dependency-free
```

The JSON document carries a single integer **format version**; `from_json` raises on unknown versions. The non-serializable set is closed and enumerated: the `.custom(sampler, validator)` shorthand, `code`/`symbolic` `validators`, `symbolic` `sampler`, `Primitive.fn`, **`ds.value`'s `fn`**, and **external `Prior` objects** — any `.ppf`/`.cdf` object supplied to `.prior()`, which carries no structural `describe()` protocol of its own. (`Encoding` and `Representation` instances never enter the IR; a representation's *target* is an ordinary `Space` and serializes as one, so encoding a param whose source form is non-serializable can leave the genotype serializable where the phenotype was not — the observation key remains the pair `(fingerprint, config_hash)`, so this identifies the proposal domain, not the phenotype space.) Built-in prior families (`Log`/`Logit`/`Power`, the categorical/ordinal/bool/choice/subset `Weights` payload, and the uniform default) are fully structural and always serialize; only external `Prior` objects are opaque, riding the same raise / `mark` (`{"$opaque": true}`) / `drop`-plus-manifest path as callables. `on_unserializable="drop"` writes the space without those sites plus a manifest of omissions — the reconstructed space is a *different* space by design.

Custom params serialize as `type_key` + the `describe()` output; `from_json` requires a `custom_types` registry entry mapping `type_key → factory` where `factory(describe_dict)` reconstructs the instance.

**Round-trip law** (fully serializable spaces): `Space.from_json(s.to_json()).fingerprint() == s.fingerprint()` at both scopes.

### fingerprint()

```python
.fingerprint(scope="full", on_unserializable="raise") -> str    # "1:full:9f2c…"
```

A stable identifier of the **resolved space** — post-resolution IR, never builder expressions. Output: preimage-format version (shared with `to_json`'s version counter), scope, 64 hex chars of SHA-256.

Equal fingerprints guarantee identical valid-config sets, sampling measure, path namespace, introspection, and `to_json` documents (up to derived fields). Unequal fingerprints guarantee nothing: identity is **structural after desugaring** — semantically equivalent encodings (bool+`when` vs. two-variant choice) fingerprint differently by design, and no algebraic normalization of expressions is attempted (`a & b ≠ b & a`).

**Scopes:**

| Component | `full` | `sampling` |
|---|---|---|
| Params: definition path, kind, domain, prior, quantized, periodic, condition | ✓ | ✓ |
| Conditions, forbids, requires | ✓ | ✓ |
| Declared (`.encourage`/`.discourage`) constraints | ✓ | — |
| Defaults, tags, meta, anchors | ✓ | — |
| Format version | ✓ | ✓ |

`sampling` identifies feasible set + measure + chart geometry (warm-start/surrogate transfer); `full` is document identity. Derived fields (`Constraint.params`, `dependency_graph`) never enter the preimage. More generally, **no preimage-excluded field may be feasibility- or semantics-load-bearing** — in particular `Constraint.origin`, which is why a **polarity-opposite constraint** (`origin` `bound`, `require`, or `discourage` — one that stores the polarity-inverse predicate from its `user`-origin baseline) is canonicalized to its baseline-polarity form in the pipeline below (step 1) rather than distinguished by `origin`.

**Normalization pipeline:** (1) resolve and desugar — sugared and explicit spellings of the same space are fingerprint-equal, including variadic `.repeat(*counts)` vs. the chain and expression bounds vs. their manual envelope-plus-constraint expansion; a **polarity-opposite constraint** (a bound-origin sugar, a `require`, or a `discourage`; `origin` `bound`, `require`, or `discourage`) is canonicalized to its **baseline-polarity (negated) form** before hashing, by one of two provenance-specific mechanisms (D-38/D-39): a **bound** sugar, always a single top-level `Compare`, negates by **operator flip** (`x <= y` → `x > y`, so a bound `x <= y` is fingerprint-equal to its feasibility-equivalent `.forbid(x > y)`); a **`require`** or **`discourage`**, which store an arbitrary predicate `e`, negate the **whole expression** (`e` → `~e`, so `require(e)` is fingerprint-equal to `.forbid(~e)` and `discourage(e)` to `.encourage(~e)`). Each is fingerprint-*distinct* from the polarity-opposite spelling (`.forbid(x <= y)` / `.forbid(e)` / `.encourage(e)`). **Semantic vs. syntactic:** `require(x <= y)` and `.forbid(x > y)` name the *same feasible set* — a **feasibility** equivalence — but are fingerprint-**distinct**, because `require` canonicalizes to `~(x <= y)` (a `Not` node), not the operator-flipped `x > y`; equal fingerprints imply equal feasible sets, but the converse never holds, so distinct fingerprints for identical feasibility are allowed. This puts the polarity in the preimage while `origin` itself stays excluded; (2) declaration order preserved, not sorted — permuted params or variants differ; `.when(a).when(b)` folds in call order; (3) unordered collections sort — tags lexicographically, meta/anchors by key; (4) float canonicalization — `−0.0 → 0.0`; NaN/inf are resolution errors wherever floats occur in the IR; (5) type tags at **every `Any`-typed leaf** — categorical/ordinal values, subset/permutation `items`, `is_in`/`count_of`/`sum_over` literal operands, defaults (`default`, `list_default`, `element_default`) and anchor entries, and meta values — each encodes as `{"$t": "int", "v": 1}` with tags `bool|int|float|str|null`, so `categorical(1, 2)` ≠ `categorical(1.0, 2.0)`; list/dict-shaped values (struct/list defaults, nested meta) are tagged **recursively**, per scalar leaf, the same codec as a flat default; positions that never hold `Any`-typed application data (paths, `op`/`type_kind`/variant-name strings, `hard`/`periodic` booleans, literal repeat counts) stay untagged; (6) expressions encode as ASTs — node kind, children in operand order, paths as grammar strings, literals type-tagged.

The normalized document is serialized per **RFC 8785 (JCS)** (via the `rfc8785` dependency; see Dependencies) and hashed with SHA-256. (JCS serializes `1.0` as `1` — which is precisely why type tags precede canonicalization.)

**Callables:** default raise, listing offending sites by definition path — same set as `to_json`. `on_unserializable="mark"` replaces each callable with the sentinel `{"$opaque": true}` at its site — *mark, not drop*: presence is identity-relevant. Documented limitation: two spaces differing only in a callable's behavior at the same site are fingerprint-equal under `"mark"`; content identity requires the serializable protocol (`type_key` + `describe()`).

### config_hash

Reuses the same canonical config encoding (type tags, float rules, grid canonicalization; subsets sorted, inactive stripped) but does **not** embed the space fingerprint. The globally unique observation key is the pair `(space.fingerprint(), ds.config_hash(config, space))`. Anchors in the `full` preimage use this same encoding.

---

## Config Utilities

```python
ds.flatten(config, space) -> dict[str, Any]     # path-grammar keys; non-validating
ds.unflatten(flat, space) -> dict               # inverse
ds.config_hash(config, space) -> str            # non-validating (built on flatten)
ds.config_diff(a, b, space) -> list[ParamDiff]  # structural, no magnitude; plain ==; non-validating
ds.variant(config, param_path) -> str           # active variant name of a choice
ds.payload(config, param_path) -> dict | None   # variant payload; None for bare variants
ds.destructure(config, param_path) -> tuple     # (name, payload) — a derived view;
                                                #   tuples are never valid config values

.coordinate_paths() -> tuple[str, ...]          # on Space: the fixed leaf layout (below)
```

`variant`/`payload`/`destructure` accept **instance paths** into a lifted choice — `variant(config, "pipeline[1]")` returns that element's variant name, `payload(config, "pipeline[1]")` its payload — using the path grammar's `[k]` indexing (self-describing, so these utilities still take no `Space`). Addressing a lifted choice by its **bare list path** (`"pipeline"`) is a misuse error naming the indexed form, since a list has no single variant; the scalar return types are preserved.

`config_hash` and `config_diff` are **non-validating**, like the `flatten` they are built on: they walk whatever keys structurally match `space.params` and ignore the rest rather than raising (`config_hash` still grid-canonicalizes near-grid values). A caller wanting a validated key composes with `validate()` first (`if space.validate(c).valid: key = config_hash(c, space)`). `config_diff` compares leaves by **ordinary Python `==`** — so `1` and `1.0` are *not* reported as a change — distinct from `config_hash`/`fingerprint`'s type-tagged equality, since a diff is a structural report, not a hashing law.

`config_diff`: a variant switch decomposes into the discriminator diff (old/new are variant **names**) plus newly-inactive/newly-active payload diffs using the `None` conventions. Repeat length changes align **positionally** — an insertion-at-front reports as a full rewrite; alignment-aware diffing is consumer polish.

### The fixed leaf layout

`space.coordinate_paths()` returns the ordered instance paths of the space's **leaf entries**, excluding the lift-length entries `flatten` emits as structural bookkeeping. It is the layout a consumer needs to pack a config into a positional container — a solver's parameter vector, most obviously — and it exists because deriving it is *not* a two-line filter: `flatten` emits `x` as an outer count, `x[0]` as an inner count, and `x[0][0]` as a coordinate, so telling data from bookkeeping means walking the `ListDomain` chain one bracket group at a time. Getting it wrong produces a config that still validates and is not the one you started with.

It requires a **fixed layout**, meaning every `.repeat()` count in the space is a literal integer and no param carries a condition. Either one makes the key set config-dependent, so no positional layout exists; both are path-named resolution errors (row 33) rather than a silently config-specific answer. Struct params never appear (they have no value of their own).

A fixed layout is *not* the same as numeric packability, and the spec keeps them apart because they fail differently. `subset` and `permutation` leaves have a **stable key** but a variable-length list value; `categorical` and `ordinal` leaves are scalar but not numeric. Both appear in `coordinate_paths()` — they are genuine coordinates of the space — and a caller packing floats will fail on them at the point of conversion, which is the right place. A genotype produced for a real-vector solver satisfies both conditions by construction; that is what makes it one.

`unflatten` completes the round trip: for a **static** count it recovers the length from the `ListDomain` rather than requiring the bookkeeping key, so `ds.unflatten(dict(zip(space.coordinate_paths(), values)), space)` is the inverse of reading those paths out of `flatten`. This is a fallback for *absence* only — a **present** bookkeeping key always wins over the `ListDomain`'s declared static count (D-75), matching `unflatten`'s non-validating posture everywhere else: it is `flatten`'s own realized length for the config at hand, the more specific of the two signals. Packing into any particular container — dtype, shape, batch conventions — stays with the consumer.

`unflatten` takes no activity argument, so a struct's presence is inferred from whether any descendant leaf is present: a zero-declared-member struct round-trips as `{}`, but an *active* struct all of whose members are individually inactive is indistinguishable from an *inactive* struct and is omitted. "Unconditionally-present" (the `.space()` struct type) describes **validity** — a struct's activity never depends on its own members' activity — not a guarantee about `unflatten`'s output shape.

---

## Config Representation

Nested dicts are canonical phenotypes. Inactive params are **absent**.

```python
{"optimizer": {"adam": {"beta1": 0.9, "beta2": 0.999}}}         # choice, parameterized
{"optimizer": "sgd"}                                             # choice, bare
{"n_layers": 2, "layers": [{"width": 128}, {"width": 256}]}     # struct lift
{"dropout": [0.1, 0.3, 0.0, 0.5]}                                # scalar lift
{"pipeline": ["shuffle", {"pmx": {"swap_p": 0.2}}]}              # lifted choice
{"encoder_norm": {"type": "layer", "eps": 1e-5}}                 # struct param
{"ops": ["rotation", "mixup"]}                                   # subset
{"order": ["age", "income", "tenure"]}                           # permutation
{"schedule": {"ast": ..., "source": "cos(pi * step / total)"}}   # symbolic
{"loss_fn": {"source": "def loss(pred, target): ..."}}           # code
{"tree": <ParamType.to_json output>}                             # custom
```

**DataFrame output** (`space.sample()`). Column names follow the path grammar. Inactive params are `null` (the dict-config principle doesn't govern columnar containers). A lift level with a **static** count emits `Array(dtype, n)` instead of `List`; the rule applies per level, so outer-dynamic-inner-static yields `List(Array(...))`. The rule is deterministic and conformance-tested.

| Type | Column(s) |
|---|---|
| real (incl. periodic) | `Float64` |
| integer | `Int64` |
| categorical, ordinal | `Utf8` |
| bool | `Boolean` |
| subset, permutation | `List(...)` |
| choice | `Utf8` discriminator at the param path + one `Struct` per parameterized variant at `param.variant` (null when inactive) |
| struct param | `Struct` |
| scalar lift | `List(dtype)` |
| struct lift | `List(Struct)` |
| lifted choice | `List(Struct{variant: Utf8, <variant>: Struct \| null, …})` |
| symbolic, code, custom | `Utf8` (JSON string) |

---

## Protocols

```python
class ParamType(Protocol):
    type_key: str                                 # required — identifies the type in serialization,
                                                    #   the from_json registry, and solver adapters
    def validate(self, value) -> bool: ...
    def to_json(self, value) -> Any: ...
    def from_json(self, data) -> Any: ...
    def describe(self) -> dict: ...                # MUST be JSON-serializable

    # Optional capabilities — each checked structurally (hasattr), never
    # required; a type declares only the ones it supports.
    def sample(self, rng) -> Any: ...               # generative iff present (see Sampling and
                                                      #   Generativity); the .custom(sampler, validator)
                                                      #   shorthand is always generative
    def cardinality(self) -> int | None: ...         # contributes a finite factor to
                                                      #   Space.cardinality() iff present
    def properties(self) -> dict[str, type]: ...     # enables .prop() in constraints, together with
                                                      #   extract() below — expression-visible props:
                                                      #   int|float|bool|str only
    def extract(self, value, prop: str) -> Any: ...


class Encoding(Protocol):                          # genotype for ONE param
    def target(self, param: ParamDef) -> ParamDef: ...          # required; same path
    def decode(self, param: ParamDef, value: Any) -> Any: ...   # required; genotype → phenotype

    # Optional capabilities — each checked structurally (hasattr), never
    # required; an encoding declares only the ones it supports.
    def encode(self, param: ParamDef, value: Any) -> Any: ...   # phenotype → genotype;
                                                                  #   present ⇒ invertible
    def decode_expr(self, param: ParamDef) -> Expr | None: ...   # decode as an expression, for
                                                                  #   structural transport
    def prop_expr(self, param: ParamDef, name: str) -> Expr | None: ...  # a phenotype property as
                                                                  #   a genotype expression
    def rewrite(self, param: ParamDef, node: Expr) -> Expr | None: ...   # per-node structure where
                                                                  #   substitution cannot reach
    def measure_preserving(self) -> bool: ...      # declared, never assumed


class Prior(Protocol):
    def ppf(self, q: float) -> float: ...      # required
    def cdf(self, value: float) -> float: ...  # optional; required when support exceeds bounds
```

**Value convention.** `validate`/`sample`/`extract` operate on the type's own *native* representation. `to_json`/`from_json` are the only bridge between that native form and the JSON-safe **phenotype** form every public, config-dict-shaped surface holds instead — a config leaf, `sample_one()`'s return value, `.validate()`, `.freeze()`, `.default()`. Core calls `to_json` once, immediately after `sample()` produces a fresh native value; it calls `from_json` immediately before it needs to call `validate`/`extract` on a config-sourced value. The `.custom(sampler, validator)` shorthand has no `to_json`/`from_json` — native and phenotype coincide (`sampler(rng)`'s return value is used directly).

**Custom-type contract laws:** `factory(x.describe()) ≡ x` (registry round-trip); `extract` is called only on values that passed `validate`; when payload lifts align to a custom value by index (`.repeat(ds.param("g").prop("n_edges"))`), the type must define a **canonical ordering** stable under JSON round-trips; a type embedding non-serializable content is responsible for raising in its own `to_json` — core cannot see inside `describe()` output beyond checking it is JSON-serializable.

---

## Support Types

```python
ds.Signature(args: dict[str, type | str], returns: type | str)
ds.FloatLiteral(lo, hi)               # ephemeral constant in .symbolic(); carries a chart
ds.IntLiteral(lo, hi)                 # likewise (floor rule)
ds.Primitive(name, arity, fn=None)    # user-defined operator in .symbolic()
ds.Log()  ds.Logit()  ds.Power(p)     # built-in prior families (see Charts)
ds.value(fn, *operands, returns)      # opaque derived quantity (see Expressions)
```

`.symbolic()` built-in primitives: `+ - * / ** % abs min max cos sin exp log pi e`. Unknown string primitives raise at resolution.

---

## IR

```python
@dataclass
class ParamDef:
    path: str                     # definition path
    type_kind: str                # "real" | "integer" | ... | "space" | "choice" | "list"
    domain: Domain                # type-specific; recursive: list(element_domain)
    prior: Prior | None           # also holds a Weights payload for categorical/ordinal/bool/choice/subset
    quantized: QuantizedSpec | None   # step/factor/include_hi grid spec; None otherwise
    periodic: bool
    default: Any | None
    condition: BoolExpr | None
    tags: frozenset[str]
    meta: dict[str, Any]
    chart: Chart | None           # None for non-chart kinds; always static

# One domain class per kind, each carrying exactly that kind's declared facts
# (RealDomain(lo, hi), SubsetDomain(items, min_size, max_size), ...). ListDomain
# is recursive and holds every element-level fact — element_chart,
# element_default, count, list_default, element_constraints — which is why a
# lift's own ParamDef is chartless. A struct/choice element's descendants are
# not here: they are relocated into Space.params under a "[]"-prefixed path.
Domain = (
    RealDomain | IntegerDomain | CategoricalDomain | OrdinalDomain | BoolDomain
    | SubsetDomain | PermutationDomain | ChoiceDomain | StructDomain
    | CustomDomain | ListDomain
)

class Chart(Protocol):
    def from_unit(self, u: float) -> Any: ...
    def to_unit(self, value) -> float: ...                # interval midpoint for integers/grids

@dataclass
class Constraint:
    expr: BoolExpr                # stored as the author wrote it; a polarity-opposite
                                  #   constraint (bound/require/discourage) stores the
                                  #   predicate whose polarity is inverse to its user
                                  #   baseline (require stores DESIRED x <= y; discourage
                                  #   stores the BAD state)
    hard: bool                    # True = forbid/require (feasibility), False = declared
    origin: str                   # "user" | "bound" | "require" | "discourage" — derived
                                  #   provenance; excluded from fingerprint preimage. NOT
                                  #   semantics-neutral: it selects the stored polarity, so
                                  #   the preimage canonicalizes a bound/require/discourage
                                  #   to baseline-polarity form to keep `origin` non-load-
                                  #   bearing (see Identity — Normalization pipeline).
                                  #   Read `kind`/`feasible_when_satisfied` instead of `origin`.
    tags: frozenset[str]
    meta: dict[str, Any]
    params: frozenset[str]        # derived; excluded from fingerprint preimage

    # Derived, non-serialized polarity accessors (read these, not origin/hard):
    @property
    def kind(self) -> str: ...     # "forbid"|"require"|"encourage"|"discourage"|"bound"
    @property
    def feasible_when_satisfied(self) -> bool: ...  # False only for forbid/discourage

@dataclass
class Condition:
    target: str
    expr: BoolExpr
    params: frozenset[str]        # derived

@dataclass
class ConstraintEval:
    constraint: Constraint
    instance_path: str | None     # set for per-element instantiations
    applicable: bool              # False when Kleene-Unknown on a complete config
    satisfied: bool | None        # None when inapplicable
    margin: float | None

    @property
    def violated(self) -> bool: ...  # polarity-correct across all kinds: an inapplicable
                                     #   eval is never violated; else satisfied differs from
                                     #   constraint.feasible_when_satisfied (== eval.is_violated)

@dataclass
class ValidationResult:
    valid: bool
    param_errors: list[ParamError]
    constraint_evals: list[ConstraintEval]

@dataclass
class ParamError:
    param: str                    # instance path
    reason: str                   # "missing" | "out_of_bounds" | "wrong_type"
                                  # | "inactive_but_present" | "not_on_grid"
    value: Any | None

@dataclass
class PartialEval:
    param_status: dict[str, str]  # "set" | "active_unset" | "inactive" | "unknown"
    evaluable_constraints: list[ConstraintEval]  # determined value; inactive-only
                                                 #   Unknown ⇒ applicable=False
    pending_constraints: list[Constraint]        # Kleene-Unknown on an active_unset/
                                                 #   unknown operand
    n_remaining: int                             # count of active_unset params (a lower
                                                 #   bound while a lift count is unknown)

# remaining_domain's per-kind descriptor — a closed union. Sound, not complete:
# never excludes a still-feasible value (may admit values an unreduced
# multi-operand coupling would forbid). See "Space — Partial Configs".
@dataclass
class RealRemaining:
    lo: float
    hi: float
    lo_inclusive: bool            # hi_inclusive is False for a periodic real ([lo, hi))
    hi_inclusive: bool
    grid: QuantizedSpec | None    # when quantized, the legal set is grid ∩ [lo, hi]

@dataclass
class IntegerRemaining:
    lo: int
    hi: int
    grid: QuantizedSpec | None

@dataclass
class ValueRemaining:             # bool, categorical, ordinal, choice
    values: tuple[Any, ...]       # still-legal values (choice: still-legal variant names)

@dataclass
class SubsetRemaining:
    forced_in: tuple[Any, ...]
    forced_out: tuple[Any, ...]
    free: tuple[Any, ...]
    min_size: int
    max_size: int

@dataclass
class PermutationRemaining:       # no per-item reduction under the guarantee; echoes items
    items: tuple[Any, ...]

RemainingDomain = (
    RealRemaining | IntegerRemaining | ValueRemaining
    | SubsetRemaining | PermutationRemaining
)

@dataclass
class ParamDiff:
    param: str                    # instance path
    old: Any | None               # None if newly active
    new: Any | None               # None if newly inactive

@dataclass
class SubspaceInfo:
    prefix: str                   # definition-path prefix
    kind: str                     # "struct" | "variant"
    member_paths: tuple[str, ...] # descendant definition paths relocated under prefix
    condition: BoolExpr | None    # folded activation condition gating every member —
                                  #   a struct's own `.when()`; a variant's ANDed with
                                  #   its discriminator equality
    variant_name: str | None = None  # set only for kind == "variant"

@dataclass(frozen=True)
class ConstraintReport:
    constraint: Constraint
    applicable: float             # fraction of all draws where Kleene-defined
    satisfied: float              # fraction of APPLICABLE draws satisfied

@dataclass(frozen=True)
class SamplingReport:             # see Sampling diagnostics
    n: int
    acceptance_rate: float        # fraction passing every hard constraint
    constraints: tuple[ConstraintReport, ...]
    activity: Mapping[str, float] # per-param active fraction

@dataclass(frozen=True)
class Representation:             # a Space → Space morphism; see The Representation Layer
    source: Space                 # phenotype
    target: Space                 # genotype — an ordinary Space
    encoded: tuple[str, ...]
    excluded_by_prop: tuple[str, ...]        # params a repeat() count or .prop() reads
    opaque_conditions: tuple[str, ...]       # transported opaquely, not structurally
    opaque_constraints: tuple[Constraint, ...]
    dropped_defaults: tuple[str, ...]        # phenotype defaults no encode() could carry
    dropped_anchors: tuple[str, ...]         # anchor keys likewise (an anchor drops whole)
    invertible: bool              # every applied encoding supplies encode()
    measure_preserving: bool      # every applied encoding declares it

    def decode(self, genotype: dict) -> dict: ...      # total
    def encode(self, phenotype: dict) -> dict: ...     # raises unless invertible
    def then(self, other: Representation) -> Representation: ...
    def check(self, n: int = 200, seed=None) -> ...    # the conformance laws, as a tool
```

A `Representation` **never enters the IR**, `to_json`, or the fingerprint preimage — its target is
an ordinary `Space` and serializes as one. `then` requires `other.source` to fingerprint equal to
`self.target` (a `TypeError` otherwise — misuse, not resolution); `decode` composes right-to-left,
`encode` in reverse and only when both sides are invertible.

---

## Resolution

1. Collect exprs, flatten nested spaces
2. Type-check — every param has exactly one type; layer placement of modifiers
3. Desugar — `log_scale`, `implies`, layer folding
4. Resolve references — paths bind; types compatible
5. Cycle detection on the condition, bound, and repeat-count dependency graph, including self-reference
6. Compute bound envelopes (interval arithmetic along the dependency DAG); desugar expression bounds into envelope bounds + bound-origin constraints; build charts — all static
7. Validate defaults (static domains), anchors, priors, weights
8. Emit IR

**Resolution timing.** Resolution is unspecified relative to construction. A space built in argument position (a choice variant or struct body) may carry a `.when()` condition that references a param binding only in an *enclosing* scope — the sole scoping rule's up-walk — which cannot resolve while that payload is built standalone. Reference, type, and cycle checks (rows 6, 7, 14) over such conditions are therefore deferred to a finalization pass over the fully-merged space, and any resulting error surfaces no later than the **first terminal operation** — `sample`, `sample_one`, `validate`, `validate_param`, `evaluate_constraints`, and (once implemented) `fingerprint`, `to_json`, and every introspection surface must trigger this finalization. The error is still a `ResolutionError` (phase R), computed from space structure alone with no config; only its timing moves. Constraint (`.forbid()`/`.require()`/`.encourage()`/`.discourage()`) references stay strict and raise eagerly, since cross-scope constraints use the down-reference-at-the-common-ancestor route instead. **Expression-bound** references are likewise eager (never deferred): the bound's chart envelope must be computed during the declaring scope's own resolution, before any enclosing scope merges, so a bound expression tolerates no enclosing-scope up-reference — a cross-scope bound coupling is written by hand at the common ancestor (see *Expression bounds are sugar*).

### Error table

Tagged **R** (resolution-time) or **V** (validation/fill/sample-time).

| # | Error | Tag |
|---|---|---|
| 1 | Duplicate param names in a scope | R |
| 2 | Param with no type, or more than one type method | R |
| 3 | Duplicate declared values (categorical, ordinal, subset items, permutation items; type-tagged equality) | R |
| 4 | Mixed-type categorical values sharing a string image | R |
| 5 | Name or variant name containing `.` `[` `]` — checked on the resolved name for all syntactic routes; duplicate variant names within one choice | R |
| 6 | Reference to a nonexistent param (condition, bound, constraint); `[]` definition path in an expression; `.field()` on a non-struct lift or naming an undeclared element field | R |
| 7 | Cycle in the condition/bound/repeat-count dependency graph; a param's condition, bounds, or repeat count referencing itself | R |
| 8 | `lo > hi`; non-finite bound; NaN/inf anywhere in IR floats | R |
| 9 | `log_scale`/`Log` with non-positive `lo`; `Logit` outside `(0,1)`; `Power` domain violation (`p == 0`; non-integer `p` with `lo < 0`; `p < 0` with `lo ≤ 0`; a domain straddling 0 when `p` is not a positive odd integer) | R |
| 10 | `quantized`: `step ≤ 0`, `factor ≤ 1`, non-finite, or both given | R |
| 11 | Misplaced layer modifier (e.g. `.repeat(n).log_scale()`); domain-level modifier applied to an incompatible type (e.g. `.prior(weights=…)` on a real) | R |
| 12 | Repeat count not integer-typed | R |
| 13 | Evaluated repeat count negative | V |
| 14 | Arithmetic on ordinal or categorical; ordering comparison (`<`, `>`, `<=`, `>=`) on a categorical; ordinal–ordinal comparison over differing value sequences | R |
| 15 | Unknown `.symbolic()` primitive | R |
| 16 | `.prop()` on undeclared property; non-scalar property type; type mismatch in comparison | R |
| 17 | Prior weights: wrong length; subset inclusion probabilities outside `[0,1]`; categorical/ordinal/bool/choice weights negative or all-zero | R |
| 18 | `sum_over` keys outside the item universe; `position_of` non-member; `.contains()` on permutation; ordinal comparison against a literal that is not a declared value | R |
| 19 | External prior support exceeding (envelope) bounds without `cdf` | R |
| 20 | Bound expression with no computable interval hull (workaround: write the desugared form by hand) | R |
| 21 | Default outside domain (scalar, choice variant, subset, or permutation); `.default()` on a struct param (no own value — completion is field-wise); list default under dynamic count; list default length mismatch; element and list default together | R |
| 22 | Anchor invalid against the space; anchor conflicting with a frozen/sliced value | R |
| 23 | Empty-string tag; non-JSON-serializable meta value; non-JSON-serializable `describe()` output | R |
| 24 | `is_sorted` on a lift nested deeper than one level | R |
| 25 | `==` over purely continuous unquantized aggregate/operands | R (warning) |
| 26 | Sampling retry exhaustion; non-generative materialization without default | V |
| 27 | `from_json`: unknown format version; missing `custom_types` entry for a `type_key` | V |
| 28 | Subset size bounds nonsensical: `min_size > max_size`; `min_size < 0`; `min_size` exceeds the item universe | R |
| 29 | Instance index out of range against a **static** count; boolean operator applied to a lift-valued operand; `.choice()` payload that is not a `Space` | R |
| 30 | `ds.value`: non-scalar `returns`; an operand that is not an expression | R |
| 31 | `Encoding.target()` returning a path other than the source param's; `rewrite()`/`decode_expr()` output referencing anything outside that param's own paths, or an out-of-range instance index | R |
| 32 | Encoding a param with relocated descendants (struct, payload-bearing choice discriminator, struct/choice lift), or one a `.repeat()` count or `.prop()` reads | R |
| 33 | `coordinate_paths()` on a space with no fixed layout: a dynamic `.repeat()` count, or a param carrying a condition | R |

### Degeneracy table

Generated spaces produce degenerate arities constantly; the default is *allow with defined semantics*:

| Case | Semantics |
|---|---|
| Single-variant choice | Legal; discriminator is constant |
| Single-value categorical / ordinal | Legal; constant |
| `lo == hi` | Legal; constant chart, still generative |
| `step ≥ hi − lo` | Legal; single-point grid `{lo}` (+ `hi` if `include_hi`) |
| Zero repeat count | Legal; value `[]`; see empty-aggregate rules |
| Empty subset item universe | Legal; value always `[]` |
| Permutation of 0 or 1 items | Legal; constant |
| `ds.space()` | Legal; identity for `.extend()` |
| `ds.all_()` / `ds.any_()` | Literal `True` / `False` |

---

## Solver Integration

A solver defines the space it can work with — base CMA-ES is R^n, variants add integers and categoricals, SMAC and irace add conditionals, others work on graphs. Pointing one at a `Space` therefore has exactly three shapes:

**Interpret the `Space` directly.** A solver that understands the IR walks `topological_order` → determines activity via conditions → embeds active generative params in u-space via their charts → proposes → decodes → checks margins. Charts give every solver a free, type-appropriate perturbation — mutate in u-space, decode through the chart — so log-scaled params get multiplicative noise and grids snap correctly with zero per-type code. Core still ships no operators. Negotiation is ordinary introspection: the solver checks kinds, `is_conditional`, `has_variable_length`, `ParamDef.chart is not None`, `ParamType.type_key`, and fails with its *own* message, since only the solver knows what it supports.

**Convert the `Space` to a foreign representation.** ConfigSpace and kin. Core ships no adapter and takes no dependency; the public, bidirectional IR is the socket.

**Bridge with a `Representation`.** When the solver's genotype differs from the phenotype, `space.represent(*rules)` produces a genotype `Space` plus `decode`/`encode` (see *The Representation Layer*). `rep.target` is an ordinary space, so the first shape applies to it unchanged — which is the point: a bridge does not need a new negotiation vocabulary.

The open world (`.custom()`) negotiates per param, two independent channels:

**Generation ladder** (richest available rung wins): native adapter recognizing `type_key` → a `Representation` whose target this solver can handle (geometry authored by the type author, loss declared not silent) → opaque `sample(rng)` (sufficient for random search and resampling moves).

**Modeling channel**, orthogonal to generation: `properties()` featurizes values for surrogates and reporting regardless of production rung; `to_json`/`config_hash` give observation identity. A type opaque to generation can be rich to modeling.

**Adapter conventions** (strategy-entangled operations — crossover schemes, mutation policies, trust regions — are the only thing genuinely forced into adapters): keyed by the same `type_key` used in serialization; receive the live `ParamType` instance and derive all domain facts from it (`describe`, `validate`, `extract`) rather than re-declaring; receive a `Representation` rather than embedding one; scoped per *(capability, type)*, not per *(solver, type)*.

A custom type that other params depend on through `.prop()` — a lift count, a constraint — cannot be bridged away from `custom` without dangling them. Type authors who want their type bridgeable should keep prop-driven alignment out of the space, or supply a bridge whose target is another `custom` exposing the same properties. This cuts against the tier-3 guidance below, which steers exactly the bridge-worthy structures toward carrying properties; the tension is real and belongs to the modeler.

**Structured values — tier guidance** (graphs, layouts, schedules, and kin):

1. **Parametric family** — a choice over named topologies/patterns. Fully primitive; use when the structure is nameable.
2. **Primitive decomposition** — element lifts with index params and per-element constraints. Use when constraints are local to elements; *static* counts additionally admit machine-generated unrolled pairwise constraints (metaprogramming). Rejection degrades near packing limits.
3. **Custom type with constructive sampler + properties** — use when invariants are global (connectivity, pairwise spacing) or rejection-hostile. Draw the ownership boundary at **coupling to the constructive invariant**: params coupled to it go inside the type; independent payloads stay primitive (keeping charts and priors), aligned by prop-driven lift counts under the canonical-ordering law.

The permanent expression-language boundary: value-dependent indexing (`islands[edges[k].src]`) and quantification over dynamic ranges are excluded — relational semantics belong to tier 3 or the consumer. Prefer generative reparameterization over measure-zero constraints (stick-breaking for simplexes) — the space stays primitive and chart-covered, the manifold geometry rides in an `Encoding`.

**Choosing mechanisms** (semantically overlapping encodings are structurally distinct — no normalization is attempted): bool + `.when()` for one or two dependents; choice for alternatives or heavier payloads; struct for pure grouping; bool-per-item + `.when()` + `ds.count()` when subset members need payloads.

---

## Errors, Concurrency

Exception taxonomy: `DesignSpaceError` (base) → `ResolutionError` (table above, R rows), `SerializationError`, `SamplingError`. Misuse guards (`__bool__`, `__contains__`) raise plain `TypeError`. A **missing optional dependency** likewise raises a plain `ImportError` naming the extra, never a `DesignSpaceError`: the taxonomy is reserved for semantic findings about a design space, and an uninstalled package is an environment fact. Validation-time findings surface as `ParamError` records inside results wherever a result object exists; only operations with no result channel raise.

All public objects — expressions, spaces, IR dataclasses, charts — are immutable after construction and safe to share across threads. RNG state is passed explicitly (`seed` / `Generator`); nothing mutates shared state.

---

## Dependencies

Core: `numpy` (RNG) and `rfc8785==0.1.4` (pure-Python, `py.typed`, no transitive dependencies) for the RFC 8785 (JCS) number/byte canonicalization behind `fingerprint`/`config_hash`. `rfc8785` is pinned **exactly**, not `>=`: an already-frozen digest format wants its number-formatting library pin-stable, since a transitive bump could silently shift every committed known-answer vector — bumping the pin is a deliberate act under the format-version protocol. Built-in priors are implemented internally — no distribution-library dependency; any `Prior`-satisfying object (scipy frozen distributions, preliz) plugs in. Extras: `designspace[polars]` for `space.sample()`'s DataFrame output (`sample_dicts()`/`sample_one()` need no extra); `designspace[pydantic]` for model export. `space.sample()` is the only surface that imports `polars`, lazily; absent it, the call raises a plain `ImportError` naming the extra and pointing at the no-extra sampling paths (see *Errors, Concurrency* for why this stays outside the exception taxonomy).

---

## Conformance Laws

The spec's executable laws double as the acceptance suite:

- **Charts:** known-answer vectors for the four families (including subnormal-range log); floor-integer uniformity; quantized cell measure (uniform ⇒ equiprobable grid); grid canonicalization invariance under bit-different representations.
- **Kleene:** the truth table; `count` range rule; non-`count` aggregates plain-propagate Unknown (no range tracking); empty-aggregate values; inactive-lift-projection ≠ active-empty-list; **Unknown provenance** — `.if_inactive()` coalesces inactivity, propagates pending, and propagates emptiness, each tested against the other two; **rule 3** — `.when()` coerces Unknown to False, cascading deactivation along `topological_order`; **rule 4** — the constraint verbs coerce Unknown to inapplicable (not violated, `margin = None`), and **rule 7** extends this to bound-origin couplings (an inactive bound reference makes the coupling inapplicable rather than erroring); `is_active()` totality — never Unknown under full evaluation, the sole total predicate; **runtime equality's type-tagging** (`True ≠ 1`, `1 == 1.0`, exact type match otherwise) — deliberately distinct from Identity's declaration-time/fingerprint type-tagging below, which tags uniformly (M10.5's audit: these were stated in the Three-valued-semantics prose but unnamed here, which is exactly how the Unknown-provenance gap above went untested for four milestones).
- **Margins:** sign convention per form; Boolean composition preserves the satisfaction invariant; a `require(e)` reports `margin(e)`, equal to `forbid(~e)`'s reported margin.
- **Defaults:** `apply_defaults` idempotent, monotone, activity-respecting; completeness postcondition (`is_complete(apply_defaults(c))` iff every active param is defaulted-or-supplied); element/list default exclusivity and static-count list defaults; field-wise choice/struct fill; the defaulted-count-param cascade under fill-only output.
- **Partial Configs:** three-valued activity collapses to binary activity under `unknown → inactive`; the driver-loop coincidence `next_assignable(c) == [] ⟺ is_complete(c)`; `remaining_domain` soundness (never excludes a still-feasible value; every descriptor value validates against the declared domain); the one-unset-operand reducer positive (bound and single-forbid narrowing across kinds) and negative (a two-unset-operand implication is not propagated); the `PartialEval` evaluable/pending partition.
- **Identity:** sugar-equivalence pairs fingerprint-equal (`log_scale`/prior, `implies`, variadic repeat/chain, expression bounds vs. their `.forbid(x > y)` forbidden-state manual expansion — *and* fingerprint-**distinct** from the feasibility-opposite `.forbid(x <= y)`, so fingerprint-equality tracks feasibility despite `origin`'s exclusion; `require(e)` feasibility-, margin-, and fingerprint-equal to `forbid(~e)`); permuted declarations differ; scope monotonicity (meta/tags/anchors/declared-constraint changes are `sampling`-equal, `full`-distinct); round-trip law; mark-sentinel distinctness; type-tag distinctness (`1` vs `1.0` vs `True`); `−0.0 ≡ 0.0`; known-answer digest vectors.
- **Structure:** `unflatten(flatten(c)) == c`; per-element constraint instantiation counts; `Array`-vs-`List` dtype per static/dynamic count level; leaf-flattening aggregate values on nested lifts; **the fixed leaf layout** — `coordinate_paths()` round-trips through `unflatten` with no bookkeeping keys present (`ds.unflatten(dict(zip(space.coordinate_paths(), values)), space)`) on a space where every `.repeat()` count is a literal integer and no param carries a condition, raises a path-named resolution error (row 33) otherwise, excludes lift-length bookkeeping at every nesting depth, and orders its output identically to `flatten`'s (and therefore the DataFrame's) leaf order.
- **Representation:** `decode` totality as **domain membership** — `source.validate(rep.decode(g)).param_errors == ()` for every `g` drawn from `target` (not `.valid`, which folds in feasibility, and so would be false by construction wherever a constraint is opaque); `encode` target-validity when `invertible`; **defaults and anchors** carried into the target are valid there, and every one no `encode` could carry appears in `dropped_defaults`/`dropped_anchors` rather than crossing unencoded; the **one-directional** round-trip `decode(encode(x)) == x`, with `encode(decode(g)) == g` explicitly *not* a law (integer charts, quantized grids, one-hot ties, and random-key permutations are all many-to-one); **feasibility agreement** `target.is_feasible(g) == source.is_feasible(rep.decode(g))`, unconditional because transport is total; the **identity** — a rule set matching no param leaves `target.fingerprint() == source.fingerprint()` at both scopes with `decode(c) == c == encode(c)`; `then` **associative** with identity a two-sided unit; **path and arity preservation** for derived representations — `set(target.params) == set(source.params)` over definition-path keys, dimensionality unconstrained, and a param with relocated descendants or a `.prop()` dependent never encoded; the **induced chart representation** touches exactly the chart-bearing params (own *or* element level) that no count or `.prop()` reads, targets `real(0,1)` with `periodic` mirrored, and is measure-preserving; `Representation` never enters the IR, `to_json`, or the preimage.
- **Sampling:** tighten-not-reject on bound-origin constraints is distributionally identical to rejection (truncation ≡ conditioning).
- **Sampling diagnostics:** `sampling_report` never rejects and never mutates (`n` draws behind every row regardless of `acceptance_rate`; `space.fingerprint()` unchanged); seed-reproducible; `satisfied` conditioned on `applicable`, not on all draws; Unknown-swallowing is visible (`ConstraintReport.applicable < 1.0` on an unguarded optional aggregate, `== 1.0` once `.if_inactive()` guards it, all else equal); the funnel is visible and documented as correct-by-spec, not a defect (`acceptance_rate` matches the analytic value under Kleene rule 4, and the accepted sample concentrates away from where the constraint is inapplicable); per-instance folding and `activity`'s template keys share one denominator, `n`, with every scalar row (D-73); `tighten_bounds=False` draws the full declared envelope and `=True` matches the reference sampler's own acceptance rate (D-74).

---

## Staging

Specified but shippable as **optional extras** — not part of the core surface, and not required for the initial release: `ds.from_callable` / `Annotated` domain literals (`ds.real(...)`, `ds.integer(...)`, …) as an optional module, `to_dataclass() -> type` / `to_python_source() -> str` / `to_pydantic_model()` as extras. `to_json_schema` stays core (dependency-free; cheap under nested choice).

---

## Out of Scope

Excluded **by construction** — operators act on genotypes, and core owns only the induced chart:

- Search, mutation, crossover, neighborhoods, fitness-aware generation
- Distance metrics and kernels (genotype-level notions)
- Tree/program generation strategy for `.symbolic()` (tree genomes are genotypes)
- Encoding/vectorization beyond the `Representation` morphism: core ships the **induced chart representation** only, and every *chosen* genotype — one-hot, stick-breaking, random keys, type bridges — is consumer- or type-author-supplied
- **Structural morphisms**: flattening a hierarchy into a flat table, relaxing conditions away, padding a dynamic lift to fixed width. The IR is *already* the flat table, so nothing is missing; hierarchy is a modeling decision to be handled explicitly rather than circumvented, and imputation and padding conventions are irreducibly chosen. Writable as a supplied `Representation`; never shipped by core
- Growing the expression language past chart application and `ds.value` — anything structurally expressible goes through the language, anything else through the opaque leaf, and there is no third category
- Surrogate modeling, acquisition functions; prior fitting from observed data
- LLM backends for `.code()`
- Cost-aware or multi-fidelity scheduling
- Constraint propagation beyond the one-unset-operand guarantee (CSP solving)
- Value-dependent indexing (`x[k]` for a param-valued `k`) and quantification over dynamic ranges. The cost is **loss of static dependency analysis**: the referenced element is unknown until `k` is assigned, so the expression would have to reference the whole lift conservatively, degrading `dependency_graph`, the bound envelopes, and `remaining_domain`'s one-unset-operand reducer. For a *static* count the case is already expressible by unrolling (`ds.all_(*((k == i).implies(...) for i in range(n)))`), which is the machine-generation pattern the metaprogramming surface exists for. Negative indexing is **not** covered by this exclusion — `x[-1]` resolves against the lift's own realized length and still references exactly that lift
- Exact conditional subset sampling with calibrated marginals; alignment-aware repeat diffing
- Penalty shapes, weights, priorities, relaxation policies (annotate via constraint `meta`)

