# Decisions

This file is an interpretation log for genuine gaps in `API.md`. It is not a general ADR
diary, progress log, or place to justify divergence from a clear requirement.

When a question is resolved, update `API.md` so future work no longer depends on reading
the historical entry. Keep the entry here to preserve why the answer was chosen.

## Entry template

Copy this template for each genuine specification gap.

```markdown
## Q-0001 — Short title

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

**Note:** Decision template was changed, format below is outdated template.

## D-30 (M6) — Partial-status corners the spec leaves to derivation

Question:   API.md's Partial Configs section states the container rule for
            lifts explicitly ("A list container is `set`/`unknown`/`inactive`,
            never `active_unset`") but is silent on three adjacent corners:
            (1) what status an active list container gets when its count is
            itself pending on an unresolved dependency; (2) whether a struct
            container (which likewise has no own value) gets the same
            never-`active_unset` treatment; (3) how far `remaining_domain`'s
            one-unset-operand reducer should reach across param *kinds*
            beyond the numeric bound-origin case the spec worked through.
Options:    (1) "unknown" vs "active_unset" vs "set" for a pending-count list
            container; (2) treat struct containers like ordinary scalar leaves
            (so an active-but-unfilled struct reads `active_unset`, which is
            meaningless — it has no value to await) vs. like list containers;
            (3) implement the reducer only for `Compare` over real/integer, or
            extend it to categorical/ordinal/bool/choice value-sets and subset
            membership too.
Choice:     (1) "unknown" — it is the only value consistent with the
            container being active (ruling out `inactive`) while its shape is
            still undetermined (ruling out `set`, and `active_unset` is
            already ruled out by the spec's own rule for this container kind).
            (2) Struct containers collapse `active` -> `set` exactly like list
            containers, for the identical reason: no own value, so
            `active_unset` cannot apply. (3) The reducer is implemented for
            `Compare`-shaped feasible predicates over `RealRemaining`/
            `IntegerRemaining` (interval narrowing, `!=` excluded as
            hole-punching) and `ValueRemaining` (exact eq/ne set filtering,
            plus ordinal position-based `<`/`>`/`<=`/`>=` via declared index),
            and `Contains`-shaped predicates over `SubsetRemaining` (forced-in/
            forced-out). `PermutationRemaining` is never reduced (stated
            explicitly in the IR docstring). Per-instance (lift-element)
            constraint templates are not consulted by `remaining_domain` —
            only `space.constraints` — a further soundness-preserving
            (never-excludes-a-feasible-value), or-completeness-costing,
            simplification.
Spec delta: none needed — every choice here is a forced consequence of
            already-stated rules ("no own value" for structs/lists; "sound,
            not complete" for the reducer), not a genuine two-reading fork.
            Recorded for traceability rather than because the spec conflicts
            with itself.

---

## D-31 (M7) — External `Prior` objects are not in the enumerated
non-serializable set, but have no structural encoding

Question:   API_v3.md, "to_json / from_json": "The non-serializable set is
            closed and enumerated: the `.custom(sampler, validator)`
            shorthand, `code`/`symbolic` `validators`, `symbolic` `sampler`,
            `Primitive.fn`." An external `Prior` (any object satisfying
            `.ppf(q)` required / `.cdf(value)` optional, "Charts" > "External
            priors") is not in that list, yet it is an opaque callable-ish
            object with no `type_key`/`describe()` protocol of its own — the
            spec never says how it participates in `to_json`/`fingerprint`.
Options:    (a) treat it like the enumerated callables: raise by default,
            `on_unserializable="mark"` → `{"$opaque": true}` at the prior
            slot, `"drop"` omits + manifests; (b) require external priors to
            additionally implement a `type_key`/`describe()` protocol (like
            M9 custom types) before they can serialize at all, otherwise
            reject even construction; (c) silently coerce to a built-in
            family — impossible in general (no ppf ⟶ closed-form mapping) and
            would violate "no algebraic normalization."
Choice:     (a). It is the least-surprising reading: it extends the spec's
            own stated pattern for opaque content (callables) to another kind
            of opaque content (a duck-typed numeric object), rather than
            inventing new public surface (a prior-level serialize protocol)
            that appears nowhere in API_v3.md. (b) would add API not in the
            spec and freeze untested bytes — no corpus fixture uses an
            external prior, so nothing exercises it either way; (a) costs
            nothing later, since a future milestone can add structural prior
            encoding *additively*, gated on `describe()` being present,
            without touching the opaque-sentinel path for priors that still
            lack it. Documented limitation, same as callables under `"mark"`:
            two spaces differing only in an external prior's behavior at the
            same site are fingerprint-equal. Built-in families (`Log`,
            `Logit`, `Power`, `Weights`, and the `None`/uniform default) stay
            fully structural — this only affects the `Prior` protocol case.
Spec delta: add external `Prior` objects to the enumerated non-serializable
            set in "to_json / from_json", alongside the existing four.

## D-32 (M7) — JCS implementation: dependency exception, not hand-rolled

Question:   PLAN.md.md's M7 line says "implement JCS in-repo or
            vendored, do not add a dependency without a DECISIONS entry."
            RFC 8785's one genuinely fiddly piece is the ES6 number-to-string
            algorithm (exponent thresholds, shortest-round-trip mantissa,
            trailing-zero/sign rules) — worth getting from a tested source
            rather than reimplementing for a serializer whose bytes are about
            to stabilize.
Options:    (a) implement ES6 number formatting in-repo against Python's
            `repr()` plus RFC 8785's published `es6numbers.txt` vectors as an
            oracle; (b) take a documented deviation from ES6 (Python `repr`
            directly) and record it; (c) add a small, focused, actively
            maintained dependency (`rfc8785`) and spend the effort on our own
            canonical-tree construction instead.
Choice:     (c). `rfc8785` (Trail of Bits, pure-Python, `py.typed`, MIT-style
            license, no transitive dependencies) implements `dumps(obj) ->
            bytes` matching RFC 8785 exactly, including the ES6 number rule
            (spot-checked against subnormals, the `1e21`/`1e-7` exponent
            thresholds, and `-0.0 -> "0"`) and rejects NaN/Inf natively. Our
            own encoder still does all of the *semantic* canonicalization the
            library doesn't know about — type tags, `-0.0 -> 0.0` at the tag
            layer, subset/tag/anchor sorting, the bound-origin polarity flip
            — the library only replaces the final "serialize this already-
            canonical tree to deterministic bytes" step. That step is exactly
            the kind of narrowly-scoped, well-tested infrastructure the
            dependency policy's spirit (`numpy`-only, "nothing else without a
            DECISIONS entry") is gating, not forbidding. `rfc8785` becomes
            designspace's first non-`numpy` **core** dependency; pinned
            **exactly** `rfc8785==0.1.4` (not `>=`) — an already-frozen byte
            format wants the number-formatting library itself pin-stable too,
            since a transitive `>=` bump could silently shift every digest
            (including the committed known-answer vectors) with no signal
            beyond "the vectors broke." Bumping the pin later is a deliberate
            act, same discipline as the format-version protocol.
Spec delta: none — this is purely an implementation-strategy note, not a
            reading of the spec.

## D-33 (M7) — `fingerprint` scope field partition: chart geometry rides in
both scopes, not just under "domain, prior"

Question:   API_v3.md's fingerprint scope table lists a row "Params:
            definition path, kind, domain, prior, condition" checked for both
            `full` and `sampling`. `ParamDef.quantized` and `ParamDef.periodic`
            are separate fields, not nested inside `domain`, so a literal
            reading of the table would leave them out of *both* scopes —
            silently. But the prose right above the table says `sampling`
            "identifies feasible set + measure + chart geometry," and chart
            geometry is a function of domain *and* prior *and* quantized
            *and* periodic (a quantized real and its continuous twin have
            different measure and different `capability_report` shape).
Options:    (a) read the table literally — `quantized`/`periodic` in neither
            scope; (b) put them in `full` only (closer to "extra metadata"
            reading); (c) put them in both scopes, since they are chart
            geometry, not metadata.
Choice:     (c). (a) breaks "equal fingerprints ⟹ identical valid-config sets
            [and] sampling measure" outright — a quantized-step-1 real and an
            unquantized real over the same bounds would fingerprint-equal at
            `sampling` while sampling a materially different measure and
            reporting a different `capability_report`. (b) only half-fixes
            it: `sampling`'s own stated guarantee ("measure + chart
            geometry") still requires them. The table's "domain, prior" is
            read as shorthand for "everything that determines the chart,"
            consistent with the surrounding prose rather than overriding it.
Spec delta: expand the scope table's row to read "domain, prior, quantized,
            periodic" explicitly.

## D-34 (M7) — Which `Any`-typed leaf positions get type tags

Question:   The Identity normalization pipeline names four example positions
            for type tags ("categorical/ordinal values, defaults and anchor
            entries for such params, meta values") but the underlying rule is
            general: any position holding an application-level value of
            otherwise-unknown type needs a tag so `1 != 1.0 != True` survives
            encoding. The spec's list doesn't explicitly mention subset/
            permutation `items`, `IsIn`/`CountOf`/`SumOver`-mapping literal
            operands, or `ListDomain.element_default`/`list_default`, all of
            which are equally `Any`-typed data.
Options:    (a) tag only the four named positions, leaving the rest as bare
            JSON values (risking silent `1`/`1.0` collisions elsewhere); (b)
            tag every `Any`-typed leaf uniformly, named or not.
Choice:     (b). The spec's list reads as illustrative ("e.g. categorical/
            ordinal values, ...") not exhaustive — the stated purpose is
            "`categorical(1, 2) != categorical(1.0, 2.0)`" as an instance of a
            general type-tag-distinctness law, and the spec elsewhere says
            expression "literals type-tagged" without listing which
            expression node's literals. Applying the tag uniformly is the
            forced generalization of an already-stated rule, not a fresh
            reading — same category as D-30's entries. Positions that are
            *never* `Any`-typed application data (paths, `op` names,
            `type_kind` strings, `hard`/`periodic` booleans, lift `count`
            when it's a literal int, struct/list lengths) stay untagged.
Spec delta: none needed — generalization of an already-stated rule.

## D-35 (M7) — `config_diff` value equality is plain Python `==`, not
type-tagged

Question:   `config_hash`/`fingerprint` apply type-tagged equality so
            `1 != 1.0 != True` for hashing purposes. `config_diff` is
            described as "structural, no magnitude" but the spec doesn't say
            whether "changed" means type-tagged inequality or ordinary value
            inequality — under Python's native `==`, `1 == 1.0`.
Options:    (a) reuse the type-tagged comparison from the identity encoders,
            so a config that only changed a value's Python type (`1` ->
            `1.0`) is reported as a diff; (b) use plain Python `==`/`!=` on
            the flattened leaf values.
Choice:     (b). `config_diff` is a reporting/comparison utility ("what
            changed between two observations"), not a hashing law with
            frozen known-answer vectors — "no magnitude" reads as "don't
            compute numeric distance," not "adopt hashing's stricter type
            identity." Plain equality is the least-surprising default for a
            diff a human or a logging pipeline reads, and avoids a diff
            firing on what is, config-value-wise, the same number.
Spec delta: clarify that `config_diff` equality is ordinary value equality,
            distinct from `config_hash`/`fingerprint`'s type-tagged rule.

## D-36 (M7) — Meta values are JSON-serializable (recursively tagged), not
scalar-only — corrects an earlier draft of this entry

Question:   M2/M4.5's row-23 checks (`resolve/_pipeline.py
            ::_validate_tags_meta` for param `.meta()`; `resolve/_constraints.py
            ::_check_tags_meta` for `.forbid()`/`.constrain()` `meta=`) accept
            any `json.dumps`-able value — including lists and nested dicts.
            The Identity normalization pipeline's step 5 describes meta
            values encoding as tagged scalars (`{"$t": ..., "v": ...}` with
            tags `bool|int|float|str|null`), which an early reading took as a
            closed scalar set and, on that reading, tightened row-23
            construction-time validation to reject non-scalar meta. On
            closer reading, that tightening directly conflicts with the
            error table's own row 23, whose stated bar is literally
            "non-JSON-serializable meta value" — a list/dict value passes
            that bar. Two normative texts, read at face value, disagree.
Options:    (a) keep construction-time validation scalar-only (the earlier
            choice), and treat row 23's "JSON-serializable" wording as loose;
            (b) trust row 23's literal wording — validation stays
            "JSON-serializable" — and instead teach the identity encoder to
            recurse into lists/dicts, tagging each scalar *leaf*, exactly as
            already done for `ParamDef.default`/`ListDomain.list_default`/
            `element_default` (`identity/_tags.py::encode_default_value`,
            added for those fields in this same milestone because they too
            can be struct/list-shaped, not flat scalars).
Choice:     (b). Row 23 is normative error-table text, not prose open to a
            loose reading; its wording is specific ("non-JSON-serializable")
            and a list is JSON-serializable by any ordinary meaning of the
            phrase. Step 5's "meta values encode as {"$t": ..., "v": ...}"
            is read as describing the tagging rule for a scalar *leaf*, the
            same way `default`'s encoding is described by example
            elsewhere without that being a ban on struct/list-shaped
            defaults. Recursing costs nothing new: it is the identical
            generic codec already built for `default`/`list_default` this
            milestone, reused rather than duplicated narrower. The earlier
            (a) choice made resolution reject input the error table
            explicitly permits — a real spec conflict, not a stylistic
            preference — so it is corrected here rather than left standing.
            `check_meta_json_serializable` (`build/_names.py`, renamed from
            `check_meta_scalar`) now matches its name — but walks the value
            itself rather than delegating to `json.dumps`, which is *more*
            lenient than the identity encoder in two ways: it encodes a
            tuple as a JSON array (`encode_default_value` has no tuple
            branch and raises `SerializationError` — confirmed empirically:
            `.meta(t=(1, 2))` constructed under a first pass of this fix,
            then crashed at `fingerprint()`, the exact "fail late" bug D-36
            exists to prevent), and it coerces a non-string dict key to a
            string (`encode_default_value` keeps the original key, which
            then either round-trips as a different value or is rejected by
            the JCS canonicalizer at digest time). The check accepts exactly
            what `encode_default_value` round-trips faithfully: `None`/
            `bool`/finite `int`/`float`/`str`, or `list`/`dict` (string
            keys) thereof, recursively — not `json.dumps`'s looser notion of
            serializable. No corpus fixture uses non-scalar meta, so no
            committed vector changes; scalar meta encodes byte-identically
            before and after (`encode_default_value` on a scalar falls
            straight through to the same `tag_value` call `tag_value`/
            `untag_value` used directly before).
Spec delta: state explicitly that `meta` values (param- and constraint-
            level) may be any JSON-serializable value (matching row 23),
            and that step 5's scalar tagging example generalizes
            recursively to list/dict-shaped meta the same way it already
            does for `default`.

## D-37 (M7) — `config_hash`/`config_diff` are non-validating, like `flatten`

Question:   `config_hash`/`config_diff` are both built directly on
            `config/_flatten.py::flatten()`, which API_v3.md twice calls out
            as "structural and **non-validating**" ("transformed leaves need
            not be domain members"; the inline comment on its own line in
            the utilities list). Neither `config_hash`'s nor `config_diff`'s
            own line carries that annotation, and `validate` line 461 says
            "`validate` and `config_hash` operate on the raw phenotype
            representation only; transformed views have no identity" —
            grouping them on the raw-vs-transformed axis (which representation
            they read), not the validating-vs-not axis (whether they check
            it). Net effect as implemented: `ds.config_hash(ds.space(), some_space)`
            — passing a nonsense value, or even a whole other `Space` object,
            wherever a config dict was expected — degrades gracefully to
            walking whatever keys structurally match `some_space.params` and
            silently ignoring the rest, rather than raising. Is this the
            intended behavior, or a gap `flatten`'s explicit annotation
            (and `config_hash`/`config_diff`'s lack of it) leaves ambiguous?
Options:    (a) leave both non-validating, matching `flatten`'s stated
            behavior and the absence of any "non-validating" annotation
            being read as silence, not a contradiction — `config_hash`
            already composes with `validate()` for callers who want a
            checked key: `if space.validate(c).valid: key = config_hash(c,
            space)`; (b) make `config_hash`/`config_diff` require structural
            well-formedness (reusing/extracting `validate()`'s `param_errors`
            computation) before hashing/diffing, raising on shape mismatches;
            (c) require full `validate()` (structural **and** feasibility)
            before either function proceeds.
Choice:     (a). `config_hash`'s spec line (639) carries no "non-validating"
            annotation because it doesn't need one — it inherits `flatten`'s
            behavior *by construction*, the same way `config_diff` (640,
            annotated "structural, no magnitude" — a distinct, narrower
            concern about not computing a numeric distance, not about
            validating shape) does. Line 461's grouping is about
            *representation* (raw phenotype vs. a transformed view having no
            identity, an M11-relevant boundary), not an instruction that
            `config_hash` re-runs `validate`'s checks. Validating is not
            freeze-relevant: it is fully additive and reversible later —
            every currently-*valid* config hashes identically whether or not
            a future milestone adds a validating variant, so choosing (a) now
            costs nothing to revisit. (b)/(c) would also invent a new
            "structural-only, skip feasibility" validation mode that doesn't
            exist anywhere else in the codebase, and sits awkwardly against
            `config_hash`'s own job of grid-*canonicalizing* near-grid values
            — a value `validate()` would reject as `not_on_grid` is exactly
            the kind of input `config_hash` currently snaps onto the grid and
            hashes successfully; conflating the two would need its own design
            pass, not a quick addition at the freeze point. Separation of
            concerns is the least-surprising reading: `validate()` validates,
            `config_hash`/`config_diff` canonicalize/compare; callers compose
            them when they want both.
Spec delta: state explicitly, alongside `flatten`'s existing annotation, that
            `config_hash`/`config_diff` inherit the same non-validating
            behavior (they are built on `flatten`, not `flatten_with_errors`),
            and that callers wanting a validated key should call `validate()`
            first.

---
