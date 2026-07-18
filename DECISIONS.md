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

## D-28 (M4.6) — View-class mechanism: `type_kind` as `ClassVar`, the method
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
            a plain instance field, keep `type_calls` as a resolution-time
            backstop for a hand-built two-type definition.
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
Choice:     (a) for the `type_kind` question, (b) for the other two.

            **`type_kind`/`type_calls`.** `type_kind` is a genuine `ClassVar`
            declared on `ParamExpr` itself (the only class in the hierarchy
            actually processed by `@dataclass`) — `ClassVar[str | None] =
            None`. Every leaf view overrides it with a plain class attribute
            (`RealParamExpr.type_kind: ClassVar[str] = "real"`, …) with *no*
            `@dataclass` redecoration of its own: dataclass excludes
            `ClassVar`-annotated names from field collection wherever they
            are declared in the hierarchy, so `type_kind` never becomes a
            constructor argument anywhere — `ParamExpr(path="x",
            type_kind="integer")` and `RealParamExpr(path="x",
            domain=RealDomain(0, 1), type_kind="integer")` both raise
            `TypeError: unexpected keyword argument`. `type_calls` is
            deleted outright, and with it `_check_types_and_names`'s "more
            than one type" branch — there is no longer any object, fluent or
            hand-built, capable of carrying conflicting type information for
            such a check to catch. Row 2's "however it was built" guarantee
            (API_v3.md: "resolution still rejects any definition that
            carries more than one type however it was built... the law
            holds for programmatically-constructed definitions as well as
            fluent ones") therefore holds at the Python object-model level —
            provable by the language itself, before `ds.space()` is ever
            called — rather than by a resolution-time check a test has to
            assert still fires. The "no type chosen" half of row 2 survives
            as `if d.type_kind is None`, reading the same `ClassVar` a bare
            `ParamExpr`/`FreshParamExpr` inherits.

            This was not the first design tried, and getting it right took
            writing and running the actual mechanics before trusting them,
            not reasoning from memory about dataclass/`ClassVar` interaction.
            The naive version — declaring `type_kind: ClassVar[str] = "real"`
            only on a subclass while the base still treats the name as a
            real field — is a silent no-op: the base's inherited `__init__`
            unconditionally sets the instance attribute (using the field's
            default when no value is passed), which shadows the class
            constant every time. `Real(path="x").type_kind` reads `None`
            under that version, not `"real"`, and `Real(path="x",
            type_kind="integer")` is silently *accepted*. Declaring the
            `ClassVar` on the base — so dataclass never treats `type_kind`
            as a field anywhere in the hierarchy — is what actually works,
            confirmed by running both versions before committing to either.
            The initial (wrong) assumption that this would require
            redecorating every one of the 10+ view classes with `@dataclass`
            individually (a much larger, resolve/-touching diff) is why a
            plain-field-plus-`type_calls`-backstop design was considered at
            all; once the cheaper, correct mechanism was verified, there was
            no remaining reason to keep a redundant field and a resolution
            check standing in for what the type system now guarantees
            structurally.

            `resolve/_pipeline.py`'s internal synthetic-element construction
            (the one non-fluent, non-hand-built `ParamExpr`-adjacent
            construction site that predates this decision) is the other
            piece this touches: `_ElementSnapshot.type_kind: str` becomes
            `_ElementSnapshot.element_class: type[ParamExpr]`, captured as
            `type(self)` in `_TypedParamExpr._repeat_one()` (always a
            concrete leaf class there — `.repeat()` only exists on typed
            views, and modifiers preserve the caller's class via
            `replace()`). The synthetic element is then built as
            `inner.element_class(path=..., domain=..., ...)` — reinstantiating
            the *actual* view the element was declared with, which is what
            gives it a real `type_kind` at all now that the field can't be
            passed directly. This is better than the dispatch-table
            alternative considered (`{"real": RealParamExpr, ...}`): no table
            to keep in sync when a new type is added, and it removes a
            second field that duplicated the same information
            (`_ElementSnapshot.type_kind`). Sites that still need the plain
            IR string (`ListDomain.element_kind`, `build_chart`'s
            `type_kind` argument) derive it via `element_class.type_kind` —
            one source of truth. A couple of string comparisons became class
            comparisons for the same reason (`inner.element_class is
            ListParamExpr` instead of `inner.type_kind == "list"`;
            `inner.element_class in (StructParamExpr, ChoiceParamExpr)`
            instead of a string-tuple membership test).

            `_check_modifier_placement`'s numeric/weighted backstop is
            unaffected: `quantized_spec`/`prior_spec` remain ordinary,
            freely-settable fields on every view (nothing about *this*
            decision touches them), so a hand-built
            `CategoricalParamExpr(quantized_spec=...)` — bypassing
            `.quantized()`, which doesn't exist on that view — is still
            constructible and resolution still has to catch it. Only the
            type-carrying field moved to being structurally unrepresentable;
            fields that can still independently misrepresent a param remain
            the resolution layer's job, unchanged.

            Test consequence: the gate's "programmatically-built two-type
            definition" test has nothing left to construct (its scenario is
            now a `TypeError` at the `ParamExpr(...)` call itself); it is
            replaced by `TestTypeKindIsNotAConstructorArgument`, asserting
            the stronger guarantee directly (`type_kind=` rejected on both
            the base and a leaf view; `FreshParamExpr`/leaf `type_kind`
            reads correctly). The quantized-on-categorical backstop test is
            retained, updated to construct `CategoricalParamExpr(...)`
            directly instead of a bare `ParamExpr(type_kind=...,
            type_calls=...)`.

            **The class hierarchy.** `build/_paramexpr.py` keeps `ParamExpr`
            with the identity/domain-level modifiers that stay universal
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
            always returns `type(self)`, which is exactly right for ordinary
            modifiers, which must preserve the caller's view). `build/_views.py`
            holds: `FreshParamExpr(ParamExpr)` — the 9 type methods, each
            returning `self._as(TargetView, ...)`, inheriting the base's
            `type_kind = None`; `_TypedParamExpr(ParamExpr)` — the shared
            `.repeat()`/`._repeat_one()` implementation, inherited by every
            narrowed view and by `ListParamExpr` itself (so nested lifts and
            `.repeat(2, 3)` keep working unchanged); `_NumericParamExpr
            (_TypedParamExpr)` — `.log_scale()`/`.quantized()`, inherited only
            by `RealParamExpr`/`IntegerParamExpr`; the 9 named views plus
            `ListParamExpr`, each a one-line subclass of the appropriate one
            of the above, adding only its `type_kind` `ClassVar` override.
            None of this needs `@dataclass` redecoration anywhere below
            `ParamExpr` — see above.

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

            One `__getattr__`-adjacent subtlety worth recording since it
            nearly went unnoticed: a class with a *statically visible*
            `__getattr__` is treated by mypy as accepting any attribute
            name, which would have silently defeated the Gate's static-typing
            check (`.categorical(...).log_scale()` must be a real
            `attr-defined` error). `if not TYPE_CHECKING:` around the
            `__getattr__` definition makes mypy skip it entirely while it
            still runs normally at import time — confirmed empirically, the
            same way as the `ClassVar` mechanics above: `attr-defined` fires
            under mypy, the runtime exception still raises under CPython.
Spec delta: The "Builder view types" paragraph's parenthetical grouping of
            `.contains()/.size()/.position_of()/.sum_over()` under both
            `SubsetParamExpr` and `PermutationParamExpr` should be reworded to
            match row 18 and the Combinatorial table's existing per-method
            ownership (`.contains()`/`.size()`/`.sum_over()` → subset;
            `.position_of()` → permutation) — not fixed in this milestone
            since the spec text is otherwise correct and this is a wording-only
            fix to a non-normative descriptive aside. No delta for the
            `type_kind`/`ClassVar` mechanism itself: API_v3.md's `ParamDef.
            type_kind` remains a string, and "the views add no state beyond
            ParamExpr" still holds (`ClassVar`s are not dataclass fields, so
            `fields(RealParamExpr) == fields(ParamExpr)`) — this is purely a
            builder-layer mechanism choice, invisible to the spec.

## D-29 (M5) — Expression bounds: hull direction, minimal op set, eager
scoping, the bound-origin polarity/margin interaction, and tighten-not-reject
family gating

Question:   Five points API_v3.md's "Expression bounds are sugar" leaves open
            or (in one case) genuinely in tension with an existing, already-
            normative law:
            (1) A bound expression's envelope is "the interval-arithmetic hull
            ... computed along the dependency DAG" — but a hull is an
            *interval*, and a domain's `lo`/`hi` are each a single number.
            Which end of the hull does a hi-bound's envelope take, and which
            does a lo-bound's?
            (2) "Interval arithmetic over a minimal op set" (the plan's Build
            line) — which operations are in that set, and what exactly does
            "by constants" mean for `*` (a literal operand, or any
            sub-expression that happens to be constant-valued)?
            (3) `.when()` conditions tolerate an enclosing-scope up-reference,
            deferred to `check_fully_resolved` (D-26). Do bound expressions
            get the same tolerance?
            (4) The spec states the sugar desugars to "the implicit hard
            constraint `ds.param("x") <= ds.param("y")`" *and*, separately,
            that this coupling "yields a `y − x` margin." But the existing,
            already-tested `is_violated` (`eval/_constraint_eval.py`, D-4)
            hard-codes one global invariant: `hard=True` ⟺ the stored predicate
            names the *forbidden* state (violated iff satisfied). Storing the
            literal sugared predicate `x <= y` (the *desired* state) under
            `hard=True` breaks that invariant outright — satisfied-and-good
            would register as violated. Which one gives?
            (5) The spec explicitly flags that tightening an external prior
            needs `cdf` (rejection otherwise) — does that caveat generalize to
            other families (quantized grids), and is "recognize a bound-origin
            constraint and tighten" mandatory or best-effort?
Options:    For (1): (a) hi-bound envelope = hull's supremum, lo-bound
            envelope = hull's infimum; (b) always take the hull's own
            "natural" bound (whichever end the expression's own operators
            happen to produce, with no fixed rule); (c) reject any bound
            expression whose hull isn't already a degenerate point, forcing
            every dependency to be a plain literal.
            For (2): (a) `+`/`-` between any two computable sub-hulls, `*`
            only when one operand is *syntactically* a `Literal` node; (b)
            allow `*` between any two sub-hulls generally (full interval
            multiplication, four-corner-product rule); (c) treat any
            sub-expression whose *computed hull happens to be a point*
            (`lo == hi`) as a "constant" for `*` purposes, not just literal
            nodes.
            For (3): (a) eager — a bound expression is checked and resolved
            entirely within its own scope, no up-reference tolerance,
            mirroring `.forbid()`/`.constrain()` (which "stay strict and raise
            eagerly" per the spec's own Resolution-timing paragraph); (b) the
            same deferred-to-finalization treatment as conditions (D-26).
            For (4): (a) store the forbidden state (`x > y` for a hi-bound),
            keeping `is_violated`'s single hard-keyed formula untouched, and
            accept whatever margin sign that shape produces; (b) store the
            desired state (`x <= y`, matching the spec's literal sugar text)
            and generalize `is_violated` to key polarity off `Constraint.
            origin` instead of `hard` alone for this one provenance.
            For (5): (a) tighten only for the built-in closed-form families
            (uniform / `Log` / `Logit` / `Power`) over a non-quantized
            real/integer, falling back to the pre-existing hard-constraint
            rejection everywhere else; (b) attempt tightening universally,
            including external priors and quantized grids.
Choice:     (1)(a). A hi-bound's envelope must be the *widest* value the
            expression could ever take — `x` must be able to reach that value
            under *some* legal assignment of its dependencies, since charts
            are static and built once, independent of any one config
            ("All charts are static": "the genotype→phenotype map ... never
            depends on other genes"). The generated bound-origin constraint is
            what narrows the domain back down *per config*; the envelope only
            has to cover every config that could ever need it. Symmetrically
            for a lo-bound's infimum. (c) was rejected as needlessly narrow —
            it would reject the spec's own worked example the moment `y` had
            any prior/quantization beyond a bare literal.

            (2)(a). `+`/`-` are unrestricted (both a constant and an
            enveloped-param operand compute cleanly via standard interval
            addition/subtraction: `[l1,h1]+[l2,h2] = [l1+l2, h1+h2]`;
            subtraction similarly with the right interval's ends swapped).
            `*` is restricted to *syntactically* literal because interval
            multiplication between two genuinely-variable sub-hulls needs the
            four-corner-product rule (`min/max` over `lo·lo, lo·hi, hi·lo,
            hi·hi`) — a small step up in mechanism, but the plan's Build line
            says "minimal op set" and CLAUDE.md's out-of-scope list bars "no
            algebraic expression normalization," which a `lo==hi` semantic
            check for (c) would edge toward (deciding "constant-ness" by
            evaluating a sub-hull rather than by syntax). Recursion already
            handles the common chained case for free — `y * 2 * 3` is two
            literal-on-one-side `mul` nodes, each independently computable —
            so (a) loses no real expressiveness a spec-consistent minimal
            engine should have. Two non-constant operands multiplied (`x * y`)
            is row 20, with the stated workaround (write the desugared literal
            bound and constraint by hand) always available.

            (3)(a). A chart is built *during* the bound-owning param's own
            `resolve_space` call — before any enclosing scope has merged in.
            An up-reference literally cannot be resolved yet at the point a
            chart needs its envelope, unlike a condition (only evaluated
            later, at sample/validate time, by which point finalization has
            run). Deferring bound-ref resolution the way D-26 defers
            conditions would require deferring chart-building itself past
            `resolve_space`, a far larger restructuring the spec never asks
            for. Eager is also consistent with the *other* half of the same
            Resolution-timing paragraph: constraints — which a bound
            expression's implicit constraint literally becomes — are already
            carved out as the strict, eager exception to conditions'
            tolerance ("cross-scope constraints use the down-reference-at-
            the-common-ancestor route instead"). Bound expressions in practice
            reference sibling params in the same declaring scope (the spec's
            own `ds.param("y")` example), so this is no real restriction on
            the common case, only on a construct (an up-scope bound
            reference) the spec never demonstrates.

            (4)(b), discovered empirically, not just reasoned to on paper:
            implementing (4)(a) first (`x > y`, `hard=True`, `is_violated`
            unchanged) gives a margin of `x - y` by the existing margin table
            (`a > b` ⇒ `a - b`) — the *negation* of the spec's stated `y - x`.
            The margin table's four fixed formulas admit exactly one stored
            shape that produces `y - x`: `Compare("le", x, y)` (`a <= b` ⇒
            `b - a`). That shape is also, verbatim, the spec's own sugar
            description — so it is simultaneously the literal reading of two
            separate spec sentences ("the implicit hard constraint `x <= y`"
            and "yields a `y - x` margin"), which only coexist if `is_violated`
            stops assuming `hard` alone determines polarity. `.forbid()`'s
            "stores the forbidden state" convention is a property of *that
            API path* — a user calling `.forbid(cond)` is defining `cond` to
            be the bad thing by the act of calling `.forbid()` — not a law
            every `hard=True` `Constraint` must independently satisfy
            regardless of how it was constructed. A bound-origin constraint is
            never built through `.forbid()`; nothing obligates it to that
            convention. `is_violated` now reads: `origin == "bound"` ⇒
            violated iff not satisfied (regardless of `hard`); otherwise
            unchanged (`satisfied == hard`). This was caught by an end-to-end
            check, not a unit test in isolation — a hard bound-origin
            constraint on a config that plainly violated it (`x=90 > y=10`)
            came back `validate().valid == True` under the naive (4)(a)-then-
            unmodified-`is_violated` combination, which is exactly the class
            of bug this project's "never resolve an ambiguity by weakening a
            stated law" rule exists to catch before it ships. This choice also
            has a forward-looking payoff: M7 promises the sugared form and its
            manual expansion are fingerprint-equal with `origin` excluded from
            the preimage — but the *expr shape* is not excluded, so the two
            forms must already store the same shape. Storing `x <= y` (the
            literal sugar text) is what makes that future equality possible at
            all; a forbidden-state `x > y` would have made it structurally
            impossible no matter what `origin` does. The sharp edge this
            creates: the "hand-written equivalent" of the sugar is
            `.forbid(ds.param("x") > ds.param("y"))`, *not*
            `.forbid(ds.param("x") <= ds.param("y"))` — a user who reads the
            spec's desugaring sentence and transcribes it verbatim into a
            `.forbid()` call gets inverted feasibility. Recorded in
            `is_violated`'s docstring and in
            `tests/conformance/test_bounds.py`'s module docstring so this
            doesn't have to be rediscovered.

            (5)(a). The spec's own external-prior caveat ("tightening ... to a
            sub-interval needs `cdf`; absent that, rejection") is explicit
            about *why* universal tightening is unsafe: rebuilding a support-
            contained external-prior chart with a narrower hi can push it into
            needing truncation it has no `cdf` for, raising mid-sample instead
            of degrading to rejection. Quantized/grid domains are excluded too
            — cell-boundary interaction under a narrowed extension is
            certainly *computable* but subtler to prove equivalent, and
            nothing in the Gate requires it this milestone. Tightening is a
            pure optimization layered *in addition to* the hard constraint
            already sitting in `space.constraints` (from resolution) — every
            un-tightened case (external, quantized, or an unassigned/Unknown
            dependency at draw time, or an infeasible tightened interval)
            falls through unchanged to the pre-existing rejection path, so
            nothing about correctness depends on the family list being
            complete, only on it being *sound* (never tightening somewhere
            truncation ≠ conditioning).
Spec delta: None. All five points are resolvable within the existing text
            once (4)'s tension is noticed — API_v3.md's sugar-description and
            margin sentences are both literally true simultaneously, they
            just require `is_violated`'s hard/polarity coupling (a resolve/
            eval-layer mechanism, not spec text) to key off `origin` instead
            of `hard` for this one provenance. Candidate for a future
            clarifying footnote at "Expression bounds are sugar": the implicit
            constraint's polarity is *not* `.forbid()`'s "argument names the
            forbidden state" convention.
