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

_Ledger tail._ D-30 (M6) through D-37 (M7) were resolved into `API.md` on
2026-07-21 and their entries removed here (preserved in git history), matching the
post-M5 reset. See `PROGRESS.md` for the fold record. D-38 (M7.5) and D-39 (M7.6)
above remain as open-format entries recording decisions resolved with the user.
