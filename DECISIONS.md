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

## D-38 — `require` fingerprint canonicalization: whole-expression negation, not operator flip

- Status: Resolved
- Date: 2026-07-21
- Spec section: API.md §Identity ("Normalization pipeline"); §Constraints ("`require` — the positive complement")
- Decided by: User

### Question

How does a `require(e)` constraint canonicalize into the (frozen) fingerprint preimage,
and — since `require`'s canonical form must be feasibility-tracking — is it fingerprint-equal
to `.forbid(x > y)` for `require(x <= y)`, as one reading of §Identity states?

### Why the specification is insufficient

API.md gave two claims that cannot both be *syntactic* preimage equalities:

- §Constraints (and the M7.5 gate): `require(e)` is fingerprint-equal to `.forbid(~e)`.
- §Identity (normalization pipeline, parenthetical): `require(x <= y)` is fingerprint-equal
  to `.forbid(x > y)`.

`.forbid(~(x <= y))` stores `Not(Compare le)`; `.forbid(x > y)` stores `Compare gt`. The
freeze forbids the algebraic normalization that would merge them (it would also change
existing `implies`-using corpus fingerprints, e.g. `flow_chemistry`). So at most one of the
two equalities can hold as an IR-level (fingerprint) equality.

### Possibilities considered

1. **Whole-expression negation (`Not`-wrap).** `require(e)` canonicalizes to `Not(stored_expr)`
   — byte-identical to `.forbid(~e)`. Works for any predicate `e` (comparisons and composites
   alike) and satisfies the binding gate law. `require(x <= y)` is then fingerprint-*distinct*
   from `.forbid(x > y)` (they share a feasible set but not a preimage).
2. **Operator flip (like bound).** `require(x <= y)` → `Compare gt`, matching `.forbid(x > y)`.
   But this fails the gate law `require(e) ≡ forbid(~e)` for a `Compare` `e`, and cannot
   canonicalize a non-`Compare` `require(a & b)` at all — there is no single operator to flip.

### Answer

**Possibility 1.** `require` canonicalizes by whole-expression negation (`Not`-wrap), matching
`.forbid(~e)`. Bound-origin sugar keeps its operator-flip (a bound is always a single top-level
`Compare`, and this preserves all M7 known-answer vectors byte-identically). The §Identity claim
that `require(x <= y) ≡ forbid(x > y)` is reinterpreted as a **semantic (feasibility)** equivalence
— the same feasible set — **not** a syntactic/fingerprint one. This is sound because "equal
fingerprints ⇒ equal feasible sets" is one-way (API.md, §fingerprint): distinct fingerprints for
identical feasibility are permitted.

### Reasoning

Only Possibility 1 is implementable for a general `require(e)` and satisfies the gate law, which
is the binding acceptance criterion and agrees with the twice-stated §Constraints text. The freeze
rules out any expression normalization that would reconcile the two readings. The user confirmed
the intended meaning of the §Identity parenthetical is feasibility-semantic, not IR-syntactic.

### Specification update

API.md §Identity normalization-pipeline step (1) rewritten to describe the two provenance-specific
negation mechanisms (bound = operator flip; `require` = whole-expression `Not`) and to state
explicitly that `require(x <= y) ≡ forbid(x > y)` is a feasibility equivalence, fingerprint-distinct
from the `require`'s `~(x <= y)` canonical form. Implemented in `identity/_ir_codec.py`
(`_canonicalize_polarity`, since generalized) under milestone M7.5.

---

## D-39 — Constraint API symmetrization: `constrain` → `encourage`, add `discourage`, derived polarity accessors

- Status: Resolved
- Date: 2026-07-21
- Spec section: API.md §Constraints and Feasibility; §IR; §Identity
- Decided by: User

### Question

The constraint verbs formed an asymmetric set — hard `forbid`/`require` (a
polarity pair) but only a single soft `constrain` — and there was no intuitive
way to read a constraint's polarity ("is its stored predicate supposed to be
true or false?") for display: consumers had to re-derive it from `(origin,
hard)`, which broke silently when a `forbid` was switched to a `require`
(observed in `examples/03`). Should the API complete the 2×2 grid, and how?

### Why the specification is insufficient

`API.md` defined `forbid`/`require`/`constrain` with polarity only described in
prose; no accessor exposed it. Completing the grid needs a fourth verb (a soft
`forbid`) and a decision on naming and on how its new stored form interacts with
the frozen format and the fingerprint invariant.

### Possibilities considered

1. **Derived accessors only.** Add `Constraint.kind` /
   `feasible_when_satisfied` / `ConstraintEval.violated`; keep three verbs.
   Fixes the *display* awkwardness but leaves the grid asymmetric.
2. **Add `discourage`, keep `constrain`.** Names stay asymmetric
   (`constrain`/`discourage`), and the verb `constrain` keeps colliding with the
   umbrella noun (`Constraint`, `space.constraints`).
3. **Rename `constrain` → `encourage`, add `discourage`, plus the accessors.**
   Symmetric quartet `forbid`/`require` + `encourage`/`discourage`; the verb no
   longer collides with the noun; polarity is a first-class derived property.

### Answer

**Possibility 3.** Rename the soft verb `constrain` → `encourage` and add its
bad-state complement `discourage` (`== encourage(~e)`); expose `Constraint.kind`,
`Constraint.feasible_when_satisfied`, and `ConstraintEval.violated`. `is_violated`
collapses to the property; `infeasibility_reasons` labels by `kind`.

### Reasoning

The quartet is self-documenting and parallels the just-added `require`. The
rename does not touch stored IR (`encourage` produces the identical
`origin="user", hard=False` constraint as the old `constrain`), so **every corpus
and `require_demo` KA vector stays byte-identical and there is no format-version
bump**. `discourage` only adds an `origin` value additively (like `require`,
under the pre-release exemption). To keep the preimage-excluded `origin`
non-load-bearing, `discourage` canonicalizes to `Not(e)` in the fingerprint
preimage exactly as `require` does — otherwise `discourage(e)` and `encourage(e)`
(same `expr`/`hard`, opposite polarity) would collide. The derived accessors are
properties (not fields), so they never enter the preimage or serialization.

### Specification update

API.md §Constraints table (rename + `discourage` row + "constraint quartet" and
polarity-accessor paragraph), §Sampling (`reject_soft` names the soft pair),
§Identity (scope table, normalization pipeline step 1 extended to `discourage`),
§IR (`Constraint.origin` gains `"discourage"`; `kind`/`feasible_when_satisfied`/
`ConstraintEval.violated` documented). Implemented under milestone M7.6.

---

## D-40 — `sat_solver`'s "anchors" corpus-table note vs. the never-replace KA-vector rule

- Status: Resolved
- Date: 2026-07-22
- Spec section: PLAN.md corpus table (`sat_solver` row); API.md §Constraints and Feasibility (`.anchor()`); §Identity (KA-vector freeze discipline)
- Decided by: User (M8 planning)

### Question

PLAN.md's corpus table lists `sat_solver`'s exercised features as "choice+ordinal,
anchors, ordinal comparisons (M3, freeze asserts at M8)" — read literally, this
says the `sat_solver` fixture should gain `.anchor()` calls. But `.anchor()`
doesn't exist until M8, and `sat_solver.json`'s known-answer vector (`fingerprint_full`,
`to_json`) is already committed from M7. Adding anchors to `sat_solver.py`'s
`build_space()` would change both (anchors are `full`-scope only, so
`fingerprint_sampling` is unaffected) — which the frozen-format discipline's
"add — never replace — known-answer vectors" rule forbids. Which wins?

### Why the specification is insufficient

PLAN.md's corpus table is a planning artifact, not itself a normative freeze rule,
but the two constraints it and CLAUDE.md state are in direct conflict for this one
fixture: the table's forward note asks for a change that the vector-freeze
discipline (CLAUDE.md, "Frozen after M7") disallows performing on that specific
file. `sat_solver.py`'s own docstring already anticipated the tension ("gains
`.anchor()` calls whenever that milestone lands") without resolving it.

### Possibilities considered

1. **Add anchors to `sat_solver.py`, replace its KA vector.** Satisfies the
   corpus-table note literally. Violates "never replace" — a KA vector's entire
   purpose is to detect accidental changes to already-shipped fixtures; replacing
   it on a deliberate change is still a replacement the discipline forbids without
   a format-version bump, and no version bump is warranted here (anchors are
   additive, like `require`/`discourage` before them).
2. **Leave `sat_solver.py` untouched; exercise anchors via a new demo fixture.**
   Follows the M7.5/M7.6 precedent exactly (`_require_demo.py`/`_discourage_demo.py`
   under `tests/conformance/`, added — not substituted for — a corpus fixture).
   `sat_solver`'s corpus-table cell is read as "conceptually associated with anchors
   in the design history" rather than a literal instruction to mutate the frozen
   fixture; the *only* literal M8 obligation for `sat_solver` is the freeze-ablation
   asserts ("freeze asserts at M8"), which touch its test file, not `build_space()`.

### Answer

**Possibility 2.** `sat_solver.py`'s `build_space()` and its committed KA vector
stay byte-identical. A new `tests/conformance/_anchor_demo.py` (parallel to
`_require_demo.py`/`_discourage_demo.py`) exercises `.anchor()`/`.meta()` for a
committed `anchor_demo` KA vector. `sat_solver`'s test file gains `.freeze()`-
ablation assertions only, operating on a derived (in-test) space — never mutating
`build_space()`'s output. `sat_solver.py`'s docstring is updated to drop the
"gains `.anchor()` calls" forward guess.

### Reasoning

The never-replace rule is the stronger, more specific commitment (an explicit
CLAUDE.md law spanning the whole pre-release span M8–M12), and the demo-fixture
pattern already has two precedents that solved the identical shape of problem
(introduce a new frozen-format value; need a KA vector for it; must not touch any
existing corpus vector). Reading the corpus table's forward note as
design-historical color rather than a literal mandate costs nothing: the fixture
still ends up "associated with anchors" in spirit via `_anchor_demo.py`, and the
table's real, testable obligation ("freeze asserts at M8") is satisfied precisely.

### Specification update

None required — PLAN.md's corpus-table cell already reads as historical
intent, not a normative requirement; `API.md` is unaffected. `sat_solver.py`'s
docstring updated in-repo to state the resolution directly (avoiding a future
reader re-opening the same question).

---

## D-41 — `param_from_def` on a struct/choice `ParamDef`: raise, don't return a descendant-less view

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Space — Metaprogramming (`ds.param_from_def`)
- Decided by: Agent (low-risk, reversible pre-release implementation choice)

### Question

`ds.param_from_def(pd: ParamDef) -> TypedParamExpr` takes a single `ParamDef`.
For a struct (`type_kind="space"`) or choice (`type_kind="choice"`) param, the
*descendants* (a struct's fields; a choice's variant payloads) are not part of
that `ParamDef` at all — `resolve/_pipeline.py::_emit` relocates them into
separate flat `Space.params` entries (`"s.field"`, `"c.variant."`) that a lone
`ParamDef` carries no reference to. What should `param_from_def` do when handed
one of these two kinds (or a repeated element of one)?

### Why the specification is insufficient

API.md states the IR is "bidirectional" and gives `param_from_def`'s signature,
but doesn't address the struct/choice case specifically — every worked example
(`.real()`, `.integer()`, lifts) is scalar-shaped, where a single `ParamDef`
genuinely is the complete picture.

### Possibilities considered

1. **Return a descendant-less container** (`StructParamExpr` with
   `struct_space=None` / `ChoiceParamExpr` with empty `choice_payloads`). Matches
   the signature's promise to always return *some* `TypedParamExpr`, but is a
   silent data-loss trap: fed straight into `ds.space(...)`, it resolves without
   error into a struct/choice with **zero** descendants — a legal-looking but
   wrong space, with no signal anything was dropped.
2. **Raise `TypeError`, naming `space_from_ir` as the correct tool.** A
   struct/choice param's full reconstruction needs the *whole* flat `params`
   mapping (where every descendant already exists as its own entry) —
   `space_from_ir` receives exactly that, so it is the actual inverse for these
   two kinds, not `param_from_def`.

### Answer

**Possibility 2.** `param_from_def` raises `TypeError` for `type_kind in
("space", "choice")`, and for a `"list"` `ParamDef` whose repeated element is a
struct/choice, naming `space_from_ir()` in the message. Every scalar kind
(real/integer/bool/categorical/ordinal/subset/permutation) and any list thereof
inverts fully and is fingerprint-equal to the original.

### Reasoning

Silent partial reconstruction is the wrong default here — unlike
`remaining_domain`'s documented "sound, not complete" narrowing (which never
excludes a *feasible* value, just doesn't find every reduction), a
descendant-less struct/choice is a **different, wrong** space, not a
conservative under-approximation of the right one. Raising costs nothing: the
real per-param use case for `param_from_def` (map a scalar param's domain,
tags, etc. — the coarsening/registry-driven-generation patterns
`API.md`/PLAN.md's M8 gate names) never needs it on a container kind, and
`space_from_ir` — needed anyway for a struct/choice-bearing space — already
has every descendant in hand. This is a pre-release (M8, no shipped v0.1)
implementation choice with no format/serialization impact, revisited freely if
a real use case for the container form emerges before M13.

### Specification update

None required — API.md's `param_from_def` entry already only illustrates the
scalar case; this is a documented gap-fill, not a correction.

---

## D-42 — `space_from_ir` re-validation: flat-IR re-checks, not a builder round-trip

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Space — Metaprogramming (`ds.space_from_ir`)
- Decided by: Agent (low-risk, reversible implementation choice; matches the M8 plan's stated recommendation)

### Question

`space_from_ir(params, conditions, constraints, anchors=None, meta=None) -> Space`
must turn already-resolved IR back into a validated `Space` ("resolution
re-validates whatever comes in"). Two shapes of implementation are available:
(a) re-run the *builder* pipeline (`resolve_space`), which expects nested,
unrelocated `ParamExpr` expressions and performs structural relocation of
struct/choice payloads, or (b) re-validate the *already-flat* IR directly,
since `params`/`conditions`/`constraints` here are exactly the shape
`Space.params`/`.conditions`/`.constraints` already have (struct/choice
descendants already present as separate flat entries, conditions already
folding in discriminator equalities).

### Why the specification is insufficient

API.md gives the signature and the general "re-validates" principle but not
the mechanism. `resolve_space` is builder-shaped (step 8, `_emit`, performs
relocation that assumes *unrelocated* nested payloads); its input shape does
not match what `space_from_ir` naturally receives from `Space.params`, an
already-relocated flat mapping.

### Possibilities considered

1. **Round-trip through the builder.** Reconstruct nested `ParamExpr` trees
   from the flat IR (re-inferring struct/choice nesting from path prefixes)
   and feed them to `resolve_space`. Reuses the most machinery, but requires
   *re-deriving* structure that the input already discarded (relocation is
   lossy about which flat entries were originally which payload) — solving a
   harder, backwards problem to reach the same place.
2. **Re-validate the flat IR directly.** Reuse the *validation* half of the
   pipeline (`_validate_domain`/`_validate_prior`/`_validate_quantized`/
   `_validate_default`/`_validate_lift`/`_validate_tags_meta`/
   `_validate_list_defaults_deep`) per already-flat `ParamDef`, plus the
   existing cross-definition re-check (`check_fully_resolved`) that every
   other terminal entry point (`fingerprint`, `to_json`, `validate`, `sample`,
   `partial`) already runs. Skip structural relocation entirely — there is
   nothing left to relocate.

### Answer

**Possibility 2.** `resolve/_pipeline.py` gains `param_def_to_view` (the
per-`ParamDef` inverse of `_emit`, shared with `meta._meta.param_from_def`),
`validate_param_defs` (re-runs the per-definition validators over a flat
`ParamDef` mapping), `rebuild_charts`/`rebuild_list_domain_charts` (charts are
always derived, never trusted from input — promoted from
`serialize/_fromjson.py`, which now imports them instead of duplicating), and
`revalidate_space` (bundles all of the above plus `check_fully_resolved`).
`meta._meta.space_from_ir` rebuilds each `ParamDef`'s chart, assembles the
`Space`, and calls `revalidate_space`.

### Reasoning

The flat-IR shape is exactly what `space.params`/`.conditions`/`.constraints`
already are — re-validating it directly is the natural, lower-effort path,
and it reuses tested per-definition validators verbatim rather than solving
the strictly harder inverse-relocation problem Possibility 1 requires for no
additional correctness benefit. Promoting `rebuild_charts` out of
`serialize/_fromjson.py` (rather than duplicating it in `meta/`) keeps chart
re-derivation in one place, used by every "assemble a `Space` from raw
`ParamDef`s" entry point (`from_json`, now `space_from_ir`).

### Specification update

None required — API.md's `space_from_ir` entry states the "re-validates
whatever comes in" principle; this decision only fixes the implementation
mechanism.

---

## D-43 — M8 introspection accessors: scope, and the shapes API.md leaves unstated

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Space — Introspection
- Decided by: User (scope) + Agent (shapes — low-risk, reversible)

### Question

API.md's Introspection block lists roughly fifteen accessors with only
signatures, no bodies: `.subspaces -> dict[str, SubspaceInfo]`,
`.dependency_graph -> dict[str, frozenset[str]]`, `.param_constraints(path)`,
`.param_conditions(path)`, several boolean flags, `.cardinality()`, and
`.capability_report()`. M8's own `**Spec:**` line only names "Structural
Operations" and "Metaprogramming" — it does not scope the Introspection
block at all. Two questions: (1) how much of this list does M8 build, and
(2) for the parts M8 does build, API.md never defines `SubspaceInfo`'s
fields, nor `dependency_graph`'s exact edge semantics for a plain
(non-bound) constraint, nor whether `param_conditions(path)` means "path's
own condition" or "conditions referencing path."

### Why the specification is insufficient

The Introspection section is written as a bare method-signature block with
one paragraph of prose (covering only `dependency_graph`, and only its
order-imposing subset — "only conditions, bound-origin constraints, and
repeat counts impose assignment order"). No prose at all covers
`SubspaceInfo`'s shape, or clarifies whether a plain constraint's coupling
is bidirectional, or resolves the target-vs-reference ambiguity in
`param_conditions`.

### Possibilities considered — scope (question 1)

1. **M8 builds only what its `**Spec:**` line names** (ops/meta), leaving the
   entire Introspection block to a later, unscheduled milestone.
2. **M8 builds the cheap, pure-IR-projection accessors** (`.subspaces`,
   `.dependency_graph`, `.param_constraints`, `.param_conditions`, the
   boolean flags) and defers `.cardinality()` (needs enumeration) and
   `.capability_report()`/`Capabilities` (needs the M11 Encoding registry).
3. **M8 builds the entire block**, including `.cardinality()` and
   `.capability_report()`, pulling M11 machinery forward.

### Answer — scope

**Possibility 2** (user-selected). `.has_nongenerative_params` is further
deferred to M9 alongside it — no non-generative (custom-type) param can
exist before M9, so implementing it now would be a stub returning `False`
forever, which "no dead scaffolding" (CLAUDE.md) rules out; it is added
alongside `.custom()` instead.

### Possibilities considered — shapes (question 2)

For `SubspaceInfo`: mirror the *relocation* data `resolve/_relocate.py`
already computes (prefix, the folded activation condition) plus enough to
identify member scope (`member_paths`) and kind (`kind`, `variant_name`),
since that is the only structural information a struct/variant subspace
*has*. For `dependency_graph`'s constraint edges: a plain constraint (no
`Constraint.target` field exists) either (a) contributes no edge at all —
too little, contradicts "via conditions, **constraints**, and repeat
counts" — or (b) contributes a symmetric coupling among every param it
mentions (added to *each* mentioned param's own entry). For
`param_conditions`: either "target only," "referenced only," or the union
of both.

### Answer — shapes

`SubspaceInfo(prefix, kind, member_paths, condition, variant_name=None)`
(`ir/_results.py`). `dependency_graph` uses symmetric constraint coupling
(possibility b above) and includes every `space.params` key, lift templates
included (matching `.params`'s own unfiltered transparency, unlike
`partial/_partial.py::topological_order`, which filters `"[]"` paths for its
own execution-order purpose). `param_conditions(path)` returns the union:
`c.target == path OR path in c.params`.

### Reasoning

Symmetric constraint coupling is the only reading consistent with the
prose's explicit inclusion of "constraints" as an edge source, given
`Constraint` has no target to hang a directed edge from — a param
co-mentioned in a forbid/require/encourage/discourage genuinely depends on
its co-mentioned siblings in the sense the section describes (structural
coupling), even though (per the same sentence) it imposes no assignment
*order*. Unfiltered `"[]"` inclusion matches `.params`'s own transparency
rather than inventing a new filtering rule with no textual basis.
`param_conditions`'s union reading is the most complete without being
wrong in either direction: a narrower reading (target-only, or
reference-only) would silently omit a real answer to "what conditions
touch this param."

### Specification update

None required — this fills in shapes API.md leaves as bare signatures; no
existing text is contradicted.

---

## D-44 — `.freeze()`'s per-kind mechanism, and its M8 kind coverage

- Status: Resolved
- Date: 2026-07-22
- Spec section: API.md §Space — Structural Operations (`.freeze(values=None, **kw)`)
- Decided by: User (core mechanism: domain-narrowing, not slice-style substitution) + Agent (per-kind completion, low-risk/reversible)

### Question

The user confirmed `.freeze(x=5)` narrows `x`'s own domain to `{5}` (keeping
`x` in `.params`, unlike `.slice()`, which removes it and substitutes its
value at every reference site) rather than rewriting every other expression
that references `x`. That settles the *real* case cleanly (`RealDomain(5, 5)`
is already a legal degenerate domain — Degeneracy Table: "`lo == hi` |
Legal"). It leaves open how every *other* param kind should be "fixed,"
since not every `Domain` shape has a way to represent "exactly one value":
`BoolDomain` has no `values` tuple to narrow; `SubsetDomain`/
`PermutationDomain` describe a combinatorial family, not a single member,
via `items`/size bounds alone; a struct/choice container isn't a "value" at
all in the same sense.

### Why the specification is insufficient

API.md's `.freeze()` row is one line covering the general "fix values, keep
params, conditions resolve statically" behavior; it gives no per-kind
mechanism, and the worked examples elsewhere in the spec are all
real/integer-shaped.

### Possibilities considered

1. **Domain-narrowing only, kind by kind, wherever the domain shape allows
   it** (real/integer: `lo=hi=value`; categorical/ordinal: `values=(value,)`);
   a param whose domain has no single-value representation (bool; subset;
   permutation; struct; choice; list) is **out of scope** for `.freeze()` in
   M8, raising a clear error.
2. **Domain-narrowing plus a hard `require`/`forbid` fallback** for kinds a
   domain can't narrow (bool: `require(x)`/`require(~x)`; choice: `require(x
   == variant)`, if `Compare` even type-checks a choice discriminator —
   untested) **for every kind**, including subset/permutation (which would
   need an `IsIn`-driven per-item pinning) and struct (undefined — a struct
   has no scalar value).
3. **Full cascading removal for choice**, narrowing `ChoiceDomain.variants`
   to the fixed variant and pruning every *other* variant's already-relocated
   descendant params (`.select()`-like behavior folded into `.freeze()`).

### Answer

**Possibility 1, extended narrowly to bool.** Real/integer/categorical/
ordinal narrow their domain to the single value (default set to it too,
prior dropped as moot). Bool is pinned via a hard `require(x)`/`require(~x)`
constraint (the domain itself is untouched — there is nothing to narrow, and
this needs no `Compare`, sidestepping the untested choice-discriminator
question). Choice, subset, permutation, struct, and list are **not yet
supported** by `.freeze()` in M8 — calling it on one of these raises a clear
`ResolutionError` naming the param and its kind.

### Reasoning

Real/integer/categorical/ordinal narrowing is a direct, low-risk application
of the user's confirmed mechanism, using an *already-legal* degenerate domain
shape (Degeneracy Table) — no new domain concept needed. Bool's
`require`/`require(~.)` pin is the simplest possible instance of "no domain
to narrow, use a constraint instead" and needs no unverified assumption about
operator support. Extending to choice would require *also* solving
`.select()`-shaped structural pruning (removing non-selected variants'
descendants) to avoid leaving unreachable-but-still-declared payload params
— a materially different, larger piece of work than "fix one value," and
better left to a future milestone or an explicit combination of
`.freeze()`+`.select()` by the caller. Subset/permutation have no
domain-narrowing analogue at all (a specific combination isn't expressible
via `items`/size bounds), and a `Compare`-based pin is unverified for
list-valued domains; struct has no value to fix in the first place. Scoping
these out, with a clear error, is safer than shipping an unverified or
half-correct mechanism for the less-common kinds this milestone's gate does
not require.

### Specification update

None required — API.md's `.freeze()` row states the general behavior; this
decision fixes the per-kind mechanism and records a scope boundary for a
future milestone to lift.

---

_Ledger tail._ D-30 (M6) through D-37 (M7) were resolved into `API.md` on
2026-07-21 and their entries removed here (preserved in git history), matching the
post-M5 reset. See `PROGRESS.md` for the fold record. D-38 (M7.5) and D-39 (M7.6)
above remain as open-format entries recording decisions resolved with the user.
