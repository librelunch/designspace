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
