# Decisions

This file is an interpretation log for genuine gaps in `API.md`. It is not a
general ADR diary, a progress log, or a place to justify divergence from a clear
requirement.

**Who decided determines whether the answer reaches `API.md`.**

- A gap the **user** resolves is folded into `API.md`, so future work no longer
  depends on reading the entry. The entry stays here for reference, holding the
  reasoning behind the requirement.
- A gap an **agent** resolves is recorded here and nowhere else. It is not
  folded into `API.md`, whatever the entry concludes. The entry is a request for
  review, and the specification changes only once the user has reviewed it. Its
  `Specification update` field says so.

Entries are numbered for this file's own use. **Nothing outside this file cites
an entry by number.** Code and specification state their reasons directly, in
words, so that reading them never requires following a number to a second
document.

## Entry template

Copy this template for each genuine specification gap.

```markdown
## D-NN: Short title

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

For a user decision, the `API.md` section changed after resolution. For an agent
decision, `Awaiting user review` and the section that would change. `Pending` while
the entry is open.
```

---

## D-91: Resolution timing for a `.repeat()` count's enclosing-scope reference

- Status: Resolved
- Date: 2026-08-03
- Spec section: API.md §Resolution > Resolution timing; §Modifiers and Layering
- Decided by: User

### Question

A `.repeat()` count declared inside a struct body or choice variant payload may
reference a param that binds only in an *enclosing* scope. Is that reference
checked **eagerly**, while the payload resolves standalone (making it a
resolution error, since the referent is not yet visible), or **deferred** to the
finalization pass over the merged space, the way a `.when()` condition's
up-reference is?

### Why the specification is insufficient

"Resolution timing" enumerates the three positions it governs and assigns each a
timing: `.when()` conditions are **deferred**; constraint references "stay
strict and raise eagerly"; expression-bound references are "likewise eager and
never deferred", with a stated reason: the chart envelope must be computed
during the declaring scope's own resolution.

Repeat counts are named in none of the three. The surrounding text points both
ways. In favor of deferral, "Modifiers and Layering" says a count "joins the
dependency graph and cycle check … **exactly as a condition does**". In favor of
eagerness, a count is checked at resolution against the row-12 calculus, which
reads the referent's declared type, a check that superficially resembles the
bound engine's need for the referent's declared bounds.

### Possibilities considered

1. **Deferred, like conditions.** A cross-scope count becomes legal; row 6/12
   checks and cycle detection move to the finalization pass, so they still run
   at the first terminal operation. Matches the "exactly as a condition does"
   wording. Costs: the row-12 type check must be expressible over the merged IR
   (`ListDomain` chain) as well as over builder snapshots.
2. **Eager, like bounds.** A cross-scope count stays a resolution error.
   Cheapest, being the current behavior, and defensible if the row-12 check is
   held to need its referent in scope. Costs: rejects a natural declaration (`n`
   at root, a list inside a struct sized by it) that the scoping rule's up-walk
   otherwise admits everywhere, and leaves the spec's own "exactly as a
   condition does" false.

### Answer

**Deferred, like conditions** (possibility 1).

### Reasoning

The bound engine's eagerness has a *mechanical* cause, which the spec states
outright: a chart is built during the declaring scope's resolution and is static
thereafter, so an unresolvable bound reference has no later repair. No such
consumer exists for a count. API.md is explicit that counts "remain
runtime-evaluated, unlike bounds, because lists are structure rather than
charts": nothing in the declaring scope reads a count, so nothing forces the
check early. The row-12 type check is not a counterexample. It is a *check*
rather than a consumer, and a check can move.

That leaves the "exactly as a condition does" wording as the operative
statement, and deferral is what makes it true. Deferral also moves only *when*
the error surfaces, never whether: rows 6, 12, and 7 all re-run at finalization,
which every terminal operation triggers.

### Specification update

"Resolution timing" now names repeat counts alongside conditions as deferred,
with the runtime-evaluated rationale. Error-table row 6 names the repeat count
as a checked reference position. A conformance law was added under "Structure"
(`tests/conformance/test_relocated_lifts.py`).

---

## D-92: Do `.slice()`/`.freeze()` statically resolve the structure a fixed value determines?

- Status: Resolved
- Date: 2026-08-03
- Spec section: API.md §Space: Structural Operations
- Decided by: User

### Question

`.slice()` and `.freeze()` substitute a fixed value at its reference sites. Once
every param a piece of *derived* structure reads is determined, is that
structure **folded** to its constant form, a `.repeat()` count becoming a static
`int` and a now-always-true condition becoming no condition, or is it left as an
expression that merely happens to be constant?

And is a `.repeat()` count a `.slice()` reference site at all, given the count
param is being removed?

### Why the specification is insufficient

The `.slice()` row says "substitute the value at every reference site, across
conditions, constraint expressions … and `.repeat()` counts", and the
`.freeze()` row says "conditions resolve statically". Neither is decidable as
written:

- The `.slice()` enumeration names three reference sites and not the fourth. A
  repeat count is a reference site by every other measure, entering
  `dependency_graph`, `topological_order`, and row 7's cycle check, but it is
  the one whose *substituted* form is a `ListDomain` field rather than an
  expression store, and the spec never says whether it participates.
- "Resolve statically" does not say what the resolved form *is*. Substituting
  into a condition already produces a constant expression, so the sentence is
  satisfiable without folding, which is what the implementation did, leaving
  `.freeze()`'s conditions reading the frozen param and `.slice()`'s as
  `BoolLiteral(True)`.

The distinction is not cosmetic, because every static-ness surface tests
representation, not value: `has_variable_length`, `coordinate_paths()`'s row 33,
`cardinality()`, and the `Array`-vs-`List` dtype rule all ask `isinstance(count,
int)`. An unfolded space misreports itself on all four. It was also observable
as a gap: with `.slice()` on a count unimplemented and `.freeze()` not folding,
**no operation could turn a dynamic-count space into a fixed-layout one**, so
`coordinate_paths()` was unreachable for any space that ever had a param-driven
count.

### Possibilities considered

1. **Substitute only; never fold.** Status quo. Cheapest, and no fingerprint
   moves. Costs: the four static-ness surfaces stay wrong, `coordinate_paths()`
   stays unreachable, and `.freeze()`'s documented "conditions resolve
   statically" stays false.
2. **Fold to a constant expression** (`Literal(3)`, `BoolLiteral(True)`). Fixes
   the semantics and nothing else: every surface above tests `isinstance(count,
   int)` or `condition is None`, so none of them move. Strictly worse than 3 for
   the same cost.
3. **Fold to the canonical static form**: a count to `int`, an always-true
   condition to `None`. All four surfaces become correct, and `.slice()` on a
   count becomes the route to a fixed layout.

Independently, for `.freeze()` only: **which** frozen params may contribute a
literal.

- **3a. Every frozen param.** Uniform, but unsound in a specific way. Freeze
  *keeps* the param, and the kinds it pins by a hard `require` rather than by
  domain narrowing (bool, choice, subset, permutation, custom, program) keep a
  domain that still admits their other values. A config holding one is
  domain-valid and merely infeasible, and folding a condition against the pinned
  value reports a param *active* there where evaluation says it is not. It also
  breaks the standing law that a choice `.freeze()` is fingerprint-equal to its
  hand-written pin-and-prune expansion, by dropping the variant's activation
  condition.
- **3b. Only params whose domain admits exactly one value.** Real/integer
  narrowed to `lo == hi`, categorical/ordinal to a single value. Covers the
  count case (a count is integer-typed by row 12, so its referent is always
  domain-narrowed) and leaves the constraint-pinned kinds alone.

### Answer

**Possibility 3**, with **3b** for `.freeze()`.

`.slice()` folds unconditionally: having removed the param, there is no config
in which it could hold another value. `.freeze()` folds only where the domain
admits a single value. Counts fold to `int`; conditions folding to `True` become
`None`, while a `False` fold is left alone.

### Reasoning

Folding to the canonical static form is the only option under which the space's
own introspection tells the truth about it. The `int`-versus-`Literal(3)` detail
is the whole decision rather than a detail: possibility 2 would satisfy every
reading of "resolve statically" while changing nothing a caller can observe.

The `.slice()`/`.freeze()` asymmetry is the difference between the two
operations rather than a special case bolted on. Slice removes the param, so
substitution is total and folding is unconditionally sound. Freeze keeps it, so
soundness is bounded by what the param's domain guarantees, and a constraint pin
is deliberately not a domain fact (API.md is explicit that a bool freeze is
"visible in `.constraints` and in the fingerprint … rather than a silent domain
fact"). Gating on the domain rather than on the freeze mechanism keeps that
deliberate choice load-bearing instead of quietly overriding it.

`True → None` but not `False → prune`: an always-active param *is* an
unconditional param, so dropping the condition is information-preserving,
whereas removing a permanently-inactive param would take a declared name out of
the path namespace, which `.params`, `flatten`, and the fingerprint preimage all
observe. Sound-but-conservative, matching `cardinality()`'s posture.

The fold is best-effort over the reference-free, opaque-free expressions the
ordinary evaluator can evaluate against an empty config, reusing that evaluator
rather than writing a second one, so a folded value can never disagree with what
runtime evaluation would have produced. It refuses to descend through `ds.value`
and `.prop()`: `fn`'s calling convention promises a call with the operand values
*at evaluation*, and structural-op time is not a call site it agreed to.
Anything unfoldable stays an expression, which is always sound, the lift merely
staying dynamic.

**Fingerprint impact.** Derived spaces move: `freeze(n=3)` now hashes as the
static space it is, and becomes fingerprint-*equal* to the hand-written
`integer(3,3).default(3)` + `.repeat(3)` spelling. That is correct under the
stated law: equal fingerprints must mean identical valid-config sets, and these
two have exactly that. No format-version bump: the preimage format is untouched
(a count already encodes as either an int or an expression); only what a derived
space *is* changes.

### Specification update

The `.slice()` row now names the repeat count as a reference site; a new "Static
resolution" paragraph under *Space: Structural Operations* states the fold, its
canonical target forms, the `True`/`False` asymmetry, and the slice/freeze
soundness gate. A conformance law was added under "Structure"
(`tests/conformance/test_static_resolution.py`).

---

## D-93: The compositional route to a two-level container-element lift

- Status: Resolved
- Date: 2026-08-03
- Spec section: API.md §Modifiers and Layering; error table row 34
- Decided by: User

### Question

An earlier decision declared a `struct`/`choice` element under more than one
`.repeat()` level unsupported, and the guard rejects the **chained** spelling
`.space(...).repeat(3).repeat(2)`. The same merged shape is reachable
**compositionally**, by declaring a struct/choice lift *inside* another lift's
element `Space`, which composes to the identical `"rows[].spans[].lo"` template.
That route was unguarded. Should it be rejected, or supported?

### Why the specification is insufficient

That restriction was never written into `API.md` at all. It existed only as a
resolution error message and a ledger entry that had since been removed. So the
spec neither permits nor forbids either route, and the implementation's
behaviour differed between two spellings of one shape with nothing stating which
was intended.

The compositional route did not merely go unchecked; it fell through into
machinery that never instantiates the inner elements, and did so **silently**:

- a struct lift sampled empty element dicts (`{"r": [{"s": [{}, {}]}, …]}`),
  with `validate()` then reporting `missing` against malformed paths that mix an
  instance index with a `"[]"` template (`"r[0].s[].v"`);
- a **lifted choice** sampled an empty payload (`{"s": [{"b": {}}, "a"]}`) that
  `validate()` **accepted as valid**, which is a validation hole rather than
  only a sampling one.

### Possibilities considered

1. **Extend the guard.** Detect the merged shape (a param whose own definition
   path already sits inside a lift element and which is itself a
   struct/choice-elemented lift) and raise row 34. Small, and makes the two
   spellings agree. Costs: technically a compatibility change, since the
   lifted-choice case currently resolves and validates, though only by producing
   values that are wrong, so nothing correct can depend on it.
2. **Implement nested container lifts.** Make the shape work via recursive
   per-instance instantiation. Expands the surface past a documented boundary
   and reaches instantiation, validation, `flatten`/`unflatten`, DataFrame
   dtypes, and representation, each needing its own conformance coverage.
3. **Document as a known gap.** Cheapest; leaves a shape that silently produces
   invalid configs and, for lifted choices, passes validation.

### Answer

**Possibility 1**: extend the guard, and write the boundary into `API.md` (a new
row 34 plus a statement in *Modifiers and Layering*) so it stops being folklore.

### Reasoning

The boundary is about the shape, not the syntax that reaches it, so two
spellings of one shape disagreeing was never a defensible state; whichever way
it resolved, it had to resolve the same for both. Given that, rejecting is the
release-appropriate direction: silently emitting invalid configs is wrong under
any scope decision, and possibility 3 preserves exactly that. Possibility 2 is a
genuine feature and may still be the right long-term answer; the guard does not
preclude it, and converts a silent wrong answer into a precise, path-named error
that says the shape is unsupported.

The compatibility exposure is narrow by construction. A space in the affected
shape could not have been producing correct results: the struct case fails
`validate()` outright, and the choice case passes validation only because the
payload check never runs on an empty payload.

Writing the restriction into `API.md` is the other half. A resolution error the
normative spec never mentions is not a boundary users can design around, and it
is how the compositional route came to be unguarded in the first place: the
guard was written against the syntax someone had in mind rather than against a
stated rule.

### Specification update

*Modifiers and Layering* gains the one-lift-level statement for container
elements, naming both routes; the error table gains row 34. Conformance laws
live in `tests/unit/test_resolve_m4.py::TestD24NestedStructChoiceLiftBoundary`
and as expected-error cells of the nesting grid in
`tests/conformance/test_reference_closure.py`.

---

## D-94: Is `decode(encode(x)) == x` exact, and over which `x`?

- Status: Resolved
- Date: 2026-08-03
- Spec section: API.md §The Representation Layer > Obligations; Conformance Laws
- Decided by: User

### Question

The Representation conformance bullet states the one-directional round-trip
`decode(encode(x)) == x` with no qualification. Is that literal equality, and
does it range over every phenotype or only some?

### Why the specification is insufficient

Written as stated it is **false**, and the implementation already knew:
`_approx_equal` compares floats at `rel_tol = abs_tol = 1e-9` and its docstring
says the law "is meant up to that unavoidable slack". So the intended reading
existed in code while the normative document asserted exactness. The spec was
the thing that was wrong.

The gap was invisible because of *which* `x` the suite tried. `check()`
round-trips `x = decode(g)` for sampled `g`, and every such `x` lies on the
chart's image: `encode` recovers the very unit coordinate `x` was decoded from,
so the comparison is bit-exact and the tolerance is never exercised. An
**authored** phenotype does not lie there: `lr = 1e-3` under a `Log()` chart
composes `to_unit`/`from_unit` through `log`/`exp` and comes back
`1.0000000000000002e-3`.

Authored phenotypes are not a corner case: they are what `encode` exists for
("warm-starting ... anchors and historical observations are phenotypes, and
seeding a solver with them is `rep.encode(config)`"). So the one class of input
the law was written to serve was the one class it was never checked against, and
a supplied `Encoding` could be lossy on exactly those inputs and still report
`ok`.

There is a further consequence the spec never drew: `config_hash` is exact
(type-tagged, JCS), and `(fingerprint, config_hash)` is the stated
globally-unique observation key. A phenotype that has been through
`encode`/`decode` can therefore hash differently from the one it started as.

### Possibilities considered

1. **Make it exact.** Not achievable: no float encoding makes `exp(log(x))`
   bit-exact for arbitrary `x`. Would require storing the pre-image, which is
   stateful and defeats the point.
2. **State the law precisely and stop.** Qualify it with the tolerance and note
   the `config_hash` consequence. Zero code change, but leaves the
   authored-value case unexercised, so a lossy supplied encoding still passes
   `check()`.
3. **State it precisely *and* cover authored values in `check()`.** Same
   clarification, plus `check()` round-trips the source's anchors and
   `apply_defaults({})` under a distinct law name.

### Answer

**Possibility 3.**

The law is `decode(encode(x)) == x` **up to floating-point accuracy** (`rel_tol
= abs_tol = 1e-9`, the tolerance convention grid membership already uses).
`check()` additionally round-trips every source anchor and the defaults-filled
config, reporting under `round_trip_declared`.

### Reasoning

Possibility 2 is where the spec was already heading and is strictly incomplete:
writing down a tolerance without checking the values that exercise it documents
the property rather than enforcing it, and the whole point of `check()` is that
a supplied morphism "has no other way to be shown sound". The gap was never that
the tolerance was wrong. It was that the sampled half of `check()` cannot
construct an input that tests it.

Anchors and `apply_defaults({})` are the right corpus for it because they are
the authored phenotypes the library already holds; they need no new API and no
synthetic value generation whose in-domain-ness would itself need arguing. A
distinct law name keeps a failure diagnosable: it says which half broke, and the
two halves fail for genuinely different reasons.

No new public surface: `check()` is already "the laws, as a tool", so it checks
more rather than the library exporting a comparison helper for consumers to call
by hand.

### Specification update

The Conformance Laws round-trip clause gains the tolerance and the
authored-value scope; *Obligations* documents what `check()` now covers and
draws the `config_hash` consequence explicitly. Laws in
`tests/conformance/test_representation.py:: TestRoundTripOfAuthoredPhenotypes`,
including a negative case (a lossy supplied `encode` that every sampled draw
passes and the authored anchor catches).

---

_Numbering._ D-1 through D-90 were resolved into `API.md` and removed from this
file, and are recoverable from git history. Numbering continues unbroken, so a
number always names one question.
