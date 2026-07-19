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
