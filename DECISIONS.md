# Decisions

Record here every point where API_v3.md was ambiguous or silent, or conflicted with IMPLEMENTATION_PLAN.md. Never resolve such a point silently in code.

Entry format:

```
## D-<n> (M<milestone>) — <short title>
Question:   what the spec leaves open, with section reference
Options:    the plausible readings considered
Choice:     what was implemented, and why it is the least-surprising reading
            consistent with the Design Principles and Representation Model
Spec delta: suggested wording fix for API_v3.md, if any
```

## D-1 (M0) — `implies()` representation before resolution

Question:   API_v3.md's Expressions section glosses `expr.implies(other)` as
            "sugar for `~expr | other`" (a comment, not a construction rule),
            which could mean the operator builds `~expr | other` immediately
            and no `Implies` node ever exists. But the Resolution section
            lists "`log_scale`, `implies`, layer folding" together under a
            single desugaring pass (step 3), and the Conformance Laws section
            groups `implies` with `log_scale`/prior, variadic `.repeat`, and
            expression bounds as a "sugar-equivalence pair" checked at
            resolution — all three of those are cases where the sugared
            spelling is preserved as its own construct through construction
            and only rewritten during resolution. The spec does not say which
            reading governs `implies` specifically.
Options:    (a) `.implies(other)` immediately constructs `Not(expr) |
            other` at call time — no distinct node kind ever exists.
            (b) `.implies(other)` builds a distinct `Implies(left, right)`
            BoolExpr node, preserved through construction; resolution's
            desugar pass (M1+) rewrites it to the `~expr | other` shape for
            introspection/fingerprint purposes.
Choice:     (b). Consistent with the Resolution section explicitly listing
            `implies` as something resolution desugars (redundant under (a),
            since there would be nothing left to desugar), and with treating
            it the same way as the other three named sugar-equivalence pairs,
            all of which stay inspectable as what the author wrote until
            resolution normalizes them. This also matches "everything is
            data, and everything is constructible" — `.kind == "implies"` is
            more informative to a reader/rewriter than an already-expanded
            `Not`/`BoolOp` pair. M0 implements only the `Implies` node and the
            `.implies()` constructor (designspace.expr.Implies); the
            resolution-time rewrite into `~expr | other` is M1+'s desugar
            pass, not yet implemented.
Spec delta: API_v3.md could state explicitly, next to the `implies` line in
            Expressions, that it constructs a dedicated node desugared at
            resolution (mirroring the parenthetical already present for
            `log_scale`'s relation to `.prior(ds.Log())`).

## D-2 (M1) — Where `quantized` and categorical/ordinal/bool weights live in ParamDef

Question:   API_v3.md's `ParamDef` dataclass listing (section "IR") has no
            field for `.quantized()`'s step/factor/include_hi, and no
            separate field for `.prior(weights=...)` — only a single
            `prior: Prior | None`. But "Modifiers and Layering" documents
            both as real, distinctly-named, LWW modifiers that must survive
            resolution to be inspectable (`.params -> dict[str, ParamDef]`),
            and M1's Build line explicitly requires "duplicate-modifier
            rules (LWW vs accumulate)" for exactly these two. The spec does
            not say whether the illustrative ParamDef block is exhaustive or
            whether these two are meant to be folded into `domain`/`prior`.
Options:    (a) Treat the listing as exhaustive: fold quantized's spec into
            `domain` (a "quantized real" is a different Domain shape) and
            leave weights unrepresentable until charts (M2) give them a home.
            (b) Add a dedicated `quantized: QuantizedSpec | None` field, and
            store weights as a `Weights` payload in the *existing* `prior`
            slot (no separate `weights` field, since the spec shows only one
            slot for anything prior-shaped and the Modifiers table already
            names weights a sub-case of `.prior()`).
Choice:     (b). The single `prior` field is a strong, direct signal — the
            spec never has two `.prior(...)`-populated fields — so weights
            share it via a `Weights(values)` marker (`ir/_priors.py`),
            checked with `isinstance` wherever prior vs. weights matters.
            `quantized` gets its own field since it has no other named slot
            to share and folding a grid spec into `Domain` would blur the
            "domain = declared value space" / "chart = how it's sampled"
            split the spec draws everywhere else (Charts: "an integer param
            *is* a quantized real"). `ParamDef.chart` stays `None` in M1
            either way — nothing here depends on chart construction (M2).
Spec delta: API_v3.md's ParamDef listing could add `quantized: QuantizedSpec
            | None` and note that `Weights` values occupy the `prior` slot.

## D-3 (M1) — Scope of "error-table rows applicable to flat scalars"

Question:   IMPLEMENTATION_PLAN.md's M1 gate says to test "every implemented
            error-table row" but scopes M1 itself to only "rows applicable
            to flat scalars" without enumerating which those are. Several
            rows are scalar-shaped in the table's wording but depend on
            machinery M1 explicitly excludes (charts, step 6; `.forbid()`/
            `.constrain()`, which IMPLEMENTATION_PLAN's M2 line — not M1's —
            lists under "Constraints and Feasibility").
Options:    Implement only the rows checkable without charts or constraints,
            or pull forward pieces of M2 to cover more rows now.
Choice:     Implemented in M1: rows 1, 2, 3, 4, 5, 6 (conditions only —
            constraint/bound references don't exist yet), 7 (condition
            cycles only), 8, 10, 11, 14, 17, 21 (scalar defaults only), 23
            (tags/non-JSON meta; `describe()` is M9). Deferred: row 9
            (Log/Logit/Power domain checks — needs chart construction, M2),
            12-13 (repeat, M4), 15-16 (symbolic/prop, M12/M9), 18 (subset/
            permutation, M3), 19-20 (external priors/bound hulls, M2/M5), 22
            (anchors — under "Constraints and Feasibility", M2), 24 (lifts,
            M4), 25 (continuous-`==` warning — scoped to `.constrain()`
            predicates by its own spec wording, M2), 26-27 (sampling/
            from_json, M2/M7). Also broadened two rows beyond their literal
            error-table wording, both implemented and tested now: row 11
            covers a modifier applied to a type it doesn't apply to (e.g.
            `.prior(weights=...)` on a real), not just repeat-ordering
            (`.repeat()` doesn't exist yet to collide with anyway); row 14
            covers rejecting `>`/`<`/`>=`/`<=` on categoricals, which the
            Expressions section states in prose ("Categoricals: ==, !=,
            is_in() only") but the error table never assigns a row number.
Spec delta: The error table could tag rows with which spec section's
            machinery they depend on, so "applicable to flat scalars" is
            derivable instead of judgment-called per milestone.

## D-4 (M2) — `ConstraintEval.satisfied`/`margin` polarity for `.forbid()`

Question:   API_v3.md's Margins section gives a structural table (`a <= b`
            -> `b - a`, etc.) with no separate row or note for how it
            applies differently under `.forbid()` vs `.constrain()`, and
            never states explicitly what `ConstraintEval.satisfied` means
            for a forbidden predicate. A forbid's expression names the
            *forbidden* (bad) state (`.forbid(ds.param("lr") > 0.1)` — bad
            when true) while a declared constraint's expression names the
            *desired* (good) state (`.constrain(sum <= 4096)` — good when
            true); the spec doesn't say whether `Constraint.expr`/`margin`/
            `satisfied` are stored/computed relative to "the literal
            predicate" or "feasibility" (i.e. silently negated for forbids
            so `satisfied`/positive-margin always mean "good").
Options:    (a) Store `Constraint.expr` exactly as written for both
            `.forbid()` and `.constrain()`; `satisfied` = the stored expr's
            raw Kleene truth value; margin is computed structurally off
            that same stored expr with no hard/soft awareness anywhere.
            Feasibility is then a separate, one-line derived rule.
            (b) Silently store `~expr` for `.forbid()` conditions instead
            of what the user wrote, so `satisfied`/margin are always
            "good-means-positive" regardless of hard/soft.
Choice:     (a). Two things force it: first, the M2 conformance gate's
            "composition preserves the satisfaction invariant" law is
            tested with hypothesis-generated random `BoolExpr` trees with
            no forbid/constrain wrapper at all — margin has to be a pure
            structural property of the expression shape for that test to
            even be well-formed. Second, introspection/fingerprint fidelity
            requires `Constraint.expr` to be exactly what the author wrote
            (`.constraints[i].expr` shown via `.kind`/`.children`, and the
            "no algebraic normalization of expressions is attempted"
            principle) — (b) would mean a forbid's introspectable
            expression silently differs from its declaration.
            Feasibility is then derived with the one polarity-aware rule
            `is_violated(ce) := ce.applicable and ce.satisfied == ce.constraint.hard`
            (eval/_constraint_eval.py): a forbid violates when its (bad)
            predicate is true; a declared constraint is flagged when its
            (good) predicate is false. This was caught as a live bug during
            implementation (the sampler was accepting forbidden draws and
            rejecting safe ones) before any conformance test existed for
            it — the margin/Kleene-table/count-range conformance suite was
            written immediately after to pin this down going forward.
Spec delta: API_v3.md's Margins section could state explicitly that the
            table is computed on `Constraint.expr` as declared (not
            negated for forbids), and give the one-line feasibility rule
            (`violated iff satisfied == hard`) next to "Feasibility is
            defined by param validity plus forbids only."

## D-5 (M2) — `.anchor()` and space-level `.meta()` stay out of M2

Question:   API_v3.md's "Constraints and Feasibility" table lists
            `.forbid()`, `.constrain()`, `.anchor()`, and `.meta()` together
            as four Space-level methods, with no per-method milestone
            marker. D-3 (M1) had guessed row 22 (anchors) belonged to M2
            since it sits in that section, but IMPLEMENTATION_PLAN.md's M2
            Build line names only "charts/ ... eval/ ... validate/ ...
            sample/" — no mention of anchors or space-level meta — and
            neither the M2 gate nor the `flat_hpo` corpus fixture exercises
            either.
Options:    (a) Implement `.anchor()` and space-level `.meta()` now, since
            they're textually adjacent to `.forbid()`/`.constrain()`.
            (b) Defer both; implement only what the Build line and gate
            actually require (`.forbid()`/`.constrain()`).
Choice:     (b). The plan's per-milestone Build line is the more specific,
            more authoritative signal than a section's table grouping —
            row 22 and `.meta()` will land whenever a later milestone's
            Build line or gate first needs them (anchors require validating
            a whole config against the space, which is exactly what this
            milestone's `validate()` newly makes possible, so the
            groundwork isn't wasted). This supersedes D-3's forward guess.
Spec delta: None — this is a plan-sequencing question, not a spec gap.

## D-6 (M2) — Chart-construction edge cases the spec states informally

Question:   Several chart-building details are given as prose/formula
            without a fully worked edge case: (1) `to_unit` at the `lo ==
            hi` degenerate constant chart has no stated value; (2) `Power`'s
            "domain valid for `p`" isn't spelled out (which `p`/`lo`
            combinations are legal, and how to root a possibly-negative
            interior value back through `1/p`); (3) the geometric
            (`factor`) quantization grid's degenerate condition is only
            given for the linear (`step`) case ("step >= hi-lo"); (4) when
            `include_hi` appends `hi` as an extra grid point, its own cell
            width (needed to close the chart's extension interval) isn't
            named; (5) chart-family domain requirements ("checked against
            the envelope") vs. the wider bound actually used to build the
            math for integers (`hi+1`) and quantized reals (the grid
            extension) — the spec doesn't say the domain check uses the
            narrower, declared bound while the math uses the wider one.
Options:    Each has multiple locally-plausible answers; see
            charts/_builtin.py, charts/_grid.py, charts/_build.py docstrings
            and inline comments for the specific reasoning at each site.
Choice:     (1) `to_unit` returns `0.0` at the degenerate point (arbitrary
            but harmless — nothing observable depends on it since
            `from_unit` always returns the single legal value regardless of
            `u`). (2) `p == 0` rejected; non-integer `p` requires `lo >= 0`
            (fractional powers of negatives are undefined in the reals);
            negative `p` requires `lo > 0` (avoids a pole at zero); the
            forward direction roots a possibly-negative interior value via
            a signed `copysign`-style root, applied unconditionally since
            it's a no-op when the interior is already non-negative. (3) the
            multiplicative analogue `factor >= hi/lo` (mirrors "one step
            already reaches or exceeds hi"). (4) the appended point gets
            the same local-spacing formula as a regular point one step
            further out (`step`, or `hi*(factor-1)`), not a width derived
            from its distance to the previous point — keeps one formula
            everywhere instead of a special case. (5) domain-requirement
            checks (rows 9/19) always use the declared `(lo, hi)`; the
            actual continuous-chart math is built over whatever wider bound
            applies (`hi+1` for integers, the grid extension for
            quantized) — this is forced by row 9/19 explicitly saying
            "envelope"/"declared bounds", which don't move under
            quantization.
Spec delta: Each of these five could be pinned down explicitly next to its
            existing prose in the Charts section.

## D-7 (M2) — `==`/`!=` evaluation semantics: numeric vs. type-tagged

Question:   API_v3.md's fingerprint canonicalization explicitly type-tags
            `Any`-typed values (`categorical(1, 2) != categorical(1.0,
            2.0)`), but never states whether *runtime* `Compare` evaluation
            (Kleene `==`/`!=`, and `.is_in()` membership) uses that same
            type-tagged equality or plain value equality. Plain Python `==`
            treats `1 == 1.0` as `True` (desirable for real/integer
            domains, where the distinction is never meaningful) but also
            `True == 1` (undesirable — `bool` is declared "strict" for
            domain membership, and letting it leak into comparisons would
            contradict that).
Options:    (a) Type-tag every `==`/`!=` comparison uniformly (consistent
            with declaration-time distinctness and fingerprinting, but
            makes `ds.param("x") == 5` silently always-`False` for a real
            `x` compared against the `int` literal `5` instead of `5.0`).
            (b) Plain value equality everywhere (simple, but lets `True ==
            1` leak through for bool params).
            (c) A hybrid: `bool` is type-tagged against everything else;
            `int`/`float` compare numerically against each other; any other
            pair (str, and other `Any`-typed categorical/ordinal values)
            requires an exact type match.
Choice:     (c) — eval/_kleene.py's `_values_equal`. Closes the one
            practically dangerous gap (`bool`/`int` conflation) without
            introducing friction for the overwhelmingly common case (real
            and integer comparisons mixing `int`/`float` literals
            casually). Known, accepted gap: a categorical/ordinal domain
            that deliberately declares both `1` and `1.0` as distinct
            variants (legal per "mixed types allowed") cannot be told apart
            by `==` at evaluation time — declaration-time distinctness
            (rows 3/4) and fingerprint canonicalization are unaffected,
            since neither goes through this function.
Spec delta: API_v3.md's Expressions section could state the runtime
            equality rule for `==`/`!=`/`.is_in()` explicitly, the way the
            Identity section already does for fingerprint canonicalization.

## D-8 (M2) — Continuous-equality warning (row 25) scope

Question:   "An `==` constraint over purely continuous, unquantized
            operands is measure-zero under sampling; resolution emits a
            warning" doesn't define "purely" precisely: does one continuous
            unquantized operand suffice (e.g. `ds.param("x") == 5` with `x`
            real), or must *every* operand be continuous — and does an
            integer operand on the other side of the comparison neutralize
            the warning even though the continuous side is still
            measure-zero against it?
Options:    (a) Warn whenever *any* operand touches an unquantized real,
            regardless of what else is being compared. (b) Warn only when
            *no* operand is discrete-typed (categorical/ordinal/bool/
            integer) and *at least one* is an unquantized real.
Choice:     (b) — resolve/_constraints.py's `_warn_if_continuous_equality`.
            Reads "purely" as qualifying the whole comparison, not just one
            side: the word is doing real work in the sentence, and a
            discrete operand present anywhere is the more defensible
            reading of "not purely continuous," even though (as noted in
            the code) a continuous-vs-integer comparison is arguably still
            measure-zero from the continuous side. Chose the narrower,
            literal reading over the broader one so the warning doesn't
            fire on `.forbid(x == some_integer_param)`-shaped constraints
            that aren't the sugar-for-reparameterization case the warning
            is steering authors toward.
Spec delta: State explicitly whether one continuous operand suffices to
            trigger the warning, or all operands must be continuous.

## D-9 (M2) — `validate_param`'s "unevaluated" constraints are omitted

Question:   "`context` enables evaluating constraints that reference other
            params... without it, `validate_param` reports those as
            unevaluated rather than guessing" — `ConstraintEval` has no
            "unevaluated" state (only `applicable`/`satisfied`/`margin`,
            where `applicable=False` already means Kleene-Unknown). The
            spec doesn't say whether an under-determined constraint (needs
            a param not in `context`) appears in `evaluate_constraints`'
            output with some marker, or is left out entirely.
Options:    (a) Include it with `applicable=False` (reusing the
            Kleene-inapplicable shape) — but that conflates "Unknown due to
            inactivity" with "under-determined due to missing context",
            two different reasons for the same field value.
            (b) Omit it from `validate_param`'s `constraint_evals` list
            entirely — only constraints fully determined by `path`'s value
            plus `context` are reported.
Choice:     (b). Introducing a fake `applicable=False` result would make an
            under-determined constraint indistinguishable from a genuinely
            Kleene-Unknown one, which is a worse guess than just not
            reporting it — closer to the spirit of "rather than guessing."
            `evaluate_constraints(space, config)` (the whole-config path,
            which always has every param) is unaffected; this only touches
            `validate_param`'s partial, single-param view.
Spec delta: Could state explicitly that under-determined constraints are
            simply absent from `validate_param`'s result rather than
            appearing with a placeholder value.

## D-10 (M2) — Ordinal comparison uses declaration position, not raw value; non-member literal is Unknown

Question:   "Ordered by declaration position. Comparison yes, arithmetic no"
            (API_v3.md, ordinal domain) says comparisons follow declaration
            order, but doesn't say what a comparison should do when one side
            is a literal that isn't one of the declared values at all (e.g.
            `ds.param("size").ordinal("s", "m", "l") > "typo"`) — that's an
            author error, not a spec case the ordering rule anticipates.
Options:    (a) Raise eagerly at comparison-construction time if a literal
            operand isn't a declared member. (b) Let it fall out of the
            existing lookup: `_ordinal_index` finds no position for
            "typo", so the comparison evaluates to Unknown — silently
            inapplicable at `.forbid()`/`.constrain()` (rule 4), same as any
            other Unknown.
Choice:     (b) for M2. No error-table row calls for this check, and adding
            resolution-time literal-membership validation for every ordinal
            comparison site is new scope beyond what M2's gate asks for.
            Recorded here because it's a real silent-resolution behavior
            (a typo'd forbid never fires, with no warning) rather than an
            oversight discovered and left unfixed — worth revisiting as an
            M3+ validation-time check if it causes real authoring pain.
Spec delta: Could state that a literal compared against an ordinal that
            doesn't match any declared value evaluates to Unknown (consistent
            with "comparison yes" implicitly requiring both sides resolve to
            a position), or else mandate eager rejection at construction.

## D-11 (M3) — Anchors stay out of scope; this supersedes nothing new, just extends D-5

Question:   IMPLEMENTATION_PLAN.md's M3 corpus table lists `sat_solver`'s
            "Exercises" column as "choice+ordinal, anchors, ordinal
            comparisons," which reads as if `.anchor()` is needed now. But
            M3's own Spec/Build/Gate lines (unlike M2's, which D-5 already
            addressed) never mention `.anchor()`, "Constraints and
            Feasibility," or anchor validation anywhere.
Options:    (a) Implement `.anchor()` now, since the corpus table names it
            for this fixture. (b) Defer it; build `sat_solver` with only
            the choice+ordinal content the Spec/Build/Gate lines actually
            ask for.
Choice:     (b), for the same reason as D-5: the per-milestone Spec/Build/
            Gate lines are the more specific, more authoritative signal,
            and `greenhouse`'s own corpus-table entry establishes the
            precedent that this "Exercises" column describes a fixture's
            *lifetime* scope, not what must be live at its add-milestone
            (its "defaults cascade" is explicitly deferred to M6 in the
            very next column). CLAUDE.md's "no dead scaffolding" /
            "`__init__.py` exports exactly the surface implemented so far"
            affirmatively forbids adding `.anchor()` before some
            milestone's own gate needs it. `sat_solver` is built here with
            only choice+ordinal+comparisons; it gains `.anchor()` calls
            whichever later milestone first requires them (M8, "ops/
            ...anchor interactions," is the first place the plan actually
            names anchor machinery).
Spec delta: The corpus table could mark forward-referenced fixture content
            the same way `greenhouse`'s already does, rather than only for
            defaults.

## D-12 (M3) — Eager resolution retained; escaping `.when()` references from an inline choice/struct payload are unsupported

**SUPERSEDED by D-26.** This entry's conclusion (option (b): eager
single-pass resolution, up-references unsupported) was reversed. Its central
claim — that the permanent M1 row-6 test made deferral "a hard constraint,
not a judgment call" — conflated the error-table row-6 *law* (satisfiable
under deferred resolution) with the *architecture* choice "resolve eagerly at
`ds.space()` construction" (not spec-mandated). Up-references now resolve as
the spec's sole scoping rule intends; see D-26. The rest of D-12 is retained
for the historical record.

Question:   API_v3.md's scoping-rule example ("Paths and Scoping") shows a
            `.when()` condition *inside* a choice variant's inline
            `ds.space(...)` payload referencing a param declared in the
            *enclosing* scope (`global_flag`), commented "# up." But
            `ds.param(...).choice()`/`.space()` (struct) both take that
            payload as an already-built `Space` — and M1's permanent row-6
            test (`test_build_resolve.py::TestRow6UndeclaredReference`)
            requires `ds.space(...)` to raise immediately on any locally-
            unresolvable `.when()` reference, with no way to distinguish
            "a typo" from "an escaping reference the caller will bind
            later." Any relaxation that spares one spares the other.
Options:    (a) Make resolution lazy/two-phase so a payload can carry
            still-open references, closed only when embedded in a wider
            scope. (b) Keep resolution eager and single-pass (as M1/M2
            already built it); a payload resolves standalone and fully,
            so a `.when()` inside it can only reference params declared
            in that same payload. Cross-scope logic is instead written as
            a `.forbid()`/`.constrain()` at the common ancestor, using a
            full dotted-path *down* reference into the descendant — which
            the spec's own next paragraph prescribes ("Cross-scope
            constraints are declared at the common ancestor") and which
            already works with zero special-casing once a Space's
            `.params` is fully flat.
Choice:     (b). Option (a) is decisively ruled out by the permanent M1
            test above — it is not a judgment call, it is a hard
            constraint. Relocatability itself survives intact: it is about
            a subspace's *own* internal (local) references behaving
            identically whether resolved standalone or nested (see
            `tests/conformance/test_structure.py::TestRelocatability`) —
            an escaping up-reference isn't "internal" to the child at all,
            and inline-vs-nested is vacuously equal for it (inline also
            fails to resolve it). Cascading deactivation is unaffected:
            the discriminator/struct-activation condition is *injected by
            the enclosing resolution* after the child resolves (resolve/
            _relocate.py), not written by the child's own author, so it
            never needs the child's eager pass to see anything outside the
            child.
Spec delta: The "up" example needs either a different construction that
            defers child resolution (which `ds.space()`'s current eager
            contract doesn't provide), or a note that it illustrates the
            scoping *rule* abstractly rather than something achievable
            through inline choice/struct payload nesting today.

## D-13 (M3) — Subset default inclusion probability (no `.prior(weights=...)`)

Question:   "`.prior(weights=[...])` | subset | Independent inclusion
            probabilities in `[0,1]` per item" states the *shape* of a
            declared prior but not the default when none is given — every
            other kind's default is named explicitly (Uniform for reals,
            equal weights implied for categorical/ordinal/bool/choice by
            "Non-negative, not all zero" leaving equal weights as the
            natural reading when omitted).
Options:    (a) Default each item's inclusion probability to 0.5 (an
            uninformative per-item coin flip — the natural analogue of
            "Uniform" for an independent-Bernoulli measure). (b) Default
            to some other fixed value, or require `.prior()` be mandatory
            for subsets.
Choice:     (a). 0.5 is the maximum-entropy (least-informative) choice for
            a Bernoulli and requires no new concept — sample/_sample.py's
            `_draw_subset` uses `np.full(len(items), 0.5)` absent a
            `Weights` prior. Consistent with "priors are coordinate
            systems" defaulting to the uninformative measure everywhere
            else in the spec.
Spec delta: Could state the default inclusion probability explicitly next
            to the existing subset row in the Modifiers table.

## D-14 (M3) — `sum_over()` with a mapping that omits an included item

Question:   "`ds.param("s").sum_over(mapping)` # subset: Σ mapping[item]
            over included items; ... keys ⊆ item universe" legalizes a
            mapping that covers only *part* of the universe (⊆, not =).
            It doesn't say what the sum contributes for an included item
            with no mapping entry.
Options:    (a) Treat a missing key as a `KeyError` at evaluation time
            (the mapping is only "safe" for configs that happen to avoid
            unmapped items). (b) Treat a missing key as contributing `0`
            to the sum (a sparse cost/weight map where unlisted items are
            free).
Choice:     (b) — eval/_kleene.py's `SumOver` evaluation uses
            `mapping.get(item, 0)`. Raising on a perfectly legal config
            (per the item-universe/size-bound domain checks, which have
            no idea `sum_over` even exists) would make a validly-sampled
            config crash a `.constrain()`/`.forbid()` evaluation — a much
            worse failure mode than silently contributing zero, and "keys
            ⊆ universe" reads more naturally as "a sparse map is legal"
            than as "the author must prove every reachable item is
            covered."
Spec delta: Could state explicitly that an included item missing from the
            mapping contributes zero to the sum.

## D-15 (M3) — `.space(prebuilt: Space)` form deferred

Question:   API_v3.md lists two struct-type-method signatures: `.space(*exprs)`
            and `.space(prebuilt: Space)`, noting the prebuilt form exists
            because "per-element constraints on repeated structs require
            the prebuilt-`Space` form (the inline form has nowhere to hang
            a `.forbid`)" — but repeated structs (`.repeat()`) don't exist
            until M4.
Options:    (a) Implement both call shapes now. (b) Implement only
            `.space(*exprs)` (inline); defer the `prebuilt: Space` overload
            until a lift actually needs it.
Choice:     (b). The prebuilt form's entire stated motivation is repeat-
            element constraints, which is M4 machinery; none of M3's five
            corpus fixtures pass an already-built `Space` positionally to
            `.space()`, and CLAUDE.md forbids stubbing future milestones'
            surface. `.choice()`'s variant payloads already accept a
            `Space` (via `ds.space(...)` built inline in argument
            position) — that is a different call shape (a `dict`/keyword
            value, not `ParamExpr.space(a_space)`) and is fully
            implemented; only the struct type-method's alternate overload
            is deferred.
Spec delta: None — this is a plan-sequencing question (the prebuilt form's
            payoff is inherently an M4 concern), not a spec gap.

## D-16 (M3) — Subset size-bound sanity checks beyond the literal error table

Question:   The error table's row 3 covers duplicate subset/permutation
            items, but no row covers a subset whose `min_size`/`max_size`
            are themselves nonsensical (negative `min_size`, `max_size <
            min_size`, or `min_size` exceeding the declared item
            universe) — unlike reals/integers, which get an explicit row
            (8) for `lo > hi`/non-finite bounds.
Options:    (a) Leave these unchecked at resolution; let them surface
            later as a confusing sampling retry-exhaustion error (row 26)
            or a silently-impossible-to-satisfy domain. (b) Reject them at
            resolution, analogous to row 8's treatment of scalar bounds.
Choice:     (b) — resolve/_pipeline.py's `_check_subset_size_bounds`.
            "Choose the least-surprising behavior consistent with the
            spec's Design Principles" favors failing fast at resolution
            (the same moment `lo > hi` fails for a real) over a
            mysterious `SamplingError` naming no obviously-wrong param
            declaration. No conformance law depends on the *absence* of
            this check, so adding it strengthens rather than weakens
            anything frozen.
Spec delta: The error table could add a subset-bounds row alongside row 8,
            worded the same way ("`min_size > max_size`; `min_size < 0`;
            `min_size` exceeds the item universe").

## D-17 (M3) — `unflatten` omits a struct that is active but all of whose members are inactive

Question:   "`.space(*exprs)` ... Struct-valued param: unconditionally-
            present grouping under a namespace" suggests an active struct
            should always appear in the nested config, even as `{}`. But
            `config/_unflatten.py` can only tell a struct is "present" by
            checking whether *any* descendant leaf is present in the flat
            dict — an active struct whose every member happens to be
            individually inactive (e.g. each gated by its own `.when()`
            that's currently false) looks, from the flat dict alone,
            identical to an *inactive* struct: no descendant keys exist
            either way, and `unflatten` has no separate activity signal to
            tell them apart (the public `unflatten(flat, space)` signature
            takes no activity argument).
Options:    (a) Omit the struct entirely whenever it has no present
            descendants (current behavior) — self-consistent (`flatten`
            and `unflatten` agree, `validate` never reports a `space`-kind
            path itself, and the round-trip law holds either way, since
            both directions apply the same rule). (b) Always emit `{}` for
            a struct with zero *declared* descendants (the fully-empty-
            struct degenerate case only), still omitting the "all members
            individually inactive" case since it's indistinguishable from
            "the struct itself is inactive" without an activity parameter.
Choice:     A version of (b): zero-descendant structs always emit `{}`
            (handled explicitly); an active-but-all-members-inactive
            struct is omitted, same as a genuinely inactive one — this is
            the one case not resolved by (a) or (b) alone, and is recorded
            here as a known, accepted limitation rather than silently
            left unhandled. It doesn't violate any stated law: nothing in
            the Conformance Laws section distinguishes these two states,
            and `unflatten(flatten(c)) == c` holds regardless (the
            asymmetry only matters if a caller compares `unflatten`'s
            output against `compute_activity`'s independent notion of
            "active," which M3 has no API surface for doing).
Spec delta: Could state whether `.unflatten()` (which takes no activity
            argument) is expected to distinguish "active, all members
            inactive" from "inactive" for a struct with declared members,
            or clarify that "unconditionally-present" describes validity
            (a struct's activity never depends on its *own* members'
            activity) rather than a guarantee about `unflatten`'s output
            shape.

## D-18 (M4) — Design note: representing lifted vectors and Unknown in the evaluator

IMPLEMENTATION_PLAN.md's M4 line directs a design note before implementation
("this interaction — Kleene × aggregates × instance paths — is the
highest-complexity point in the codebase"). This entry is that note.

**Where the element template lives in the IR.** `space.params` stays the
one flat `dict[str, ParamDef]` keyed by *definition path* — no side
channel. A lift's element, when it is a struct or choice (i.e. has its own
descendant params), is relocated into that same dict under a
`"[]"`-bracketed prefix (`"edges[].src"`, `"edges[].dst"`), reusing
resolve/_relocate.py's `relocate_child` unchanged (M3 built it generically
over "a rename prefix and an injected condition"; `"edges[]."` is just
another prefix string, and the injected condition is `None` here — see
below). This matches the spec's own introspection convention verbatim:
"introspection lists them once under definition paths (`edges[].…`)." A
scalar/subset/permutation element has no descendants, so nothing is
relocated — the element's chart/prior/quantized/periodic/default live
directly on the new `ListDomain` IR node (below), not on `ParamDef`.
Nested lifts (`.repeat(8).repeat(8)`) bracket-nest the same way
(`"mask[][]"` has no descendants of its own since `bool` is a leaf, but a
struct-of-lists-of-structs would read `"grid[][].width"`).

```python
@dataclass(frozen=True)
class ListDomain:
    element_kind: str              # "real" | ... | "space" | "choice" | "list" (nested)
    element_domain: Domain         # recursive: another ListDomain for chained .repeat()
    element_chart: Chart | None    # built from element_prior/element_quantized; None for non-chart kinds
    element_prior: PriorSpec | None
    element_periodic: bool
    element_quantized: QuantizedSpec | None
    element_default: Any           # pre-repeat "element default"
    count: int | ArithExpr
    list_default: Any = None       # post-repeat "list default", this level only
```

A list-typed `ParamDef` itself carries `chart=None, prior=None,
periodic=False, quantized=None, default=None` (it joins
`_NON_CHART_KINDS`) — every element-describing fact lives inside
`ListDomain`, recursively, one level per `.repeat()` call. This is why no
new `ParamDef` field was needed.

**Why relocation cannot happen at resolution time (the key departure from
M3).** M3's struct/choice relocation runs once, at `_emit()`, because a
struct or choice has exactly one instantiation, known at resolution. A
lift's count is explicitly *not* resolution-known in general ("Counts,
unlike bounds, remain runtime-evaluated — lists are structure, not
charts") — it may reference another param's value. So the descendant
*template* (`"edges[].src"`) is relocated once, at resolution, with
`injected_condition=None` (no per-instance condition is folded in yet —
there is no instance yet); the template's own internal conditions
(a sibling field's `.when()` referencing another field of the same
element) are rewritten by the rename map exactly as M3 already does.
**Per-instance expansion** — turning the template plus a concrete index
`i` into `"edges[3].src"` with a concrete activity — happens at
evaluation time (validate/sample/evaluate_constraints), via a new sibling
of `relocate_child` that takes an integer index instead of a static
prefix and substitutes the *innermost* unresolved `"[]"` in each
descendant path with `"[i]"`. This is the one genuinely new piece of
machinery `relocate_child` didn't already have; everything else about it
(rename map, condition rewriting, constraint rewriting) is reused as-is.

**Flat config/activity shape for concrete per-draw evaluation.** The
existing evaluator (`eval/_kleene.py`) is untouched in its core recursion;
it is fed an extended flat dict. For a lift at path `p` with realized
count `n` for this draw:

- `config[p]` — an `int`: the realized count (mirrors `.length()`
  and lets `evaluate_arith` answer `ds.param(p).length()` by a single
  dict lookup, exactly like any other leaf).
- `config[f"{p}[{i}]"]` (scalar/subset/permutation element) or
  `config[f"{p}[{i}].{field}"]` (struct/choice element, recursing) for
  each `i` in `range(n)` — the per-instance value(s), keyed by *instance*
  path per the existing grammar (already "multi-index ready" from M3).
- `activity[p]` — whether the lift itself is active (existing mechanism,
  unchanged: a condition target like any other param).
- `activity[f"{p}[{i}]..."]` — per-instance leaf activity, computed by
  expanding the element template's conditions for that `i` (only
  meaningful for struct/choice elements whose fields carry their own
  `.when()` against sibling fields; a bare scalar/subset/permutation
  element has no such condition and is always active whenever the lift
  itself is active and `i < n`).

`flatten()`/`unflatten()` (config/) grow one more case alongside their
existing struct/choice handling: a list value in the canonical nested
config (`[0.1, 0.3]`, `[{"width":128}, {"width":256}]`) flattens to
`out[p] = len(value)` plus a recursive `_flatten_level` call per element
at prefix `f"{p}[{i}]."` (struct elements) or a direct
`out[f"{p}[{i}]"] = value[i]` (scalar/subset/permutation/choice-as-a-
value elements). `unflatten` reverses it by reading `flat[p]` as the
count and rebuilding each `i` from the flat dict — this is the exact
same recursion shape M3 already uses for struct/choice, parametrized by
an integer range instead of a fixed set of field names.

**Instance paths in expressions, out-of-range → Unknown.** A leaf
reference like `ds.param("stops[0].dwell_min")` parses via
`paths/_grammar.py` (unchanged) to a path with an instance bracket. Its
evaluation is the *existing* `_leaf_value` lookup unchanged in mechanism:
`config.get(path)` / `activity.get(path)`; the "out-of-range" rule is
satisfied for free by construction, *provided* an out-of-range instance
path is simply never written into `config`/`activity` at draw time (the
sampler only materializes `i in range(n)`) and `_leaf_value` already
treats an absent activity entry as `True`... which would be *wrong* here
(it would read as active-but-missing, "validate() reports as missing",
not Unknown). So `_leaf_value` gains one precondition specific to
instance-bracketed paths: if any bracket index in the path is `>=` the
realized count of its owning lift (looked up via `config[owning_lift_path]`,
falling back to "lift itself inactive" if that key is also absent), the
leaf is Unknown — checked *before* the ordinary activity-dict lookup, not
instead of it (an in-range but individually-inactive instance leaf still
goes through the ordinary activity path).

**Vector expressions and aggregates.** `.field(name)` and the aggregate
methods (`.sum()`, `.min()`, `.max()`, `.count_of()`, `.is_sorted()`,
`.distinct()`) are new AST node kinds whose *operand* is always a
lift-referencing `ParamExpr` or a `Field` node (never a scalar leaf).
Evaluating the operand produces one of:

1. `UNKNOWN` (rule 1) — the lift itself is inactive. This is mechanically
   identical to a scalar inactive leaf: no new machinery, just the
   existing activity lookup on the lift's own definition path.
2. `[]` (rule 6, active-empty) — the lift is active and its realized
   count is `0`.
3. `list[Any | Unknown]` of length `n` — the lift is active with `n > 0`
   elements, gathered by reading each instance's leaf (or, for
   `.field(name)`, each instance's named descendant leaf, flattening
   across nested lift levels per the spec's "leaves, flattened across all
   levels" rule) through the *same* per-instance activity mechanism above
   — so an individual element is `Unknown` exactly when that specific
   instance's projected leaf is inactive (only possible for a struct
   element field gated by a sibling `.when()`; a bare scalar/choice/
   subset/permutation element list never has interior Unknowns, since
   its elements carry no per-element condition of their own).

Aggregate evaluation order, uniformly: resolve the operand to one of the
three cases above; case 1 short-circuits the whole aggregate to
`UNKNOWN`; case 2 applies the rule-6 empty-aggregate table verbatim
(`sum/count_of/distinct/is_sorted` per the table, `min/max → UNKNOWN`);
case 3 is where D-19 (below) governs interior-Unknown handling.

## D-19 (M4) — Interior-Unknown handling for non-empty aggregates

Question:   Rule 2 states "Comparisons and arithmetic with an Unknown
            operand are Unknown... The same rule governs aggregates
            containing Unknown elements," immediately after describing
            `ds.count`'s range-tracking (`[t, t+u]`, Unknown only when the
            comparison outcome differs across the achievable range). Read
            broadly, "the same rule" could mean every vector aggregate
            (`sum`, `min`, `max`, `count_of`, `is_sorted`, `distinct`)
            should track an achievable-value range the way `count` does
            and only resolve to Unknown when a downstream comparison's
            outcome is range-dependent. Read narrowly, it just restates
            the paragraph's opening sentence — plain Unknown-propagation
            — applied to a vector's elements as if each were an ordinary
            operand.
Options:    (a) Full range-tracking for every aggregate: for `sum`,
            compute achievable range from each Unknown element's
            (already-enveloped, since resolution requires finite bounds)
            domain and only report Unknown if the final comparison result
            varies across it; similarly bound `min`/`max` by the envelope
            extremes, and give `count_of`/`is_sorted`/`distinct`
            comparison-aware range logic mirroring `_count_vs_threshold`.
            (b) Plain propagation: any Unknown element in a non-empty
            aggregated vector makes the aggregate itself Unknown, full
            stop — no range computed, no interaction with the downstream
            comparison. `count_of` gets no special range-tracking beyond
            this, despite superficially resembling `ds.count`.
Choice:     (b). The gate this milestone is actually held to (IMPLEMENTATION_PLAN.md's
            M4 gate line) names the empty-aggregate table and the
            inactive-lift-vs-active-empty pair — both about *whole-lift*
            activity, never about interior Unknowns inside a non-empty
            vector. No conformance law anywhere pins option (a)'s
            behavior. Building range-tracking on speculation would mean
            (i) inventing interval arithmetic ahead of M5, which the plan
            explicitly scopes to "a minimal op set" over `+`/`−`/`×` by
            constants and enveloped params — nothing about aggregating
            across a runtime-variable-length vector — and (ii) freezing a
            guess about behavior nothing requires, which cuts against
            "never weaken a stated law" from the other direction (adding
            unrequested surface is its own kind of scope creep per
            CLAUDE.md's no-dead-scaffolding rule). (b) is also the
            reading consistent with ordinary arithmetic elsewhere in the
            evaluator (an `ArithOp` with one Unknown operand is Unknown,
            no range tracked) — vectors are treated as an ordered
            collection of operands, not a special case. This is a
            judgment call, not a spec law, so its tests live in
            `tests/unit/`, not `tests/conformance/` — nothing here is
            permanent in the way the empty-aggregate table is.
Spec delta: Clarify whether "the same rule" for aggregates means
            `ds.count`-style range-tracking or plain propagation; if the
            former, specify the range semantics for `sum`/`min`/`max`
            (which have no natural finite "count" of outcomes to range
            over without invoking interval arithmetic).

## D-20 (M4) — `.space(prebuilt: Space)` and per-instance constraint instantiation

Question:   D-15 (M3) deferred the `.space(prebuilt: Space)` struct-type-
            method overload, noting its only stated motivation — per-
            element constraints on repeated structs, since "the inline
            form has nowhere to hang a `.forbid`" — is M4 machinery. M4's
            spec text confirms this is exactly how per-instance
            constraints are meant to be authored (Modifiers: "Constraints
            declared inside a repeated element `Space` are instantiated
            per element"; the vector-expressions example comment "row-
            scope forbid on" sits directly on the pre-lift struct). The
            spec does not spell out the mechanism connecting "a
            `Constraint` declared on the element `Space`" to "one
            `ConstraintEval` per instance path" at evaluation time.
Options:    (a) Statically unroll per-element constraints at resolution
            into `space.constraints`, one copy per possible index — only
            works for a literal integer count, contradicts "counts...
            remain runtime-evaluated." (b) Keep the element `Space`'s own
            `constraints` tuple as a *template*, carried on the lift's
            `ListDomain` (added as `element_constraints:
            tuple[Constraint, ...]`, populated from the prebuilt Space
            passed to `.space()`), and expand it per active instance at
            evaluation time — the same per-instance expansion that
            produces per-instance `ParamDef`/activity also rewrites each
            template constraint's expr under the concrete instance prefix
            and yields one `ConstraintEval` with `instance_path` set to
            `f"{path}[{i}]"`.
Choice:     (b). Only this option is consistent with runtime-evaluated
            counts (a dynamic count can't be unrolled at resolution,
            since it isn't known until a config exists) and with
            `ConstraintEval.instance_path` existing as a field precisely
            for this ("set for per-element instantiations" — IR section).
            `.space(prebuilt)` accepts an already-fully-resolved child
            `Space`; its `.constraints` become the element template
            (relocated the same way its `.params`/`.conditions` are, via
            `relocate_child`, so both paths and expressions are rewritten
            uniformly); the *inline* `.space(*exprs)` form used for a
            lift's element is legal too but has nowhere to hang a
            per-element `.forbid()`, exactly as D-15 anticipated —
            an element built inline can still declare ordinary struct
            fields and conditions, just no element-scoped constraints.
Spec delta: None — this resolves a mechanism gap, not a stated ambiguity;
            the spec's two facts (runtime-evaluated counts;
            `ConstraintEval.instance_path`) already imply this design.

## D-21 (M4) — Repeat counts join the dependency graph and cycle detection

Question:   Error row 7 covers "cycle in the condition/bound dependency
            graph"; row 12 covers "repeat count not integer-typed." The
            spec doesn't explicitly restate that a repeat count expression
            referencing another param must be ordered after that param
            (topological_order) or is subject to the same cycle check —
            but a count is exactly the same kind of "must be known before
            this param can be materialized" dependency conditions already
            are.
Options:    (a) Leave repeat-count references out of the dependency graph
            and cycle check — only conditions participate, matching M1-M3
            literally. (b) Fold `count.params` (when count is an
            `ArithExpr`) into the same dependency set as `condition.params`
            for both `topological_order` and `_check_condition_cycles`.
Choice:     (b). A count referencing a not-yet-known param is no
            different in kind from a condition doing so — both must
            resolve before this param's activity/materialization is
            computable — and the "Resolution" section's step 5 already
            describes cycle detection over "the condition and bound
            dependency graph," naming bounds (expression bounds, M5)
            alongside conditions as a *pattern* of "things establishing
            assignment order," which a runtime-evaluated count fits
            exactly. Treating it as an ordinary dependency-graph edge
            reuses `topological_order`/`_check_condition_cycles`/
            `compute_activity` unchanged (they already iterate a
            `path -> deps` mapping; count references are just one more
            source of edges into that mapping) rather than inventing a
            parallel ordering mechanism.
Spec delta: Could state explicitly that repeat-count expressions
            participate in the dependency graph and cycle detection
            alongside conditions and (later) expression bounds.

## D-22 (M4) — Negative evaluated repeat count (row 13)

Question:   Row 13 ("Evaluated repeat count negative") is tagged V
            (validation/fill/sample-time), not R — a literal negative
            count is already rejected by ordinary integer-domain bound
            checks if the count param's own declared domain excludes
            negatives, but nothing stops `.repeat(ds.param("n").integer(-5, 5))`
            from resolving, and nothing in the spec says what happens
            when such a count actually evaluates negative for a given
            config, since a Python list can't have negative length.
Choice:     Two call sites, one rule: (1) `sample_one` evaluates the count
            before drawing elements; a negative result raises
            `SamplingError` immediately (same exception family as row 26,
            same "can't materialize" character — sampling has no other
            channel to report through, per "only operations with no
            result channel raise"). (2) `validate()` never independently
            "evaluates" a count against a submitted list — the submitted
            list's own length *is* the count for validation purposes
            (`len(value)`); a separately-referenced count expression
            (e.g. `ds.param("n")` feeding `.repeat(ds.param("n"))`) is
            cross-checked as `len(value) == evaluated_count`, reported as
            `ParamError(reason="out_of_bounds")` on mismatch — a negative
            evaluated count simply can never match any real list's
            length, so it surfaces through the exact same mismatch check
            without a separate code path.
Spec delta: None — this is mechanism, not ambiguity; the two existing
            channels (`SamplingError`, `ParamError`) already cover it.

## D-23 (M4) — Explicitly out of M4 scope

Question:   Several spec items sit textually near M4's material but
            belong to later milestones per IMPLEMENTATION_PLAN.md, worth
            recording so they aren't accidentally half-built while
            touching adjacent code.
Choice:     `.prop()` (Expressions' general ArithExpr method block, same
            paragraph as `.length()`) is M9 (custom types) — not
            implemented now. `apply_defaults`/`has_complete_defaults`
            (Defaults section, which M4's element/list default *validation*
            necessarily touches) stay M6 — M4 only validates default
            *declarations* at resolution (row 21: domain membership,
            element/list mutual exclusivity, static-count-only for list
            defaults), the same way M1 validated scalar defaults at
            resolution years before `apply_defaults` existed. `static_shape`
            (`Capabilities`, IR section) is M10's DataFrame concern.
            Expression bounds / interval arithmetic (`ds.param("x").integer(1,
            ds.param("y"))`) remain M5, including for a repeat count that
            happens to look like a bound-shaped expression — a count is
            never desugared into a bound-origin constraint, it stays a
            plain runtime-evaluated `ArithExpr`.
Spec delta: None.

## D-24 (M4) — Struct/choice elements nested under more than one `.repeat()` level: rejected, not silently wrong

Question:   A struct or choice lift element's descendant *template* is
            relocated into `space.params` under a single `"[]"`-bracketed
            prefix (`"edges[].src"`, D-18) built from the outer param's
            own path, regardless of how many `.repeat()` levels wrap it.
            For a genuinely double-nested lift whose *innermost* element
            is a struct/choice (`.space(...).repeat(3).repeat(2)` — a list
            of lists of structs), the path grammar's own convention for a
            nested-lift definition path is `"grid[][].width"` (one `"[]"`
            per level, per "Paths and Scoping": `mask[][]` for two nested
            scalar lifts) — but the relocation in `_emit` only ever writes
            a single `"[]"`, producing a template at `"grid[].width"` that
            doesn't match either bracket-depth convention and that the
            per-instance evaluator (`eval/_kleene.py`'s `_expand_lift_activity`,
            `config/_flatten.py`) has no path to correctly address (it
            only ever substitutes *one* bracket level for a concrete
            index). None of M4's named corpus fixtures (`delivery_routes`,
            `solver_portfolio`, `memetic_pipeline`) need this — their
            struct/choice lifts are single-level; nested repetition in
            the corpus is always of *scalar* elements (which have no
            descendant template at all, so arbitrary nesting is already
            fully correct and tested).
Options:    (a) Ship it anyway, silently producing a template at the
            wrong bracket depth — works by accident for depth 1, breaks
            in a way that's hard to diagnose (wrong/missing activity,
            validate() blind to the shape) for depth > 1. (b) Extend the
            relocation and per-instance expansion machinery to track
            bracket depth generally, so an arbitrary chain of `.repeat()`
            calls terminating in a struct/choice element works uniformly.
            (c) Reject the construction at resolution with a clear
            error naming the limitation, deferring (b) until a real need
            (corpus fixture or user report) justifies the added
            complexity.
Choice:     (c) — `resolve/_pipeline.py`'s `_validate_lift` raises
            `ResolutionError` when `depth > 1` and the innermost element
            is `"space"` or `"choice"`. CLAUDE.md: "never resolve
            silently" — (a) is exactly the silent-wrongness this rule
            forbids, and it would surface as a confusing downstream
            symptom (missing per-instance activity/validation) rather
            than an error naming the actual limitation. (b) is real,
            bounded work but strictly additive — nothing about rejecting
            the case now forecloses implementing it later, and no
            conformance law or corpus fixture is blocked by deferring it.
            Scalar/subset/permutation/nested-`"list"` elements are
            already fully general (no descendant template exists for
            them at any depth, so the bracket-depth mismatch never
            arises) — only struct/choice elements are affected.
Spec delta: None — this is an implementation scope boundary, not a
            spec ambiguity; the path grammar's own `mask[][]` convention
            already says what the *correct* deeper form should look like
            whenever it is implemented.

## D-25 (M4) — `.field(name)` on a non-struct lift, or a name absent from the element: no resolution-time check

Question:   `.field(name)` (struct-lift projection, e.g.
            `ds.param("stops").field("dwell_min")`) is only meaningful
            when the base lift's `element_kind == "space"` and `name` is
            one of the element's declared descendant paths.
            `resolve/_expr_checks.py`'s `_require_lift_domain` (backing
            `Length`/`Sum`/`Min`/`Max`/`CountOf`/`IsSorted`/`Distinct`'s
            row-24-style checks) verifies the operand resolves to a
            `ListDomain` at all, but does not additionally verify (a)
            that `element_kind == "space"` before allowing `.field()`,
            or (b) that `name` matches a real element field. Concretely:
            `ds.param("xs").real(0.0,1.0).repeat(3).field("y")` resolves
            without error, and at evaluation time the projected leaf
            `"xs[i].y"` is never written into `config` for a scalar
            element, so `_leaf_value` returns Unknown for every
            instance — the aggregate built on top (e.g. `.sum()`)
            comes back Unknown, and a constraint built from it is
            simply inapplicable. Same outcome for a real struct lift
            with a misspelled field name.
Options:    (a) Add a resolution-time check in `_require_lift_domain`
            (or a new sibling) that rejects `.field()` unless the base
            is a struct lift with a matching declared field, raising a
            `ResolutionError` naming the bad field/base. (b) Leave it as
            a silent Unknown-cascade: no new check, relying on the
            evaluator's existing "absent from config -> Unknown" rule
            (already documented at the top of `eval/_kleene.py`, and the
            same mechanism that makes an out-of-range instance index
            Unknown rather than an error).
Choice:     (b) — the cascade is not a *silent wrongness* in the sense
            CLAUDE.md's rule targets (a spec law quietly weakened or an
            ambiguity resolved without a paper trail): it is the same
            "missing path -> Unknown -> inapplicable" behavior the spec
            itself prescribes for out-of-range instance indices and
            inactive lifts, applied uniformly to a third "this path
            structurally can never be written" case. No conformance law
            or M4 corpus fixture requires catching a mismatched
            `.field()` name at resolution time, and doing so would add a
            new category of builder-time schema-checking (walking a
            struct element's descendant paths from `_ElementSnapshot`
            before the element's own `Space` has necessarily been fully
            resolved) not required by any gate. Revisable later without
            foreclosing anything: adding the check is strictly additive
            (turns a previously-silent Unknown into an explicit error)
            and breaks no config that was ever valid, so nothing is lost
            by deferring it.
Spec delta: None.

## D-26 (M1/M3 rework) — Condition up-references resolve as the spec intends; row-6/7/14 checks deferred to a finalization pass

Question:   D-12 rejected an escaping `.when()` up-reference from inside an
            inline choice/struct payload (the spec's worked `# up` example,
            API_v3.md "Paths and Scoping" — `.when(ds.param("global_flag"))`
            inside an `svm=ds.space(...)` variant), calling it "not a
            judgment call, it is a hard constraint" forced by the permanent
            M1 row-6 test. Re-examination against the spec's *sole* scoping
            rule ("resolve the first segment by walking **up** to the
            innermost scope where it binds") and the Resolution section —
            which lists resolution's *steps* but never fixes its *timing*
            relative to construction — shows the framing was inverted. The
            error-table row-6 *law* ("reference to a nonexistent param → R")
            is satisfiable under deferred resolution; only the *architecture*
            choice "resolve eagerly at `ds.space()` construction," which the
            row-6 *unit* test happened to encode, foreclosed up-references.
            That architecture is not spec-mandated. The gating sub-question:
            is moving the row-6 error's *trigger* from construction to a
            terminal-op finalization a **weakening** of the row-6 law, which
            CLAUDE.md forbids?
Options:    (a) Keep D-12's eager rejection — up-references stay unbuildable
            and the spec's own `# up` example cannot be expressed.
            (b) Defer the condition reference/type/cycle checks: per-scope
            resolution *tolerates* a non-local `.when()` ref, and a
            finalization pass over the fully-merged space re-checks it.
Choice:     (b), and the deferral is **not** a weakening of row 6. The error
            still fires from pure space *structure* (no config or sample
            needed), still as a `ResolutionError` (phase R), still
            config-independent — only the moment it surfaces moves from the
            `ds.space()` call to the first terminal operation (sample/
            validate/evaluate_constraints/…). Deferral is *forced*, not
            chosen: the free `ds.space()` runs identical code for a top-level
            space and for a choice-variant payload, and during a payload's
            construction the enclosing `ds.space` is not yet on the call
            stack (Python argument-evaluation order), so nothing can
            distinguish "top-level typo" from "to-be-embedded up-reference."
            Both must be tolerated at construction; the genuine typo is
            caught at finalization.

            Mechanism (all reuse, one new pass):
            - Per-scope resolution tolerates non-local *condition* refs —
              `check_refs_declared`/`check_expr_types` skip them,
              `_check_condition_cycles` skips a dep that has no local node
              (resolve/_expr_checks.py, resolve/_pipeline.py).
            - Relocation already leaves an unmatched leaf path *unprefixed*
              (`rewrite_expr`'s `rename.get(path, path)`), so bottom-up
              embedding binds each up-reference at exactly the enclosing
              scope that declares it, folding in the discriminator/struct
              activation condition as usual — no relocation change needed.
            - `check_fully_resolved` (resolve/_pipeline.py), called at every
              terminal entry point, re-runs row 6 (refs now present) and row
              14 (types, over now-visible up-referenced params) over the
              merged conditions, and row 7 over the merged dependency graph —
              catching a **cross-scope cycle** (formable only via an up plus
              a matching down reference), which no single scope's cycle check
              can see. A space with only local references reaches this pass
              already fully checked, so every clause is a confirming no-op
              (verified: all 9 corpus fixtures and every conformance law pass
              unchanged).

            Scope: narrowed to `.when()` conditions — the spec example and
            D-12's actual subject. Constraint (`.forbid()`/`.constrain()`)
            refs stay strict (raise eagerly), since cross-scope constraints
            already have the spec's down-reference-at-the-common-ancestor
            route. Nested struct/choice bracket-depth limits (D-24) are
            untouched.

            The row-6 assertion lived in a *unit* test
            (tests/unit/test_build_resolve.py), not a permanent conformance
            test, and was updated to trigger the (unchanged) error at a
            terminal op. `tests/conformance/test_structure.py::
            TestRelocatability` and all other conformance laws are unchanged
            and green; a new `TestUpReferenceFromEnclosingScope` pins the
            spec's `# up` example (up- and down-references coexisting).
            This supersedes D-12's Choice and its Spec-delta (whose wish —
            "a construction that defers child resolution" — is now met).
Spec delta: API_v3.md could state that resolution *timing* is unspecified
            relative to construction, and that reference/type/cycle errors
            surface no later than the first terminal operation — so a payload
            carrying an enclosing-scope reference resolves once embedded,
            exactly as the sole scoping rule's up-walk requires.
