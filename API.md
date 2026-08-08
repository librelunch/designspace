# designspace specification

A Python library for declaratively defining design spaces using a chainable,
polars-like expression API. It separates space definition, meaning what a
valid configuration looks like, from search strategy, meaning how to explore
it.

```python
import designspace as ds
```

## Reading this document

Every section through *Conformance Laws* is normative and states what an
implementation must do. *Solver Integration*, *Staging*, and *Out of Scope* are
informative: they describe how the normative surface is consumed and where its
boundaries fall, and impose no further requirement.

Conventions used throughout:

- Paths are written in the grammar given under *Paths and Scoping*.
- "Row N" names a numbered row of the error table under *Resolution*. Every
  error the library raises appears in that table.
- A method written `.name(...)` belongs to `Space` or to a parameter expression,
  as its section states. A function written `ds.name(...)` is module-level.
- Conformance laws are named rather than numbered, and a law's name is the
  string an implementation reports when it reports one.

### Contents

1. [Representation Model](#representation-model)
2. [Design Principles](#design-principles)
3. [Quick Example](#quick-example)
4. [Construction](#construction)
5. [Parameter Types](#parameter-types)
6. [Modifiers and Layering](#modifiers-and-layering)
7. [Paths and Scoping](#paths-and-scoping)
8. [Expressions](#expressions)
9. [Constraints and Feasibility](#constraints-and-feasibility)
10. [Charts](#charts)
11. [Sampling and Generativity](#sampling-and-generativity)
12. [Defaults](#defaults)
13. [Space: Validation](#space-validation)
14. [Space: Partial Configs](#space-partial-configs)
15. [Space: Introspection](#space-introspection)
16. [Space: Structural Operations](#space-structural-operations)
17. [Space: Metaprogramming](#space-metaprogramming)
18. [The Representation Layer](#the-representation-layer)
19. [Identity and Serialization](#identity-and-serialization)
20. [Config Utilities](#config-utilities)
21. [Config Representation](#config-representation)
22. [Protocols](#protocols)
23. [Support Types](#support-types)
24. [IR](#ir)
25. [Resolution](#resolution)
26. [Errors and Concurrency](#errors-and-concurrency)
27. [Dependencies](#dependencies)
28. [Conformance Laws](#conformance-laws)
29. [Solver Integration](#solver-integration) (informative)
30. [Staging](#staging) (informative)
31. [Out of Scope](#out-of-scope) (informative)

---

## Representation Model

Configs are **phenotypes**: values in domain units, legible to the expert who
wrote the space. A permutation of job names, a temperature in °C, a Cholesky
factor, never an index vector or a bitstring.

A **genotype is a `Space`**, and a **`Representation`** is the `Space → Space`
morphism between them, carrying a value-level pair. **Charts** are the canonical
genotype for generative primitives, induced from phenotype declarations (bounds
and prior) rather than chosen. Every other genotype is an **`Encoding`**
supplied by a consumer or a type author. **Operators act on genotypes**, so
mutation, crossover, neighborhoods, distances, and kernels lie outside the
library by construction.

Everything below follows from this split.

## Design Principles

**Everything is data, and everything is constructible.** Constraints,
conditions, choice topology, and dependency structure are inspectable ASTs. The
IR is bidirectional, so spaces can be rebuilt from rewritten IR.

**No opinionated metrics.** Distance, encoding, and vectorization are
consumer-specific. The library provides the morphism machinery and the sockets;
consumers supply the semantics.

**Priors are coordinate systems.** Every generative param resolves to a *chart*,
a monotone map `[0,1] → domain` defining both sampling and solver geometry.
There is no separate transform concept for priors.

**Inactive means absent.** A param that is not active does not appear in a
config dict, as neither `None` nor `NaN`. Columnar containers necessarily use
`null`; the principle governs dict configs.

**Sampling is declared measure, not search.** The reference sampler interprets
the priors the expert declared. It is not an optimizer and ships no search
operators.

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

`FreshParamExpr` is a `ParamExpr` carrying the type methods. Each type method
narrows to a type-specific view (see *Builder view types* under *Parameter
Types*). `ParamExpr` remains the base type of every param object.

Names may not contain `.`, `[`, or `]`, which the path grammar reserves.
Declaration order is **significant**: it is preserved through composition, it
aligns `.prior(weights=...)`, and it enters `fingerprint()`.
---

## Parameter Types

Each `ds.param(name)` in definition position takes **exactly one** type method.
This is enforced twice over: the builder view types below make a second type
method a static type error, and resolution rejects any definition carrying more
than one type however it was built (row 2).

### Builder view types

The builder is statically typed, so an IDE offers only the methods valid at each
step and a second type choice is caught before resolution.

- `ParamExpr` is the **base** type. It is an `ArithExpr`, a `BoolExpr`, and a
  `VectorExpr`, so it is usable in reference position, and it carries the
  identity-, domain-, and lift-level modifiers. It carries **no** type methods.
  `isinstance(x, ParamExpr)` holds for every param object, in reference and in
  definition position.
- `ds.param(name)` returns a **`FreshParamExpr`**, a `ParamExpr` that
  additionally carries the type methods. It is the only object on which a type
  is chosen.
- Each type method returns a **type-specific view**, a subclass of `ParamExpr`:
  `.real → RealParamExpr`, `.integer → IntegerParamExpr`, `.bool →
  BoolParamExpr`, `.categorical → CategoricalParamExpr`, `.ordinal →
  OrdinalParamExpr`, `.subset → SubsetParamExpr`, `.permutation →
  PermutationParamExpr`, `.choice → ChoiceParamExpr`, `.space →
  StructParamExpr`.
- **`TypedParamExpr`** is the common base of every type-specific view, and is
  what `ds.param_from_def()` returns (see *Space: Metaprogramming*).
- `.repeat()` is available on any typed view, a type being required before a
  lift, and returns a **`ListParamExpr`**, which re-offers `.repeat()` for
  nested lifts.
- `BoolParamExpr` is additionally a `BoolExpr`, so a boolean param is usable
  directly as a condition.

Two kinds of method are narrowed onto the views and **omitted** from the views
they do not apply to:

- The **type methods** are removed from every view, so
  `ds.param("x").real(0, 1).bool()` is a static type error.
- The **domain-level modifiers** `.log_scale()` and `.quantized()` are present
  only on `RealParamExpr` and `IntegerParamExpr`, so
  `ds.param("x").categorical(...).log_scale()` is a static type error.

The **query and aggregate methods** are not narrowed: `.contains()`, `.size()`,
`.sum_over()`, `.position_of()`, `.field()`, `.length()`, and the vector
aggregates `.sum()`, `.min()`, `.max()`, `.count_of()`, `.is_sorted()`, and
`.distinct()` live on the base `ParamExpr`, which is itself a `VectorExpr`. They
are used in *reference* position, where the object is always the
`FreshParamExpr` returned by `ds.param(name)` and never a definition-position
view. Their type-correctness is a **runtime** law rather than a static view
restriction: a `.contains()` on a permutation, a `.field()` on a non-struct
lift, and an `is_sorted` past depth 1 each raise at resolution (rows 18, 6,
and 24).

The view types are a **build-layer** convenience. They add no state beyond
`ParamExpr`, have no serialized footprint, and do not appear in the IR:
`ParamDef.type_kind` remains a string (see *IR*), and resolution and every
downstream layer read `ParamDef` unaffected. Choosing a second type still raises
the path-named resolution error (row 2) for any definition that reaches
resolution, so the law holds for programmatically-constructed definitions as
well as fluent ones.

### Scalar

| Method | Value | Notes |
|---|---|---|
| `.real(lo, hi, periodic=False)` | `float` | Bounds inclusive; `lo == hi` legal (constant); `lo > hi` is a resolution error. Bounds accept `ArithExpr` as sugar; see *Expression bounds are sugar*. `periodic=True` makes the domain half-open `[lo, hi)` with `hi ≡ lo`; `hi` itself is then invalid. |
| `.integer(lo, hi)` | `int` | Bounds inclusive. Bounds accept `ArithExpr` as sugar; see *Expression bounds are sugar*. |
| `.categorical(*values)` | `Any` | Unordered. Only `==`, `!=`, `.is_in()`. Mixed types allowed; declared values must be distinct (type-tagged equality) and may not share a string image. |
| `.ordinal(*values)` | `Any` | Ordered by declaration position. Comparison yes, arithmetic no. Values must be distinct. Single-value ordinals are legal (constant). |
| `.bool()` | `bool` | Usable directly as `BoolExpr`. Strict: `1` and `"true"` are invalid. |

### Combinatorial

| Method | Value | Notes |
|---|---|---|
| `.subset(items, min_size=0, max_size=None)` | `list` | Set semantics: order irrelevant, no duplicates. Items must be distinct. |
| `.permutation(items)` | `list` | All items, any order. Items must be distinct. `.prior()` unsupported; sampling is uniform shuffle. Constraints via `.position_of()`. |

### Structural

| Method | Value | Notes |
|---|---|---|
| `.choice(*bare, *tuples, **keyword)` | see below | At least one variant; a single variant makes the discriminator constant. Variant names are unique **within the choice** and obey the name-character rules regardless of syntactic route (bare, tuple, keyword, or `**splat`). |
| `.space(*exprs)` / `.space(prebuilt: Space)` | `dict` | Struct-valued param: unconditionally-present grouping under a namespace. Per-element constraints on repeated structs require the prebuilt-`Space` form, the inline form having nowhere to hang a `.forbid`. |

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

Variant names never occupy the parent scope, so two choices in one scope may
both declare a variant `"fast"`.

### Program

| Method | Value | Notes |
|---|---|---|
| `.symbolic(signature, primitives, max_depth, validators=None, sampler=None)` | `{"ast", "source"}` | Structured expression trees. Variables auto-derived from `signature.args`. **Non-generative** unless `sampler=` opts in a generator (non-serializable; tree genomes are genotypes, so generation is solver territory otherwise). `validators` are callables over the AST. |
| `.code(signature, description="", constraints=None, examples=None, validators=None)` | `{"source": str}` | Freeform source. **Always non-generative**; there is no `sampler=` form. `validators` are callables over the source string. `description`, `constraints`, and `examples` are declared, serialized, fingerprinted metadata for a consumer's own backend, which core never interprets. |

Core's job for a program param is to *declare* the space, to *validate* a
submitted value's structure against that declaration, and to carry the value
through every existing surface. It never generates or evaluates one; tree and
program generation are out of scope.

**`.symbolic()`'s value.** `{"ast": <node>, "source": <str>}`. The `"source"`
key is optional, is a string when present, and is never cross-checked against
`"ast"`: core owns no printer and no parser, and rendering is not what makes a
value valid. A node is one of:

```
node ::= {"op": name, "args": [node, ...]}   # primitive application
       | {"var": name}                       # name in signature.args
       | {"const": number}                   # within some declared literal's bounds
```

A value validates when every `"op"` name is one this param declared (a bare
string in `primitives`, or a `Primitive`'s `name`), every `"var"` name is a key
of `signature.args`, every `"const"` lies within the bounds of some declared
`FloatLiteral` or `IntLiteral`, and tree depth is `<= max_depth`, where a leaf
is depth 1. With no literal declared, `{"const": ...}` is never valid.
`validators` run after this structural check, over the AST. A validator
returning `False` invalidates the value, and a raising validator is treated the
same as a malformed value, never escaping a public call.

**Primitive vocabulary is open; arity binds only where declared.** A bare string
in `primitives` names a token this param's trees may use, and core assigns it no
arity and no meaning. `ds.Primitive(name, arity, fn=None)` is the mechanism for
pinning one. `arity` is an int (exact) or a `(lo, hi)` pair (`hi=None`
unbounded), checked against a matching `{"op": name, ...}` node's `len(args)`;
an int and its `(n, n)` spelling are fingerprint-equal under the
sugar-equivalence law. A `Primitive` may shadow a built-in-sounding name, which
is the supported way to pin one's arity. `fn`, if given, is never called by
core, since no evaluator ships and a consumer's own interpreter uses it, and it
rides the non-serializable set.

**`.code()`'s value.** `{"source": <str>}`, with `"source"` required.
`description`, `constraints`, and `examples` are plain declared metadata; LLM
backends and other program-generation strategies are out of scope. `examples`
entries must be JSON-serializable under row 23's rule.

**Generativity.** `.code()` is always non-generative. `.symbolic()` is
non-generative unless `sampler=` is given. Both follow the shared
non-generative-materialization rule under *Sampling and Generativity* that every
such param, custom included, obeys. `.freeze()` pins a program param via
`require(p == value)` plus `default = value`, the mechanism `.custom()` uses
(see *Space: Structural Operations*). Unlike `.custom()`, there is no shorthand
exception: a program value is always a plain, comparable, serializable JSON
dict, so `.slice()` supports it too. Custom's `.slice()` rejection is specific
to `.prop()`, which no program param has.

### Extension

| Method | Notes |
|---|---|
| `.custom(param_type: ParamType)` | Full protocol. Serializable, constraint-integrated via `.prop()`. |
| `.custom(sampler, validator)` | Callback shorthand. **Not serializable.** |
---

## Modifiers and Layering

Modifiers are chainable and immutable; each returns a new expression. They
belong to two layers.

**Domain-level** modifiers describe the element's domain and measure:

| Modifier | Applies to | Notes |
|---|---|---|
| `.prior(dist)` | real, integer | Any object satisfying `Prior` (see *Charts*). |
| `.prior(weights=[...])` | categorical, ordinal, bool, **choice** | Non-negative, not all zero, aligned to declaration order. Bool: `[False_w, True_w]`. |
| `.prior(weights=[...])` | subset | **Independent inclusion probabilities in `[0,1]`** per item. Absent `.prior()`, each item defaults to `0.5`, the maximum-entropy Bernoulli. Sampling draws independent Bernoullis and rejects on size bounds, so realized marginals under active size bounds differ from the declared values. |
| `.log_scale()` | real, integer | Sugar for `.prior(ds.Log())`; participates in prior last-write-wins. Requires `lo > 0`. |
| `.quantized(step=None, factor=None, include_hi=False)` | real, integer | Linear grid `lo, lo+step, …` or geometric grid `lo, lo·f, lo·f², …` (`factor > 1`); exactly one of `step` and `factor`. See *Charts* for measure and tolerance. |
| `.default(value)` | all | **Element default** when applied before a lift. Validated against the domain at resolution. |

**Identity-level** modifiers describe the param as a whole. They bind to the
outer param regardless of position, and writing one before a `.repeat()` when it
concerns the list is a resolution error rather than a silent rebind:

| Modifier | Notes |
|---|---|
| `.when(condition)` | Multiple calls ANDed. Presence semantics (see *Expressions*). |
| `.tag(*tags)` | Accumulates. Empty string rejected. |
| `.meta(mapping=None, **kwargs)` | Merges; last-write-wins per key. Values may be any JSON-serializable value: scalars, lists, or nested dicts (matching row 23). Each scalar leaf is type-tagged recursively in the fingerprint, under the same codec as `default`. Constraint-level `meta=` on `.forbid`, `.require`, `.encourage`, and `.discourage` follows the identical rule. |
| `.default(value)` | **List default** when applied after a lift: legal only for static counts; length must match; mutually exclusive with element defaults on the same param. |

**The lift.** `.repeat(count)` closes the element definition. Everything left of
it defines the element; everything right applies to the list.

```python
ds.param("dropout").real(0.0, 0.6).log_scale().repeat(4)          # List(Float64)
ds.param("layers").space(...).repeat(ds.param("n_layers"))        # List(Struct)
ds.param("mask").bool().repeat(8).repeat(8)                       # List(List(Boolean)): legal
ds.param("grid").real(0.0, 1.0).repeat(2, 3)                      # variadic sugar: shape (2, 3)
ds.param("pipeline").choice(...).repeat(n)                        # heterogeneous list: legal
```

- `count: int | ArithExpr`, resolution-checked to be integer-typed (row 12)
  against a **closed, resolution-time calculus**: int literals; integer params;
  `ds.count`, `.size()`, `.length()`, `.position_of()`, and `.count_of()`, which
  are int by construction, a match count or an occurrence count being an int
  regardless of what it counts; a declared-`int` `.prop()`; `.sum()` over an
  integer- **or** bool-leaved lift, `sum([True, False])` being an `int`;
  `.min()` and `.max()` over an **integer**-leaved lift only, `min([True,
  False])` being a `bool`, which is the one asymmetry in the calculus; a
  literal-valued `.sum_over()` mapping; `+ - * %` over two int-valued operands;
  `**` with a non-negative literal integer exponent; and `.if_inactive()` when
  both branches are int-valued. Division and anything outside this set is row
  12. A negative evaluated count is a validation error, and `0` yields `[]`.
      Counts remain runtime-evaluated, unlike bounds, because lists are
      structure rather than charts. A count that references another param joins
      the dependency graph and cycle check, so that param must be assigned
      before the list can be materialized, exactly as a condition does.
- **Variadic sugar.** `.repeat(*counts)` reads as a numpy shape, first count
  outermost, and desugars to chained lifts in reverse order: `.repeat(2, 3)` is
  `.repeat(3).repeat(2)`, fingerprint-equal under the sugar-equivalence law. Any
  count may be an `ArithExpr` per axis. The chain retains one capability the
  sugar elides, namely per-level list modifiers between lifts
  (`.repeat(8).default([...]).repeat(8)`).
- **Container elements are bounded to one lift level.** A `struct`- or
  `choice`-typed element may sit under **at most one** `.repeat()`. Scalar,
  subset, and permutation elements nest arbitrarily, so
  `mask.repeat(8).repeat(8)` is legal. Two levels is a resolution error (row
  34). The boundary is the merged *shape* rather than the syntax reaching it, so
  the chained spelling (`.space(...).repeat(3).repeat(2)`) and the
  **compositional** one (a struct/choice lift declared inside another lift's
  element `Space`, composing to `rows[].spans[].lo`) are rejected identically.
  The boundary is a scope boundary: the per-instance expansion that turns a
  `"[]"` template into `"[k]"` entries is single-level.
- Element values are the element type's self-contained value: scalars, dicts,
  choice values.
- Constraints declared inside a repeated element `Space` are **instantiated per
  element**. Introspection lists them once under definition paths (`edges[].…`);
  evaluation reports one `ConstraintEval` per instance path.

**Duplicate modifiers.** Value-bearing modifiers (`prior`, `default`,
`quantized`) are last-write-wins within a layer. Accumulating modifiers (`tag`,
`meta`, `when`) stack.

---

## Paths and Scoping

One grammar is used everywhere: references, `flatten` keys, DataFrame columns,
`validate_param` names, diffs, and error messages.

```
path     := segment ("." segment)*
segment  := name ("[" i "]")*        # instance path
          | name ("[]")*             # definition path
```

Segments are param names, variant names, and struct-param names. `name[i]`
addresses a repeat element (**instance path**), with one index per lift level
for nested lifts (`mask[2][3]`). An index `i` may be **negative**, resolved
against the lift's realized length, so `name[-1]` is the last element. `name[]`
denotes the element schema (**definition path**), used by introspection and
illegal in expressions, likewise repeated per level (`mask[][]`).

**Scoping rule, the only one:** resolve the first segment by walking **up** to
the innermost scope where it binds, then descend through the remaining segments.
A bare name is the one-segment case. Shadowing behaves like lexical closures.
Cross-scope constraints are declared at the common ancestor. Composed spaces are
therefore *relocatable*: nesting a space under a variant or struct never
rewrites its internal references.

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

`BoolExpr` and `ArithExpr` are walkable ASTs exposing `.kind: str`, `.params:
frozenset[str]`, and `.children: tuple`. **`Expr`** names their common base, for
signatures accepting or returning either (`Encoding.decode_expr`,
`Encoding.rewrite`).

**BoolExpr**, for `.when()` and the constraint verbs (`.forbid()`, `.require()`,
`.encourage()`, `.discourage()`):

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

**ArithExpr**, for the constraint verbs, expression bounds, and repeat counts.
Comparisons yield `BoolExpr`:

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
expr.if_inactive(fallback)              # inactive -> fallback; unset stays pending
```

**`ds.value`** generalizes `.prop()` from one custom param and a named property
to any operands and an arbitrary function, and is dual-typed the same way.
`returns` is one of `int|float|bool|str`, row 16's scalar restriction applying
identically, and a `bool`-returning value is usable bare as a condition.
Operands are ordinary expressions passed positionally, so `.if_inactive()` and
any other coercion composes inside them. `fn` is called with **exactly those
operand values and never the config**, which is what makes the reference set
trustworthy: a function reading something it was not given raises rather than
reading it silently. The referenced params are the union of the operands' own
references, leaving `dependency_graph`, ordering, and cycle detection
unaffected. `returns=float` keeps margins, so `ds.value(deflection, …) <= 0.005`
reports `0.005 − deflection`. `returns=int` may drive a `.repeat()` count.
Operand choice is asymmetric: under-declaring fails loudly, while
**over-declaring weakens silently**, since an operand the function ignores still
makes the whole node Unknown when it goes inactive, and Unknown constraints are
inapplicable. `fn` is opaque, so a space using `ds.value` is not serializable
(see *Identity and Serialization*).

**Chart application** is the one other opaque-free leaf: a node applying a
param's chart to a unit coordinate, emitted by a representation when it
substitutes a decode into a transported expression (see *The representation
layer*). It carries the **source** chart's declaration, meaning domain, prior,
and quantization, because the param it reads in the genotype is an ordinary
`real(0,1)` whose own chart is uniform. It is vector-polymorphic: applied to a
lift or a projection it maps element-wise. These two are the only nodes the
expression language will grow. Anything structurally expressible goes through
the language; anything else goes through `ds.value`. There is no third category.

`.prop()` is dual-typed like a bare param reference (see *Builder view types*,
`BoolParamExpr`): a bool-declared prop is usable directly as a condition, as in
`.require(ds.param("c").prop("ok"))`, with `&`, `|`, `~`, and `.implies()`, and
no `== True` needed. It coerces via `bool(value)` at evaluation exactly like any
other bare `BoolExpr` leaf. Row 16's undeclared-property and non-scalar-type
checks apply uniformly to this position. A non-bool-declared prop used bare is
not separately rejected, matching the same convention.

**Vector expressions and aggregates.** A scalar lift *is* a vector expression,
and `.field(name)` projects a struct lift into one. The aggregate namespace
lives on vector expressions only:

```python
.sum()  .min()  .max()
.count_of(*values)          # equality-comparable elements; on lifted choices, counts variants
.is_sorted(descending=False)
.distinct()                 # scalar lift: pairwise-distinct elements
.distinct(*fields)          # struct lift: distinct field tuples
```

**Nested lifts.** Numeric and equality aggregates (`sum`, `min`, `max`,
`count_of`, `distinct`) operate over the **leaves**, flattened across all
levels. `.field()` on nested struct lifts projects leaves shape-preservingly,
and its aggregates likewise flatten. `is_sorted` is restricted to depth 1;
deeper is a resolution error, a grid having no canonical order. Kleene and the
empty-aggregate rules apply unchanged to the leaf set. Per-axis constraints need
no axis machinery: give the axis a scope and use per-instance instantiation.

```python
ds.param("rows").space(
    ds.param("cells").real(0.0, 1.0).repeat(8),   # row-scope forbid on
).repeat(8)                                        # ds.param("cells").sum() -> per row
```

Instance paths are legal in expressions, as in `ds.param("stops[0].dwell_min") <
10`, at any nesting the grammar admits (`g[0][1]`, `layers[2].act[1]`).
**Negative indices are admitted**, resolved against the lift's own realized
length. For a *dynamic* count, `x[-1]` is the only way to name the last element.
A negative index still references exactly that lift, leaving
`dependency_graph`, `topological_order`, and the bound envelopes untouched. An
out-of-range index makes the leaf inactive, and so Unknown, wherever the length
is a *runtime* fact, meaning a dynamic count. Against a **static** count the
length is known at resolution, so an out-of-range index such as `repeat(3)` with
`y[7]` is a resolution error (row 29) rather than a silently inapplicable
constraint. An `ArithExpr` index is excluded entirely (see *Out of Scope*).
`.field(name)` requires a struct lift whose element declares `name`; projecting
an undeclared field, or `.field()` on a non-struct lift, is a resolution error
under row 6 as a nonexistent definition path, not a silent Unknown. Ordinals
support comparison only; two ordinal *params* compare only if they declare
identical value sequences, and comparing an ordinal against a literal that is
not one of its declared values is a resolution error (row 18). Categoricals
support `==`, `!=`, and `.is_in()` only.

**Runtime equality.** `==`, `!=`, and `.is_in()` compare `bool` by type-tagged
identity against everything else, so `True ≠ 1` and bool is strict; `int` and
`float` numerically against each other, so `1 == 1.0`; and every other pair,
meaning strings and other `Any`-typed categorical or ordinal values, by exact
type match. This runtime rule is distinct from declaration-time distinctness
(rows 3 and 4) and from fingerprint canonicalization, both of which type-tag
uniformly. A categorical declaring both `1` and `1.0` as distinct variants
therefore cannot tell them apart by a runtime `==`.

**Guardrails.** `__bool__` and `__contains__` on expressions raise informative
`TypeError`s, so `expr1 and expr2`, `0 < ds.param("x") < 1`, and `v in
ds.param("s")` fail loudly rather than miscompiling silently.

### Three-valued semantics

Expressions evaluate in Kleene logic. **Unknown** arises only from inactivity.

1. **Leaves.** Any predicate or arithmetic term over an *inactive* param is
   Unknown. `is_active()` is the sole total predicate. Projection over an
   *inactive* lift is Unknown, which is distinct from an *active empty* list
   (rule 6). A `ds.value(...)` node is Unknown if and only if **evaluating** one
   of its operands yields Unknown, joining provenance per rule 5 when more than
   one does. This is not a literal scan of the referenced params' activity, so
   `.if_inactive()` and any other coercion inside an operand composes, and `fn`
   is not called in that case. An opaque leaf obeys the same rule as a
   transparent one. An exception `fn` itself raises propagates uncaught: the
   calling convention, exactly the operand values and never the config, is the
   whole contract.
2. **Propagation.**

| a | b | `a & b` | `a \| b` |   | a | `~a` |
|---|---|---|---|---|---|---|
| T | T | T | T |   | T | F |
| T | U | U | T |   | U | U |
| T | F | F | T |   | F | T |
| U | U | U | U |
| U | F | F | U |
| F | F | F | F |

   Comparisons and arithmetic with an Unknown operand are Unknown.
   Range-tracking is specific to `ds.count`, which tracks `[t, t + u]` over the
   True count and the Unknown count and is Unknown if and only if the comparison
   outcome differs across that range. Every *other* aggregate (`sum`, `min`,
   `max`, `count_of`, `is_sorted`, `distinct`) containing any Unknown element is
   itself Unknown by plain propagation, with no range computed: a non-empty
   vector is an ordered collection of operands, and one Unknown operand makes
   the whole Unknown, as for ordinary arithmetic. `count_of` resembles
   `ds.count` but is a distinct construct over a vector and does not
   range-track.

3. **Coercion at `.when()`:** Unknown becomes False. Deactivation therefore
   cascades along `topological_order`.
4. **Coercion at the constraint verbs on complete configs:** Unknown becomes
   **inapplicable**, not violated, with `margin = None` and
   `ConstraintEval.applicable = False`.
5. **Unknown has a provenance, and `.if_inactive()` discriminates on it.**
   Unknown arises from three sources: *inactivity* (rule 1), *emptiness*, being
   `min` or `max` over an active empty lift (rule 6), and, in partial evaluation
   only, an *unset* operand, which makes a constraint **pending** rather than
   Unknown. `.if_inactive(fallback)` coalesces **inactivity alone**. It never
   eats pending and never eats emptiness. Both restrictions fail silently if
   ignored: eating pending makes a driver loop conclude a constraint is
   satisfied while the values that will violate it are still unassigned, and
   eating emptiness turns an undefined `max([])` into the fallback while the
   lift is *active*, which the method's own name disclaims. An author who wants
   an empty lift to contribute a value writes that explicitly rather than
   relying on the inactivity guard. A node combining more than one
   Unknown-valued operand, such as `a & b` with `a` inactive and `b` pending,
   keeps the **strongest** provenance under `inactive < pending < permanent`, so
   `.if_inactive()` refuses to coalesce whenever any contributing operand was
   pending or a structurally malformed value, the latter carrying permanent
   provenance.
6. **Empty aggregates** over an active lift with zero elements: `sum → 0`,
   `count_of → 0`, `distinct → True`, `is_sorted → True`, and `min`/`max` →
   **Unknown**, whose containing constraint goes inapplicable rather than
   erroring.
7. **Bound couplings are constraints and follow rule 4.** Expression bounds
   desugar to bound-origin constraints (see *Expression bounds are sugar*). When
   the referenced param is inactive while the target is active, the coupling is
   inapplicable and the target ranges over its envelope. An author wanting
   strict coupling writes it explicitly as `.when(ds.param("y").is_active())`.

The inactive-projection and active-empty cases are the most confusable pair in
the semantics:

```python
# use_aux = False  -> aux_layers inactive -> .field("w").sum() is Unknown -> constraint inapplicable
# use_aux = True, n_aux count yields []  -> sum() == 0 -> constraint applies and is satisfied
```
---

## Constraints and Feasibility

Chainable on `Space`, each returning a new `Space`:

| Method | Purpose |
|---|---|
| `.forbid(*conditions, tags=(), meta=None)` | Defines **feasibility**. Violating configs are invalid and rejected by the reference sampler. The argument names the **forbidden (bad)** state |
| `.require(*conditions, tags=(), meta=None)` | Defines **feasibility** via the **required (good)** state: feasible if and only if the predicate is satisfied. The polarity-inverse of `.forbid`, sugar-equivalent to `.forbid(~condition)` in feasibility, margin, and fingerprint |
| `.encourage(*conditions, tags=(), meta=None)` | Declares an evaluated, annotated predicate naming a **desired (good)** state. Reported with a margin; **never** affects feasibility or the reference measure |
| `.discourage(*conditions, tags=(), meta=None)` | Declares an evaluated, annotated predicate naming an **undesirable (bad)** state, the soft complement of `.encourage` (`== encourage(~condition)`). Reported; never affects feasibility |
| `.anchor(configs: dict[str, dict])` | Named reference configs, validated at resolution |
| `.meta(mapping=None, **kwargs)` | Space-level metadata (objectives, cost models, anchor-role conventions) |

**The constraint quartet.** The four predicate verbs are two polarity pairs on
two axes. **Hard** verbs (`forbid`, `require`) affect feasibility; **soft**
verbs (`encourage`, `discourage`) are declared and reported and never affect
feasibility. Crossed with that is the **polarity** of the stored predicate: a
`forbid` or `discourage` names a *bad* state, where the good outcome is not
satisfying it, and a `require` or `encourage` names a *good* state. Each verb is
the polarity-inverse of its partner: `require(e) == forbid(~e)` and
`discourage(e) == encourage(~e)`. Every verb produces a `Constraint`. Read its
category and polarity through the derived accessors rather than the storage:
`Constraint.kind` is one of `"forbid"`, `"require"`, `"encourage"`,
`"discourage"`, `"bound"`; `Constraint.feasible_when_satisfied` gives the
polarity and is `False` only for the bad-state verbs; and
`ConstraintEval.violated` is polarity-correct, an inapplicable eval never being
violated and any other being violated if and only if `satisfied` differs from
the desired polarity.

Feasibility is defined by param validity plus forbids **and requires** only.
`validate().valid`, `is_feasible()`, and `infeasibility_reasons()` never
consider the soft `.encourage()` and `.discourage()` declarations, which appear
in `constraint_evals` with margins so that nothing is hidden. Core stores `tags`
and `meta` on constraints and never interprets them; penalty shapes, weights,
priorities, and relaxation orders are consumer policy attached via `meta`. A
directional preference with no threshold, such as "minimize capex", has no
predicate and no margin, is not a constraint, and belongs in space-level
`.meta()` as an objective declaration.

**`require`, the positive complement.** `space.require(e)` declares that
feasible configs must *satisfy* `e`, sparing the user the inversion `.forbid`
demands. It carries `origin="require"` and stores the **desired (feasible)**
predicate `e`, the same feasible-if-satisfied convention a bound-origin
constraint uses, so introspection and `infeasibility_reasons` read in the user's
own terms and the reported `margin` is `margin(e)` directly, positive being
slack. Its Kleene behavior is `forbid(~e)`'s: `require(e)` is **violated if and
only if `e` is definitely False**, and an Unknown or True `e` is feasible,
Unknown giving an inapplicable eval with `margin = None`. It is therefore
feasibility-, margin-, and fingerprint-equal to `.forbid(~e)`. The fingerprint
preimage canonicalizes every polarity-opposite constraint, whether `origin` is
`bound`, `require`, or `discourage`, to its baseline-polarity (negated) form,
which keeps `origin` semantics-neutral (see *Identity and Serialization*,
normalization pipeline).

**`discourage`, the soft complement of `encourage`.** `space.discourage(e)`
declares that `e` names an *undesirable* state, the soft sibling of `.forbid` as
`.encourage` is the soft sibling of `.require`. It carries
`origin="discourage"`, stores the bad-state predicate `e`, and is flagged as a
violation if and only if `e` is satisfied, mirroring `.forbid`'s Kleene
polarity. Being soft, it **never affects feasibility**: it is dropped from the
`sampling` fingerprint scope, and only `sample(..., reject_soft=True)` rejects
on it. It is fingerprint-equal to `.encourage(~e)` and fingerprint-distinct from
`.encourage(e)`, its preimage canonicalizing to `Not(e)` for the same reason
`require`'s does.

**White, grey, and black box.** A predicate's transparency decides how much of
the library's machinery can act on it:

| tier | form | margins | `remaining_domain` narrowing | tighten-not-reject |
|---|---|---|---|---|
| white | expression over param values | yes | yes | yes (bound-origin) |
| grey | opaque scalar under a structural comparison: `prop("n") > 3`, `ds.value(f, …, returns=float) <= c` | yes | no | no |
| black | opaque predicate: `ds.value(f, …, returns=bool)` | no (`None`) | no | no |

Margins, `evaluate_partial`, `remaining_domain`, and bound-origin tightening all
run on structure. A grey predicate is available wherever the quantity under test
has a numeric value: exposing it as `returns=float` under a comparison keeps the
margin that a `returns=bool` wrapper discards.

### Margins

`ConstraintEval.margin` is the signed distance to the boundary in the
constraint's own units. Positive is slack, negative is violation magnitude, zero
is on the boundary.

| Form | Margin |
|---|---|
| `a <= b` / `a < b` | `b − a` |
| `a >= b` / `a > b` | `a − b` |
| `a == b` | `−abs(a − b)` |
| `a != b` | `abs(a − b)`; violated implies 0, never negative |
| non-numeric leaf, such as categorical `==` | `None` |
| `p & q` | `min(margin(p), margin(q))` |
| `p \| q` | `max(margin(p), margin(q))` |
| `~p` | `−margin(p)` |

`None` absorbs through composition. The composition rules preserve the
satisfaction invariant, so `&` holds if and only if the minimum is at least 0,
and composite geometric constraints such as exclusion zones keep usable margins.

**Continuous-equality warning.** An `==` constraint over purely continuous,
unquantized operands is measure-zero under sampling, and resolution emits a
warning pointing at generative reparameterization (see *Solver Integration*) or
`.custom()`. *Purely* qualifies the whole comparison: the warning fires only
when no operand is discrete-typed (categorical, ordinal, bool, integer, or
quantized) and at least one is an unquantized real. A discrete operand anywhere
suppresses it.

### Expression bounds are sugar

`ds.param("x").integer(1, ds.param("y"))` desugars at resolution to
`ds.param("x").integer(1, env_hi)` plus the implicit hard constraint
`ds.param("x") <= ds.param("y")`. There is exactly one encoding of a bound
coupling, and the bound syntax is notation for it. The envelope is the
interval-arithmetic hull of the bound expression over the referenced params'
already-enveloped domains, computed along the dependency DAG. A **hi**-bound's
envelope is the hull's **supremum** and a **lo**-bound's its **infimum**: the
chart must cover the widest value any legal assignment of the dependencies could
produce, charts being static, and the bound-origin constraint narrows the domain
back down per config. A dependency need not be a literal; it may be any real or
integer param carrying its own prior, quantization, or bounds, and envelopes
chain along the DAG. A bound expression with no computable hull is a resolution
error (row 20), whose stated workaround is the desugared form written by hand.

- **Computable op set.** The envelope engine is **minimal**: `+` and `−` over
  any enveloped sub-expressions, and `*` with one **syntactically literal**
  operand, so chained literal scaling such as `y * 2 * 3` is admitted. `/`,
  `**`, `%`, `*` of two non-literal operands, and any vector, count, or field
  operator have no computable interval hull and are row 20; the workaround is
  the manual expansion, a hand-computed literal envelope plus a `.forbid()` in
  forbidden-state form. A bound on a param *inside* a `.repeat()` element is not
  supported; express it as a per-element `.forbid()` via the prebuilt-`Space`
  form.
- **Scope.** Bound expressions resolve **eagerly** in the declaring scope and
  tolerate no enclosing-scope up-reference, unlike `.when()` conditions (see
  *Resolution*, resolution timing). The chart is built during this scope's
  resolution, before any enclosing scope merges, so an up-reference could not
  yet resolve. Cross-scope bound couplings use the same route as cross-scope
  constraints: write them by hand at the common ancestor.
- **Provenance and polarity.** The implicit constraint carries `origin="bound"`,
  against `"user"` for a user constraint, so errors can say "`x` exceeds its
  declared bound `y`" and introspection can distinguish the two. It stores the
  **desired** predicate `x <= y`, which is what yields the `y − x` margin. This
  is the opposite of `.forbid()`'s convention that the argument names the
  *forbidden* state, because feasibility here is evaluated as
  feasible-if-satisfied. The hand-written *feasibility*-equivalent is therefore
  `.forbid(ds.param("x") > ds.param("y"))`, the forbidden-state spelling, and
  not `.forbid(x <= y)`, which would invert feasibility. `origin` is derived
  provenance and is excluded from the fingerprint preimage, so that
  fingerprint-equality still tracks feasibility, equal fingerprints having to
  mean equal valid-config sets, the preimage encodes a bound-origin constraint
  in its **forbidden-state (negated) form**. That makes the sugar
  fingerprint-equal to its `.forbid(x > y)` manual expansion (see *Identity and
  serialization*, normalization pipeline), and upholds the invariant that **no
  preimage-excluded field may be feasibility-load-bearing**.
- **Ordering.** Bound-origin constraints, unlike user constraints, enter
  `dependency_graph` and `topological_order`, preserving assign-`y`-before-`x`
  ordering.
- **Margins.** The coupling yields a `y − x` margin, which is why the stored
  predicate is the desired `x <= y` rather than the forbidden `x > y`.
- **Inclusivity.** Bounds are inclusive. Strict orderings, such as Wolfe's `c1 <
  c2`, need an explicit strict constraint or an epsilon.
- **Scaled measures**, such as "Beta scaled to `[0, y]`", are not truncations
  and are not expressible as bounds. Use generative reparameterization: encode
  `frac ∈ [0,1]` with the prior and let the consumer derive `x = frac·y`. ---

## Charts

Every generative scalar param resolves to a **chart**, a monotone map `[0,1] →
domain`. Sampling is `chart(u)`, solver geometry is u-space, and integers and
quantization are the same mechanism.

### Built-in prior families

Bounds-aware and parameterless; resolution composes them with `[lo, hi]`:

| Prior | `chart(u)` | Requires |
|---|---|---|
| Uniform (default) | `lo + u·(hi − lo)` | none |
| `ds.Log()` | `exp(log lo + u·(log hi − log lo))` | `lo > 0` |
| `ds.Logit()` | `σ(logit(lo) + u·(logit(hi) − logit(lo)))` | `0 < lo ≤ hi < 1` |
| `ds.Power(p)` | `(lo^p + u·(hi^p − lo^p))^(1/p)` | `p ≠ 0`; `tᵖ` monotone on `[lo, hi]`: `lo ≥ 0` unless `p` is a positive odd integer, and `lo > 0` when `p < 0` |

The `Requires` column is the operative rule (`p ≠ 0`; `lo ≥ 0` unless `p` is a
positive odd integer; `lo > 0` when `p < 0`). It guarantees that the closed-form
signed-root chart is a strictly increasing bijection onto `[lo, hi]`.
Monotonicity of `tᵖ` is necessary but is not the test, the rule being stricter,
because the signed-root formula does not recover `[lo, hi]` on every monotone
domain. It rejects (row 9) a domain straddling 0 (`lo < 0 < hi` with
non-odd-integer `p`), including the degenerate `lo^p == hi^p` case (`Power(2)`
over `[-a, a]`) and the domain-incomplete `Power(2)` over `[-2, 3]`, which would
map onto `[2, 3]`; and an all-negative even-`p` domain (`Power(2)` over `[-4,
-2]`), which is monotone yet unrecoverable by the formula.

Each family has a closed-form inverse, so `to_unit(value)` always exists for
built-ins. `lo == hi` yields the constant chart, still generative; `to_unit` at
that degenerate point is unspecified and returns `0.0`, and nothing observable
depends on it, `from_unit` returning the single legal value for every `u`.

### External priors

Any object satisfying `Prior`, with `.ppf(q)` required and `.cdf(value)`
optional. At resolution: if `ppf(0)` and `ppf(1)` are finite and inside `[lo,
hi]`, the support is contained and `ppf` is used directly, `cdf` then gating
only inverse mapping, surfaced as `invertible` in introspection. Otherwise the
chart is the truncation `ppf(cdf(lo) + u·(cdf(hi) − cdf(lo)))`, and a missing
`cdf` is an error. **Silent clipping of tail mass onto the bounds is
forbidden**, the same rule as the ban on default clamping.

### Integers

The continuous chart is built over `[lo, hi + 1)` and the emitted value is
`floor(chart(u))`. A uniform prior gives exactly uniform draws over `{lo..hi}`,
and `Log()` gives standard log-uniform integers with no endpoint bias. The
inverse is interval-valued: value `k` owns `[chart⁻¹(k), chart⁻¹(k+1))`,
`to_unit(k)` returns the interval midpoint, and the interval itself is exposed
for solvers.

### Quantization

The grid is `g_k = lo + k·step`, or `g_k = lo·factor^k`. The chart is built over
the extension `[g_0, g_K + cell)` and the emitted value is the greatest grid
point at or below the continuous draw. Consequently a uniform prior gives
equiprobable grid points, any prior gives each point the prior measure of its
cell, and an integer param *is* a quantized real with `step=1`.
`include_hi=True` appends `hi` as a final grid point whose own cell width
follows the same local-spacing formula as a grid point one step further out
(`step`, or `hi·(factor − 1)`). A degenerate `step ≥ hi − lo`, with geometric
analogue `factor ≥ hi / lo`, yields the single-point grid `{lo}`, plus `hi` if
included. A `step ≤ 0` or non-finite step is a resolution error.

**Grid membership and canonicalization.** Validation recovers `k = round((v −
lo)/step)` and the value is valid if and only if `0 ≤ k ≤ K` and `|v − (lo +
k·step)| ≤ tol`, with `rtol=1e-9` by default and overridable. `config_hash`
canonicalizes to `lo + k·step` computed the same way. Canonicalization is
context-free, all grids being static, as all charts are.

### Periodicity

For `periodic=True` reals the canonical domain is `[lo, hi)`, the chart maps
`[0,1) → [lo, hi)`, and `hi` is invalid, so hashing is canonical by
construction. The flag sits on `ParamDef` for solvers to read and apply
wraparound moves and periodic kernels, and a representation must **mirror it
onto the genotype**: `from_unit(1.0)` yields `hi`, which is not a domain member,
so an unmirrored unit target would decode outside the source domain.

### All charts are static

Every chart is built once, at resolution, over the param's envelope bounds, with
expression bounds desugared first (see *Expression bounds are sugar*).
Chart-family requirements, meaning `Log()`'s `lo > 0`, `Logit()`'s `(0,1)`, and
`Power(p)`'s monotonicity domain, are checked against the *declared* envelope
bounds `(lo, hi)`, which do not move under quantization or the integer
extension, even though the continuous chart math is built over a wider bound
(`hi + 1` for integers, the grid extension for quantized). `ParamDef.chart` is a
plain attribute. The genotype-to-phenotype map therefore never depends on other
genes, so u-space coordinates are comparable across configs.

**`to_unit` is what makes a representation invertible.** It exists for every
closed-form family, and for an external prior only when that prior supplies
`cdf`. A `Prior` with `ppf` alone yields a chart that decodes but cannot encode,
so any representation touching it is not invertible. The two cell-valued kinds
return different representatives: an **integer**'s `to_unit(k)` is the interval
**midpoint**, while a **quantized** real's is the cell's **left edge**,
`to_unit(g_k) = (g_k − lo) / (g_K + cell − lo)`. Both satisfy
`from_unit(to_unit(v)) == v`, which is the only law either owes.

The reference sampler *may* recognize a bound-origin constraint whose referenced
params are already assigned and draw from the correspondingly tightened chart
instead of rejecting. The result is observably identical, truncation being
conditioning, and tightening an external prior to a sub-interval needs `cdf`,
absent which the sampler rejects. This is a **best-effort** optimization,
layered on top of the hard bound-origin constraint that always sits in
`space.constraints`. It applies only to the closed-form families (Uniform,
`Log()`, `Logit()`, `Power(p)`) over a non-quantized real or integer. External
priors without `cdf`, quantized grids, and any dependency not yet assigned at
draw time fall through unchanged to rejection. Correctness requires only that
tightening never fire where truncation differs from conditioning; completeness
of the tightened-family list is not required, since every un-tightened case
rejects and rejection is always sound.
---

## Sampling and Generativity

```python
.sample(n, seed=None, reject_soft=False) -> pl.DataFrame   # requires the `polars` extra
.sample_one(seed=None, reject_soft=False) -> dict
.sampling_report(n=1000, seed=None, tighten_bounds=False) -> SamplingReport
```

`seed: int | numpy.random.Generator | None`. The reference sampler is an
interpreter of declared measure: it walks `topological_order`, decides activity,
and draws active generative params through their charts, using weights for
categorical, ordinal, bool, and choice; Bernoulli draws plus size rejection for
subsets; a uniform shuffle for permutations; and `sample(rng)` for customs. It
rejects on **forbids and requires only**, a `require` being a forbid of the
negated condition. `reject_soft=True` additionally rejects soft-constraint
(`.encourage()`, `.discourage()`) violations, which is rejection on a
user-declared predicate and is off by default. The default maximum is 10,000
retries, after which an informative error names the constraints that dominated
rejection.

**Rejection hostility.** Dense combinatorial forbids, such as pairwise
`distinct` or conflict sets near packing limits, collapse rejection acceptance.
The remedy is constructive: enforce the invariant inside a `.custom()` sampler,
or reparameterize (see *Solver Integration*). The retry-exhaustion error links
here.

**Generative and non-generative params.** Every param is generative except
`.code()`, `.symbolic()` without `sampler=`, and a full-protocol
`.custom(param_type)` whose `param_type` declares no `sample()`. The
`.custom(sampler, validator)` shorthand is always generative, a sampler being
required. `sample()` raises a `SamplingError` naming the offending params **if
and only if** it must materialize a value for a non-generative param. A
`.default()` satisfies it, `freeze` and `slice` remove it, and a param inactive
for the draw in progress never triggers it.

Sampling always produces explicit values and **ignores defaults**. Measure bias
is the prior's job.

---

## Defaults

Defaults follow a cascade:

- A **choice default names a variant**, as a string. A struct param or activated
  variant payload fills **field-wise** from its members' own defaults, and a
  struct carries no own default value. If a config already supplies a choice's
  variant, partial input wins and that variant's payload is filled from its own
  members' defaults.
- **Element defaults**, declared pre-lift, are count-independent and legal under
  dynamic counts. **List defaults**, declared post-lift, are legal only for
  static counts, must match the length, and are mutually exclusive with element
  defaults on the same param. A default declared on a param inside a lifted
  struct or choice, meaning a `[]`-template field, fills into each materialized
  instance the same way.

```python
.apply_defaults(config) -> dict
.has_complete_defaults -> bool
```

`apply_defaults` is a **partial-evaluation operator**: idempotent, monotone,
never overwriting and never removing, and activity-respecting. It walks
`topological_order`, recomputing activity as it fills, and fills only params
whose activity resolves to *active* given the config so far, so a filled default
triggers downstream defaults in one pass. Params of *inactive* or *unknown*
activity are left untouched. Partial input wins field-wise: the fill merges into
the leaf representation and never replaces a supplied value or subtree.

**Counts and lifts.** A param used as a repeat count is filled from its own
default like any other, and since `topological_order` places a count param
before its list, that default determines the list length before materialization.
A count is **determined** when it is a static integer, when it evaluates to a
definite integer over the config, or when it is Unknown *solely because a
referenced param is inactive*, in which case it is **0** and the lift is the
complete value `[]`. `apply_defaults` emits only default values: it materializes
a lift, meaning its count and filled instance leaves, if and only if the count
is determined and either the count is 0 or at least one instance leaf receives a
default. Otherwise the lift is left implicit. `is_complete` and `missing_params`
re-derive the count from the config, so completeness is exact regardless.

Postcondition: the result is complete if and only if every param active under
the filled config has a default or was supplied. `apply_defaults` does not
guarantee completeness; check `is_complete`. `has_complete_defaults` is
`is_complete(apply_defaults({}))`.

Defaults validate against their static domain at resolution, and are **never
silently clamped**, the same rule as the ban on prior tail-clipping. The check
spans every kind: a choice default must name a declared variant, a subset or
permutation default must be a valid subset or ordering, and a struct param
admits no own default (row 21). `apply_defaults` is constraint-blind, so its
output may violate forbids, bound-origin couplings included, which `validate`
reports. This matches user forbids, which were never checked at fill time.

**Defaults and anchors.** Defaults are per-param fill values for completion;
anchors are named whole configs for reference. When a space has complete
defaults, derive rather than duplicate:
`.anchor(configs={"shipped": space.apply_defaults({})})`. Defaults do not
auto-create an anchor. Anchor roles such as incumbent and baseline are a
`.meta()` convention rather than API.

### Sampling diagnostics

`.sampling_report(n=1000, seed=None, tighten_bounds=False) -> SamplingReport`
draws `n` configs from the **unconditioned** measure, before rejection, and
aggregates what happened. It reports, and never repairs, reweights, or suggests.

`sample()` returns the post-rejection distribution, in which two pathologies are
invisible:

- **Unknown-swallowing.** Kleene rule 4 makes an unevaluable constraint
  *inapplicable*, and so accepted, which is the permissive direction and is
  silent. A constraint aggregating over optional params, such as `a + b + c <=
  budget` with `c` conditional, stops enforcing wherever `c` is inactive.
  `ConstraintReport.applicable` is the only signal, and `.if_inactive()` is
  usually the fix.
- **Funnels.** A constraint that is inapplicable on part of the space biases the
  conditioned measure toward that part, rejection accepting those draws
  unconditionally. This is correct, `require` conditioning the declared measure,
  and it is not visible from the resulting sample.

`satisfied` is conditioned on **applicability** rather than on all draws: a
constraint applicable in 1% of draws and always satisfied there reports `1.0`,
not `0.01`. When `applicable == 0.0`, meaning the constraint was never
Kleene-defined across all `n` draws, `satisfied` reports `0.0` by convention
rather than `NaN`, so a frozen report always equals itself. It carries no
information in that case, and `applicable` is the number to read.

**Tightening is opt-in and off by default.** The reference sampler's best-effort
tighten-not-reject optimization (see *All charts are static*) folds an
already-assigned bound-origin coupling into the draw itself, which is observably
identical to rejection *after* rejection. Drawn unconditioned it would launder
the report's own subject, collapsing the `ConstraintReport` rows of a
bound-coupled space to `satisfied ≈ 1.0`. `tighten_bounds=False`, the default,
draws every config against the full declared envelope, so `acceptance_rate`
reads as how much of the declared measure the hard constraints cut away and
bound-origin rows show their real satisfaction fractions. `tighten_bounds=True`
draws the way the reference sampler does, answering how much tightening saves.
The three sampling entry points (`sample`, `sample_one`, `sample_dicts`) take no
such flag, tightening being unable to change their returned distribution because
truncation is conditioning.

**Per-instance folding.** A per-element constraint, held in
`ListDomain.element_constraints` and instantiated once per active lift instance,
contributes one `ConstraintReport` row keyed by its template `Constraint` and
folded **per draw**: `applicable` is the fraction of draws where at least one
instance eval was Kleene-defined, and `satisfied` is the fraction of those draws
where every applicable instance was satisfied. A draw materializing zero
instances, the lift being inactive or active and empty, counts as inapplicable
for that row. `SamplingReport.activity` keys are exactly `set(space.params)`,
including `"[]"`-templated definition paths from inside a lifted struct or
choice, and a template key's value uses the identical per-draw fold, the
fraction of draws in which at least one of its instances was active. Every row
and every key therefore shares one denominator, `n`, and stays comparable to
`acceptance_rate` and to each other.
---

## Space: Validation

```python
.validate(config) -> ValidationResult
.validate_param(path, value, context=None) -> ValidationResult   # instance paths supported
.is_feasible(config) -> bool
.infeasibility_reasons(config) -> list[str]
.evaluate_constraints(config) -> list[ConstraintEval]
```

`is_feasible(c) == validate(c).valid`, both being defined by param errors plus
hard constraints. `evaluate_constraints` reports every constraint, hard and
declared, with `applicable` and `margin`. `context` enables evaluating
constraints that reference other params, bound-origin couplings included.
Without it, `validate_param` reports those as unevaluated rather than guessing:
an under-determined constraint, one referencing a param absent from `context`,
is **omitted** from `validate_param`'s `constraint_evals` rather than appearing
with a placeholder. `ConstraintEval` has no pending-on-missing-context state,
and reusing `applicable=False` would conflate it with a genuine Kleene-Unknown.

`validate` and `config_hash` operate on this space's own **phenotype** configs.
A genotype is a config of its own target `Space` and takes that space's
identity, `target.fingerprint()` and `config_hash(g, target)`, rather than being
a transformed view of a phenotype (see *The Representation Layer*).

---

## Space: Partial Configs

```python
.evaluate_partial(config) -> PartialEval
.remaining_domain(path, config) -> RemainingDomain | None
.param_activity(config) -> dict[str, "active" | "inactive" | "unknown"]
.is_complete(config) -> bool
.missing_params(config) -> list[str]
.topological_order -> list[str]              # definition paths
.next_assignable(config) -> list[str]        # instance paths: active, unset, dependency-ready
```

`topological_order` gives an assignment order in which every condition and
bound-origin constraint references only already-assigned params, so following it
makes any interruption point a well-defined partial config. It lists definition
paths and omits lift descendant templates. `next_assignable` is the derived
driver-loop sugar.

**Three-valued activity.** `param_activity` classifies each param as `active`,
its condition being `True` or absent; `inactive`, its condition being `False`;
or `unknown`, its condition being Kleene-Unknown **and** at least one param the
condition references being itself `active`-unset or `unknown`, meaning a
still-resolvable dependency. A condition left Unknown *solely* by inactive
operands is `inactive`, by the same cascading deactivation a full config
applies. So `unknown` means undetermined but resolvable, a param is `unknown`
only if a param it gates on is `active`-unset or `unknown`, and collapsing
`unknown` to `inactive` reproduces the full-config activity. An `is_active(p)`
inside a condition follows the same three values: determined for a determined
`p`, and Unknown for an `unknown` one.

**Status, completeness, order.** `evaluate_partial` reports each param's
`param_status`, one of `set` (active and present), `active_unset` (active and
absent), `inactive`, or `unknown`. It also reports `evaluable_constraints`, a
`ConstraintEval` for every constraint of determined value including those
settled inapplicable by inactivity alone; `pending_constraints`, those still
Kleene-Unknown on an `active_unset` or `unknown` operand; and `n_remaining`, the
number of `active_unset` params, which is a lower bound while any lift count is
undetermined. `is_complete(config)` holds if and only if no param is
`active_unset` or `unknown`, and `missing_params` lists the `active_unset`
instance paths in `topological_order`.

A lift contributes instance statuses only when its count is **determined**, per
the count rule under *Defaults*, an inactive count-dependency yielding the
complete `[]`. An **undetermined** count, meaning a pending count-dependency,
contributes none, and the count param's own status carries the incompleteness. A
list container is `set`, `unknown`, or `inactive`, never `active_unset`: `set`
once its count is determined and its instances present, `unknown` while its
count is still pending, and `inactive` when its condition is false. A **struct
container** likewise collapses `active` to `set`, having no own value, so
`active_unset` cannot apply.

`next_assignable` lists the `active_unset` params every one of whose referenced
params, across condition, bound-origin bound, and repeat count, is `set` or
`inactive`. **This coincides with completeness: `next_assignable(config) == []`
if and only if `is_complete(config)`.** Following `topological_order`, the first
param that is not `set` or `inactive` is always `active_unset` with all
references settled, so a driver loop assigning `next_assignable` halts exactly
at completeness. Assign a lift's count param and its instance leaves, never the
container.

`remaining_domain` returns a per-kind descriptor, or `None` if the param is
inactive: `RealRemaining` and `IntegerRemaining` give an interval,
grid-intersected if quantized; `ValueRemaining` gives the still-legal values for
bool, categorical, ordinal, and choice; `SubsetRemaining` gives items forced in,
forced out, and free; `PermutationRemaining` gives the declared items,
unreduced. It starts from the declared domain and intersects the narrowing of
every **hard** constraint (forbid, bound-origin, or require, excluding the soft
`.encourage()` and `.discourage()`) that, after substituting all other operands
from the config, leaves the param as the sole unset **bare** operand of a
comparison. It takes the feasible side by origin, a bound or require storing the
feasible predicate and a forbid storing its negation.

**Guarantee level:** declared bounds intersected with constraints reducible with
exactly one unset bare operand, bound-origin couplings included, so bound
tightening falls out of the same rule. A param buried in arithmetic, two unset
operands, or an unsupported operator is not reduced; full propagation across
multi-param constraints is CSP solving and is consumer territory. The descriptor
is **sound, not complete**: it never excludes a still-feasible value, though it
may admit values an unreduced coupling would forbid. `remaining_domain` on a
struct or list container path, or on an empty or otherwise non-existent param
path, is a misuse `TypeError`: it names no leaf param, and `None` is reserved
for an inactive param and must not be overloaded to mean no such param.

---

## Space: Introspection

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
.has_nongenerative_params -> bool
.has_complete_defaults -> bool
.is_finite -> bool
.cardinality() -> int | None                 # None if infinite or not enumerable
.fingerprint(scope="full", on_unserializable="raise") -> str
.represent(*rules: EncodingRule) -> Representation      # see The representation layer
```

`has_nongenerative_params` is also true for a non-generative param under a
`.repeat()` element.

`cardinality()` is the finite-config count over the structural product,
closed-form per kind: an integer range; a quantized-real grid; a categorical,
ordinal, or bool value count; a subset as the sum over size bounds; a
permutation as `n!`; a choice as the sum over variants, a bare variant
contributing 1 and a payload-bearing one the product of the variant's own
fields; a struct as the product over fields; a static-count list as
`element_count ** count`; a custom as the type's own `cardinality()` if it
declares one and `None` otherwise; and `.symbolic()` or `.code()` as always
`None`, both being opaque with no declared-cardinality capability of any kind.
It recurses through each param's own domain shape rather than scanning flat, so
a choice or struct's own relocation-injected activation condition is handled
implicitly by the variant-sum and field-product formulas, needing no CSP or
enumeration machinery for that case.

An **unquantized real, a dynamic-count list, a custom with no declared
`cardinality()`, or a `.symbolic()` or `.code()` param** makes the whole result
`None`. A param carrying its own **independent** condition, meaning one
referencing anything beyond what its struct or choice nesting alone would
inject, or any condition at all on a root (non-nested) param, also makes the
result `None`. General conditional enumeration is out of scope, and this rule is
sound, never over-counting, though conservative.

`dependency_graph` maps each definition path to the params it depends on via
conditions, constraints, and repeat counts, bound-origin constraints and repeat
counts included. Only conditions, bound-origin constraints, and repeat counts
impose assignment order; a runtime-evaluated count is not a bound, but it must
still be assigned before its list. A plain constraint has no distinguished
target, so it couples every param it mentions **symmetrically**, each mentioned
path's entry gaining every other mentioned path. Every key of `.params` gets an
entry, lift-descendant templates (`"[]"`) included, matching `.params`'s own
unfiltered transparency.

`param_conditions(path)` returns the **union** of every condition whose `target
== path` and every condition that merely *references* `path` in its expression.
`param_constraints(path)` returns every constraint that references `path`, a
constraint having no target to distinguish.

---

## Space: Structural Operations

Each returns a new `Space`. Path arguments accept both keyword form and a
positional `dict[str, Any]`, the latter required when paths contain `.` or `[]`.

| Method | Semantics |
|---|---|
| `.slice(values=None, **kw)` | Remove params and **substitute** the value at every reference site, across conditions, constraint expressions (bound-origin included, envelopes recomputing on re-resolution), and `.repeat()` counts; then statically resolve (below) and re-resolve |
| `.freeze(values=None, **kw)` | Fix values and keep params in the output; conditions and counts resolve statically (below) |
| `.active_subspace(config)` | Subspace of params active for this config |
| `.select(*paths, strict=False)` | Definition-path **prefix subtree**; selecting a choice brings its variants. Best-effort: constraints referencing excluded params are dropped with a warning, and `strict=True` raises |
| `.filter(tags=..., mode="any", strict=False)` | Same best-effort semantics |
| `.extend(*exprs)` | Additive: inherits params, conditions, constraints, anchors, and meta. `ds.space()` is the identity |

**Static resolution.** Substitution is half of either operation. Once every
param a piece of *derived* structure reads is determined, that structure is no
longer derived, and both operations **fold** it to its canonical static form: a
`.repeat()` count becomes a static **`int`**, and a condition that folds to
`True` becomes **no condition**, `ParamDef.condition is None`. The fold must
reach the canonical form rather than a constant expression, because
`has_variable_length`, `coordinate_paths()`'s row-33 check, `cardinality()`, and
the `Array`-versus-`List` dtype rule all test the static *form*; a `Literal(3)`
count would leave every one of them misreporting the space. Folding is also what
makes `coordinate_paths()` reachable for a space declared with a param-driven
count, `.slice()`-ing that count being the route to a fixed layout.

A `True` fold drops the condition. A **`False` fold is left in place**: an
always-active param is an unconditional one, so dropping the condition is
information-preserving, whereas removing a permanently-inactive param would take
a declared name out of the path namespace that `.params`, `flatten`, and the
fingerprint preimage all observe.

The two operations fold with different reach, and the difference is what
distinguishes them. **`.slice()` folds unconditionally**, the param being gone,
so no config can hold another value for it. **`.freeze()` folds only where the
frozen param's own domain admits a single value**, a real or integer narrowed to
`lo == hi`, or a categorical or ordinal narrowed to one value. `.freeze()` keeps
the param, and the kinds it pins by a hard `require` instead of by domain
narrowing (bool, choice, subset, permutation, custom, program; see the per-kind
mechanism below) retain a domain still admitting their other values, so a config
may legally hold one and merely be infeasible. Folding there would report a
param active where evaluation says it is not, and would drop a frozen choice's
variant-activation condition, breaking that freeze's fingerprint equality with
its hand-written pin-and-prune expansion. A count is integer-typed by row 12, so
its referent is always domain-narrowed and always folds.

The fold is **best-effort over a closed set**: the reference-free expressions
the ordinary evaluator can evaluate against an empty config, excluding any
reaching a `ds.value` or `.prop()` leaf, since `fn`'s calling convention
promises a call with the operand values *at evaluation* and a structural
operation is not a call site it agreed to. Anything unfoldable stays an
expression, which is always sound, the lift merely staying dynamic.
Derived-space fingerprints move accordingly: `freeze(n=3)` is fingerprint-equal
to the hand-written `integer(3,3).default(3)` plus `.repeat(3)` spelling, those
two spaces having identical valid-config sets.

**Anchors under structural operations.** `freeze` and `slice` re-validate
anchors, and a conflict with a frozen or sliced value is a resolution error.
`select` and `filter` drop conflicting anchor keys with the same warning
mechanism. `extend` keeps anchors and re-validates. One exception: a choice
`.freeze()` that structurally prunes non-selected variants (below) uses `select`
and `filter`'s strip-and-drop mechanism instead of the hard failure every other
freeze kind uses, because pruning removes params and the unchanged-shape
assumption behind the hard failure does not hold.

**`.freeze`'s per-kind mechanism.** Real, integer, categorical, and ordinal
params narrow their own domain to the single fixed value, `lo == hi` being
already a legal degenerate domain (see the degeneracy table), and set `default`
to it, dropping any prior. Bool has no domain to narrow and is pinned via a hard
`require` or `require(~·)` constraint on the param, which is visible in
`.constraints` and in the fingerprint, fingerprint-equal to a hand-written
`.require(b)`, rather than a silent domain fact.

A **custom** param is opaque to domain-narrowing. A full-protocol
`.custom(param_type)` is pinned via `require(p == value)`, comparing
structurally on `to_json()` output, which every full-protocol type supports for
free and which needs no native `__eq__`, **and** `default` is set to the fixed
phenotype value, so a non-generative custom's `sample()`-time `SamplingError` is
satisfied too. Real, integer, categorical, and ordinal already get this from
domain-narrowing alone, and bool never needs it, being always generative. The
`.custom(sampler, validator)` shorthand has no comparable, serializable value
and is not freezable, which is a path-named resolution error. A `.symbolic()` or
`.code()` param is pinned by the identical mechanism as a full-protocol custom,
`require(p == value)` plus `default = value`, with no shorthand exception, a
program value always being a plain JSON dict and so unconditionally comparable
and serializable.

A **subset** is fixed by a per-item `require`: `require(contains(p, i))` for
every declared item present in the fixed value, and `require(~contains(p, i))`
for every declared item absent from it. There is no domain narrowing,
`SubsetDomain` having no single-value representation, and `default` is set to
the fixed value, matching the domain-narrowing kinds. A **permutation** is fixed
the same way, by a per-position `require(position_of(p, item) == k)` for each
`k`, with `default` likewise set. A **struct** has no value of its own to fix,
so `.freeze()` fans out to a per-field `.freeze()` call at each given field's
own fully-qualified path. A partial dict fixes only the given fields, and the
same dispatch composes recursively when a field is itself a struct, choice,
subset, permutation, or list. There is no struct-level `default`.

A **choice** is fixed by a discriminator pin `require(c == variant)` plus
structural pruning: a variant's already-relocated descendant params are dropped
if and only if **no instance being frozen in this call selects it**. For a plain
choice, having one instance, this reduces to every variant but the chosen one.
For a lifted choice the same rule aggregates over every element in one pass, so
a variant selected by at least one element survives for all of them.
`ChoiceDomain.variants` is never narrowed, nothing analogous to `lo == hi`
existing for it, mirroring bool, and no `default` is set, choice sampling being
always generative and the pin alone fully determining it. Pinning a payload
field alongside the discriminator needs no separate sugar: give both paths in
the same `.freeze()` call, as in `freeze(algo="svm-rbf",
**{"algo.svm-rbf.gamma": 0.1})`.

A **list** (`.repeat()`) is fixed by narrowing its own `count` to the literal
length of the given value, dropping any prior `int` or expression count and
mirroring real and integer's drop-any-prior narrowing, and by setting
`list_default` to the given value. The exception is choice-typed elements, where
a bare discriminator selection is not a complete nested-config value for a
payload-bearing variant, so `list_default` is left alone, mirroring choice's own
no-`default` precedent. Each element is then pinned per its own kind: a scalar,
custom, or bool element by a per-instance `require(p[i] == value[i])`; a struct
element by the same field fan-out rooted at `p[i]`; a nested list element by the
same mechanism one level deeper, only the outermost `.repeat()` level's own
domain ever being narrowed, a nested level's element facts being a template
shared across every outer row rather than a per-instance fact; and a
lifted-choice element by a per-instance discriminator `require`, with variant
pruning computed once per list over the union of variants selected by any of its
instances, which is the rule above generalized from one instance to many.

`.slice()` does not support a custom param, there being no substitution target
for a `.prop()` expression's operand, and rejects it with a path-named
resolution error. A `.symbolic()` or `.code()` param has no `.prop()` and so no
such obstruction; `.slice()` supports it like any ordinary leaf.

---

## Space: Metaprogramming

The IR is bidirectional:

```python
ds.param_from_def(pd: ParamDef) -> TypedParamExpr
ds.space_from_ir(params, conditions, constraints, anchors=None, meta=None) -> Space

.map_params(fn: Callable[[ParamDef], ParamDef]) -> Space     # sugar
.without_constraints(tags=...) -> Space                       # sugar
```

`param_from_def` returns the type-specific builder view for `pd`'s type (see
*Builder view types*). It inverts every scalar kind (real, integer, bool,
categorical, ordinal, subset, permutation) and any list thereof,
fingerprint-equal to the original. A struct or choice `ParamDef`, or a `"list"`
`ParamDef` repeating one, has no single-`ParamDef` inverse, its descendants
living as separate flat entries the lone `ParamDef` carries no reference to, so
`param_from_def` **raises `TypeError`** for these, naming `space_from_ir` as the
tool that reconstructs them from the full flat IR, where every descendant
already exists as its own entry.

Resolution re-validates whatever comes in. Expressions are values, so rewrites
reattach existing `BoolExpr` objects, and `.kind` and `.children` walking covers
expression-level rewrites. `ds.all_` and `ds.any_` provide fold identities for
generated constraint sets. Degenerate arities produced by generators are legal
with defined semantics (see the degeneracy table). A space-valued param, as in
searching a catalog of inner spaces, needs no new machinery: use a `.custom()`
type with `fingerprint()` as value identity.
---

## The Representation Layer

A genotype **is a `Space`**. A representation is a `Space → Space` morphism
carrying a value-level pair, so a solver can ask the genotype the same questions
it would ask any space, across kinds, bounds, conditionality, cardinality, and
fingerprint, rather than reverse-engineering structure from transformed dicts.

```python
.represent(*rules: EncodingRule) -> Representation
```

`EncodingRule = Callable[[ParamDef], Encoding | None]`. Rules are tried in
argument order per param and the first non-`None` wins, which is **union
dispatch** rather than composition. `Encoding` is a per-param arrow (see
*Protocols*); `Representation` is the whole-space morphism (see *IR*).

### Two tiers

**Derived.** `space.represent(*rules)` builds the target mechanically from
per-param `Encoding`s. It is path-preserving and arity-1, so the laws below hold
by construction.

**Supplied.** `Representation(source=…, target=…, decode=…, encode=None)` is
constructed directly: the consumer supplies the target `Space`, via
`ds.space_from_ir`, and both value maps. Core supplies the type, `then`, and
`check()`, and provides **no structural guarantee, no arity law, and no path
law**. This tier carries the morphisms core has no opinion about: hierarchy
flattening, foreign-format export, fixed-width padding, imputation policies. A
derived representation *is* a supplied one, and both compose through `then`.
Soundness of a supplied morphism is the author's obligation, verified by
`check()` and never enforced.

`rep.check(n=200, seed=None)` samples the target, decodes, and asserts the
conformance laws, since a supplied morphism has no other way to be shown sound.
It additionally round-trips the source's **authored** phenotypes, meaning every
anchor and `apply_defaults({})`, under the law name `round_trip_declared`. Those
are the values `encode` exists to carry, and the only ones that exercise the
round-trip's tolerance: a phenotype obtained from `decode` sits on the chart's
image, so `encode` recovers the very unit coordinate it came from and the
comparison is exact, whereas an authored `1e-3` under a `Log()` chart is
recovered only to within floating-point accuracy. One consequence is silent and
so is stated here: `config_hash` is exact, so a phenotype that has been through
`encode` and `decode` may hash differently from the one you started with. Key
observations on the phenotype you hold, not on a round-tripped copy.

### Path and arity (derived only)

One source param maps to **one `ParamDef` at the same path**, and kind and shape
may change. Hence `set(target.params) == set(source.params)` over
*definition-path* keys. A lift is a single key, so genotype **dimensionality is
unconstrained**: one-hot maps `algo` to a `list` of `real` still keyed `algo`,
with its coordinates at instance paths `algo[0]…`.

A param `p` is **encodable** if and only if no other key of `source.params`
begins `f"{p}."` or `f"{p}[]."`. An encoding owns its whole subtree, and
structs, payload-bearing choice discriminators, and struct or choice lifts have
descendants relocated into separate flat entries that nothing reconnects. A
*bare* choice has no descendants and is encodable, being semantically a
categorical. A param a `.repeat()` count reads is **excluded unconditionally**:
transport rewrites conditions and constraints and never a count expression, so
encoding the param a count reads would silently change what the count means. A
param any `.prop()` reads is excluded too, *unless* the matched `Encoding`
supplies `prop_expr()` to rewrite every such reference structurally, which is
what makes a custom-to-u-space bridge buildable at all when the bridged type
declares properties (see *Protocols*, `Encoding.prop_expr`). Violations are
resolution errors (row 32).

### The induced chart representation

`space.represent()` with no rules. It touches exactly the params that carry a
chart **at their own level or at any element level of their `ListDomain`
chain**: a scalar lift's chart lives in `ListDomain.element_chart` rather than
on the `ParamDef`, and omitting those would drop whole vectors from the
genotype. It **excludes** any param a count or `.prop()` reads. Each touched
param becomes `real(0, 1)`, rewritten at the level the chart was found, with
`periodic` mirrored onto the target, because a periodic real's `from_unit(1.0)`
equals `hi`, which is not a domain member, so without the mirror `decode` would
not be total. Everything else is left alone: subset, permutation, categorical,
bool, and custom have no chart, and that is what a solver needs to be told.

This is the only representation core ships. It is *induced*: the chart is the
coordinate system the declaration already fixed. Every chosen genotype, whether
one-hot, stick-breaking, random keys, or a type bridge, is supplied by a
consumer or a type author.

### Transport

Conditions and constraints are rewritten, never dropped. There are three
mechanisms, preferred in order:

1. **Leaf substitution** (`decode_expr`) substitutes the decode *into* the
   expression rather than restructuring it, so `forbid(x + y > 10)` becomes
   `forbid(chart_x(x) + chart_y(y) > 10)`. Structure is untouched and
   multi-param nodes work, each leaf wrapping independently.
2. **Node rewriting** (`rewrite`) is optional, for solver-visible structure
   substitution cannot reach, as when one-hot turns `algo == "adam"` into
   `(algo[1] > algo[0]) & (algo[1] > algo[2])`.
3. **Opaque transport** wraps the source expression as a `ds.value(...)`
   returning `bool` whose function decodes its operands and evaluates the source
   expression. Core can always do this, knowing both `decode` and the source
   AST, so **transport is total**, with one narrow boundary: `ds.value`'s own
   operands must each be a scalar-evaluable expression, so a lift touched by the
   expression is enumerated into per-instance operands under a *static* count
   and cannot be under a *dynamic* one, no fixed operand list existing at
   resolution time. This is unreachable for the induced chart representation,
   whose `decode_expr` always succeeds, and arises only from a user-supplied
   `Encoding` that supplies neither `decode_expr` nor `rewrite` for a
   dynamic-count lift a condition or constraint touches. `represent()` raises
   there, naming the param and the remedy, rather than silently narrowing
   feasibility agreement.

Because nothing is dropped, target activity always matches source activity, and
**feasibility agreement holds by construction** for every representation
`represent()` successfully builds. What differs is *quality*, reported as
`opaque_conditions` and `opaque_constraints`: structurally transported
expressions keep margins and partial evaluation, and opaque ones do not (see
*Constraints and Feasibility* on the white, grey, and black tiers). Expressions
are rewritten in all four stores they inhabit: `Space.conditions`, each
`ParamDef.condition`, `Space.constraints`, and `ListDomain.element_constraints`.
A projection such as `p.field("w").sum()` reads the lift's *descendant* rather
than the lift its `params` set names, and must be rewritten at the projection
node.

### Obligations

`decode` must be **total**: every config valid in `target` decodes to one valid
in `source`. Encodings divide by whether this is free. Charts, stick-breaking,
random keys, and argmax are surjective onto their domains by construction. A
bool vector over a size-bounded subset, or an adjacency matrix over a
connectivity-constrained graph, is not: an invariant carried by the type's
`validate` that no genotype constraint can express means `decode` must
**repair**, or the genotype must be chosen so it cannot represent an invalid
value. The failure is otherwise silent, the target sampling happily and
producing invalid phenotypes.

`encode` is optional, and `rep.invertible` is true when every applied encoding
supplies it. It is what warm-starting needs: anchors and historical observations
are phenotypes, and seeding a solver with them is `rep.encode(config)`.
`measure_preserving` is likewise per-encoding and declared, never assumed. Core
proves it only for the induced representation, where `chart(u)` on `u ~ U[0,1]`
*is* the declared measure.

**Defaults and anchors are phenotype values.** `ParamDef.default` and
`Space.anchors` hold values in source units, so only `encode` can carry them
into a genotype target. Where the applied encoding supplies it, `represent()`
encodes them and **validates the result itself** rather than trusting the
assembler. Where it does not, they are dropped and reported, in
`dropped_defaults` and `dropped_anchors`. A default drops per param; an
**anchor drops whole**, a config missing an active param not being a valid
anchor. The drop is not a corner case: an `Encoding` need not supply `encode` at
all, and even the induced representation cannot encode a param whose external
`Prior` offers `ppf` without `cdf`, that chart decoding but not encoding (see
*Charts*). Carrying an unencoded phenotype value across is the failure this
prevents: a `1e-3` default lands inside a unit target's `[0,1]` and passes the
domain check while meaning something else entirely.

Operators never live on `ParamType`: neighborhoods and distances are properties
of a genotype, and the same phenotype admits many.
---

## Identity and Serialization

### to_json / from_json

```python
.to_json(on_unserializable="raise") -> dict
Space.from_json(data, custom_types=None) -> Space        # classmethod
.to_json_schema() -> dict                                 # oneOf per choice; dependency-free
```

The JSON document carries a single integer **format version**, and `from_json`
raises on an unknown one. The non-serializable set is closed and enumerated: the
`.custom(sampler, validator)` shorthand, `code` and `symbolic` `validators`,
`symbolic` `sampler`, `Primitive.fn`, **`ds.value`'s `fn`**, and **external
`Prior` objects**, meaning any `.ppf`/`.cdf` object supplied to `.prior()`,
which carries no structural `describe()` protocol of its own. Built-in prior
families (`Log`, `Logit`, `Power`, the categorical/ordinal/bool/choice/subset
`Weights` payload, and the uniform default) are fully structural and always
serialize; only external `Prior` objects are opaque, riding the same raise,
`mark` (`{"$opaque": true}`), or drop-plus-manifest path as callables.

`Encoding` and `Representation` instances never enter the IR. A representation's
*target* is an ordinary `Space` and serializes as one, so encoding a param whose
source form is non-serializable can leave the genotype serializable where the
phenotype was not. The observation key remains the pair `(fingerprint,
config_hash)`, so this identifies the proposal domain rather than the phenotype
space.

`on_unserializable="drop"` writes the space without those sites plus a manifest
of omissions, and the reconstructed space is a *different* space by design. A
`ds.value` site sits *inside* an expression tree, in a constraint, a `.when()`
condition, or a dynamic repeat count, rather than at a removable field, so there
is nothing to omit the way a whole param or prior can be dropped. There `"drop"`
degrades it to the same `mark` sentinel in place, plus a manifest entry naming
the site, which is the precedent the `.custom(sampler, validator)` shorthand
sets, where `"drop"` also degrades to the opaque marker rather than removing the
whole param. The `code` and `symbolic` `validators`, `symbolic` `sampler`, and
`Primitive.fn` follow the same in-place precedent one level finer: each is a
single opaque *field* inside an otherwise-structural `.symbolic()` or `.code()`
domain, where `signature`, `primitives`' own names and arities, `max_depth`,
`description`, `constraints`, and `examples` all serialize plainly regardless.
Raise, mark, and drop therefore degrade only that field and never the whole
param, unlike the `.custom(sampler, validator)` shorthand.

Custom params serialize as `type_key` plus the `describe()` output, and
`from_json` requires a `custom_types` registry entry mapping `type_key →
factory` where `factory(describe_dict)` reconstructs the instance.

**Round-trip law** for fully serializable spaces:
`Space.from_json(s.to_json()).fingerprint() == s.fingerprint()` at both scopes.

### fingerprint()

```python
.fingerprint(scope="full", on_unserializable="raise") -> str    # "1:full:9f2c…"
```

A stable identifier of the **resolved space**, meaning the post-resolution IR
and never builder expressions. The output is the preimage-format version, shared
with `to_json`'s version counter, then the scope, then 64 hex chars of SHA-256.

Equal fingerprints guarantee identical valid-config sets, sampling measure, path
namespace, introspection, and `to_json` documents, up to derived fields. Unequal
fingerprints guarantee nothing: identity is **structural after desugaring**.
Semantically equivalent encodings, such as bool-plus-`when` against a
two-variant choice, fingerprint differently by design, and no algebraic
normalization of expressions is attempted, so `a & b ≠ b & a`.

**Scopes:**

| Component | `full` | `sampling` |
|---|---|---|
| Params: definition path, kind, domain, prior, quantized, periodic, condition | ✓ | ✓ |
| Conditions, forbids, requires | ✓ | ✓ |
| Declared (`.encourage`/`.discourage`) constraints | ✓ | |
| Defaults, tags, meta, anchors | ✓ | |
| Format version | ✓ | ✓ |

`sampling` identifies the feasible set, the measure, and the chart geometry, for
warm-start and surrogate transfer; `full` is document identity. Derived fields
(`Constraint.params`, `dependency_graph`) never enter the preimage. More
generally, **no preimage-excluded field may be feasibility- or
semantics-load-bearing**. This applies in particular to `Constraint.origin`,
which is why a **polarity-opposite constraint**, one whose `origin` is `bound`,
`require`, or `discourage` and which therefore stores the polarity-inverse
predicate from its `user`-origin baseline, is canonicalized to its
baseline-polarity form in step 1 below rather than distinguished by `origin`.

**Normalization pipeline.**

1. **Resolve and desugar.** Sugared and explicit spellings of the same space are
   fingerprint-equal, including variadic `.repeat(*counts)` against the chain,
   and expression bounds against their manual envelope-plus-constraint
   expansion. A **polarity-opposite constraint**, meaning a bound-origin sugar,
   a `require`, or a `discourage`, is canonicalized to its **baseline-polarity
   (negated) form** before hashing, by one of two provenance-specific
   mechanisms. A **bound** sugar is always a single top-level `Compare` and
   negates by **operator flip**, `x <= y` becoming `x > y`, so a bound `x <= y`
   is fingerprint-equal to its feasibility-equivalent `.forbid(x > y)`. A
   **`require`** or **`discourage`** stores an arbitrary predicate `e` and
   negates the **whole expression**, `e` becoming `~e`, so `require(e)` is
   fingerprint-equal to `.forbid(~e)` and `discourage(e)` to `.encourage(~e)`.
   Each is fingerprint-*distinct* from the polarity-opposite spelling,
   respectively `.forbid(x <= y)`, `.forbid(e)`, and `.encourage(e)`.

   Feasibility equivalence and fingerprint equality are different relations.
   `require(x <= y)` and `.forbid(x > y)` name the *same feasible set* yet are
   fingerprint-**distinct**, because `require` canonicalizes to `~(x <= y)`, a
   `Not` node, rather than to the operator-flipped `x > y`. Equal fingerprints
   imply equal feasible sets; the converse never holds, so distinct fingerprints
   for identical feasibility are allowed. This puts the polarity in the preimage
   while `origin` itself stays excluded.
2. **Declaration order is preserved, not sorted.** Permuted params or variants
   differ, and `.when(a).when(b)` folds in call order.
3. **Unordered collections sort**: tags lexicographically, meta and anchors by
   key.
4. **Float canonicalization**: `−0.0` becomes `0.0`. NaN and inf are resolution
   errors wherever floats occur in the IR.
5. **Type tags at every `Any`-typed leaf**: categorical and ordinal values,
   subset and permutation `items`, `is_in`/`count_of`/`sum_over` literal
   operands, defaults (`default`, `list_default`, `element_default`), anchor
   entries, and meta values. Each encodes as `{"$t": "int", "v": 1}` with tags
   `bool|int|float|str|null`, so `categorical(1, 2) ≠ categorical(1.0, 2.0)`.
   List- and dict-shaped values, such as struct and list defaults and nested
   meta, are tagged **recursively** per scalar leaf, under the same codec as a
   flat default. Positions that never hold `Any`-typed application data, namely
   paths, `op`/`type_kind`/variant-name strings, `hard` and `periodic` booleans,
   and literal repeat counts, stay untagged.
6. **Expressions encode as ASTs**: node kind, children in operand order, paths
   as grammar strings, literals type-tagged.

The normalized document is serialized per **RFC 8785 (JCS)**, via the `rfc8785`
dependency (see *Dependencies*), and hashed with SHA-256. JCS serializes `1.0`
as `1`, which is why type tags precede canonicalization.

**Callables** default to raising, listing offending sites by definition path,
over the same set as `to_json`. `on_unserializable="mark"` replaces each
callable with the sentinel `{"$opaque": true}` at its site. This marks rather
than drops, presence being identity-relevant. Documented limitation: two spaces
differing only in a callable's behavior at the same site are fingerprint-equal
under `"mark"`, and content identity requires the serializable protocol,
`type_key` plus `describe()`.

### config_hash

`config_hash` reuses the same canonical config encoding, with type tags, float
rules, and grid canonicalization, subsets sorted and inactive params stripped,
but does **not** embed the space fingerprint. The globally unique observation
key is the pair `(space.fingerprint(), ds.config_hash(config, space))`. Anchors
in the `full` preimage use this same encoding.

---

## Config Utilities

```python
ds.flatten(config, space) -> dict[str, Any]     # path-grammar keys; non-validating
ds.unflatten(flat, space) -> dict               # inverse
ds.config_hash(config, space) -> str            # non-validating (built on flatten)
ds.config_diff(a, b, space) -> list[ParamDiff]  # structural, no magnitude; plain ==; non-validating
ds.variant(config, param_path) -> str           # active variant name of a choice
ds.payload(config, param_path) -> dict | None   # variant payload; None for bare variants
ds.destructure(config, param_path) -> tuple     # (name, payload): a derived view;
                                                #   tuples are never valid config values

.coordinate_paths() -> tuple[str, ...]          # on Space: the fixed leaf layout (below)
```

`variant`, `payload`, and `destructure` accept **instance paths** into a lifted
choice, so `variant(config, "pipeline[1]")` returns that element's variant name
and `payload(config, "pipeline[1]")` its payload, using the path grammar's `[k]`
indexing, which is self-describing, so these utilities still take no `Space`.
Addressing a lifted choice by its **bare list path**, as in `"pipeline"`, is a
misuse error naming the indexed form, a list having no single variant. The
scalar return types are preserved.

`config_hash` and `config_diff` are **non-validating**, like the `flatten` they
are built on: they walk whatever keys structurally match `space.params` and
ignore the rest rather than raising, and `config_hash` still grid-canonicalizes
near-grid values. A caller wanting a validated key composes with `validate()`
first: `if space.validate(c).valid: key = config_hash(c, space)`. `config_diff`
compares leaves by **ordinary Python `==`**, so `1` and `1.0` are not reported
as a change. That is distinct from `config_hash` and `fingerprint`'s type-tagged
equality, a diff being a structural report rather than a hashing law.

In `config_diff`, a variant switch decomposes into the discriminator diff, whose
old and new values are variant **names**, plus newly-inactive and newly-active
payload diffs using the `None` conventions. Repeat length changes align
**positionally**, so an insertion at the front reports as a full rewrite;
alignment-aware diffing is consumer polish.

### The fixed leaf layout

`space.coordinate_paths()` returns the ordered instance paths of the space's
**leaf entries**, excluding the lift-length entries `flatten` emits as
structural bookkeeping. It is the layout a consumer needs in order to pack a
config into a positional container, a solver's parameter vector most obviously.
Deriving it is not a two-line filter: `flatten` emits `x` as an outer count,
`x[0]` as an inner count, and `x[0][0]` as a coordinate, so telling data from
bookkeeping means walking the `ListDomain` chain one bracket group at a time,
and getting it wrong produces a config that still validates and is not the one
you started with.

It requires a **fixed layout**, meaning that every `.repeat()` count in the
space is a literal integer and no param carries a condition. Either one makes
the key set config-dependent, so no positional layout exists, and both are
path-named resolution errors (row 33) rather than a silently config-specific
answer. Struct params never appear, having no value of their own.

A fixed layout is not the same as numeric packability, and the two are kept
apart because they fail differently. `subset` and `permutation` leaves have a
**stable key** but a variable-length list value, and `categorical` and `ordinal`
leaves are scalar but not numeric. Both appear in `coordinate_paths()`, being
genuine coordinates of the space, and a caller packing floats fails on them at
the point of conversion, which is the right place. A genotype produced for a
real-vector solver satisfies both conditions by construction, which is what
makes it one.

`unflatten` completes the round trip: for a **static** count it recovers the
length from the `ListDomain` rather than requiring the bookkeeping key, so
`ds.unflatten(dict(zip(space.coordinate_paths(), values)), space)` is the
inverse of reading those paths out of `flatten`. This is a fallback for
*absence* only: a **present** bookkeeping key always wins over the
`ListDomain`'s declared static count, matching `unflatten`'s non-validating
posture everywhere else, the bookkeeping key being `flatten`'s own realized
length for the config at hand and so the more specific of the two signals.
Packing into any particular container, with its dtype, shape, and batch
conventions, stays with the consumer.

`unflatten` takes no activity argument, so a struct's presence is inferred from
whether any descendant leaf is present. A zero-declared-member struct
round-trips as `{}`, but an *active* struct all of whose members are
individually inactive is indistinguishable from an *inactive* struct and is
omitted. "Unconditionally present", the `.space()` struct type's property,
describes **validity**, a struct's activity never depending on its own members'
activity, and is not a guarantee about `unflatten`'s output shape.

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

**DataFrame output** (`space.sample()`). Column names follow the path grammar.
Inactive params are `null`, the dict-config principle not governing columnar
containers. A lift level with a **static** count emits `Array(dtype, n)` instead
of `List`, and the rule applies per level, so an outer-dynamic, inner-static
lift yields `List(Array(...))`. The rule is deterministic and
conformance-tested.

| Type | Column(s) |
|---|---|
| real (incl. periodic) | `Float64` |
| integer | `Int64` |
| categorical, ordinal | `Utf8` |
| bool | `Boolean` |
| subset, permutation | `List(...)` |
| choice | `Utf8` discriminator at the param path plus one `Struct` per parameterized variant at `param.variant`, null when inactive |
| struct param | `Struct` |
| scalar lift | `List(dtype)` |
| struct lift | `List(Struct)` |
| lifted choice | `List(Struct{variant: Utf8, <variant>: Struct \| null, …})` |
| symbolic, code, custom | `Utf8` (JSON string) |
---

## Protocols

```python
class ParamType(Protocol):
    type_key: str                                 # required; identifies the type in serialization,
                                                  #   the from_json registry, and solver adapters
    def validate(self, value) -> bool: ...
    def to_json(self, value) -> Any: ...
    def from_json(self, data) -> Any: ...
    def describe(self) -> dict: ...               # MUST be JSON-serializable

    # Optional capabilities, each checked structurally (hasattr) and never
    # required; a type declares only the ones it supports.
    def sample(self, rng) -> Any: ...             # generative iff present (see Sampling and
                                                  #   generativity); the .custom(sampler, validator)
                                                  #   shorthand is always generative
    def cardinality(self) -> int | None: ...      # contributes a finite factor to
                                                  #   Space.cardinality() iff present
    def properties(self) -> dict[str, type]: ...  # enables .prop() in constraints, together with
                                                  #   extract() below. Expression-visible props:
                                                  #   int|float|bool|str only
    def extract(self, value, prop: str) -> Any: ...


class Encoding(Protocol):                         # genotype for ONE param
    def target(self, param: ParamDef) -> ParamDef: ...          # required; same path
    def decode(self, param: ParamDef, value: Any) -> Any: ...   # required; genotype -> phenotype

    # Optional capabilities, each checked structurally (hasattr) and never
    # required; an encoding declares only the ones it supports.
    def encode(self, param: ParamDef, value: Any) -> Any: ...   # phenotype -> genotype;
                                                                #   present implies invertible
    def decode_expr(self, param: ParamDef) -> Expr | None: ...  # decode as an expression, for
                                                                #   structural transport
    def prop_expr(self, param: ParamDef, name: str) -> Expr | None: ...  # a phenotype property as
                                                                #   a genotype expression
    def rewrite(self, param: ParamDef, node: Expr) -> Expr | None: ...   # per-node structure where
                                                                #   substitution cannot reach
    def measure_preserving(self) -> bool: ...     # declared, never assumed


class Prior(Protocol):
    def ppf(self, q: float) -> float: ...      # required
    def cdf(self, value: float) -> float: ...  # optional; required when support exceeds bounds
```

**Value convention.** `validate`, `sample`, and `extract` operate on the type's
own *native* representation. `to_json` and `from_json` are the only bridge
between that native form and the JSON-safe **phenotype** form every public,
config-dict-shaped surface holds instead: a config leaf, `sample_one()`'s return
value, `.validate()`, `.freeze()`, `.default()`. Core calls `to_json` once,
immediately after `sample()` produces a fresh native value, and calls
`from_json` immediately before it needs to call `validate` or `extract` on a
config-sourced value. The `.custom(sampler, validator)` shorthand has no
`to_json` or `from_json`, native and phenotype coinciding, and
`sampler(rng)`'s return value is used directly.

**Custom-type contract laws.** `factory(x.describe()) ≡ x` is the registry
round-trip. `extract` is called only on values that passed `validate`. When
payload lifts align to a custom value by index, as in
`.repeat(ds.param("g").prop("n_edges"))`, the type must define a **canonical
ordering** stable under JSON round-trips. A type embedding non-serializable
content is responsible for raising in its own `to_json`, core being unable to
see inside `describe()` output beyond checking that it is JSON-serializable.

---

## Support Types

```python
ds.Signature(args: dict[str, type | str], returns: type | str)
ds.FloatLiteral(lo, hi)                          # ephemeral constant in .symbolic(); carries a chart
ds.IntLiteral(lo, hi)                            # likewise (floor rule)
ds.Primitive(name, arity: int | tuple[int, int | None], fn=None)  # a .symbolic() operator
ds.Log()  ds.Logit()  ds.Power(p)                # built-in prior families (see Charts)
ds.value(fn, *operands, returns)                 # opaque derived quantity (see Expressions)
```

**Type aliases.** The names the public signatures are written in. They carry no
behavior, each being exactly the spelling given here, and are exported so a
reader can follow a signature to a definition rather than guess at a bare
`Seed`:

```python
ds.Config = dict[str, Any]                         # a configuration, keyed by instance path
ds.Seed = int | np.random.Generator | None         # every sampling surface's randomness source
ds.OnUnserializable = Literal["raise", "mark", "drop"]     # to_json
ds.FingerprintScope = Literal["full", "sampling"]          # fingerprint (see fingerprint())
ds.FingerprintUnserializable = Literal["raise", "mark"]    # fingerprint; no "drop"
```

`Config` values are in **phenotype** form, and inactive params are absent rather
than null. For `Seed`, an `int` seeds reproducibly, a `Generator` is used as
given, which is what to pass when several draws must advance one stream, and
`None` draws fresh entropy. `fingerprint` admits no `"drop"`, omitting a site
would silently change what is being identified.

**`Signature`.** `args` and `returns` accept a Python `type`, normalized to
`type.__name__`, or a bare string. Argument order is meaningful and preserved:
it drives `.symbolic()`'s auto-derived variables and it is fingerprint-relevant.
Normalization keeps the fingerprint preimage canonical and this type free of any
unserializable object.

**`FloatLiteral` and `IntLiteral`.** Declared inside a `.symbolic()` param's
`primitives` sequence alongside strings and `Primitive`s, and the only place a
`{"const": ...}` AST node's bounds come from (see *Parameter Types*, Program).
`.chart` is a consumer-only convenience over the declared `[lo, hi]`, a
`RealChart` or `IntegerChart` respectively, `IntLiteral` following the same
floor rule as `.integer()`. Core never draws from it; a consumer's own tree
generator does.

**`Primitive`.** `arity` is an int, meaning exact, or a `(lo, hi)` pair with
`hi=None` unbounded, and is the only place a `.symbolic()` op's argument count
is checked at all. A bare string in `primitives` carries no arity and no
meaning, a primitive vocabulary being otherwise fully open. An int and its `(n,
n)` spelling are fingerprint-equal. `fn`, when given, is never called by core.
It rides the non-serializable set like `validators` and `.symbolic()`'s
`sampler`, degrading in place under raise, mark, or drop rather than poisoning
the whole param.

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
# is recursive and holds every element-level fact: element_chart,
# element_default, count, list_default, element_constraints. That is why a
# lift's own ParamDef is chartless. A struct/choice element's descendants are
# not here; they are relocated into Space.params under a "[]"-prefixed path.
Domain = (
    RealDomain | IntegerDomain | CategoricalDomain | OrdinalDomain | BoolDomain
    | SubsetDomain | PermutationDomain | ChoiceDomain | StructDomain
    | CustomDomain | SymbolicDomain | CodeDomain | ListDomain
)

class Chart(Protocol):
    def from_unit(self, u: float) -> Any: ...
    def to_unit(self, value) -> float: ...                # interval midpoint for integers/grids

@dataclass
class Constraint:
    expr: BoolExpr                # stored as the author wrote it. A polarity-opposite
                                  #   constraint (bound/require/discourage) stores the
                                  #   predicate whose polarity is inverse to its user
                                  #   baseline: require stores DESIRED x <= y, discourage
                                  #   stores the BAD state
    hard: bool                    # True = forbid/require (feasibility), False = declared
    origin: str                   # "user" | "bound" | "require" | "discourage". Derived
                                  #   provenance, excluded from the fingerprint preimage.
                                  #   NOT semantics-neutral: it selects the stored polarity,
                                  #   so the preimage canonicalizes a bound/require/discourage
                                  #   to baseline-polarity form to keep `origin` non-load-
                                  #   bearing (see Identity and serialization).
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
                                     #   eval is never violated; otherwise satisfied differs
                                     #   from constraint.feasible_when_satisfied

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
                                                 #   Unknown implies applicable=False
    pending_constraints: list[Constraint]        # Kleene-Unknown on an active_unset/
                                                 #   unknown operand
    n_remaining: int                             # count of active_unset params (a lower
                                                 #   bound while a lift count is unknown)

# remaining_domain's per-kind descriptor, a closed union. Sound, not complete:
# never excludes a still-feasible value, though it may admit values an unreduced
# multi-operand coupling would forbid. See "Space: partial configs".
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
    condition: BoolExpr | None    # folded activation condition gating every member:
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
class Representation:             # a Space -> Space morphism; see The representation layer
    source: Space                 # phenotype
    target: Space                 # genotype; an ordinary Space
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
    def check(self, n: int = 200, seed=None) -> RepresentationCheck: ...  # the laws, as a tool

@dataclass(frozen=True)
class RepresentationCheckFailure:
    law: str             # short law name, e.g. "decode_totality" | "feasibility_agreement"
    detail: str          # a representative message naming the offending path/value
    count: int           # how many of the n draws exhibited this failure

@dataclass(frozen=True)
class RepresentationCheck:
    n: int
    ok: bool
    failures: tuple[RepresentationCheckFailure, ...]
```

A `Representation` **never enters the IR**, `to_json`, or the fingerprint
preimage; its target is an ordinary `Space` and serializes as one. `then`
requires `other.source` to fingerprint equal to `self.target`, raising a
`TypeError` otherwise, which is misuse rather than resolution. `decode` composes
right-to-left and `encode` in reverse, and only when both sides are invertible.
---

## Resolution

1. Collect exprs, flatten nested spaces.
2. Type-check: every param has exactly one type; layer placement of modifiers.
3. Desugar: `log_scale`, `implies`, layer folding.
4. Resolve references: paths bind, types compatible.
5. Detect cycles in the condition, bound, and repeat-count dependency graph,
   including self-reference.
6. Compute bound envelopes by interval arithmetic along the dependency DAG,
   desugar expression bounds into envelope bounds plus bound-origin constraints,
   and build charts. All static.
7. Validate defaults against static domains, plus anchors, priors, and weights.
8. Emit IR.

**Resolution timing.** Resolution is unspecified relative to construction. A
space built in argument position, as a choice variant or a struct body, may
carry a `.when()` condition **or a `.repeat()` count** that references a param
binding only in an *enclosing* scope, under the sole scoping rule's up-walk, and
that reference cannot resolve while the payload is built standalone. Reference,
type, and cycle checks over such conditions and counts (rows 6, 7, 12, 14) are
therefore deferred to a finalization pass over the fully-merged space. Any
resulting error surfaces no later than the **first terminal operation**:
`sample`, `sample_one`, `validate`, `validate_param`, `evaluate_constraints`,
`fingerprint`, `to_json`, and every introspection surface must trigger
finalization. The error is still a `ResolutionError`, phase R, computed from
space structure alone with no config. Only its timing moves.

Constraint references, across `.forbid()`, `.require()`, `.encourage()`, and
`.discourage()`, stay strict and raise eagerly, cross-scope constraints using
the down-reference-at-the-common-ancestor route instead. **Expression-bound**
references are likewise eager and never deferred: the bound's chart envelope
must be computed during the declaring scope's own resolution, before any
enclosing scope merges, so a bound expression tolerates no enclosing-scope
up-reference, and a cross-scope bound coupling is written by hand at the common
ancestor (see *Expression bounds are sugar*). A **repeat count** falls on the
*deferred* side of that line: counts are runtime-evaluated, so no chart or other
in-scope consumer forces the check early, and the count's own row-12 calculus is
a check rather than a consumer, and a check can move. This is what makes a count
join "the dependency graph and cycle check … exactly as a condition does" (see
*Modifiers and Layering*) in timing as well as in ordering.

**Relocation rewrites every reference a param carries, not only
`ParamDef.condition`.** A lift keeps two more inside its `ListDomain`, the
`count` expression and the per-element constraint templates, so merging a child
space under a struct, variant, or lift prefix must reprefix those by the same
rename. Both fail *silently* otherwise: a dangling count reads as
Kleene-Unknown-from-inactivity and materializes `[]`, per the count rule under
*Defaults*, and a dangling element constraint goes inapplicable under Kleene
rule 4, so a hard `.forbid()` stops deciding feasibility while `validate()`
still reports `valid`. The finalization pass audits both stores.

### Error table

Tagged **R** for resolution-time or **V** for validation, fill, or sample-time.

| # | Error | Tag |
|---|---|---|
| 1 | Duplicate param names in a scope | R |
| 2 | Param with no type, or more than one type method | R |
| 3 | Duplicate declared values (categorical, ordinal, subset items, permutation items; type-tagged equality) | R |
| 4 | Mixed-type categorical values sharing a string image | R |
| 5 | Name or variant name containing `.` `[` `]`, checked on the resolved name for all syntactic routes; duplicate variant names within one choice | R |
| 6 | Reference to a nonexistent param (condition, bound, constraint, repeat count, per-element constraint); `[]` definition path in an expression; `.field()` on a non-struct lift or naming an undeclared element field | R |
| 7 | Cycle in the condition/bound/repeat-count dependency graph; a param's condition, bounds, or repeat count referencing itself | R |
| 8 | `lo > hi`; non-finite bound; NaN or inf anywhere in IR floats | R |
| 9 | `log_scale`/`Log` with non-positive `lo`; `Logit` outside `(0,1)`; `Power` domain violation (`p == 0`; non-integer `p` with `lo < 0`; `p < 0` with `lo ≤ 0`; a domain straddling 0 when `p` is not a positive odd integer) | R |
| 10 | `quantized`: `step ≤ 0`, `factor ≤ 1`, non-finite, or both given | R |
| 11 | Misplaced layer modifier, such as `.repeat(n).log_scale()`; domain-level modifier applied to an incompatible type, such as `.prior(weights=…)` on a real | R |
| 12 | Repeat count not integer-typed | R |
| 13 | Evaluated repeat count negative | V |
| 14 | Arithmetic on ordinal or categorical; ordering comparison (`<`, `>`, `<=`, `>=`) on a categorical; ordinal-to-ordinal comparison over differing value sequences | R |
| 15 | `.symbolic()`/`.code()` declaration hygiene: duplicate primitive name; malformed `Primitive` arity; non-positive `max_depth`; a `signature` arg name that is not a valid identifier; a literal's `lo > hi` or non-finite; a `primitives` entry that is not a `str`/`Primitive`/`FloatLiteral`/`IntLiteral`; non-JSON-serializable `.code()` `examples` (row 23's rule) | R |
| 16 | `.prop()` on undeclared property; non-scalar property type; type mismatch in comparison | R |
| 17 | Prior weights: wrong length; subset inclusion probabilities outside `[0,1]`; categorical/ordinal/bool/choice weights negative or all-zero | R |
| 18 | `sum_over` keys outside the item universe; `position_of` non-member; `.contains()` on permutation; ordinal comparison against a literal that is not a declared value | R |
| 19 | External prior support exceeding (envelope) bounds without `cdf` | R |
| 20 | Bound expression with no computable interval hull (workaround: write the desugared form by hand) | R |
| 21 | Default outside domain (scalar, choice variant, subset, or permutation); `.default()` on a struct param (no own value, completion being field-wise); list default under dynamic count; list default length mismatch; element and list default together | R |
| 22 | Anchor invalid against the space; anchor conflicting with a frozen or sliced value | R |
| 23 | Empty-string tag; non-JSON-serializable meta value; non-JSON-serializable `describe()` output | R |
| 24 | `is_sorted` on a lift nested deeper than one level | R |
| 25 | `==` over purely continuous unquantized aggregate or operands | R (warning) |
| 26 | Sampling retry exhaustion; non-generative materialization without default | V |
| 27 | `from_json`: unknown format version; missing `custom_types` entry for a `type_key` | V |
| 28 | Subset size bounds nonsensical: `min_size > max_size`; `min_size < 0`; `min_size` exceeds the item universe | R |
| 29 | Instance index out of range against a **static** count; boolean operator applied to a lift-valued operand; `.choice()` payload that is not a `Space` | R |
| 30 | `ds.value`: non-scalar `returns`; an operand that is not an expression; comparison type mismatch against the declared `returns` (row 16's clause mirrored, strict, with no int/float leniency) | R |
| 31 | `Encoding.target()` returning a path other than the source param's; `rewrite()`/`decode_expr()` output referencing anything outside that param's own paths, or an out-of-range instance index | R |
| 32 | Encoding a param with relocated descendants (struct, payload-bearing choice discriminator, struct/choice lift); one a `.repeat()` count reads, unconditionally; or one a `.prop()` reads, unless the matched `Encoding` supplies `prop_expr()` to repair every such reference | R |
| 33 | `coordinate_paths()` on a space with no fixed layout: a dynamic `.repeat()` count, or a param carrying a condition | R |
| 34 | A `struct` or `choice` element nested under more than one `.repeat()` level, by either the chained or the compositional route (see *Modifiers and Layering*) | R |

### Degeneracy table

Generated spaces produce degenerate arities constantly, and the default is to
allow them with defined semantics:

| Case | Semantics |
|---|---|
| Single-variant choice | Legal; discriminator is constant |
| Single-value categorical / ordinal | Legal; constant |
| `lo == hi` | Legal; constant chart, still generative |
| `step ≥ hi − lo` | Legal; single-point grid `{lo}`, plus `hi` if `include_hi` |
| Zero repeat count | Legal; value `[]`; see the empty-aggregate rules |
| Empty subset item universe | Legal; value always `[]` |
| Permutation of 0 or 1 items | Legal; constant |
| `ds.space()` | Legal; identity for `.extend()` |
| `ds.all_()` / `ds.any_()` | Literal `True` / `False` |

---

## Errors and Concurrency

The exception taxonomy is `DesignSpaceError` as base, with `ResolutionError`
(the R rows of the error table), `SerializationError`, and `SamplingError` under
it. Misuse guards such as `__bool__` and `__contains__` raise plain `TypeError`.
A **missing optional dependency** raises a plain `ImportError` naming the extra,
never a `DesignSpaceError`: the taxonomy is reserved for semantic findings about
a design space, and an uninstalled package is an environment fact.
Validation-time findings surface as `ParamError` records inside results wherever
a result object exists, and only operations with no result channel raise.

All public objects, across expressions, spaces, IR dataclasses, and charts, are
immutable after construction and safe to share across threads. RNG state is
passed explicitly, as `seed` or `Generator`, and nothing mutates shared state.

---

## Dependencies

Core depends on `numpy`, for its RNG, and `rfc8785==0.1.4`, a pure-Python
`py.typed` package with no transitive dependencies, for the RFC 8785 (JCS)
number and byte canonicalization behind `fingerprint` and `config_hash`.
`rfc8785` is pinned **exactly** rather than with `>=`: an already-frozen digest
format wants its number-formatting library pin-stable, a transitive bump being
able to shift every committed known-answer vector silently, so bumping the pin
is a deliberate act under the format-version protocol.

Built-in priors are implemented internally, with no distribution-library
dependency, and any `Prior`-satisfying object, such as a scipy frozen
distribution or a preliz one, plugs in.

Extras: `designspace[polars]` for `space.sample()`'s DataFrame output, with
`sample_dicts()` and `sample_one()` needing no extra; `designspace[pydantic]`
for model export. `space.sample()` is the only surface that imports `polars`,
lazily. Absent it, the call raises a plain `ImportError` naming the extra and
pointing at the no-extra sampling paths (see *Errors and Concurrency* for why
this stays outside the exception taxonomy).
---

## Conformance Laws

The spec's executable laws double as the acceptance suite. Each law states one
claim and names the test module that enforces it. Law names are stable
identifiers: where an implementation reports a law by name, as
`RepresentationCheckFailure.law` does, it reports the name given here.

### Chart laws

| Law | Statement | Enforced by |
|---|---|---|
| `chart_known_answers` | The four built-in families reproduce their committed known-answer vectors, including the subnormal range under `Log()` | `tests/conformance/test_charts.py` |
| `integer_floor_uniformity` | A uniform prior over an integer domain draws exactly uniformly over `{lo..hi}` under the floor rule | `tests/conformance/test_charts.py` |
| `quantized_cell_measure` | Each grid point's probability is the prior measure of its cell, so a uniform prior gives an equiprobable grid | `tests/conformance/test_charts.py` |
| `grid_canonicalization_invariance` | Grid canonicalization gives one answer for bit-different representations of the same grid point | `tests/conformance/test_charts.py` |

### Kleene laws

| Law | Statement | Enforced by |
|---|---|---|
| `kleene_truth_table` | `&`, `\|`, and `~` follow the truth table under *Three-valued semantics* | `tests/conformance/test_kleene.py` |
| `count_range_rule` | `ds.count` tracks `[t, t + u]` and is Unknown if and only if the comparison outcome differs across that range | `tests/conformance/test_kleene.py` |
| `aggregate_plain_propagation` | Every aggregate other than `ds.count` propagates Unknown plainly, tracking no range | `tests/conformance/test_kleene.py` |
| `empty_aggregate_values` | An active empty lift gives `sum → 0`, `count_of → 0`, `distinct → True`, `is_sorted → True`, and `min`/`max` → Unknown | `tests/conformance/test_kleene.py` |
| `inactive_projection_is_not_empty` | Projection over an inactive lift is Unknown, and is distinguishable from an active empty list | `tests/conformance/test_kleene.py` |
| `if_inactive_provenance` | `.if_inactive()` coalesces inactivity, propagates pending, and propagates emptiness, each tested against the other two | `tests/conformance/test_kleene.py` |
| `when_coerces_unknown_false` | `.when()` coerces Unknown to False, cascading deactivation along `topological_order` | `tests/conformance/test_kleene.py` |
| `verbs_coerce_unknown_inapplicable` | The constraint verbs coerce Unknown to inapplicable rather than violated, with `margin = None` | `tests/conformance/test_kleene.py` |
| `bound_coupling_inapplicable` | An inactive bound reference makes the bound-origin coupling inapplicable rather than raising | `tests/conformance/test_kleene.py` |
| `is_active_totality` | `is_active()` is never Unknown under full evaluation, and is the sole total predicate | `tests/conformance/test_kleene.py` |
| `runtime_equality_type_tagging` | Runtime `==` gives `True ≠ 1`, `1 == 1.0`, and exact type match otherwise, distinctly from the uniform type-tagging of declaration time and the fingerprint | `tests/conformance/test_kleene.py` |

### Margin laws

| Law | Statement | Enforced by |
|---|---|---|
| `margin_sign_convention` | Each comparison form yields the margin its row of the margin table gives, positive being slack | `tests/conformance/test_margins.py` |
| `margin_composition_invariant` | Boolean composition preserves the satisfaction invariant, `&` holding if and only if the minimum margin is at least 0 | `tests/conformance/test_margins.py` |
| `require_margin_equivalence` | A `require(e)` reports `margin(e)`, equal to the margin `forbid(~e)` reports | `tests/conformance/test_require.py` |

### Default laws

| Law | Statement | Enforced by |
|---|---|---|
| `apply_defaults_operator` | `apply_defaults` is idempotent, monotone, and activity-respecting | `tests/conformance/test_defaults.py` |
| `completeness_postcondition` | `is_complete(apply_defaults(c))` holds if and only if every active param is defaulted or supplied | `tests/conformance/test_defaults.py` |
| `element_list_default_exclusivity` | Element and list defaults are mutually exclusive on one param, and a list default requires a static count of matching length | `tests/conformance/test_defaults.py` |
| `field_wise_fill` | Choice and struct params fill field-wise from their members' own defaults, partial input winning | `tests/conformance/test_defaults.py` |
| `defaulted_count_cascade` | A defaulted count param determines its list's length in the same pass, under fill-only output | `tests/conformance/test_defaults.py` |

### Partial-config laws

| Law | Statement | Enforced by |
|---|---|---|
| `activity_collapse` | Collapsing three-valued activity under `unknown → inactive` reproduces full-config binary activity | `tests/conformance/test_partial.py` |
| `driver_loop_coincidence` | `next_assignable(c) == []` if and only if `is_complete(c)` | `tests/conformance/test_partial.py` |
| `remaining_domain_soundness` | `remaining_domain` never excludes a still-feasible value, and every value its descriptor admits validates against the declared domain | `tests/conformance/test_partial.py` |
| `one_unset_operand_reduction` | A bound or single forbid leaving one unset bare operand narrows across kinds | `tests/conformance/test_partial.py` |
| `no_multi_operand_propagation` | An implication with two unset operands is not propagated | `tests/conformance/test_partial.py` |
| `partial_eval_partition` | `PartialEval` partitions constraints into evaluable and pending with no overlap and no omission | `tests/conformance/test_partial.py` |

### Identity laws

| Law | Statement | Enforced by |
|---|---|---|
| `sugar_equivalence` | Sugared and explicit spellings fingerprint-equal: `log_scale` against its prior, `implies` against its expansion, variadic `.repeat()` against the chain, an expression bound against its manual envelope-plus-`forbid(x > y)` expansion, and an exact `Primitive` arity against its `(n, n)` spelling | `tests/conformance/test_identity.py` |
| `polarity_tracks_feasibility` | An expression bound is fingerprint-distinct from the feasibility-opposite `.forbid(x <= y)`, so fingerprint equality tracks feasibility despite `origin`'s exclusion | `tests/conformance/test_bounds.py` |
| `require_equivalence` | `require(e)` is feasibility-, margin-, and fingerprint-equal to `.forbid(~e)`, and `discourage(e)` likewise to `.encourage(~e)` | `tests/conformance/test_constraint_kinds.py` |
| `declaration_order_significant` | Permuted param or variant declarations fingerprint differently | `tests/conformance/test_identity.py` |
| `scope_monotonicity` | A change to meta, tags, anchors, or a declared constraint is `sampling`-equal and `full`-distinct | `tests/conformance/test_identity.py` |
| `json_round_trip` | `Space.from_json(s.to_json()).fingerprint() == s.fingerprint()` at both scopes, for fully serializable spaces | `tests/conformance/test_identity.py` |
| `mark_sentinel_distinctness` | A marked opaque site is fingerprint-distinct from the absence of that site | `tests/conformance/test_identity.py` |
| `type_tag_distinctness` | `1`, `1.0`, and `True` are distinct at every `Any`-typed leaf, and `−0.0` canonicalizes to `0.0` | `tests/conformance/test_identity.py` |
| `digest_known_answers` | Committed known-answer digest vectors reproduce byte-identically | `tests/conformance/test_vectors.py` |

### Static-resolution laws

| Law | Statement | Enforced by |
|---|---|---|
| `count_folds_to_int` | A determined count folds to a static `int`, so `has_variable_length`, `coordinate_paths()`, `cardinality()`, and the `Array` dtype rule all agree, and slicing a count is the route to a fixed layout | `tests/conformance/test_static_resolution.py` |
| `condition_folds_to_none` | An always-true condition folds to `None`, and a `False` fold is left in place | `tests/conformance/test_static_resolution.py` |
| `fold_reach_differs` | `.slice()` folds unconditionally while `.freeze()` folds only where the domain admits a single value, so a constraint-pinned kind keeps its condition and a frozen choice stays fingerprint-equal to its pin-and-prune expansion | `tests/conformance/test_static_resolution.py` |
| `fold_is_best_effort` | An unfoldable expression, or one reaching a `ds.value` or `.prop()` leaf, is left alone and `fn` is never called | `tests/conformance/test_static_resolution.py` |
| `freeze_matches_static_spelling` | `freeze(n=3)` is fingerprint-equal to the hand-written static spelling | `tests/conformance/test_structural_ops.py` |

### Reference-closure laws

| Law | Statement | Enforced by |
|---|---|---|
| `reference_closure` | Every param reference a resolved space stores names something declared in that space, across all four stores (`Space.conditions` and `ParamDef.condition`, `Space.constraints`, `ListDomain.count`, and `ListDomain.element_constraints`, the last two at every lift level), asserted against the predicate row 6 uses and swept over every corpus fixture and the full product of reference-carrying declaration against nesting route | `tests/conformance/test_reference_closure.py` |
| `owning_lift_resolution` | A lifted choice's discriminator template (`pipe[]`) and an instance path (`stops[0].dwell`) resolve through their owning lift, so neither being a `params` key of its own is not a violation | `tests/conformance/test_reference_closure.py` |

### Structure laws

| Law | Statement | Enforced by |
|---|---|---|
| `relocation_preserves_count` | A lift's `count` keeps binding to the param it named through every relocation route (struct body, choice variant payload, lifted-struct element) and through chained lifts at every level, so realized length equals the count param's value | `tests/conformance/test_relocated_lifts.py` |
| `relocation_preserves_element_constraints` | Per-element constraint templates likewise keep binding, so a per-element hard constraint keeps deciding feasibility | `tests/conformance/test_relocated_lifts.py` |
| `dependency_graph_is_closed` | `dependency_graph` names only real `space.params` keys | `tests/conformance/test_structure.py` |
| `finalization_enforces_row_6` | Row 6 is enforced over the count and element-constraint stores at finalization, so a typo raises instead of going silently Unknown | `tests/conformance/test_relocated_lifts.py` |
| `enclosing_count_reference_deferred` | A count's enclosing-scope reference is deferred rather than eagerly rejected, and a cross-scope cycle through one is still row 7 | `tests/conformance/test_relocated_lifts.py` |
| `flatten_round_trip` | `unflatten(flatten(c)) == c` | `tests/conformance/test_structure.py` |
| `per_element_instantiation_counts` | A per-element constraint yields one `ConstraintEval` per active instance path | `tests/conformance/test_lifts.py` |
| `array_dtype_per_level` | A lift level with a static count emits `Array(dtype, n)` and a dynamic one `List`, applied per level | `tests/conformance/test_dataframe.py` |
| `nested_lift_leaf_aggregates` | Aggregates over nested lifts flatten to the leaf set | `tests/conformance/test_lifts.py` |
| `fixed_leaf_layout` | `coordinate_paths()` round-trips through `unflatten` with no bookkeeping keys present, raises row 33 where no fixed layout exists, excludes lift-length bookkeeping at every nesting depth, and orders its output identically to `flatten`'s leaf order | `tests/conformance/test_coordinates.py` |

### Representation laws

| Law | Statement | Enforced by |
|---|---|---|
| `decode_totality` | `source.validate(rep.decode(g)).param_errors == ()` for every `g` drawn from `target`. The law is domain membership, not `.valid`, which folds in feasibility and so would be false wherever a constraint is opaque | `tests/conformance/test_representation.py` |
| `encode_target_validity` | When `invertible`, `rep.encode(x)` is valid in `target` | `tests/conformance/test_representation.py` |
| `carried_values_valid` | Defaults and anchors carried into the target are valid there, and every one no `encode` could carry appears in `dropped_defaults` or `dropped_anchors` rather than crossing unencoded | `tests/conformance/test_representation.py` |
| `round_trip` | `decode(encode(x)) == x` up to floating-point accuracy, at `rel_tol = abs_tol = 1e-9`, the tolerance convention grid membership uses. `encode(decode(g)) == g` is explicitly not a law: integer charts, quantized grids, one-hot ties, and random-key permutations are all many-to-one | `tests/conformance/test_representation.py` |
| `round_trip_declared` | The round trip holds over the source's authored phenotypes, every anchor and `apply_defaults({})`, which are the only inputs that exercise the tolerance | `tests/conformance/test_representation.py` |
| `feasibility_agreement` | `target.is_feasible(g) == source.is_feasible(rep.decode(g))`, unconditionally for every representation `represent()` builds, transport being total over that set. The one exception, a dynamic-count lift touched by an expression whose encoding supplies neither `decode_expr` nor `rewrite`, is a build-time error rather than an unsound representation | `tests/conformance/test_representation.py` |
| `identity_representation` | A rule set matching no param leaves `target.fingerprint() == source.fingerprint()` at both scopes, with `decode(c) == c == encode(c)` | `tests/conformance/test_representation.py` |
| `then_associativity` | `then` is associative with the identity a two-sided unit, asserted on target fingerprints and on decoded values over derived representations, which requires representing a representation target and so requires transport to handle the `ChartApply` node a representation itself emits | `tests/conformance/test_representation.py` |
| `path_and_arity_preservation` | For a derived representation, `set(target.params) == set(source.params)` over definition-path keys, dimensionality unconstrained, with a param carrying relocated descendants or read by a count never encoded, and one read by a `.prop()` encoded only when the matched `Encoding` supplies `prop_expr()` | `tests/conformance/test_representation.py` |
| `induced_chart_representation` | `space.represent()` touches exactly the chart-bearing params, at their own or any element level, that no count or `.prop()` reads, targets `real(0,1)` with `periodic` mirrored, and is measure-preserving | `tests/conformance/test_representation.py` |
| `representation_outside_ir` | A `Representation` never enters the IR, `to_json`, or the fingerprint preimage | `tests/conformance/test_representation.py` |

### Sampling laws

| Law | Statement | Enforced by |
|---|---|---|
| `tighten_equals_reject` | Tighten-not-reject on a bound-origin constraint is distributionally identical to rejection, truncation being conditioning | `tests/conformance/test_bounds.py` |

### Sampling-diagnostic laws

| Law | Statement | Enforced by |
|---|---|---|
| `report_never_rejects` | `sampling_report` puts `n` draws behind every row regardless of `acceptance_rate`, and leaves `space.fingerprint()` unchanged | `tests/conformance/test_sampling_diagnostics.py` |
| `report_seed_reproducible` | The same seed gives the same report | `tests/conformance/test_sampling_diagnostics.py` |
| `satisfied_conditioned_on_applicable` | `satisfied` is the fraction of applicable draws, not of all draws | `tests/conformance/test_sampling_diagnostics.py` |
| `unknown_swallowing_visible` | An unguarded optional aggregate reports `ConstraintReport.applicable < 1.0`, and `== 1.0` once `.if_inactive()` guards it, all else equal | `tests/conformance/test_sampling_diagnostics.py` |
| `funnel_visible` | `acceptance_rate` matches the analytic value under Kleene rule 4, and the accepted sample concentrates away from where the constraint is inapplicable | `tests/conformance/test_sampling_diagnostics.py` |
| `one_denominator` | Per-instance folding and `activity`'s template keys share the denominator `n` with every scalar row | `tests/conformance/test_sampling_diagnostics.py` |
| `tighten_bounds_flag` | `tighten_bounds=False` draws the full declared envelope, and `=True` matches the reference sampler's own acceptance rate | `tests/conformance/test_sampling_diagnostics.py` |

### Opaque-value laws

| Law | Statement | Enforced by |
|---|---|---|
| `opaque_float_margin` | `returns=float` under a comparison reports a real margin, at parity with `.prop()`'s own baseline | `tests/conformance/test_opaque_values.py` |
| `opaque_bool_bare` | `returns=bool` is usable bare, with `margin = None` absorbing through Boolean composition | `tests/conformance/test_opaque_values.py` |
| `opaque_int_count` | `returns=int` drives a `.repeat()` count, and a non-int `returns` there is row 12 | `tests/conformance/test_opaque_values.py` |
| `opaque_declaration_errors` | Row 30's three clauses hold: non-scalar `returns`, a non-expression operand, and a comparison type mismatch against the declared `returns`, the last strict with no int/float leniency | `tests/conformance/test_opaque_values.py` |
| `opaque_calling_convention` | `fn` receives exactly the operand values, positionally, never the config, and an exception `fn` raises propagates uncaught | `tests/conformance/test_opaque_values.py` |
| `opaque_unknown_is_value_driven` | An inactive operand yields Unknown without calling `fn`, `.if_inactive()` inside an operand composes, and an unset operand under partial evaluation is pending and never coalesced | `tests/conformance/test_opaque_values.py` |
| `opaque_identity` | `to_json` and `fingerprint` raise with the closed-set message by default, `mark` yields `{"$opaque": true}`, and `drop` yields the same marker plus a manifest entry naming the site, across all three positions a `ds.value` can occupy: a constraint, a `.when()` condition, and a dynamic repeat count | `tests/conformance/test_opaque_values.py` |
| `opaque_dependency_graph` | `dependency_graph` includes the operands' referenced params | `tests/conformance/test_opaque_values.py` |
| `opaque_cardinality` | `.cardinality()` is conservatively `None` wherever structural equality cannot see through the opacity | `tests/conformance/test_opaque_values.py` |
| `opaque_no_narrowing` | `remaining_domain` never narrows off a grey or black predicate, per the tier table | `tests/conformance/test_opaque_values.py` |

### Program-type laws

| Law | Statement | Enforced by |
|---|---|---|
| `symbolic_value_validity` | A `.symbolic()` value validates if and only if every `"op"` is a name this param declared, every `"var"` is a `signature.args` key, every `"const"` lies within some declared literal's bounds, and depth is at most `max_depth`, a leaf being depth 1 | `tests/conformance/test_program_types.py` |
| `open_vocabulary_checked_at_value_time` | Any string names a primitive at declaration time, and the name is still checked at value time | `tests/conformance/test_program_types.py` |
| `arity_binds_where_declared` | A bare string accepts any arity, and only a `Primitive` binds one | `tests/conformance/test_program_types.py` |
| `validators_run_after_structure` | `validators` run only after the structural check passes, and a raising validator never escapes a public call | `tests/conformance/test_program_types.py` |
| `program_generativity` | `.code()` is always non-generative, `.symbolic()` is non-generative unless `sampler=` is given, and `has_nongenerative_params` is true for either kind under a `.repeat()` element as well as at the top level | `tests/conformance/test_program_types.py` |
| `per_field_opacity` | `validators`, `.symbolic()`'s `sampler`, and `Primitive.fn` each ride raise, mark, and drop *in place*, degrading only that field and never the whole domain, and `from_json` raises on a marked field | `tests/conformance/test_program_types.py` |
| `program_freeze_and_slice` | `.freeze()` is fingerprint-equal to the hand-written `require(p == value)` plus `.default(value)` expansion, and `.slice()` supports a program param unconditionally, a program value always being a plain, comparable, serializable JSON dict | `tests/conformance/test_program_types.py` |
---

## Solver Integration

*Informative.* This section describes how the normative surface above is
consumed and imposes no further requirement.

A solver defines the space it can work with: base CMA-ES is R^n, variants add
integers and categoricals, SMAC and irace add conditionals, and others work on
graphs. Pointing one at a `Space` therefore has exactly three shapes.

**Interpret the `Space` directly.** A solver that understands the IR walks
`topological_order`, determines activity via conditions, embeds active
generative params in u-space via their charts, proposes, decodes, and checks
margins. Charts give every solver a free, type-appropriate perturbation: mutate
in u-space and decode through the chart, so log-scaled params get multiplicative
noise and grids snap correctly with no per-type code. Core still ships no
operators. Negotiation is ordinary introspection: the solver checks kinds,
`is_conditional`, `has_variable_length`, `ParamDef.chart is not None`,
`ParamType.type_key`, and fails with its *own* message, only the solver knowing
what it supports.

**Convert the `Space` to a foreign representation.** ConfigSpace and kin. Core
ships no adapter and takes no dependency; the public, bidirectional IR is the
socket.

**Bridge with a `Representation`.** When the solver's genotype differs from the
phenotype, `space.represent(*rules)` produces a genotype `Space` plus `decode`
and `encode` (see *The Representation Layer*). `rep.target` is an ordinary
space, so the first shape applies to it unchanged, and a bridge needs no new
negotiation vocabulary.

The open world of `.custom()` negotiates per param, over two independent
channels.

**Generation ladder**, richest available rung winning: a native adapter
recognizing `type_key`; then a `Representation` whose target this solver can
handle, its geometry authored by the type author and its loss declared rather
than silent; then an opaque `sample(rng)`, which is sufficient for random search
and resampling moves.

**Modeling channel**, orthogonal to generation: `properties()` featurizes values
for surrogates and reporting regardless of the production rung, and `to_json`
and `config_hash` give observation identity. A type opaque to generation can be
rich to modeling.

**Adapter conventions.** Strategy-entangled operations, meaning crossover
schemes, mutation policies, and trust regions, are the only thing genuinely
forced into adapters. Adapters are keyed by the same `type_key` used in
serialization; they receive the live `ParamType` instance and derive all domain
facts from it, through `describe`, `validate`, and `extract`, rather than
re-declaring them; they receive a `Representation` rather than embedding one;
and they are scoped per capability and type, not per solver and type.

For guidance on modeling structured values (graphs, layouts, schedules, and
kin), on the limits of the expression language, on the tension between
`.prop()`-driven alignment and later bridging, and on choosing among
semantically overlapping mechanisms, see
`docs/design-notes/structured-values.md` and
`docs/design-notes/choosing-a-mechanism.md`.

---

## Staging

*Informative.*

Two groups of surface are specified but deferred past the initial release, on
different bases. `ds.from_callable` and `Annotated` domain literals
(`ds.real(...)`, `ds.integer(...)`, and so on) as an optional module, together
with `to_dataclass() -> type`, `to_python_source() -> str`, and
`to_pydantic_model()`, ship as **optional extras**: they are not part of the
core surface and require their own installs.

`to_json_schema` is dependency-free, being cheap under nested choice, and stays
part of the core surface once it ships rather than becoming an extra. Its build
is scheduled after the initial release. Its output contract, covering the JSON
Schema draft, the per-kind domain mapping, whether conditions and constraints
surface, and opaque-param handling, is not yet specified under *Identity and
serialization*, and is resolved when that work opens.

---

## Out of Scope

*Informative in presentation, binding in effect: nothing on this list is
implemented, including as a helper.*

Excluded **by construction**, operators acting on genotypes and core owning only
the induced chart:

- Search, mutation, crossover, neighborhoods, and fitness-aware generation.
- Distance metrics and kernels, which are genotype-level notions.
- Tree and program generation strategy for `.symbolic()`, tree genomes being
  genotypes.
- Encoding and vectorization beyond the `Representation` morphism. Core ships
  the **induced chart representation** only, and every *chosen* genotype,
  whether one-hot, stick-breaking, random keys, or a type bridge, is consumer-
  or type-author-supplied.
- **Structural morphisms**: flattening a hierarchy into a flat table, relaxing
  conditions away, padding a dynamic lift to fixed width. The IR is *already*
  the flat table, so nothing is missing; hierarchy is a modeling decision to be
  handled explicitly rather than circumvented, and imputation and padding
  conventions are irreducibly chosen. These are writable as a supplied
  `Representation` and are never shipped by core.
- Growing the expression language past chart application and `ds.value`.
  Anything structurally expressible goes through the language and anything else
  through the opaque leaf, and there is no third category.
- Surrogate modeling, acquisition functions, and prior fitting from observed
  data.
- LLM backends for `.code()`.
- Cost-aware and multi-fidelity scheduling.
- Constraint propagation beyond the one-unset-operand guarantee, which is CSP
  solving.
- Value-dependent indexing (`x[k]` for a param-valued `k`) and quantification
  over dynamic ranges. The cost is **loss of static dependency analysis**: the
  referenced element is unknown until `k` is assigned, so the expression would
  have to reference the whole lift conservatively, degrading `dependency_graph`,
  the bound envelopes, and `remaining_domain`'s one-unset-operand reducer. For a
  *static* count the case is already expressible by unrolling, as in
  `ds.all_(*((k == i).implies(...) for i in range(n)))`, which is the
  machine-generation pattern the metaprogramming surface exists for. Negative
  indexing is **not** covered by this exclusion: `x[-1]` resolves against the
  lift's own realized length and still references exactly that lift.
- Exact conditional subset sampling with calibrated marginals, and
  alignment-aware repeat diffing.
- Penalty shapes, weights, priorities, and relaxation policies, which are
  annotated via constraint `meta`.
