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
remain in this repo's git history (see the commit that reset this file).

Entries **D-27, D-28, D-29** (M4.6, M5) were folded into API_v3.md on 2026-07-19
(faithfulness review) and cleared from this ledger; their full original bodies
remain in this repo's git history (see the commit that reset this file). Three
findings resulted:

- *D-27 / D-28 (Builder view types).* The §Parameter Types "Builder view types"
  paragraph was self-contradictory (line 90 makes the base a `VectorExpr` owning the
  aggregates; the old line 92 narrowed the aggregates/combinatorial queries onto the
  views) and its parenthetical grouped `.contains()`/`.size()`/`.sum_over()` under
  permutation and `.position_of()` under subset, contradicting row 18. Reworded: only
  type methods and the domain-level `.log_scale()`/`.quantized()` are narrowed; query
  and aggregate methods stay on the base (reference-position), type-correct by rows
  6/18/24 at runtime. Documentation-only; the code was already correct.
- *D-29 (1)(2)(3)(5) (bounds: hull direction, op set, eager scope, tighten gating).*
  Spec-silent points; the least-surprising readings were folded as normative
  clarifications (§Expression bounds are sugar, §All charts are static, §Resolution
  timing). Documentation-only.
- *D-29 (4) (bound-origin polarity).* Faithful to the bound text but latently breaks
  the fingerprint feasibility guarantee, because `is_violated` keys off `origin` and
  `origin` is preimage-excluded. Resolved via **Route A** (keep the M5 runtime;
  canonicalize the preimage to forbidden-state form) — the runtime/wording half is
  folded into the spec now; the `fingerprint()` canonicalization + its conformance
  law are a **required M7 build step and gate item** (see IMPLEMENTATION_PLAN.md M7).
  Do not treat this as fully settled when M7 begins: the preimage canonicalization
  and its polarity law still have to be implemented and tested there.

Add new entries below as future milestones surface fresh ambiguities.

---
