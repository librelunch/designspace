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
