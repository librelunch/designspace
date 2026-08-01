# Decisions

This file is an interpretation log for genuine gaps in `API.md`. It is not a general ADR
diary, progress log, or place to justify divergence from a clear requirement.

When a question is resolved, update `API.md` so future work no longer depends on reading
the historical entry. Keep the entry here to preserve why the answer was chosen.

## D-71 — Unknown provenance join and the malformed-leaf case

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Expressions > Three-valued semantics, rule 5
- Decided by: Agent

### Question

Rule 5 names three provenances Unknown can carry (inactivity, emptiness, an unset
partial-eval operand) and states that `.if_inactive()` coalesces only the first. It does
not say how provenance *combines* when one expression node has more than one Unknown-valued
operand (e.g. `a & b` where `a` is inactive and `b` is pending), nor what provenance a
structurally malformed leaf (an invalid custom-type value, a non-member ordinal literal)
should carry — malformed values already degraded to Unknown defensively before M10.5, but
undifferentiated.

### Why the specification is insufficient

The prose states the three sources and `.if_inactive()`'s behavior toward each individually;
it does not define a join operation, because before this milestone `Unknown` had no
provenance to join at all (a single undifferentiated singleton). Implementing rule 5
faithfully requires *some* answer for the mixed case, or `.if_inactive()`'s "never eats
pending, never eats emptiness" guarantee could be violated by a node that combines a
coalescible inactive operand with a non-coalescible one.

### Possibilities considered

1. **Max-join over `INACTIVE < PENDING < PERMANENT`.** A mixed node keeps the *strongest*
   (least-resolvable) provenance. `.if_inactive()` then still refuses to coalesce whenever
   any contributing operand was pending or permanent — the guarantee holds unconditionally.
2. **First-operand-wins (evaluation order).** Cheaper, but makes `.if_inactive()`'s behavior
   depend on AST shape/operand order for a semantically symmetric expression like `a & b`,
   which is surprising and not chart/order-invariant.
3. **Reject mixed-provenance nodes as an error.** Over-strict — mixed provenance is common
   (e.g. one lift inactive, a sibling's count merely unset) and not itself a defect.

### Answer

Possibility 1 (max-join). A malformed leaf (defensive degrade — `_ordinal_index` on a
non-member value, `_evaluate_prop`'s `from_json`/`validate` failure) carries `PERMANENT`
provenance: it is neither coalescible (it is not mere inactivity) nor resolvable by assigning
more params (it is malformed, not merely absent).

### Reasoning

The max-join is the only option that preserves rule 5's stated guarantee ("never eats
pending", "never eats emptiness") symmetrically and order-independently. `PERMANENT` for a
malformed leaf matches its existing defensive posture (never a crash; `validate()` reports
the real `ParamError`) while correctly refusing to let `.if_inactive()` paper over it.

### Specification update

Folded into API.md's rule 5 (§Expressions > Three-valued semantics) and the Kleene
conformance bullet.

## D-72 — The integer-valued calculus for `.repeat()` counts

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Modifiers and Layering (the `count` bullet), error-table row 12
- Decided by: Agent

### Question

Row 12 says a repeat count must be "integer-typed" and is tagged **R** (resolution-time);
row 13 (a negative *evaluated* count) is tagged **V**. Neither the row nor the `count`
bullet defines which `ArithExpr` node shapes count as integer-*valued* beyond a bare integer
param — e.g. is `ds.param("m").sum()` over a bool lift integer-typed (`sum([True, False])`
is `int` in Python), and is `.min()` over the same lift (`min([True, False])` is `bool`)?

### Why the specification is insufficient

The prose lists `int | ArithExpr` for `count` and separately says a count "is
resolution-checked to be integer-typed," but never enumerates a closed node-type calculus.
The pre-M10.5 implementation used a *reference*-based rule (walk to every leaf `ParamExpr`,
require `type_kind == "integer"`) rather than a *result*-typed one, which incorrectly
rejected `Sum`/`Min`/`Max`/`Count`/`Size`/`Length`/`PositionOf`/`CountOf` wholesale — every
one of these is itself int-valued regardless of the leaf types it reads.

### Why deferring to row 13 (runtime) is not available

Row 12 is tagged **R** specifically to keep type-ness a resolution-time fact, separate from
row 13's *runtime* negativity check; collapsing 12 into 13 would weaken a stated error-table
row and make count-typing config-dependent (`.repeat(n / 2)` would resolve for even `n` and
fail only at sample-time for odd `n`) — a change to what the row means, not merely to its
timing.

### Possibilities considered

1. **Minimal closed calculus** (chosen): int literals, integer params,
   `Count`/`Size`/`Length`/`PositionOf`/`CountOf` (always int by construction — a match-count
   or occurrence-count is int regardless of what it counts), a declared-int `Prop`, `Sum`
   over an integer- *or* bool-leaved lift, `Min`/`Max` over an integer-leaved lift only (the
   `sum`-vs-`min` bool asymmetry — Python's own `sum([True, False])` is `int` but
   `min([True, False])` is `bool`), a literal-valued `SumOver` mapping, `+ - * %` over two
   int-valued operands, `**` with a non-negative literal integer exponent, `IfInactive` when
   both branches are int-valued. Division and anything outside this set stays row 12 —
   mirrors the bounds engine's own "minimal computable op set" precedent.
2. **Narrow allowlist** (aggregates only, keep the reference-based rule for everything else).
   Fixes the named `Sum`-over-bool-lift case and nothing more; leaves the `Min`/`Max` bool
   asymmetry and arithmetic composition unaddressed.
3. **Full symbolic type inference.** Unbounded scope for a milestone about closing eight
   specific silent-bug reports, not redesigning the count grammar.

### Answer

Possibility 1.

### Reasoning

A closed, resolution-time-checkable set is the same shape API.md already uses for
expression-bound envelopes ("the envelope engine is minimal... anything else... is row 20"),
so this follows an established precedent rather than inventing a new one. The `Sum`-vs-`Min`
asymmetry is not a design choice but a direct consequence of what Python's own `sum`/`min`
return over a bool sequence — encoding anything else would misrepresent the runtime value.

### Specification update

Folded into API.md's `count` bullet (§Modifiers and Layering, "The lift").

## D-73 — Folding per-instance evals and template activity into per-draw fractions

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Sampling diagnostics
- Decided by: User, Agent

### Question

`SamplingReport.constraints` is a `ConstraintReport` per `Constraint`, and `ConstraintReport.
applicable`/`.satisfied` are documented as fractions "of all draws". But a per-element
constraint (`ListDomain.element_constraints`, instantiated once per active lift instance —
API.md, "Modifiers and Layering") produces *k* `ConstraintEval`s per draw, not one, so the
per-draw fraction is underspecified without a fold rule. The same question recurs for
`SamplingReport.activity`: a param declared inside a lifted struct/choice exists in
`space.params` only as a `"[]"`-templated definition path (`workers[].timeout_s`) and per draw
only as concrete instance paths (`workers[0].timeout_s`); "per-param active fraction" does not
say which key set `activity` uses or how instances fold onto their template.

### Why the specification is insufficient

The diagnostics section was written against the scalar/whole-constraint case (the funnel and
optional-aggregate examples) and never states a rule for either the many-instances-per-draw or
the template-vs-instance-path case. Both are real: `delivery_routes` has an
`element_constraints` template, and every corpus fixture with a lifted struct has template-only
paths in `space.params`.

### Possibilities considered

1. **Per-draw fold** (chosen). A row's `applicable` is the fraction of draws where ≥1 instance
   eval was Kleene-defined; `satisfied` is the fraction of *applicable* draws where every
   applicable instance was satisfied. `activity`'s template keys use the identical fold: the
   fraction of draws where ≥1 instance was active. Denominator is `n` for every row and every
   key, matching the stated "fraction of all draws" verbatim, and rows stay comparable to each
   other and to `acceptance_rate`. A draw materializing zero instances (an active-empty lift, or
   the lift itself inactive) counts as inapplicable/inactive for that row — exactly the
   Unknown-swallowing signal the surface exists to expose, not a special case to work around.
2. **Per-instance observations.** Each `(draw, instance)` pair is one observation; denominator is
   the instantiation count, not `n`. Finer-grained, but breaks "fraction of all draws" for
   exactly the rows that have instances, and makes those rows incomparable to every scalar row
   and to `acceptance_rate` in the same report.
3. **Exclude element constraints and template paths from the report.** Simplest, but silently
   drops the row/keys most likely to carry the Unknown-swallowing signal (a per-stop budget
   constraint, a lifted-struct field's activity) — the exact failure mode this milestone exists
   to surface.

### Answer

Possibility 1, for both `ConstraintReport` rows and `activity` keys.

### Reasoning

A single fold rule, applied uniformly to constraint evals and activity, keeps the whole report's
denominator at `n` — the reading a user brings from `acceptance_rate` and the scalar rows
extends without exception to the lifted case, rather than requiring a per-row footnote about
what's being divided by what.

### Specification update

Folded into API.md's §Sampling diagnostics.

## D-74 — `sampling_report` and the best-effort tightening optimization

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Sampling diagnostics; §Charts > "All charts are static" (tighten-not-reject)
- Decided by: User

### Question

The reference sampler *may* recognize an already-assigned bound-origin coupling and draw from a
tightened chart instead of rejecting (API.md, "All charts are static") — a `may`, best-effort
optimization, observably identical to rejection by the tighten-not-reject law.
`sampling_report` draws the *unconditioned* measure specifically to expose what rejection
hides. Should its draw path apply this optimization?

### Why the specification is insufficient

Nothing in §Sampling diagnostics says whether "unconditioned" means "no rejection" alone or
"no rejection and no best-effort conditioning of any kind." The two readings diverge sharply in
practice: measured on `firmware_buffers` (n=2000, seed 0), `acceptance_rate` is **0.0515**
without tightening and **1.00** with it, and the three bound-origin `ConstraintReport` rows show
`satisfied` 0.524/0.193/0.511 vs 1.00/1.00/1.00 — tightening does not merely speed up sampling,
it makes the diagnostic numbers unable to show the exact pathology the report exists to surface
on a bound-coupled space.

### Possibilities considered

1. **Report-only flag, default off** (chosen). `sampling_report(n=1000, seed=None,
   tighten_bounds=False)`. Default bypasses tightening — draws are made with `bound_targets={}`,
   the same call shape `_draw_config` already accepts. `tighten_bounds=True` opts into drawing
   the way the reference sampler actually would, answering "how much does tightening save me"
   directly. The three sampling entry points (`sample`/`sample_one`/`sample_dicts`) are
   untouched — tightening is truncation-equals-conditioning there, so a flag would be inert by
   the very law that licenses the optimization.
2. **Always bypass, no flag.** Keeps the spec's fixed `.sampling_report(n=1000, seed=None)`
   signature untouched. One canonical reading, nothing to test twice — but no way to ask "is my
   sampling actually cheap because of tightening," a question `acceptance_rate` alone doesn't
   answer once tightening is in play.
3. **Always tighten** (report what the sampler experiences). Rejected: on any space with a bound
   coupling this collapses the report's most informative rows to `satisfied ≈ 1.0`, hiding
   exactly the declared-measure hostility the surface exists to reveal.

### Answer

Possibility 1.

### Reasoning

Tightening is optimization, not semantics (the spec's own `may` and the tighten-not-reject
distributional-equivalence law say so) — so it belongs behind an opt-in switch on the one
surface that specifically wants the *un*optimized measure, not baked into either reading
unconditionally. The switch lives only on `sampling_report`, where it is meaningful; adding it
to the three samplers would be a knob with no observable effect, since there tightening only
ever changes speed, never the returned distribution.

### Specification update

Folded into API.md's `.sampling_report` signature (§Sampling and Generativity) and §Sampling
diagnostics.

## D-75 — `unflatten`'s static-count fallback vs. a present, disagreeing bookkeeping key

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §Config Utilities > "The fixed leaf layout"
- Decided by: Agent

### Question

"For a static count [`unflatten`] recovers the length from the `ListDomain` rather than
requiring the bookkeeping key" states the fallback for an *absent* count key. It does not say
what happens when the bookkeeping key is **present** but disagrees with the `ListDomain`'s own
declared static count (e.g. `flat = {"dropout": 2, "dropout[0]": ..., "dropout[1]": ...}` against
a `.repeat(3)` declaration) — does the present key win, or the declared static count?

### Why the specification is insufficient

The fixed-leaf-layout paragraph was written to justify `coordinate_paths()`'s existence (a flat
dict with *no* bookkeeping keys at all) and states only that direction. It never had reason to
address a flat dict carrying *both* signals at once.

### Possibilities considered

1. **Present key wins** (chosen). `unflatten` already treats every other bookkeeping/leaf key as
   authoritative when present (that is what "non-validating... walks whatever keys structurally
   match" means throughout Config Utilities); the static-count fallback exists solely to cover
   *absence*. A present key is `flatten`'s own realized length for that exact config — the more
   specific, more trustworthy signal — while the domain's static count is a resolution-time upper
   fact that says nothing about which config produced this particular flat dict.
2. **Declared static count wins.** Would make `unflatten` silently reject or truncate a
   `flatten()`-produced dict whose count happens to be pinned already (impossible in practice,
   since `flatten` only ever writes the true length) — solves no real case and contradicts
   `unflatten`'s established "trust present keys" posture everywhere else.
3. **Raise on disagreement.** Turns `unflatten` from non-validating into partially validating,
   a role `.validate()` already owns; API.md is explicit elsewhere that `flatten`/`unflatten`
   "walk whatever keys structurally match... and ignore the rest rather than raising."

### Answer

Possibility 1.

### Reasoning

Consistent with `unflatten`'s existing non-validating contract (a present key is always trusted)
and the narrowest reading of "static count... rather than requiring the bookkeeping key" — a
fallback for absence, not an override for presence.

### Specification update

Folded into API.md's "The fixed leaf layout" (§Config Utilities).

---

## D-76 — `ds.value`'s Unknown rule and the calling convention's exception boundary

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §Expressions > `ds.value`; rule 1 (Three-valued semantics)
- Decided by: User

### Question

Rule 1 states a `ds.value(...)` node "is Unknown iff any param its operands reference is
inactive." The `ds.value` paragraph separately states operands are ordinary expressions "so
`.if_inactive()` and any other coercion compose inside them." These disagree whenever an operand
itself guards its own inactivity: `ds.value(f, ds.param("x").if_inactive(0.0), returns=float)`
with `x` inactive — rule 1's literal wording (a param-activity scan over `.params`) says Unknown;
the composition promise says `f(0.0)`. Separately: what happens when `fn` itself raises?

### Why the specification is insufficient

Rule 1's clause was written to state the common case (no operand guards its own inactivity, so
both readings agree) and never anticipated the guarded case explicitly. Nothing in the spec
states whether `fn`'s own exceptions are caught or propagate.

### Possibilities considered

1. **Operand-*value* driven** (chosen). Evaluate each operand; the node is Unknown iff some
   operand *evaluates* Unknown (joining provenance per D-71), and `fn` is not called in that
   case. Coincides with rule 1's literal wording whenever no operand carries a guard; differs
   only in the guarded case, where it honors the composition promise instead.
2. **Literal activity scan.** Scan `node.params` (the union of every operand's referenced
   params) for inactivity, regardless of what the operands themselves evaluate to. Makes
   `.if_inactive()` inside an operand a silently useless no-op — exactly the failure mode the
   spec's own "over-declaring weakens silently" warning describes, just one level deeper.
3. **`fn`'s exceptions caught, degrading to Unknown** (mirroring `_evaluate_prop`'s defensive
   swallow for a malformed custom value). Rejected: `Prop`'s swallow is licensed by the
   custom-type contract law ("`extract` is called only on a value that passed `validate`");
   `fn` has no such contract, and "a function reading something it was not given raises rather
   than reading it silently" is the whole point of the calling convention. Swallowing would let
   a broken `fn` masquerade as legitimate Unknown-propagation.

### Answer

Possibility 1 for the Unknown rule; `fn`'s exceptions propagate uncaught (rejecting possibility
3 for that question).

### Reasoning

The operand-value reading is the only one under which every stated promise (rule 1's activity
clause, the composition promise, D-71's provenance guarantees) holds simultaneously. Letting
exceptions propagate keeps `ds.value` diagnosable — a user's bug in `fn` surfaces immediately at
the call site (`evaluate_constraints`/`validate`/`is_feasible`) rather than silently degrading
into a constraint that looks merely inapplicable.

### Specification update

Folded into API.md's rule 1 (§Three-valued semantics).

## D-77 — `on_unserializable="drop"` for an in-expression opaque site

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §to_json / from_json
- Decided by: User

### Question

`"drop"` is specified as writing "the space without those sites plus a manifest of omissions."
Every non-serializable site through M9 (an external `Prior`, a `.custom()` shorthand) is a whole
*domain* or *param* — removable as a field. A `ds.value` site is an expression *leaf*, nested
inside a constraint, a `.when()` condition, or a dynamic repeat count. There is no field to
omit — the enclosing constraint/condition/count would have to be removed *entirely*, or something
else has to happen.

### Why the specification is insufficient

The "without those sites" phrasing was written against the field-shaped case and never
considered a site nested inside a tree, where removal has different (and non-uniform)
consequences depending on position: dropping a constraint only weakens feasibility, but dropping
a `.when()` condition makes its param unconditional (an activity change) and dropping a dynamic
count has no sensible fallback at all.

### Possibilities considered

1. **Opaque marker in place, plus a manifest entry** (chosen). Same as `raise`/`mark`'s node-level
   handling, just also appending to the manifest — D-47's exact precedent, where `"drop"` on the
   `.custom(sampler, validator)` shorthand also degrades to the opaque marker rather than
   removing the whole param, because "a whole custom param has no serializable substance without
   its type." Uniform across all three positions a `ds.value` can occupy.
2. **Drop the whole enclosing constraint.** Matches "without those sites" more literally for the
   constraint case, but has no coherent answer for a `.when()` condition (removing it changes
   activity, not just feasibility) or a dynamic repeat count (removing it leaves no count at
   all) — not extensible to the other two positions.

### Answer

Possibility 1.

### Reasoning

D-47 already established the precedent that "drop" degrades to the mark sentinel wherever
removal has no coherent field-level meaning; a `ds.value` site is exactly that case for all
three of its legal positions, not just constraints. Uniformity across positions is worth more
than a closer literal match to "without those sites" for one position alone.

### Specification update

Folded into API.md's §to_json / from_json.

## D-78 — Row 30's comparison-type-mismatch clause

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md error table, row 30; row 16 (`.prop()`'s third clause)
- Decided by: User

### Question

Row 16 gives `.prop()` a third clause: "type mismatch in comparison" (strict, no int/float
leniency, per D-34's type-tagged-equality precedent). Row 30 as originally stated lists only
two `ds.value` clauses: non-scalar `returns`, and an operand that is not an expression. Should
`ds.value` get the same comparison check `.prop()` has, given the spec calls it "dual-typed the
same way" as `.prop()`?

### Why the specification is insufficient

The "dual-typed the same way" sentence is the only textual link between the two error surfaces;
it was written to establish the bare-boolean-usage parity, not to settle whether every one of
`.prop()`'s checks also applies to `ds.value`. Row 30 was drafted independently and simply never
enumerated a third clause.

### Possibilities considered

1. **No check — row 30 stays closed at two clauses.** Smallest surface; a mistyped comparison is
   a silently-always-False constraint, which `sampling_report`'s `satisfied` column would surface
   downstream. Argument against: it under-delivers on "dual-typed the same way," and leaves a
   real bug class (comparing a `returns=int` value against a string) with no dedicated error.
2. **Check, with int/float leniency.** Rejects genuinely incompatible pairs while letting an int
   literal compare against `returns=float` and vice versa (mirroring the runtime-equality rule,
   "`1 == 1.0`"). Catches more real bugs than option 1 without taxing `returns=float`'s literal
   comparisons, but introduces a third comparison-strictness rule distinct from both `.prop()`'s
   own (fully strict) and runtime equality's (numeric-lenient, bool-strict) — a new rule for a
   node that is supposed to be `.prop()`'s direct generalization.
3. **Strict, mirroring `.prop()` verbatim** (chosen). Exact Python type match, no leniency,
   identical message shape, added as row 30's third clause. Consistent with D-34's type-tagged-
   equality precedent and with `.prop()`'s own established behavior; the cost is rejecting
   `ds.value(f, ..., returns=float) <= 5` (an int literal against a float-declared value),
   which a space author must then spell as `5.0`.

### Answer

Possibility 3.

### Reasoning

Consistency with `.prop()` — the construct `ds.value` is explicitly generalizing — outweighs the
literal-comparison convenience option 2 would preserve; introducing a third, bespoke leniency
rule for the one node meant to unify with `.prop()`'s behavior would be the more surprising
outcome, not the less surprising one.

### Specification update

Folded into API.md's error table, row 30.

---

## D-79 — Row 32's `.prop()` half: strict, or capability-gated permissive?

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §The Representation Layer ("Path and arity"); error table row 32; §Protocols (`Encoding.prop_expr`)
- Decided by: User

### Question

Row 32, as folded from D-53, excludes a param from encoding unconditionally if a `.repeat()`
count or a `.prop()` reads it. `Encoding.prop_expr` exists specifically ("a phenotype property as
a genotype expression") to repair a `.prop()` reference structurally. Read literally, row 32 never
lets `prop_expr` fire — so should the `.prop()` half of the exclusion stay an unconditional error,
or open when the matched `Encoding` supplies `prop_expr`?

### Why the specification is insufficient

D-53 (path and arity) and D-63 (the repair obligation, "`prop_expr` is what makes a bridge
buildable at all rather than merely conceivable") were resolved in the same spec pass but pull in
opposite directions on this one point, and neither entry reconciles the other. The folded API.md
text inherited D-53's unconditional wording, silently overriding D-63's own stated purpose for
`prop_expr` — an oversight of the fold, not a deliberate re-decision.

### Possibilities considered

1. **Strict — row 32 fires unconditionally**, matching the folded text verbatim. Never weakens a
   stated law, but makes `prop_expr` permanently dead code: no future milestone calls it, and the
   one motivating case the spec names — bridging a custom type that declares properties into a
   genotype — becomes impossible for any such type.
2. **Permissive, capability-gated** (chosen): a `.prop()`-read param may be encoded iff its matched
   `Encoding` supplies `prop_expr()`, which then rewrites every such reference structurally; row 32
   still raises, naming the path and property, when the capability is absent. The `.repeat()`-count
   half of the exclusion stays unconditional regardless (see D-80) — the two halves are not
   symmetric.
3. **Permissive with an opaque fallback** — encode a `.prop()`-read param unconditionally, using
   `prop_expr` when supplied and otherwise transporting the containing constraint opaquely. Rejected:
   opaque transport already exists for expressions the encoding's author did not anticipate; using
   it here would silently downgrade every unrepaired `.prop()` site to rejection-only quality
   instead of failing loudly, which guts row 32 far more broadly than the capability check does.

### Answer

Possibility 2.

### Reasoning

`.repeat()` counts and `.prop()` reads are excluded for different reasons, and only one of them
generalizes. A count is structural: transport rewrites conditions, `ParamDef.condition`,
constraints, and `ListDomain.element_constraints` — deliberately not `ListDomain.count` — so an
encoded count-read param's count expression would silently change what the count means, with no
protocol capability able to repair it (inventing one would perturb the integer-valued repeat-count
calculus, D-72, the sampler's count resolution, `has_variable_length`, and `cardinality`). A
`.prop()` read is a *value* dependency with a purpose-built repair already in the protocol; refusing
to use it defeats the reason `prop_expr` was added at all (D-63).

### Specification update

API.md error table row 32 (reworded); "Path and arity" section (the `.prop()` clause).

---

## D-80 — `check()`'s report shape

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §The Representation Layer; §IR (`Representation.check`)
- Decided by: Agent

### Question

API.md's illustrative `Representation` listing elides `check()`'s return type
(`def check(self, n=200, seed=None) -> ...`). What should it return?

### Why the specification is insufficient

"The suite as a tool, since a supplied morphism has no other way to be shown sound" states the
purpose but not the shape; nothing else in the spec constrains it.

### Possibilities considered

1. **Return `None`, raise on the first law violation.** Smallest surface, and matches the literal
   verb "asserts the conformance laws." Stops at the first failure, giving a supplied morphism's
   author no inventory of what else is wrong — the opposite of a diagnostic tool.
2. **A tuple of failure strings.** No new dataclass, but unstructured text carries no law identity
   or machine-readable path, and every other diagnostic surface in this library (`ValidationResult`,
   `SamplingReport`, `PartialEval`) is a typed dataclass, not a string list.
3. **A frozen report dataclass** (chosen): `RepresentationCheck(n, ok, failures)`, with
   `RepresentationCheckFailure(law, detail, count)` deduped by `(law, detail)` across the sampled
   draws. Never raises on a violation.

### Answer

Possibility 3.

### Reasoning

Matches the established pattern this library already uses everywhere else a multi-faceted result
needs reporting instead of raising. `RepresentationCheck` covers the laws a supplied morphism can
meaningfully violate — decode totality, feasibility agreement, and (when invertible) the
round-trip — deliberately not the structural laws (path/arity), which the derived tier guarantees
by construction and the supplied tier has no comparable law to check at all.

### Specification update

API.md's `Representation`/IR listing (`check`'s return type; `RepresentationCheck`/
`RepresentationCheckFailure` added to the IR).

---

## D-81 — `Representation`'s `decode`/`encode`: stored callables, not delegating methods

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §IR (`Representation`)
- Decided by: Agent

### Question

API.md's illustrative listing shows `decode`/`encode` as instance methods (`def decode(self,
genotype: dict) -> dict: ...`). The **supplied** tier's own constructor call is
`Representation(source=…, target=…, decode=…, encode=None)` — passing `decode`/`encode` as
constructor arguments. A frozen dataclass cannot have both a field and a same-named method (the
`def` statement overwrites the field), so which is it?

### Why the specification is insufficient

The spec shows both shapes (methods in the class body, keyword arguments at the call site) without
reconciling them; this is an implementation-mechanism question the illustrative listing was never
precise enough to settle.

### Possibilities considered

1. **Fields storing callables, called directly** (chosen): `rep.decode(g)` invokes the stored
   function object; there is no separate `Representation.decode` method to collide with it.
2. **A private-suffixed field plus a public delegating method** (the pattern this codebase already
   uses for `ParamExpr.meta_map`/`.meta()` and `Space.meta_map`/`.meta()`). Works, but the
   constructor would then need `_decode_fn=`/`_encode_fn=` keywords, breaking the spec's own
   illustrative constructor call verbatim.

### Answer

Possibility 1. `__post_init__` derives `invertible` from whether `encode` was supplied and, when it
was not, replaces the stored `None` with a callable that raises a message naming why — so
`rep.encode` is always callable and "raises unless invertible" produces a real message rather than
`NoneType is not callable`.

### Reasoning

Possibility 1 is what makes the spec's own supplied-tier constructor call type-check exactly as
written; possibility 2 would require silently deviating from it. `then`'s composition and `check`'s
sampling both call `self.decode`/`self.encode` the same way regardless, so nothing downstream
depends on which mechanism is chosen — only the constructor's own keyword names do.

### Specification update

None — an implementation-mechanism clarification, not a behavior change; recorded per CLAUDE.md
because it resolves an apparent internal inconsistency in the illustrative listing.

---

## D-82 — Opaque transport's dynamic-lift boundary

- Status: Resolved
- Date: 2026-07-31
- Spec section: API.md §The Representation Layer ("Transport"); §Expressions (`ds.value`)
- Decided by: Agent

### Question

"Core can always [synthesize the opaque leaf], knowing both `decode` and the source AST, so
transport is total." `ds.value`'s own operands must each be a scalar-evaluable expression (M10.8) —
enumerable into one operand per instance for a lift under a *static* count, but not for a *dynamic*
one, where no fixed operand list exists at resolution time. Does "transport is total" hold through
this case, and if not, what happens?

### Why the specification is insufficient

The totality claim was written when opaque transport was designed (D-54), reasoning only from what
core *knows* (decode, the source AST) — not from `ds.value`'s own construction-time constraint on
its operands, which predates M11 (M10.8) and was not re-examined against it.

### Possibilities considered

1. **Widen `ds.value` to accept a vector operand.** Would restore totality, but contradicts D-66
   ("the expression language is closed at two nodes") and reopens a boundary settled for unrelated
   reasons — the fix does not belong to this problem.
2. **Silently fall back to a weaker transport** (e.g. drop the constraint, or approximate it).
   Rejected outright — D-54 already establishes that dropping breaks feasibility agreement and
   over-activates the target; silent narrowing is worse than a loud failure.
3. **Raise, naming the param and the remedy** (chosen): unreachable for the induced chart
   representation (`decode_expr` always succeeds, so opaque transport is never invoked at all);
   reachable only through a user-supplied `Encoding` that supplies neither `decode_expr` nor
   `rewrite` for a dynamic-count lift a condition or constraint touches.

### Answer

Possibility 3. "Transport is total" holds over every representation `represent()` successfully
builds; the dynamic-lift case is a build-time error rather than a silently-unsound one.

### Reasoning

Feasibility agreement is a property of representations that exist; a representation `represent()`
refuses to build cannot violate it. Raising loudly, at the point the boundary is actually hit, keeps
that property true without inventing new expression-language surface or silently degrading
correctness — consistent with how every other row-31/32 violation in this milestone is handled.

### Specification update

API.md §The Representation Layer ("Transport") — the boundary noted where "transport is total" is
stated; the Representation conformance bullet reworded to scope feasibility agreement to
representations that build successfully.

---

## D-83 — The `.symbolic()` AST encoding, core's validation depth, and no evaluator

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Parameter Types > "Program"; §Support Types
- Decided by: User

### Question

`.symbolic()`'s value is `{"ast": ..., "source": str}`, but API.md never defines what `ast` is —
no node grammar, no statement of what core checks against `max_depth`/`primitives`/`FloatLiteral`/
`IntLiteral`. Does core define and check a concrete AST shape, or is `ast` an opaque JSON blob core
only requires to be present and validator-approved? And does core ship an evaluator for the built-in
primitive vocabulary the table names?

### Why the specification is insufficient

Tree/program generation is explicitly Out of Scope, but the spec still lists `max_depth`, a
`primitives` vocabulary, and `FloatLiteral`/`IntLiteral` as declared facts about a `.symbolic()`
param — facts that mean nothing unless *something* checks a submitted tree against them. The spec
never says what that something is, nor whether it is core or entirely the caller's `validators`.

### Possibilities considered

1. **Core-defined, core-checked AST (chosen).** A concrete JSON node grammar
   (`{"op", "args"}` / `{"var"}` / `{"const"}`); core structurally validates a value against the
   declaration before any user `validators` run.
2. **Opaque AST, validators only.** Core requires only the two keys and JSON-serializability;
   `max_depth`/`primitives`/`FloatLiteral`/`IntLiteral` become declared-but-unenforced metadata.
   Smallest surface, but then `.symbolic()` differs from `.code()` only in value shape — nothing
   distinguishes "structured expression tree" from "freeform source" in what core actually checks.
3. **Ship an evaluator** alongside the AST checker (`ds.evaluate_symbolic(value, **args)`),
   implementing the built-in primitives and dispatching to `Primitive.fn` for user-defined ones.

### Answer

Possibility 1 for the AST; possibility 3 rejected — no evaluator ships.

### Reasoning

Possibility 1 is what makes `max_depth`/`primitives`/the literal types mean anything: without a
core-checked grammar they are declared and serialized but never enforced, silently contradicting
the "declares the space, validates against it" framing the rest of the type system follows (custom,
choice, subset all validate a submitted value against their declaration). No evaluator: `API.md`'s
own Out-of-Scope list already excludes "tree/program generation strategy for `.symbolic()`" and
"LLM backends for `.code()`" — an evaluator is the missing third leg of the same boundary (structure
without semantics), and shipping one would require deciding numeric edge-case semantics (division by
zero, log of a non-positive) the spec never states, for a language it does not otherwise touch.

### Specification update

API.md §Parameter Types > "Program" gains the node grammar, the validation rules (vocabulary, arity
iff declared — see D-89 — variable names, literal bounds, depth), and an explicit "no evaluator"
statement.

---

## D-84 — `.symbolic()`/`.code()` value shape

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Parameter Types > "Program"
- Decided by: Agent

### Question

Given D-83's node grammar, what exactly is the value dict's shape — is `"source"` required for
`.symbolic()`, and is it ever cross-checked against `"ast"`?

### Why the specification is insufficient

The table's `{"ast", "source"}` column notation doesn't say which keys are required, nor whether
`"source"` must agree with `"ast"` (core owns no printer/parser to check that against).

### Possibilities considered

1. **`"source"` optional, never cross-checked** (chosen) — a str when present, purely a
   human-readable rendering the author supplies.
2. **`"source"` required, unchecked.** Forces every symbolic value to carry a string even when
   nothing consumes it (no printer exists to require one).
3. **Cross-check `source` against `ast`.** Requires core to own a parser/printer for whatever
   surface syntax `source` is written in — direct scope creep past "no evaluator" (D-83).

### Answer

Possibility 1. `.code()`'s value is `{"source": <str>}`, `"source"` required (it is the entire
value there — nothing else exists to hold the definition).

### Reasoning

`"source"` is documentation for a human or an LLM backend reading the space, not load-bearing data
core validates against anything — optional-and-unchecked is the only reading consistent with "core
owns no printer/parser." `.code()`'s value has no second field, so its one key is naturally required.

### Specification update

API.md §Parameter Types > "Program" states the value shapes explicitly.

---

## D-85 — `.code()`'s `description`/`constraints`/`examples`

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Parameter Types > "Program"
- Decided by: Agent

### Question

`.code(signature, description="", constraints=None, examples=None, validators=None)` lists three
parameters (`description`, `constraints`, `examples`) API.md never explains anywhere else. What are
they for, and does core do anything with them beyond storing them?

### Why the specification is insufficient

No prose anywhere in API.md describes these three parameters' purpose or constraints.

### Possibilities considered

1. **Declared, serialized, fingerprinted metadata for a consumer's backend** (chosen) — core stores
   and round-trips them, never interprets them (an LLM backend is Out of Scope).
2. **Core validates against them** (e.g., checks `source` against `constraints` as executable
   rules). Rejected — this is exactly the "no evaluator" boundary D-83 draws; `constraints` here are
   natural-language/backend-specific hints, not a core-checkable predicate language.

### Answer

Possibility 1. `examples` entries must be JSON-serializable (row 23's existing rule, reused
verbatim — the same bar `.meta()` values clear).

### Reasoning

Consistent with `.symbolic()`'s own `validators`/`sampler` treatment: core's job stops at structural
declaration and value validation, never semantic interpretation of a backend's own convention.

### Specification update

API.md §Parameter Types > "Program" describes all three as consumer-facing metadata.

---

## D-86 — `Signature` normalization

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Support Types
- Decided by: Agent

### Question

`ds.Signature(args: dict[str, type | str], returns: type | str)` accepts either a Python `type` or a
bare string per argument. How is this stored so the fingerprint preimage stays canonical and the
support type carries no unserializable object?

### Why the specification is insufficient

The signature's own `type | str` union is stated; nothing says whether a `type` is normalized at
construction or carried as-is (which would make `Signature` itself non-serializable whenever a
caller passes `int`/`float`/`bool` directly).

### Possibilities considered

1. **Normalize at construction to `type.__name__`** (chosen) — `args`/`returns` are plain strings
   from the moment a `Signature` exists; argument order is preserved (`MappingProxyType` over an
   insertion-ordered dict).
2. **Carry the raw `type | str` union, normalize only at encode time.** Leaves a `Signature` object
   holding a `type` object between construction and serialization — an unnecessary latent
   unserializable state for a value meant to be fully structural.

### Answer

Possibility 1.

### Reasoning

A `type | str` union has exactly one serializable representation (the name), so normalizing
immediately removes an entire class of "encode-time surprise" and matches how every other support
type in the codebase (`Log`, `Power`, `Weights`) carries only serializable fields from construction.

### Specification update

API.md §Support Types states the normalization and that argument order is meaningful and preserved.

---

## D-87 — `.freeze()`/`.slice()` on a program param

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Space — Structural Operations
- Decided by: Agent

### Question

The `.freeze`/`.slice` per-kind mechanism paragraph enumerates real/integer/categorical/ordinal/
bool/custom but predates program types. Does a `.symbolic()`/`.code()` param freeze like a custom
(with the same shorthand exception), and does `.slice()` support it?

### Why the specification is insufficient

Program types didn't exist when that paragraph was written; nothing says which existing mechanism,
if any, extends to them.

### Possibilities considered

1. **Mirror `_pin_custom` exactly, no shorthand exception** (chosen) — `require(p == value)` plus
   `default = value`; `.slice()` supported unconditionally.
2. **Reject freeze entirely**, treating a program param like the five M9.5 container kinds needing
   dedicated per-kind machinery. Rejected — a program value is an ordinary JSON dict; there is
   nothing structurally special about it that the existing opaque-pin mechanism doesn't already
   handle.
3. **Mirror custom including the shorthand rejection.** There is no shorthand form for
   `.symbolic()`/`.code()` at all (no `to_json`-less callback path), so this possibility doesn't
   actually apply — every program value is unconditionally comparable and serializable.

### Answer

Possibility 1. `.slice()`'s custom-only rejection is grounded specifically in `.prop()` ("no
substitution target for a `.prop()` expression's operand") — no program param supports `.prop()`,
so the obstruction never arises and `.slice()` needs no new code at all.

### Reasoning

Reusing `_pin_custom`'s exact mechanism needs zero new machinery beyond a dispatch branch, and a
program value's always-plain-JSON-dict nature means the one exception custom needs (the shorthand
has no serializable form) simply doesn't exist here.

### Specification update

API.md's `.freeze`'s per-kind mechanism paragraph and the `.slice()` custom-rejection sentence both
gain a program-type clause.

---

## D-88 — Per-field opacity for `validators`/`sampler`/`Primitive.fn`

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Identity and Serialization (non-serializable set)
- Decided by: Agent

### Question

The non-serializable set already names `code`/`symbolic` `validators`, `symbolic` `sampler`, and
`Primitive.fn` (anticipated at M10.8). Given a `.symbolic()`/`.code()` domain is otherwise fully
structural (`signature`, `primitives`' names/arities, `max_depth`, `description`/`constraints`/
`examples` all serialize plainly), does raise/mark/drop poison the *whole* domain the way the
`.custom(sampler, validator)` shorthand does, or degrade only the opaque field?

### Why the specification is insufficient

Every prior opacity precedent (`.custom(sampler, validator)`, an external `Prior`) poisons an entire
domain/field that has *no* structural content without the opaque part. A `.symbolic()`/`.code()`
domain is different: it has substantial structural content even when `validators`/`sampler`/`fn` are
present, so the existing precedent doesn't settle whether opacity should be whole-domain or per-field.

### Possibilities considered

1. **Per-field opacity, in place** (chosen) — each of the three fields independently rides raise/
   mark/drop; the rest of the domain (and, for `Primitive.fn`, the rest of that one primitive entry)
   always serializes.
2. **Whole-domain opacity**, matching `.custom(sampler, validator)` exactly — any one opaque field
   present degrades the entire `.symbolic()`/`.code()` domain to the marker sentinel.

### Answer

Possibility 1, generalizing the precedent D-77 already set for a `ds.value` site: "one opaque leaf
inside an otherwise-structural tree degrades in place" — here the tree is a domain instead of an
expression, but the principle is the same.

### Reasoning

Whole-domain opacity would silently discard a program param's entire declaration (signature,
vocabulary, depth budget) just because it also happens to carry a validator — a much larger loss of
information than the custom shorthand's poisoning, which has no structural content to lose in the
first place. Per-field opacity preserves everything serializable and only marks what genuinely isn't.

### Specification update

API.md's non-serializable-set paragraph gains a sentence distinguishing this per-field precedent
from the whole-domain one.

---

## D-89 — Arity binds only where declared; `Primitive.arity` accepts a range

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Support Types (`ds.Primitive`)
- Decided by: User

### Question

A tree node `{"op": "+", "args": [...]}` can only be arity-checked if core knows `+`'s arity — but
API.md never states one for any built-in name, and `ds.Primitive(name, arity, fn=None)`'s `arity`
reads as a single int. Does core assign an arity to a built-in name, and can an author declare a
variadic or unary-or-binary primitive at all?

### Why the specification is insufficient

The built-in list (before D-90 dropped it) fixed names only, never arities; arity-checking a bare
built-in string would require core to invent a fact the spec never states, for a vocabulary an
author can already extend via `ds.Primitive`. Separately, `arity: int` cannot express "two or more"
or "one or two" — real tree-language operators (`+`, `-`) commonly need exactly that.

### Possibilities considered

1. **Core assumes no arity for a bare string; `Primitive.arity` widened to `int | (int, int|None)`**
   (chosen) — arity is checked exactly where an author wrote it, and a range expresses variadic/
   flexible operators.
2. **Core ships a fixed built-in arity table.** Rejected in the same exchange that produced D-90 —
   requires inventing three more facts the spec is silent on (is `-` unary-capable? are `min`/`max`
   variadic? does a `Primitive` shadowing a built-in override or conflict?), compounding rather than
   resolving the underlying problem.
3. **Arity-check nothing, ever — even a declared `Primitive`.** Simplest, but leaves
   `Primitive.arity` unused by core, contradicting the method's own listed purpose.

### Answer

Possibility 1.

### Reasoning

The user's framing throughout this exchange was consistent: core should assume nothing it isn't
told. A bare string is genuinely untold information (no arity was ever declared for it); a
`ds.Primitive` is exactly where an author tells core the arity, so that is exactly where core should
check it — and checking it precisely requires the range form, since an exact int cannot express a
variadic or flexible operator at all.

### Specification update

API.md §Parameter Types > "Program" and §Support Types both state: a bare string carries no arity;
`ds.Primitive.arity` is `int | tuple[int, int | None]`; an int and its `(n, n)` spelling are
fingerprint-equal.

---

## D-90 — The built-in primitive set is dropped; row 15 is rewritten

- Status: Resolved
- Date: 2026-08-01
- Spec section: API.md §Parameter Types > "Program"; §Support Types; Error table row 15
- Decided by: User

### Question

Once D-89 settles that core assigns no arity to a bare built-in string, does the fixed built-in name
list (`+ - * / ** % abs min max cos sin exp log pi e`) still serve a purpose? If not, should it be
dropped — and this is a **stated law** (row 15, "Unknown `.symbolic()` primitive"), so dropping it is
a deliberate change to normative text, not a routine implementation gap.

### Why the specification is insufficient

This is not a case of the specification being silent — API.md stated the list and row 15's rejection
plainly. The question raised, directly by the user, was whether that stated law should itself
change, once its only surviving justification (typo-catching) was weighed against what it costs.

### Possibilities considered

1. **Keep the closed list.** Row 15 stands as written; a name outside the 15 requires
   `ds.Primitive(name, arity)`. Preserves typo-catching for a bare string; costs one `Primitive(...)`
   call per non-listed operator, and the list's own 15 names are an arbitrary, incomplete snapshot
   (no `sqrt`, `tan`, `floor`, `where`, no comparisons) that constrains nothing real once arity is
   author-declared anyway.
2. **Drop the fence entirely — any non-empty string names a primitive** (chosen by the user). Row 15
   is repurposed to the declaration checks that survive (duplicate name, malformed arity, bad
   `max_depth`, bad literal bounds, bad signature arg name); a `Primitive` may still shadow a common
   name (that is how its arity gets pinned).
3. **Keep the list, widen its contents** to cover more real-world operators. Rejected by the user —
   still an arbitrary, incomplete vocabulary, and cuts against the direction of D-89.

### Answer

Possibility 2, explicitly chosen by the user over the agent's recommended possibility 1.

### Reasoning

Once arity carries no meaning at the built-in-name level, a closed list constrains nothing a
`ds.Primitive` declaration couldn't already extend past, its contents are demonstrably incomplete
for real symbolic-regression/tree-search vocabularies, and its only remaining function — catching a
typo in a bare string — is a narrow benefit purchased at the cost of an arbitrary ceiling on
`.symbolic()`'s expressiveness. Vocabulary checking is not eliminated, only relocated: a tree's `op`
must still be a name the param declared (D-83's AST check), so `{"op": "cos"}` against
`primitives=["cso"]` is still invalid — only the *declaration-time* membership fence is gone.

### Specification update

API.md §Parameter Types > "Program" drops the built-in-list sentence entirely; error table row 15 is
rewritten from "Unknown `.symbolic()` primitive" to the surviving declaration-hygiene checks.

---

## Entry template

Copy this template for each genuine specification gap.

```markdown
## D-73 — Short title

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

_Ledger tail._ D-1 through D-70 were resolved into `API.md` and their entries removed here
(preserved in git history). D-71 through D-82 (M10.5, M10.6, M10.7, M10.8, M11) are resolved above
and will fold out on the next spec pass; continue with D-83.
