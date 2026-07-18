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

---

Entries D-1 … D-26 (M0–M4) were reviewed and resolved into API_v3.md as normative
spec text, with the remaining code corrections tracked under milestone **M4.5 —
Faithfulness corrections** in IMPLEMENTATION_PLAN.md. The full original entries
remain in this repo's git history (see the commit that reset this file). Add new
entries below as future milestones surface fresh ambiguities.

---

## D-27 (M4.6) — Builder return types: per-type view subclasses

Question:   The type-method tables (§Parameter Types) give a sampled-value "Value"
            column but never state the builder object each method returns, and
            §Construction said `ds.param(name) -> ParamExpr` (§Modifiers: modifiers
            "each return a new expression", unpinned). So the builder's static
            return types were left open.
Options:    (a) keep one flat `ParamExpr` — the IDE offers every method on every
            param and a second type method is caught only at resolution;
            (b) per-type view subclasses of `ParamExpr`, with the type methods
            hidden once a type is chosen; (c) a typing-only Protocol/`cast` overlay
            with no new runtime classes.
Choice:     (b). `ds.param -> FreshParamExpr` (a `ParamExpr` that carries the type
            methods); each type method narrows to a type-specific view
            (`RealParamExpr` … `StructParamExpr`, and `.repeat() -> ListParamExpr`)
            that exposes only its valid modifiers/queries and omits the type
            methods, so a second type method is a static error. All views subclass
            `ParamExpr`, so `isinstance(_, ParamExpr)` and every resolution/eval
            annotation are unchanged. The runtime error contract is preserved: a
            second type method still raises the path-named `ResolutionError`
            (row 2) via the views' `__getattr__`, and resolution still rejects
            programmatically-built two-type definitions. The IR is untouched —
            `ParamDef.type_kind` stays a string and the views have no serialized
            footprint. Least-surprising because it makes the "exactly one type
            method" law statically visible without changing any observable value,
            JSON format, fingerprint, chart, or conformance law. Chosen over (c)
            because concrete subclasses type-check trivially under `mypy --strict`
            (no self-referential Protocol risk) and give end users a nameable,
            `isinstance`-able `RealParamExpr`.
Spec delta: §Construction (`ds.param -> FreshParamExpr` + pointer) and a new
            §Parameter Types *Builder view types* subsection — folded into API_v3.md
            by M4.6. Mechanism (the `_as()` constructor, `__getattr__`, and the
            builder-layer `type_kind`/`type_calls` cleanup) lives in the plan, not
            the spec.
Deferred:   §Space — Metaprogramming names `TypedParamExpr` (return of
            `param_from_def`, M8). Making `TypedParamExpr` the common base of the
            view types is deferred to M8 to avoid introducing a metaprogramming
            surface early; until then the views subclass `ParamExpr` directly. A
            one-line forward note was added at that line. The builder-layer
            `type_kind`-from-class / `type_calls`-retirement question gets its own
            design note before M4.6 implementation (see M4.6 directive).
