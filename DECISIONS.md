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
live in `tests/unit/test_resolve_m4.py::TestNestedStructChoiceLiftBoundary`
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

## D-95: May user-facing text cite the error table?

- Status: Resolved
- Date: 2026-08-08
- Spec section: API.md §Error table, §Errors and Concurrency
- Decided by: User

### Question

The error table numbers its rows, and 52 raised messages ended by citing the
row they implement, as in `... to materialize from (row 26)`. 24 citations of
`API.md`, an error-table row, or a private module also sat in the docstrings of
exported objects, which are published as the API reference. May text a user
meets, in an exception or on the documentation site, name a document that ships
with the repository rather than with the package?

### Why the specification is insufficient

`API.md` requires every `ResolutionError` message to name the offending
definition path or paths, and the error table fixes what each row covers. It
says nothing about anything else a message may contain, so the row citation was
neither required nor forbidden, and it spread by imitation.

### Possibilities considered

1. **Publish the error table on the documentation site.** The row citation
   becomes resolvable, and 56 tests matching on `row N`, several of them
   conformance tests, stand unchanged. The number stays positional, so
   inserting a row still renumbers every row below it and invalidates every
   message already emitted into a log.
2. **Keep the citation, treat it as an internal detail.** Costs nothing to
   implement and leaves a user holding an identifier that resolves nowhere.
3. **State the condition, drop the number.** The message says what went wrong.
   The row-to-test correspondence moves into the tests, which are read by the
   people row numbers are for.

### Answer

Possibility 3. A reference resolves for its reader. Maintainer-facing text,
meaning private modules, comments and everything under `tests/`, may cite
`API.md`, its sections and its error-table rows. User-facing text, meaning
runtime messages, the docstrings of exported objects and their public members,
and everything under `docs/`, states the thing.

### Reasoning

A row number is not an error code in the sense `mypy` and `rustc` have one.
Those are stable public identifiers with a documented registry; a row number is
a position in a markdown table that renumbers on insertion, so it cannot
identify a condition durably even for a reader holding the table. Publishing
the table would have made a fragile reference reachable rather than making it
good.

`API.md` states the target, unshipped surface included, so publishing it would
also show a reader things that do not exist and would leave the site with two
reference surfaces to drift apart.

### Specification update

`CLAUDE.md`'s prose standards gain the rule as their fifth entry, that being
where the standards governing authored text live. `API.md` is unchanged: it
already says what a message must name, and says nothing this contradicts.
Enforced by `messages_cite_no_error_table_row` and
`every_error_row_is_named_by_a_test` in `tests/test_docs_site.py`,
`site_prose_is_self_contained` in the same file, and
`published_docstrings_are_self_contained` in `tests/test_docs.py`.

---

## D-96: Do public objects render themselves for a human, and what is the stability of that rendering?

- Status: Resolved
- Date: 2026-08-09
- Spec section: none (gap); resolved into API.md §Human-Readable Rendering
- Decided by: User

### Question

Every exported type relies on the `@dataclass`-generated `__repr__`. That repr
is faithful but unreadable at any real size: a three-parameter space prints as
one line of nested `mappingproxy`, `frozenset()`, and unresolved defaults such
as `FreshParamExpr(path='optimizer', domain=None, periodic=False,
prior_spec=None, ...)`. Should a public object render itself readably for a
person, through which hook, with what stability guarantee on the exact layout,
and should that extend to a module-level formatting function?

### Why the specification is insufficient

`API.md` says nothing about `__repr__`, `__str__`, `str()`, or printing.
Pretty-printing is absent from the binding *Out of Scope* list, whose entries
are all semantic (search operators, distances, genotype encodings, structural
morphisms, CSP solving). The one adjacent sentence, under *Parameter Types*,
states that core owns no printer or parser for a `.symbolic()` value's AST;
that is scoped to rendering a value back to source and says nothing about
rendering a declaration or any other type.

### Possibilities considered

1. **Do nothing.** Leaves the repr as the only rendering, unreadable at any
   real size, and leaves `infeasibility_reasons` printing a violated
   constraint as its bare node kind (`compare`) rather than the expression.
2. **`__str__` only.** `print(space)` and `str(space)` render prettily;
   `repr(space)` stays the faithful dataclass form, so a debugger and the two
   existing repr-pinning doctests are untouched.
3. **`__str__` plus the IPython and Jupyter display hooks**
   (`_repr_pretty_`, `_repr_html_`). Because the user-guide pages are executed
   myst-nb notebooks, a cell ending on a bare object renders into the built
   documentation site through these hooks.
4. **Replace `__repr__` as well**, the polars approach: a bare object at a
   REPL shows the pretty form. Costs the faithful constructor-shaped repr and
   would rewrite the doctests at `builder/_views.py:94` and `ir/_param.py:68`.
5. **A public `ds.pretty(...)` function**, alongside or instead of a dunder.
   Gains caller-supplied width and column selection, and is the only way to
   render a `Config`, since `sample_one` returns a plain `dict` that no
   dunder can reach.

### Answer

Possibility 3, `__str__` plus the notebook hooks, `__repr__` left untouched.
The exact layout is explicitly not a compatibility contract: it may be tuned
after v0.1 without a version bump, unlike the wire format under the freeze
discipline.

`ds.pretty()` (possibility 5) was considered and deferred rather than
rejected. Two of its three arguments are weak: caller-supplied width and
column selection do not by themselves justify new public surface, and
rendering something that is not one object (a space diff, a config pair) is a
separate feature. The third argument survives: there is no way to print a
`Config` against its space, since `sample_one` returns a plain `dict` and no
dunder can reach it. That gap is real but is its own design question, how an
inactive parameter is shown, whether printing validates, one config or many,
and is left for a later milestone to answer on its own rather than folded in
here under a "printing" scope.

### Reasoning

Nothing in the specification forbids this, and the repository already
concedes the problem: `tests/test_docs.py` exempts non-callables from the
worked-example gate because a dataclass repr is "unreadable and brittle as
expected output." A dunder is not an export, so it does not weigh against
`PLAN.md`'s requirement that `__init__.py` hold exactly the implemented spec
surface; a new function would. Possibility 4 was rejected because the
faithful repr has a real use, is what a doctest and a debugger see, and two
doctests already depend on its exact shape.

### Specification update

`API.md` gains `## Human-Readable Rendering`, stating that every public
object renders itself through `str()` and the notebook hooks, that `repr()`
remains the faithful form, that the layout is not a compatibility contract,
that rendered paths use the one grammar from *Paths and Scoping*, and that a
`.symbolic()` parameter renders its declaration only, never a value's AST as
source. The *Conformance Laws* table gains the new laws enforced in
`tests/conformance/test_display.py`.

---

## D-97: How is a configuration rendered against its space, and what public surface does that take?

- Status: Resolved
- Date: 2026-08-09
- Spec section: none (gap); resolved into API.md §Human-Readable Rendering
- Decided by: User

### Question

D-96 gave every public object a `__str__` and the notebook hooks, but named
one gap and deferred it: a configuration is a plain `dict`, and `sample_one`
returns one, so no dunder can ever reach it. There is no way to print an
assignment beside the domain it satisfies, or beside which parameters a
condition switched off. Should that gap be closed now, through what surface,
and with what arguments?

### Why the specification is insufficient

`API.md` says nothing about rendering, human-readable or otherwise; D-96
already established that printing is not covered by the binding *Out of
Scope* list. A configuration itself is specified only as "a `dict[str, Any]`
keyed by definition and instance paths" under *Config Representation*, which
says nothing about how one is displayed.

### Possibilities considered

1. **Do nothing.** The gap D-96 named stays open. `sample_one`'s result is
   printed as a bare dict, `repr`-only, with no reference to the space that
   declares it.
2. **A method on `Space`**, `space.pretty_config(config)`. No new module-level
   export, and the space is always in hand at the call site. Rejected: the
   library's rendering surface would then be split between a dunder-driven
   convention for every other type and a differently-named method for this
   one, and a caller who already has `ds.pretty(other_thing)` in scope would
   have no reason to expect the config path to look different.
3. **A wrapper type**, a wrapping `RenderedConfig` or similar carrying both
   the config and its space. Rejected: it exists solely to be printed and
   would need everything a plain `dict` gives away for free (iteration,
   equality, `in`), and gives no independent design freedom a well-chosen
   function signature does not already give.
4. **A module-level function, `ds.pretty(obj, space=None, ...)`.** One name
   dispatches on what it is given: a configuration paired with its space, or
   any other displayable object read on its own. Reaches the config gap and
   gives `width` and column selection a home, without the split surface of
   possibility 2 or the ceremony of possibility 3.

### Answer

Possibility 4. `ds.pretty(obj, space=None, *, width, columns, show, hide)`
is one new export.

A configuration is rendered as one row per coordinate: its value beside the
domain it satisfies for a `"set"` parameter, or one of `"unset"`, `"inactive"`,
`"unknown"` in place of a value otherwise, distinguishing a parameter waiting
on an assignment from one a condition has switched off, which
`infeasibility_reasons`'s own vocabulary already keeps distinct at the
`evaluate_partial` layer. The header reports the config's real totals and,
when validation succeeds, whether it is valid; the trailing block, when
requested, carries each constraint's verdict and margin. `evaluate_partial`
and `validate` both raise on a value whose type does not match its domain,
exactly the config a printer is reached for, so both run behind a guard and
degrade the affected accounting to `"unknown"` rather than propagating: a
printer must never be less robust than the thing it summarizes failed to
validate cleanly.

`show` and `hide` narrow the rendered rows by status, and apply only to a
configuration: `hide="inactive"` is the common case of wanting to see what is
actually set without the parameters a condition switched off, and `show`
names what is left to assign. A filter is honest about what it drops: the
header keeps the config's real counts, and a trailing line states how many
rows of each hidden status were left out, so a reader can never mistake a
filtered render for a config with nothing to hide. A filter selects rows and
never touches one: a kept row renders identically whether or not a sibling
row was hidden, which is what keeps repeated `pretty()` calls under different
filters comparable by eye.

`columns` and the `width` argument extend to every displayable object, not
only a configuration, since a `Space`, a `ParamDef`, or a `ParamExpr` already
share the same row vocabulary a config's own rows draw from. `pretty(x)` at
its defaults is required to equal `str(x)` for every type this applies to, a
conformance law (`pretty_matches_the_display_hooks`) pins directly, so the two
surfaces cannot silently drift apart. The one deliberate exception is a bare
`Constraint`: its own `__str__` never wraps regardless of length, since a
standalone constraint outside a table was never covered by the width-budget
law D-96 introduced, and `pretty` only wraps one when a caller names a width
of their own.

### Reasoning

A method (possibility 2) reads naturally at one call site but forks the
rendering surface in two: a bare object goes through the display hooks
`str()` already reaches, while a config alone would need its own
differently-shaped entry point, and a caller has no way to guess which
applies without checking the type first. A dedicated wrapper (possibility 3)
solves nothing a function signature does not, and costs a type whose only
job is to be printed, meaning it duplicates `dict`'s own protocol for no
independent benefit. Extending `columns` to every displayable object, not
just a configuration, was a small addition once the vocabulary already
existed for a `Space` table's own columns, and keeping `pretty(x) == str(x)`
at defaults, enforced as a law rather than left as an informal expectation,
is what stops the two rendering paths from drifting once either one changes
independently later.

### Specification update

`API.md`'s `## Human-Readable Rendering` section gains `pretty`'s contract:
the dispatch rule between a configuration and every other displayable object,
the column and status vocabularies, the rule that a row filter reports what
it suppresses rather than dropping it silently, and the statement that a
rendered value is exact while a rendered domain may still elide. The
*Conformance Laws* table gains the new laws enforced in
`tests/conformance/test_pretty.py`.

---

_Numbering._ D-1 through D-90 were resolved into `API.md` and removed from this
file, and are recoverable from git history. Numbering continues unbroken, so a
number always names one question.
