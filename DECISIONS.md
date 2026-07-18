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

## D-28 (M4.6) — View-class mechanism: `type_kind`/`type_calls`, the method
split, and two departures from the plan's Build section

Question:   The M4.6 directive asks two things settled on paper before coding:
            (1) how `ParamExpr.type_kind` is derived from the view class and
            whether `type_calls` is retired; (2) by extension, exactly which
            methods move off the base `ParamExpr` and how the `__getattr__`
            row-2 trap is implemented so it composes with the *existing*,
            already-tested resolution-time checks (`_check_types_and_names`,
            `_check_modifier_placement`) without weakening the error table.
            Working through (2) surfaced two further ambiguities: the spec's
            "Builder view types" paragraph groups `.contains()/.size()/
            .position_of()/.sum_over()` under *both* `SubsetParamExpr` and
            `PermutationParamExpr`, contradicting row 18 (`.contains()` on
            permutation is a resolution error) and the pre-existing,
            already-tested `_require_subset_domain`/`_require_permutation_domain`
            split; and the plan's Build section says modifiers/aggregates
            "stay on the base" while the Gate requires a static (mypy)
            rejection of `.categorical(...).log_scale()`, which is only
            achievable if `.log_scale()` is *not* inherited by
            `CategoricalParamExpr`.
Options:    For (1): (a) derive `type_kind` from the view's class (a
            `ClassVar` per view) and retire `type_calls`; (b) keep `type_kind`
            a plain instance field exactly as today, keep `type_calls` as the
            resolution-time backstop.
            For the combinatorial-query grouping: (a) mirror the spec
            paragraph literally, adding `.contains()`/`.size()`/`.sum_over()`
            to `PermutationParamExpr` too; (b) leave these methods where they
            are today (universal, on the base), unchanged.
            For the modifier-narrowing boundary: (a) take the plan's Build
            section literally — nothing moves off the base but the 9 type
            methods and `.repeat()`; accept the Gate's `.log_scale()` example
            as unreachable/aspirational; (b) additionally move `.log_scale()`/
            `.quantized()` into a Real/Integer-only mixin, since the Gate
            names them explicitly and they are the only modifiers the spec
            ties to specific types outside the type methods.
Choice:     (b) in all three cases.
            **type_kind/type_calls.** `type_kind` stays a plain instance
            field, set by the type methods exactly as before (unaffected by
            which subclass holds the method). `type_calls` is *retained*,
            unchanged in shape or the one place it's read
            (`_check_types_and_names`). Reasoning: since a fluent second type
            call now fails structurally (the method is simply absent on the
            narrowed view — see below), `type_calls` can never again
            accumulate more than one real entry via the builder API; but
            API_v3.md's own text ("resolution still rejects any definition
            that carries more than one type however it was built... the law
            holds for programmatically-constructed definitions as well as
            fluent ones") requires a mechanism that survives someone
            constructing a bare `ParamExpr(...)` by hand with conflicting
            state — a class-derived `type_kind` cannot represent "two types"
            at all (it is a single string), so history-tracking via
            `type_calls` is the only representation that can. It becomes a
            backstop exercised only by hand-built defs, not dead code (M4.6
            gate requires exactly this: a "programmatically-built two-type
            definition" test alongside the fluent one).

            **The class hierarchy.** `build/_paramexpr.py` keeps `ParamExpr`
            (all fields unchanged, including `type_kind`/`type_calls`) with
            the identity/domain-level modifiers that stay universal
            (`.prior()`, `.default()`, `.when()`, `.tag()`, `.meta()`), the
            combinatorial queries (`.contains()`, `.size()`, `.sum_over()`,
            `.position_of()`), `.length()`, and the inherited `VectorExpr`
            aggregates (`.field()`, `.sum()`, `.min()`, `.max()`,
            `.count_of()`, `.is_sorted()`, `.distinct()`) — API_v3.md requires
            the base to *be* a `VectorExpr` ("ParamExpr is the base type. It
            is an ArithExpr/BoolExpr/VectorExpr"), so these cannot be removed
            from it without contradicting that sentence, and reference-position
            usage (`ds.param("layers").field("width").sum()`, written before
            any type is known at the reference site) needs them universally
            available regardless. A private `_as(cls, **changes)` helper on
            `ParamExpr` builds a *different* concrete subclass from `self`'s
            current field values (`dataclasses.replace()` can't do this — it
            always returns `type(self)`). New `build/_views.py` holds:
            `FreshParamExpr(ParamExpr)` — the 9 type methods, each returning
            `self._as(TargetView, ...)`; `_TypedParamExpr(ParamExpr)` — the
            shared `.repeat()`/`._repeat_one()` implementation (identical
            logic to before, relocated), inherited by every narrowed view and
            by `ListParamExpr` itself (so nested lifts and `.repeat(2, 3)`
            keep working unchanged); `_NumericParamExpr(_TypedParamExpr)` —
            `.log_scale()`/`.quantized()`, inherited only by `RealParamExpr`/
            `IntegerParamExpr`; the 9 named views plus `ListParamExpr`, each a
            thin `pass`-body subclass of the appropriate one of the above.
            Ordinary modifiers (`.prior()`, `.tag()`, …) need no special
            handling: `dataclasses.replace()` on an undecorated subclass of a
            frozen dataclass returns `type(self)`, so they preserve the
            caller's view automatically.

            **Combinatorial queries stay universal, not split per the spec
            paragraph.** `.contains()`/`.size()`/`.sum_over()`/`.position_of()`
            remain on the base, unchanged from pre-M4.6 behavior — *not*
            narrowed to match the literal "SubsetParamExpr/PermutationParamExpr
            have `.contains()`/`.size()`/`.position_of()`/`.sum_over()"
            wording. That wording, read as an exhaustive per-class table,
            would put `.contains()` on `PermutationParamExpr`, but row 18
            (frozen error-table text, tag R) *requires* `.contains()` on a
            permutation to be a resolution error, and the already-implemented,
            already-tested `_require_subset_domain`/`_require_permutation_domain`
            checks in `resolve/_expr_checks.py` already enforce exactly that
            split (`.contains()`/`.size()`/`.sum_over()` require a subset
              domain; `.position_of()` requires a permutation domain). CLAUDE.md
            forbids weakening a stated law to resolve an ambiguity, so the
            parenthetical is read as loose descriptive prose (naming the kinds
            of query methods combinatorial params use) rather than a precise
            membership table, and the existing, law-consistent split is left
            untouched. Static (mypy) per-view narrowing of these four methods
            is not attempted this milestone — no Gate test requires it, and
            row 18 already covers the runtime law regardless of what an IDE
            offers.

            **`__getattr__`, and where it deliberately overrides the plan's
            own "non-type-method miss stays a normal AttributeError" line.**
            One `__getattr__` on the base `ParamExpr`, inherited everywhere;
            it fires only when normal attribute lookup fails (i.e., only on
            the views that genuinely lack the method):
              - The 9 type-method names → `ResolutionError`, path-named,
                "(row 2)" — fires on any narrowed view or `ListParamExpr`
                (which lack them) but never on `FreshParamExpr` (which has
                them as real methods, so lookup never fails).
              - `log_scale`/`quantized` → `ResolutionError`, path-named,
                "(row 11)" — branches on `self.lift is not None` to
                distinguish "written after `.repeat()`" from "wrong type",
                matching `_check_modifier_placement`'s existing wording
                closely enough that `match="row 11"` in
                `tests/unit/test_resolve_m4.py::TestRow11MisplacedLayerModifier`
                keeps passing unchanged. Fires on every view except
                `RealParamExpr`/`IntegerParamExpr`.
              - Anything else → plain `AttributeError`, per the plan.
            The `log_scale`/`quantized` branch is a **deliberate departure**
            from the plan's Build-section sentence "a non-type-method miss
            stays a normal AttributeError" — that sentence was written with
            only the 9 type methods in view and doesn't account for the
            Gate's separate requirement that `.log_scale()` be statically
            absent from `CategoricalParamExpr`. Once `.log_scale()`/
            `.quantized()` move into `_NumericParamExpr` (required for the
            Gate's mypy check), leaving their absence as a bare
            `AttributeError` would silently downgrade row 11 (frozen
            error-table text, tag R: must be a `ResolutionError`) for the
            fluent path, and would also break the existing tests
            `TestRow11ModifierPlacement.test_quantized_on_categorical_raises`
            and `TestRow11MisplacedLayerModifier.{test_prior_after_repeat_raises,
            test_quantized_after_repeat_raises}`, none of which this milestone
            is permitted to weaken. Per the plan's own conflict rule (spec
            outranks plan), the frozen error table wins over the Build
            section's one-line generalization. `.repeat()` before a type is
            chosen (`ds.param("x").repeat(4)`) is *not* given the same
            treatment — it stays a plain `AttributeError` (mypy already
            catches it statically; no test exercises the runtime path; the
            plan's default sentence is left standing where nothing forces an
            exception).

            **Resolution-time backstops that become hand-built-only.** After
            this split, `_check_types_and_names`'s `len(type_methods) > 1`
            branch and `_check_modifier_placement`'s numeric/weighted checks
            for `quantized_spec` are no longer reachable via the fluent
            builder (the `__getattr__` trap fires first) — they remain live
            only as the "however it was built" backstop for a hand-constructed
            `ParamExpr`. This mirrors `type_calls`'s own status exactly and is
            not dead code: the M4.6 gate requires a message-content test for
            both the fluent and the programmatically-built two-type case, and
            an equivalent programmatically-built test is added for the
            quantized-on-categorical backstop.
Spec delta: The "Builder view types" paragraph's parenthetical grouping of
            `.contains()/.size()/.position_of()/.sum_over()` under both
            `SubsetParamExpr` and `PermutationParamExpr` should be reworded to
            match row 18 and the Combinatorial table's existing per-method
            ownership (`.contains()`/`.size()`/`.sum_over()` → subset;
            `.position_of()` → permutation) — not fixed in this milestone
            since the spec text is otherwise correct and this is a wording-only
            fix to a non-normative descriptive aside.

## D-29 (M4.6) — `type_kind` becomes a `ClassVar`; `type_calls` retired

Question:   D-28 kept `type_kind` a plain instance field and `type_calls` a
            plain instance field, reasoning that (a) resolve/_pipeline.py's
            internal synthetic-element construction builds a bare `ParamExpr`
            outside the view hierarchy and needs *something* settable to
            carry its kind, and (b) row 2's "however it was built" law needs
            a hand-buildable *invalid* state to check against, which a
            class-derived `type_kind` cannot represent. Post-implementation
            review asked directly: is that still true once the fluent route
            can no longer produce a type mismatch at all (D-28 already
            established this), and can (a) be worked around cheaply enough
            that (b) stops being a reason to keep a redundant field around?
Options:    (a) leave D-28's choice as shipped — plain field, `type_calls`
            retained as a resolution-time backstop for hand-built defs;
            (b) make `type_kind` a genuine `ClassVar` per view (excluded
            from `__init__` via dataclass's own ClassVar handling) and
            retire `type_calls` and the "more than one type" branch of
            `_check_types_and_names` entirely, accepting that
            resolve/_pipeline.py's synthetic-element construction must
            change to match.
Choice:     (b). Empirically verified (not assumed) two things that make (b)
            cheap: first, declaring `type_kind` as a genuine
            `ClassVar[str | None]` *on `ParamExpr` itself* (the only class in
            the hierarchy actually processed by `@dataclass`) means every
            subclass can override it with a plain class attribute —
            `RealParamExpr.type_kind: ClassVar[str] = "real"` — without
            itself needing `@dataclass` redecoration; dataclass's field
            collection excludes `ClassVar`-annotated names wherever they are
            declared, so no subclass ever gets `type_kind` back as a
            constructor argument (`ParamExpr(path="x", type_kind="integer")`
            raises `TypeError: unexpected keyword argument`, both on the
            base and on every leaf). This was not obvious in advance — an
            earlier, wrong mental model (that every subclass needs its own
            `@dataclass` redecoration for `ClassVar` exclusion to apply) was
            corrected by writing and running the actual pattern before
            committing to it, twice: once to confirm a `ClassVar` declared
            *only* on a subclass, with the field still real on the base, is
            a complete no-op (the inherited `__init__` unconditionally sets
            the instance attribute, silently shadowing the class constant —
            `Real(path="x").type_kind` reads `None`, and `Real(path="x",
            type_kind="integer")` is accepted and reads back `"integer"`);
            and once more to confirm declaring it as `ClassVar` on the base
            itself is sufficient and needs no redecoration downstream.

            Second, (a)'s reason (a) dissolves with a mechanism change, not
            a compromise: `_ElementSnapshot.type_kind: str` becomes
            `_ElementSnapshot.element_class: type[ParamExpr]` — captured as
            `type(self)` in `_TypedParamExpr._repeat_one()` (always a
            concrete leaf class there, never `None`, since `.repeat()` only
            exists on typed views and modifiers preserve the caller's class
            via `replace()`). resolve/_pipeline.py's synthetic-element
            construction becomes `inner.element_class(path=..., domain=...,
            ...)` — reinstantiating the *actual* view the element was
            declared with, not a bare `ParamExpr` carrying a borrowed
            `type_kind` string. This is strictly better than the dispatch
            table (`{"real": RealParamExpr, ...}`) considered and rejected
            in the same discussion: no table to keep in sync when a new type
            is added, and it eliminates a second redundant field
            (`_ElementSnapshot.type_kind`) that D-28 didn't touch. Every
            other read site that needs the plain IR string (`ListDomain.
            element_kind`, `build_chart`'s `type_kind` argument) now derives
            it via `element_class.type_kind` — one source of truth. Two
            string comparisons became class comparisons for the same reason
            (`inner.element_class is ListParamExpr` instead of
            `inner.type_kind == "list"`; `inner.element_class in
            (StructParamExpr, ChoiceParamExpr)` instead of a string-tuple
            membership test) — not required for correctness, but consistent
            with leaning on the type system where D-28 was leaning on string
            comparison out of caution.

            With (a) gone, `type_calls` has no remaining job: the "more than
            one type" branch of `_check_types_and_names` is deleted outright
            (not just unreachable-but-kept, as D-28 left it) — there is no
            longer any object, fluent or hand-built, that can carry
            conflicting type information for it to check. The "no type
            chosen" branch survives as `if d.type_kind is None`, reading the
            same `ClassVar` a `FreshParamExpr`/bare `ParamExpr` inherits.
            Row 2's "however it was built" guarantee is now stronger than a
            resolution-time check: it holds at the Python object-model level,
            before `ds.space()` is ever called, provable by the language
            itself rather than by a test asserting a check still fires.
            `_check_modifier_placement`'s numeric/weighted backstop is
            unaffected and stays — `quantized_spec`/`prior_spec` remain
            ordinary settable fields on every view (D-28's universal-modifier
            choice was untouched by this decision), so a hand-built
            `CategoricalParamExpr(quantized_spec=...)` is still constructible
            and still needs resolution to catch it; only the *type*-carrying
            field moved, not every field capable of an internally
            inconsistent value.

            Test consequence: `TestRow2SecondTypeMethod
            .test_programmatically_built_two_type_definition_raises`
            (D-28's gate test for the hand-built case) no longer has
            anything to construct — its scenario is a `TypeError` at the
            `ParamExpr(...)` call itself, before any `ResolutionError` logic
            runs. Replaced with `TestTypeKindIsNotAConstructorArgument`,
            asserting the stronger guarantee directly (`type_kind=` rejected
            on both the base and a leaf view; `FreshParamExpr`/leaf
            `type_kind` reads correctly). The quantized-on-categorical
            backstop test is retained, updated to construct
            `CategoricalParamExpr(...)` directly instead of a bare
            `ParamExpr(type_kind=..., type_calls=...)`.
Spec delta: None — API_v3.md's `ParamDef.type_kind remains a string` and
            "the views add no state beyond ParamExpr" both still hold
            (`ClassVar`s are not dataclass fields, so `fields(RealParamExpr)
            == fields(ParamExpr)` continues to be true); this is purely a
            builder-layer mechanism refinement of D-28's own choice.
