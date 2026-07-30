# Decisions

This file is an interpretation log for genuine gaps in `API.md`. It is not a general ADR
diary, progress log, or place to justify divergence from a clear requirement.

When a question is resolved, update `API.md` so future work no longer depends on reading
the historical entry. Keep the entry here to preserve why the answer was chosen.

## D-71 — Unknown provenance join and the malformed-leaf case

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Expressions > Three-valued semantics, rule 5
- Decided by: Agent

### Question

Rule 5 names three provenances Unknown can carry (inactivity, emptiness, an unset
partial-eval operand) and states that `.if_inactive()` coalesces only the first. It does
not say how provenance *combines* when one expression node has more than one Unknown-valued
operand (e.g. `a & b` where `a` is inactive and `b` is pending), nor what provenance a
structurally malformed leaf (an invalid custom-type value, a non-member ordinal literal)
should carry — malformed values already degraded to Unknown defensively before M10.5, but
undifferentiated.

### Why the specification is insufficient

The prose states the three sources and `.if_inactive()`'s behavior toward each individually;
it does not define a join operation, because before this milestone `Unknown` had no
provenance to join at all (a single undifferentiated singleton). Implementing rule 5
faithfully requires *some* answer for the mixed case, or `.if_inactive()`'s "never eats
pending, never eats emptiness" guarantee could be violated by a node that combines a
coalescible inactive operand with a non-coalescible one.

### Possibilities considered

1. **Max-join over `INACTIVE < PENDING < PERMANENT`.** A mixed node keeps the *strongest*
   (least-resolvable) provenance. `.if_inactive()` then still refuses to coalesce whenever
   any contributing operand was pending or permanent — the guarantee holds unconditionally.
2. **First-operand-wins (evaluation order).** Cheaper, but makes `.if_inactive()`'s behavior
   depend on AST shape/operand order for a semantically symmetric expression like `a & b`,
   which is surprising and not chart/order-invariant.
3. **Reject mixed-provenance nodes as an error.** Over-strict — mixed provenance is common
   (e.g. one lift inactive, a sibling's count merely unset) and not itself a defect.

### Answer

Possibility 1 (max-join). A malformed leaf (defensive degrade — `_ordinal_index` on a
non-member value, `_evaluate_prop`'s `from_json`/`validate` failure) carries `PERMANENT`
provenance: it is neither coalescible (it is not mere inactivity) nor resolvable by assigning
more params (it is malformed, not merely absent).

### Reasoning

The max-join is the only option that preserves rule 5's stated guarantee ("never eats
pending", "never eats emptiness") symmetrically and order-independently. `PERMANENT` for a
malformed leaf matches its existing defensive posture (never a crash; `validate()` reports
the real `ParamError`) while correctly refusing to let `.if_inactive()` paper over it.

### Specification update

Folded into API.md's rule 5 (§Expressions > Three-valued semantics) and the Kleene
conformance bullet.

## D-72 — The integer-valued calculus for `.repeat()` counts

- Status: Resolved
- Date: 2026-07-30
- Spec section: API.md §Modifiers and Layering (the `count` bullet), error-table row 12
- Decided by: Agent

### Question

Row 12 says a repeat count must be "integer-typed" and is tagged **R** (resolution-time);
row 13 (a negative *evaluated* count) is tagged **V**. Neither the row nor the `count`
bullet defines which `ArithExpr` node shapes count as integer-*valued* beyond a bare integer
param — e.g. is `ds.param("m").sum()` over a bool lift integer-typed (`sum([True, False])`
is `int` in Python), and is `.min()` over the same lift (`min([True, False])` is `bool`)?

### Why the specification is insufficient

The prose lists `int | ArithExpr` for `count` and separately says a count "is
resolution-checked to be integer-typed," but never enumerates a closed node-type calculus.
The pre-M10.5 implementation used a *reference*-based rule (walk to every leaf `ParamExpr`,
require `type_kind == "integer"`) rather than a *result*-typed one, which incorrectly
rejected `Sum`/`Min`/`Max`/`Count`/`Size`/`Length`/`PositionOf`/`CountOf` wholesale — every
one of these is itself int-valued regardless of the leaf types it reads.

### Why deferring to row 13 (runtime) is not available

Row 12 is tagged **R** specifically to keep type-ness a resolution-time fact, separate from
row 13's *runtime* negativity check; collapsing 12 into 13 would weaken a stated error-table
row and make count-typing config-dependent (`.repeat(n / 2)` would resolve for even `n` and
fail only at sample-time for odd `n`) — a change to what the row means, not merely to its
timing.

### Possibilities considered

1. **Minimal closed calculus** (chosen): int literals, integer params,
   `Count`/`Size`/`Length`/`PositionOf`/`CountOf` (always int by construction — a match-count
   or occurrence-count is int regardless of what it counts), a declared-int `Prop`, `Sum`
   over an integer- *or* bool-leaved lift, `Min`/`Max` over an integer-leaved lift only (the
   `sum`-vs-`min` bool asymmetry — Python's own `sum([True, False])` is `int` but
   `min([True, False])` is `bool`), a literal-valued `SumOver` mapping, `+ - * %` over two
   int-valued operands, `**` with a non-negative literal integer exponent, `IfInactive` when
   both branches are int-valued. Division and anything outside this set stays row 12 —
   mirrors the bounds engine's own "minimal computable op set" precedent.
2. **Narrow allowlist** (aggregates only, keep the reference-based rule for everything else).
   Fixes the named `Sum`-over-bool-lift case and nothing more; leaves the `Min`/`Max` bool
   asymmetry and arithmetic composition unaddressed.
3. **Full symbolic type inference.** Unbounded scope for a milestone about closing eight
   specific silent-bug reports, not redesigning the count grammar.

### Answer

Possibility 1.

### Reasoning

A closed, resolution-time-checkable set is the same shape API.md already uses for
expression-bound envelopes ("the envelope engine is minimal... anything else... is row 20"),
so this follows an established precedent rather than inventing a new one. The `Sum`-vs-`Min`
asymmetry is not a design choice but a direct consequence of what Python's own `sum`/`min`
return over a bool sequence — encoding anything else would misrepresent the runtime value.

### Specification update

Folded into API.md's `count` bullet (§Modifiers and Layering, "The lift").

---

## Entry template

Copy this template for each genuine specification gap.

```markdown
## D-73 — Short title

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

_Ledger tail._ D-1 through D-70 were resolved into `API.md` and their entries removed here
(preserved in git history). D-71 and D-72 (M10.5) are resolved above and will fold out on
the next spec pass; continue with D-73.
