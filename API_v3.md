# designspace — API v3

A Python library for declaratively defining algorithm design spaces using a chainable, polars-like expression API.

The library separates **space definition** (what a valid configuration looks like) from **search strategy** (how to explore it).

```python
import designspace as ds
```

---

## Representation Model

Configs are **phenotypes**: values in domain units, legible to the expert who wrote the space. A permutation of job names, a temperature in °C, a Cholesky factor — never an index vector or a bitstring.

**Charts** are the canonical genotype for generative primitives, *induced* from phenotype declarations (bounds + prior) rather than chosen. All other genotypes are **Encodings** supplied by consumers or type authors. **Operators act on genotypes** — mutation, crossover, neighborhoods, distances, kernels — and are therefore out of scope by construction.

Everything below is a consequence of this split.

## Design Principles

**Everything is data, and everything is constructible.** Constraints, conditions, choice topology, and dependency structure are inspectable ASTs. The IR is bidirectional: spaces can be rebuilt from rewritten IR.

**No opinionated metrics.** Distance, encoding, and vectorization are consumer-specific. The library provides traversal machinery and sockets; consumers supply semantics.

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
).constrain(
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

`ds.embed` is removed; use the `.space()` type method (below), which subsumes it.

Names may not contain `.`, `[`, or `]` (reserved by the path grammar). Declaration order is **significant**: it is preserved through composition, aligns `.prior(weights=...)`, and enters `fingerprint()`.

---

## Parameter Types

Each `ds.param(name)` in definition position takes **exactly one** type method. This is enforced two ways: the builder view types (below) make a second type method a static type error, and resolution rejects any definition that carries more than one type however it was built (error table row 2).

### Builder view types

The builder is statically typed so that an IDE offers only the methods valid at each step, and choosing a second type is caught before resolution.

- `ParamExpr` is the **base** type. It is an `ArithExpr`/`BoolExpr`/`VectorExpr` (usable in reference position) and carries the identity-, domain-, and lift-level modifiers, but **no** type methods. `isinstance(x, ParamExpr)` holds for every param object, in reference or definition position.
- `ds.param(name)` returns a **`FreshParamExpr`** — a `ParamExpr` that additionally carries the type methods. It is the only object on which a type is chosen.
- Each type method returns a **type-specific view**, a subclass of `ParamExpr`: `.real → RealParamExpr`, `.integer → IntegerParamExpr`, `.bool → BoolParamExpr`, `.categorical → CategoricalParamExpr`, `.ordinal → OrdinalParamExpr`, `.subset → SubsetParamExpr`, `.permutation → PermutationParamExpr`, `.choice → ChoiceParamExpr`, `.space → StructParamExpr`. `.repeat()`, available on any typed view (a type is required before a lift), returns a **`ListParamExpr`**, which itself re-offers `.repeat()` for nested lifts. Each view exposes only the modifiers and query methods valid for its type (`RealParamExpr`/`IntegerParamExpr` have `.log_scale()`/`.quantized()`; `SubsetParamExpr`/`PermutationParamExpr` have `.contains()`/`.size()`/`.position_of()`/`.sum_over()`; `ListParamExpr` has the vector aggregates, `.field()`, and `.length()`) and **omits the type methods** — so `ds.param("x").real(0, 1).bool()` is a static type error. `BoolParamExpr` is additionally a `BoolExpr` (a boolean param is usable directly as a condition).

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
| `.space(*exprs)` / `.space(prebuilt: Space)` | `dict` | Struct-valued param: unconditionally-present grouping under a namespace. Subsumes v2's `embed`. Per-element constraints on repeated structs require the prebuilt-`Space` form (the inline form has nowhere to hang a `.forbid`). |

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
| `.meta(mapping=None, **kwargs)` | Merges; last-write-wins per key. Values must be JSON-serializable. |
| `.default(value)` | **List default** when applied after a lift: legal only for static counts; length must match; mutually exclusive with element defaults on the same param. |

**The lift.** `.repeat(count)` closes the element definition: everything left of it defines the element; everything right applies to the list.

```python
ds.param("dropout").real(0.0, 0.6).log_scale().repeat(4)          # List(Float64)
ds.param("layers").space(...).repeat(ds.param("n_layers"))        # List(Struct)
ds.param("mask").bool().repeat(8).repeat(8)                       # List(List(Boolean)) — legal
ds.param("grid").real(0.0, 1.0).repeat(2, 3)                      # variadic sugar: shape (2, 3)
ds.param("pipeline").choice(...).repeat(n)                        # heterogeneous list — legal
```

- `count: int | ArithExpr`, resolution-checked to be integer-typed; a negative evaluated count is a validation error; `0` yields `[]`. Counts, unlike bounds, remain runtime-evaluated — lists are structure, not charts. A count that references another param nonetheless joins the dependency graph and cycle check (that param must be assigned before the list can be materialized), exactly as a condition does.
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

Segments are param names, variant names, and struct-param names. `name[i]` addresses a repeat element (**instance path**), with one index per lift level for nested lifts (`mask[2][3]`); `name[]` denotes the element schema (**definition path** — used by introspection; illegal in expressions), likewise repeated per level (`mask[][]`).

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

`BoolExpr` and `ArithExpr` are walkable ASTs exposing `.kind: str`, `.params: frozenset[str]`, `.children: tuple`.

**BoolExpr** — for `.when()`, `.forbid()`, `.constrain()`:

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

**ArithExpr** — for `.constrain()`, expression bounds, and repeat counts. Comparisons yield `BoolExpr`:

```python
ds.param("x") + - * / ** % (expr | literal)
ds.param("s").size()                    # subset cardinality
ds.param("s").sum_over(mapping)         # subset: Σ mapping[item] over included items;
                                        #   mapping stored literally in the AST; keys ⊆ item universe;
                                        #   an included item absent from the mapping contributes 0
ds.param("p").position_of(item)         # permutation index; item must be a member
ds.param("r").length()                  # lift length
ds.param("c").prop(name)                # custom type property (scalar-typed)
expr.if_inactive(fallback)              # inactive → fallback; unset stays pending
```

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

Instance paths are legal in expressions: `ds.param("stops[0].dwell_min") < 10`. An out-of-range index makes the leaf inactive (→ Unknown) — this is a *runtime* condition (the index depends on the realized count), distinct from a *structural* one caught at resolution. `.field(name)` requires a struct lift whose element declares `name`; projecting an undeclared field, or `.field()` on a non-struct lift, is a resolution error (a nonexistent definition path — row 6), not a silent Unknown. Ordinals: comparison only; two ordinal *params* compare only if they declare identical value sequences; comparing an ordinal against a literal that is not one of its declared values is a resolution error (row 18). Categoricals: `==`, `!=`, `.is_in()` only.

**Runtime equality.** `==`, `!=`, and `.is_in()` compare `bool` by type-tagged identity against everything else (so `True ≠ 1` — bool is strict), `int` and `float` numerically against each other (`1 == 1.0`), and every other pair (strings and other `Any`-typed categorical/ordinal values) by exact type match. This runtime rule is deliberately distinct from declaration-time distinctness (rows 3–4) and fingerprint canonicalization, which type-tag uniformly; a categorical that declares both `1` and `1.0` as distinct variants therefore cannot be told apart by a runtime `==`.

**Guardrails.** `__bool__` and `__contains__` on expressions raise informative `TypeError`s, so `expr1 and expr2`, `0 < ds.param("x") < 1`, and `v in ds.param("s")` fail loudly instead of silently miscompiling.

### Three-valued semantics

Expressions evaluate in Kleene logic; **Unknown** arises only from inactivity.

1. **Leaves.** Any predicate or arithmetic term over an *inactive* param is Unknown. `is_active()` is the sole total predicate. Projection over an *inactive* lift is Unknown — distinct from an *active empty* list (below).
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
4. **Coercion at `.forbid()`/`.constrain()` on complete configs:** Unknown → **inapplicable** — not violated, `margin = None`, `ConstraintEval.applicable = False`.
5. **Unset ≠ inactive.** In partial evaluation an unset operand makes a constraint *pending*; an inactive one makes it Unknown now. `.if_inactive()` coalesces inactivity only and never eats pending.
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
| `.forbid(*conditions, tags=(), meta=None)` | Defines **feasibility** — violating configs are invalid and rejected by the reference sampler |
| `.constrain(*conditions, tags=(), meta=None)` | Declares an evaluated, annotated predicate — never affects feasibility or the reference measure |
| `.anchor(configs: dict[str, dict])` | Named reference configs, validated at resolution |
| `.meta(mapping=None, **kwargs)` | Space-level metadata (objectives, cost models, anchor-role conventions) |

Feasibility is defined by param validity plus forbids **only**. `validate().valid`, `is_feasible()`, and `infeasibility_reasons()` never consider `.constrain()` declarations; those appear in `constraint_evals` with margins so nothing is hidden. Core stores `tags` and `meta` on constraints and never interprets them — penalty shapes, weights, priorities, and relaxation orders are consumer policy attached via `meta`. A directional preference with no threshold ("minimize capex") is not a constraint — no predicate, no margin — and belongs in space-level `.meta()` as an objective declaration.

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

`ds.param("x").integer(1, ds.param("y"))` desugars at resolution to `ds.param("x").integer(1, env_hi)` plus the implicit hard constraint `ds.param("x") <= ds.param("y")` — there is exactly one encoding of a bound coupling, and the bound syntax is notation for it. The envelope is the interval-arithmetic hull of the bound expression over the referenced params' (already-enveloped) domains, computed along the dependency DAG; a bound expression with no computable hull is a resolution error, with the stated workaround being exactly the desugared form written by hand.

- **Provenance.** The implicit constraint carries `origin="bound"` (vs. `"user"`) so errors can say "`x` exceeds its declared bound `y`" and introspection can distinguish. `origin` is derived provenance and excluded from the fingerprint preimage — the sugared form and its manual expansion are fingerprint-equal.
- **Ordering.** Bound-origin constraints, unlike user constraints, enter `dependency_graph` and `topological_order`, preserving assign-`y`-before-`x` ordering.
- **Margins for free.** The coupling yields a `y − x` margin, which the old per-config-chart encoding never had.
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

`periodic=True` reals: canonical domain `[lo, hi)`, chart maps `[0,1) → [lo, hi)`, `hi` invalid — so hashing is canonical by construction. The flag is visible in `capability_report` so solvers apply wraparound moves and periodic kernels.

### All charts are static

Every chart is built once, at resolution, over the param's (envelope) bounds — expression bounds having been desugared first (see *Expression bounds are sugar*). Chart-family requirements (`Log()` needs `lo > 0`, `Logit()` needs `(0,1)`, `Power(p)`'s monotonicity domain) are checked against the *declared* envelope bounds `(lo, hi)`, which do not move under quantization or the integer extension — even though the continuous chart math is built over a wider bound (`hi + 1` for integers, the grid extension for quantized). `ParamDef.chart` is a plain attribute. The genotype→phenotype map therefore never depends on other genes — u-space coordinates are comparable across configs.

The reference sampler *may* recognize a bound-origin constraint whose referenced params are already assigned and draw from the correspondingly tightened chart instead of rejecting — observably identical, because truncation is conditioning (tightening an external prior to a sub-interval needs `cdf`; absent that, rejection).

---

## Sampling and Generativity

```python
.sample(n, seed=None, reject_soft=False) -> pl.DataFrame
.sample_one(seed=None, reject_soft=False) -> dict
```

`seed: int | numpy.random.Generator | None`. The reference sampler is an interpreter of declared measure: walk `topological_order`, decide activity, draw active generative params through their charts (weights for categorical/ordinal/bool/choice; Bernoulli-plus-size-rejection for subsets; uniform shuffle for permutations; `sample(rng)` for customs), reject on **forbids** only. `reject_soft=True` additionally rejects `.constrain()` violations — rejection on a user-declared predicate, off by default. Default max retries 10,000 with an informative error naming the constraints that dominated rejection.

**Rejection hostility.** Dense combinatorial forbids (pairwise `distinct`, conflict sets near packing limits) collapse rejection acceptance. The remedy is constructive: enforce the invariant inside a `.custom()` sampler or reparameterize (see Solver Integration, tiers). The retry-exhaustion error links here.

**Generative vs. non-generative.** Every param is generative except `.code()` and `.symbolic()` (without `sampler=`). `sample()` raises a `SamplingError` naming the offending params **iff** it must materialize a value for a non-generative param — a `.default()` satisfies it, `freeze`/`slice` removes it, and a param inactive for the draw in progress never triggers it.

Sampling always produces explicit values and **ignores defaults** — measure bias is the prior's job, not the default's.

---

## Defaults

`.default()` semantics were unified in v3 around a cascade:

- A **choice default names a variant** (a string). A struct param or activated variant payload fills **field-wise** from its members' own defaults.
- **Element defaults** (pre-lift) are count-independent and legal under dynamic counts. **List defaults** (post-lift) are legal only for static counts, must match the length, and are mutually exclusive with element defaults on the same param.

```python
.apply_defaults(config) -> dict
.has_complete_defaults -> bool
```

`apply_defaults` is a **partial-evaluation operator**: idempotent, monotone (never overwrites, never removes), activity-respecting. It walks `topological_order`, filling only params whose activity resolves to *active* given the config as it fills (so defaults trigger downstream defaults); params with *unknown* activity are left untouched. Partial input wins field-wise (merge, not replace).

Postcondition: the result is complete iff every param active under the filled config has a default or was supplied — `apply_defaults` does not guarantee completeness; check `is_complete`.

Defaults validate against their (static) domain at resolution — **never a silent clamp** (cross-reference: the prior tail-clipping ban). `apply_defaults` is constraint-blind: its output may violate forbids — bound-origin couplings included — which `validate` reports; this matches user forbids, which were never checked at fill time.

**Defaults vs. anchors.** Defaults are per-param fill values for completion; anchors are named whole configs for reference. When a space has complete defaults, derive rather than duplicate: `.anchor(configs={"shipped": space.apply_defaults({})})`. Defaults do not auto-create an anchor. Anchor roles (incumbent, baseline) are a `.meta()` convention, not API.

---

## Space — Validation

```python
.validate(config) -> ValidationResult
.validate_param(path, value, context=None) -> ValidationResult   # instance paths supported
.is_feasible(config) -> bool
.infeasibility_reasons(config) -> list[str]
.evaluate_constraints(config) -> list[ConstraintEval]
```

Relations: `is_feasible(c) == validate(c).valid`, both defined by param errors plus hard constraints; `evaluate_constraints` reports every constraint (hard and declared) with `applicable` and `margin`. `context` enables evaluating constraints that reference other params (bound-origin couplings included); without it, `validate_param` reports those as unevaluated rather than guessing — concretely, an under-determined constraint (one referencing a param absent from `context`) is **omitted** from `validate_param`'s `constraint_evals` rather than appearing with a placeholder: `ConstraintEval` has no "pending on missing context" state, and reusing `applicable=False` would conflate it with a genuine Kleene-Unknown. `validate` and `config_hash` operate on the **raw phenotype representation** only; transformed views have no identity.

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

`topological_order` gives an assignment order where every condition and bound-origin constraint references only already-assigned params; follow it and any interruption point is a well-defined partial config. `next_assignable` is the derived driver-loop sugar.

`remaining_domain` returns a per-kind descriptor: interval (grid-intersected if quantized) for real, integer range, value subset for categorical/ordinal/choice, and for `.subset()` a three-way partition (items forced-in / forced-out / free). **Guarantee level:** declared bounds ∩ constraints reducible with exactly one unset operand — bound-origin couplings included, so bound tightening falls out of the same rule. Full propagation across multi-param constraints is CSP solving — consumer territory. `None` if inactive.

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
.capability_report(encodings=None) -> dict[str, Capabilities]
```

`dependency_graph` maps each definition path to the params it depends on via conditions, constraints, and repeat counts (bound-origin constraints and repeat counts included; only conditions, bound-origin constraints, and repeat counts impose assignment order — a runtime-evaluated count is not a bound, but it must still be assigned before its list).

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

**Anchors under structural operations:** `freeze`/`slice` re-validate anchors; a conflict with a frozen/sliced value is a resolution error. `select`/`filter` drop conflicting anchor keys with the same warning mechanism. `extend` keeps anchors and re-validates.

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

Resolution re-validates whatever comes in. Expressions are values — rewrites reattach existing `BoolExpr` objects; `.kind`/`.children` walking covers expression-level rewrites. `ds.all_`/`ds.any_` provide fold identities for generated constraint sets. Degenerate arities produced by generators are legal with defined semantics (see Degeneracy Table). A space-valued param (searching a catalog of inner spaces) needs no new machinery: a `.custom()` type with `fingerprint()` as value identity.

---

## Transforms and Encodings — the Representation Layer

### Transforms

```python
.transform(config, fn: ParamTransform) -> dict
.inverse_transform(config, fn: ParamTransform) -> dict
```

The space owns structural traversal — choice branches, lift elements, struct scoping, inactive params; the consumer supplies leaf logic. Rules:

- A **lifted param is a single leaf** whose value is the whole list — element-coupling maps (stick-breaking) are legitimate leaf logic.
- Leaves may change **shape** (scalar → one-hot vector); transforms preserve **structure** (output is still a nested dict).
- Traversal is **children-first**: a choice or struct leaf receives its self-contained value after its payload's leaves were transformed.
- `flatten` is structural and **non-validating** — transformed leaves need not be domain members.

The canonical genotype recipe is the two-step pipeline: `space.transform(config, fn)` then `ds.flatten(...)`. Mixed genotypes per space are natural — `ParamTransform.forward(param: ParamDef, value)` receives the full `ParamDef` per leaf (including `.chart`), so per-param dispatch is built in: u-space for chart-bearing params, one-hot for categoricals, native encodings for customs.

### Encodings

```python
class Encoding(Protocol):                 # genotype–phenotype map for one param
    def dim(self) -> int: ...
    def decode(self, u: Sequence[float]) -> Any: ...     # genotype → phenotype
    def encode(self, value) -> Sequence[float]: ...      # optional, like Prior.cdf
```

Core defines the protocol and a registry type keyed by `type_key`; **core never populates the registry**. Type authors may ship a default `Encoding` next to their type as a sibling object — substitutable by any solver. Operators never live on `ParamType`: neighborhoods and distances are properties of a genotype, and the same phenotype admits many.

---

## Identity and Serialization

### to_json / from_json

```python
.to_json(on_unserializable="raise") -> dict
Space.from_json(data, custom_types=None) -> Space        # classmethod
.to_json_schema() -> dict                                 # oneOf per choice; dependency-free
```

The JSON document carries a single integer **format version**; `from_json` raises on unknown versions. The non-serializable set is closed and enumerated: the `.custom(sampler, validator)` shorthand, `code`/`symbolic` `validators`, `symbolic` `sampler`, `Primitive.fn`. (`Encoding` instances never enter the IR.) `on_unserializable="drop"` writes the space without those sites plus a manifest of omissions — the reconstructed space is a *different* space by design.

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
| Params: definition path, kind, domain, prior, condition | ✓ | ✓ |
| Conditions, forbids | ✓ | ✓ |
| Declared (`.constrain`) constraints | ✓ | — |
| Defaults, tags, meta, anchors | ✓ | — |
| Format version | ✓ | ✓ |

`sampling` identifies feasible set + measure + chart geometry (warm-start/surrogate transfer); `full` is document identity. Derived fields (`Constraint.params`, `dependency_graph`) never enter the preimage.

**Normalization pipeline:** (1) resolve and desugar — sugared and explicit spellings of the same space are fingerprint-equal, including variadic `.repeat(*counts)` vs. the chain and expression bounds vs. their manual envelope-plus-constraint expansion (`origin` is excluded from the preimage); (2) declaration order preserved, not sorted — permuted params or variants differ; `.when(a).when(b)` folds in call order; (3) unordered collections sort — tags lexicographically, meta/anchors by key; (4) float canonicalization — `−0.0 → 0.0`; NaN/inf are resolution errors wherever floats occur in the IR; (5) type tags at `Any`-typed positions — categorical/ordinal values, defaults and anchor entries for such params, meta values encode as `{"$t": "int", "v": 1}` with tags `bool|int|float|str|null`, so `categorical(1, 2)` ≠ `categorical(1.0, 2.0)`; (6) expressions encode as ASTs — node kind, children in operand order, paths as grammar strings, literals type-tagged.

The normalized document is serialized per **RFC 8785 (JCS)** and hashed with SHA-256. (JCS serializes `1.0` as `1` — which is precisely why type tags precede canonicalization.)

**Callables:** default raise, listing offending sites by definition path — same set as `to_json`. `on_unserializable="mark"` replaces each callable with the sentinel `{"$opaque": true}` at its site — *mark, not drop*: presence is identity-relevant. Documented limitation: two spaces differing only in a callable's behavior at the same site are fingerprint-equal under `"mark"`; content identity requires the serializable protocol (`type_key` + `describe()`).

### config_hash

Reuses the same canonical config encoding (type tags, float rules, grid canonicalization; subsets sorted, inactive stripped) but does **not** embed the space fingerprint. The globally unique observation key is the pair `(space.fingerprint(), ds.config_hash(config, space))`. Anchors in the `full` preimage use this same encoding.

---

## Config Utilities

```python
ds.flatten(config, space) -> dict[str, Any]     # path-grammar keys; non-validating
ds.unflatten(flat, space) -> dict               # inverse
ds.config_hash(config, space) -> str
ds.config_diff(a, b, space) -> list[ParamDiff]  # structural, no magnitude
ds.variant(config, param_path) -> str           # active variant name of a choice
ds.payload(config, param_path) -> dict | None   # variant payload; None for bare variants
ds.destructure(config, param_path) -> tuple     # (name, payload) — a derived view;
                                                #   tuples are never valid config values
```

`config_diff`: a variant switch decomposes into the discriminator diff (old/new are variant **names**) plus newly-inactive/newly-active payload diffs using the `None` conventions. Repeat length changes align **positionally** — an insertion-at-front reports as a full rewrite; alignment-aware diffing is consumer polish.

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
    def sample(self, rng) -> Any: ...
    def validate(self, value) -> bool: ...
    def to_json(self, value) -> Any: ...
    def from_json(self, data) -> Any: ...
    def describe(self) -> dict: ...              # MUST be JSON-serializable

    # Optional — enables .prop() in constraints
    def properties(self) -> dict[str, type]: ...  # expression-visible props: int|float|bool|str only
    def extract(self, value, prop: str) -> Any: ...


class ParamTransform(Protocol):
    def forward(self, param: ParamDef, value: Any) -> Any: ...
    def inverse(self, param: ParamDef, transformed: Any) -> Any: ...


class Prior(Protocol):
    def ppf(self, q: float) -> float: ...      # required
    def cdf(self, value: float) -> float: ...  # optional; required when support exceeds bounds
```

**Custom-type contract laws:** `factory(x.describe()) ≡ x` (registry round-trip); `extract` is called only on values that passed `validate`; when payload lifts align to a custom value by index (`.repeat(ds.param("g").prop("n_edges"))`), the type must define a **canonical ordering** stable under JSON round-trips; a type embedding non-serializable content is responsible for raising in its own `to_json` — core cannot see inside `describe()` output beyond checking it is JSON-serializable.

---

## Support Types

```python
ds.Signature(args: dict[str, type | str], returns: type | str)
ds.FloatLiteral(lo, hi)               # ephemeral constant in .symbolic(); carries a chart
ds.IntLiteral(lo, hi)                 # likewise (floor rule)
ds.Primitive(name, arity, fn=None)    # user-defined operator in .symbolic()
ds.Log()  ds.Logit()  ds.Power(p)     # built-in prior families (see Charts)
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

class Chart(Protocol):
    def from_unit(self, u: float) -> Any: ...
    def to_unit(self, value) -> float: ...                # interval midpoint for integers/grids

@dataclass
class Constraint:
    expr: BoolExpr
    hard: bool                    # True = forbid, False = declared
    origin: str                   # "user" | "bound" — derived provenance;
                                  #   excluded from fingerprint preimage
    tags: frozenset[str]
    meta: dict[str, Any]
    params: frozenset[str]        # derived; excluded from fingerprint preimage

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
    evaluable_constraints: list[ConstraintEval]
    pending_constraints: list[Constraint]
    n_remaining: int

@dataclass
class ParamDiff:
    param: str                    # instance path
    old: Any | None               # None if newly active
    new: Any | None               # None if newly inactive

@dataclass
class SubspaceInfo:
    prefix: str                   # definition-path prefix
    space: Space
    condition: BoolExpr | None    # variant subspaces carry the discriminator condition

@dataclass
class Capabilities:
    path: str
    type_kind: str
    generative: bool
    has_chart: bool
    static_shape: tuple[int, ...] | None   # static-count lift shape; product = unit
                                           #   dimension for scalar lifts
    periodic: bool
    invertible: bool | None       # prior inverse available
    properties: dict[str, type]
    type_key: str | None
    encodings: tuple[str, ...]    # names registered in the (consumer-supplied) registry
```

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

**Resolution timing.** Resolution is unspecified relative to construction. A space built in argument position (a choice variant or struct body) may carry a `.when()` condition that references a param binding only in an *enclosing* scope — the sole scoping rule's up-walk — which cannot resolve while that payload is built standalone. Reference, type, and cycle checks (rows 6, 7, 14) over such conditions are therefore deferred to a finalization pass over the fully-merged space, and any resulting error surfaces no later than the **first terminal operation** — `sample`, `sample_one`, `validate`, `validate_param`, `evaluate_constraints`, and (once implemented) `fingerprint`, `to_json`, and every introspection surface must trigger this finalization. The error is still a `ResolutionError` (phase R), computed from space structure alone with no config; only its timing moves. Constraint (`.forbid()`/`.constrain()`) references stay strict and raise eagerly, since cross-scope constraints use the down-reference-at-the-common-ancestor route instead.

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
| 21 | Default outside domain; list default under dynamic count; list default length mismatch; element and list default together | R |
| 22 | Anchor invalid against the space; anchor conflicting with a frozen/sliced value | R |
| 23 | Empty-string tag; non-JSON-serializable meta value; non-JSON-serializable `describe()` output | R |
| 24 | `is_sorted` on a lift nested deeper than one level | R |
| 25 | `==` over purely continuous unquantized aggregate/operands | R (warning) |
| 26 | Sampling retry exhaustion; non-generative materialization without default | V |
| 27 | `from_json`: unknown format version; missing `custom_types` entry for a `type_key` | V |
| 28 | Subset size bounds nonsensical: `min_size > max_size`; `min_size < 0`; `min_size` exceeds the item universe | R |

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

A solver is an **interpreter over the IR**. The canonical loop for the closed world (built-in kinds): walk `topological_order` → determine activity via conditions → embed active generative params in u-space via their charts → propose → decode → check margins. Charts give every solver a free, type-appropriate perturbation — mutate in u-space, decode through the chart — so log-scaled params get multiplicative noise and grids snap correctly with zero per-type code. Core still ships no operators.

The open world (`.custom()`) negotiates per param, two independent channels:

**Generation ladder** (richest available rung wins): native adapter recognizing `type_key` → registered `Encoding` (`[0,1]^d` box, geometry authored by the type author, loss declared not silent) → opaque `sample(rng)` (sufficient for random search and resampling moves).

**Modeling channel**, orthogonal to generation: `properties()` featurizes values for surrogates and reporting regardless of production rung; `to_json`/`config_hash` give observation identity. A type opaque to generation can be rich to modeling.

**Adapter conventions** (strategy-entangled operations — crossover schemes, mutation policies, trust regions — are the only thing genuinely forced into adapters): keyed by the same `type_key` used in serialization; receive the live `ParamType` instance and derive all domain facts from it (`describe`, `validate`, `extract`) rather than re-declaring; receive an `Encoding` rather than embedding one; scoped per *(capability, type)*, not per *(solver, type)*. `capability_report()` is the negotiation surface: fail fast with "param `topology` (type_key=`digraph`) has no unit embedding — register an adapter or use a sampling-based solver" instead of degrading silently.

**Structured values — tier guidance** (graphs, layouts, schedules, and kin):

1. **Parametric family** — a choice over named topologies/patterns. Fully primitive; use when the structure is nameable.
2. **Primitive decomposition** — element lifts with index params and per-element constraints. Use when constraints are local to elements; *static* counts additionally admit machine-generated unrolled pairwise constraints (metaprogramming). Rejection degrades near packing limits.
3. **Custom type with constructive sampler + properties** — use when invariants are global (connectivity, pairwise spacing) or rejection-hostile. Draw the ownership boundary at **coupling to the constructive invariant**: params coupled to it go inside the type; independent payloads stay primitive (keeping charts and priors), aligned by prop-driven lift counts under the canonical-ordering law.

The permanent expression-language boundary: value-dependent indexing (`islands[edges[k].src]`) and quantification over dynamic ranges are excluded — relational semantics belong to tier 3 or the consumer. Prefer generative reparameterization over measure-zero constraints (stick-breaking for simplexes) — the space stays primitive and chart-covered, the manifold geometry rides in a `ParamTransform`.

**Choosing mechanisms** (semantically overlapping encodings are structurally distinct — no normalization is attempted): bool + `.when()` for one or two dependents; choice for alternatives or heavier payloads; struct for pure grouping; bool-per-item + `.when()` + `ds.count()` when subset members need payloads.

---

## Errors, Concurrency

Exception taxonomy: `DesignSpaceError` (base) → `ResolutionError` (table above, R rows), `SerializationError`, `SamplingError`. Misuse guards (`__bool__`, `__contains__`) raise plain `TypeError`. Validation-time findings surface as `ParamError` records inside results wherever a result object exists; only operations with no result channel raise.

All public objects — expressions, spaces, IR dataclasses, charts — are immutable after construction and safe to share across threads. RNG state is passed explicitly (`seed` / `Generator`); nothing mutates shared state.

---

## Dependencies

Core: `numpy` (RNG), `polars` (`sample()` output). Built-in priors are implemented internally — no distribution-library dependency; any `Prior`-satisfying object (scipy frozen distributions, preliz) plugs in. Extras: `designspace[pydantic]` for model export.

---

## Conformance Laws

The spec's executable laws double as the acceptance suite:

- **Charts:** known-answer vectors for the four families (including subnormal-range log); floor-integer uniformity; quantized cell measure (uniform ⇒ equiprobable grid); grid canonicalization invariance under bit-different representations.
- **Kleene:** the truth table; `count` range rule; non-`count` aggregates plain-propagate Unknown (no range tracking); empty-aggregate values; inactive-lift-projection ≠ active-empty-list.
- **Margins:** sign convention per form; Boolean composition preserves the satisfaction invariant.
- **Defaults:** `apply_defaults` idempotent, monotone, activity-respecting.
- **Identity:** sugar-equivalence pairs fingerprint-equal (`log_scale`/prior, `implies`, variadic repeat/chain, expression bounds/manual expansion); permuted declarations differ; scope monotonicity (meta/tags/anchors/declared-constraint changes are `sampling`-equal, `full`-distinct); round-trip law; mark-sentinel distinctness; type-tag distinctness (`1` vs `1.0` vs `True`); `−0.0 ≡ 0.0`; known-answer digest vectors.
- **Structure:** `unflatten(flatten(c)) == c`; `transform`/`inverse_transform` round-trip when both leaf directions exist; per-element constraint instantiation counts; `Array`-vs-`List` dtype per static/dynamic count level; leaf-flattening aggregate values on nested lifts.
- **Sampling:** tighten-not-reject on bound-origin constraints is distributionally identical to rejection (truncation ≡ conditioning).

---

## Staging

Specified but non-blocking for v0.1: `capability_report()` (sugar over introspection), `ds.from_callable` / `Annotated` domain literals (`ds.real(...)`, `ds.integer(...)`, …) as an optional module, `to_dataclass() -> type` / `to_python_source() -> str` / `to_pydantic_model()` as extras. `to_json_schema` stays core (dependency-free; cheap under nested choice).

---

## Out of Scope

Excluded **by construction** — operators act on genotypes, and core owns only the induced chart:

- Search, mutation, crossover, neighborhoods, fitness-aware generation
- Distance metrics and kernels (genotype-level notions)
- Tree/program generation strategy for `.symbolic()` (tree genomes are genotypes)
- Encoding/vectorization beyond the `transform`+`flatten` pipeline and the `Encoding` protocol
- Surrogate modeling, acquisition functions; prior fitting from observed data
- LLM backends for `.code()`
- Cost-aware or multi-fidelity scheduling
- Constraint propagation beyond the one-unset-operand guarantee (CSP solving)
- Value-dependent indexing and quantification over dynamic ranges (tier-3 or consumer territory)
- Exact conditional subset sampling with calibrated marginals; alignment-aware repeat diffing
- Penalty shapes, weights, priorities, relaxation policies (annotate via constraint `meta`)

---

## Changes from v2

Headline: nested self-contained choice values (variant collisions impossible; one path grammar everywhere); `.space()` struct type replacing `embed`; `.repeat()` as a chainable lift replacing `repeat(count, body=)` and `shape=`; Kleene three-valued semantics with `is_active()` and `if_inactive()`; charts unifying priors, integers, quantization, and periodicity; `.constrain()` made purely declarative with constraint `tags`/`meta` and Boolean-composed margins; vector aggregates (`field`, `sum`, `min`, `max`, `count_of`, `is_sorted`, `distinct`, `sum_over`, `count`, `position_of`); the defaults cascade and `apply_defaults`; generative/non-generative split (`.expr()` renamed `.symbolic()`, reference tree sampler removed); bidirectional IR; the `Encoding` protocol and phenotype/genotype representation model; the full `fingerprint()` specification; regenerated error and degeneracy tables; conformance laws. Post-consolidation: expression bounds desugared to envelope bounds plus bound-origin hard constraints — all charts static, `unresolvable_bound`/`default_out_of_bounds` deleted; variadic `.repeat(*counts)` with multi-index paths, leaf-flattening aggregates, and `Array` dtypes for static counts; `ds.payload`/`ds.destructure` config helpers.
