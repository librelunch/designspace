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

Entries D-1 … D-29 (M0–M5) were reviewed and folded into API_v3.md as normative
spec text; their full original bodies remain in this repo's git history. Remaining
code corrections are tracked in their milestones — **M4.5 — Faithfulness
corrections** (D-1 … D-26) and **M7** (D-29(4)'s bound-origin fingerprint-preimage
canonicalization) — in IMPLEMENTATION_PLAN.md. Add new entries below as future
milestones surface fresh ambiguities.

---

## D-30 (M6) — Partial-status corners the spec leaves to derivation

Question:   API_v3.md's Partial Configs section states the container rule for
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
