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
