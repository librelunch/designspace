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
(`_canonicalize_feasible_predicate`) under milestone M7.5.

---

_Ledger tail._ D-30 (M6) through D-37 (M7) were resolved into `API.md` on
2026-07-21 and their entries removed here (preserved in git history), matching the
post-M5 reset. See `PROGRESS.md` for the fold record. D-38 (M7.5) above remains as an
open-format entry recording a genuine spec inconsistency resolved with the user.
