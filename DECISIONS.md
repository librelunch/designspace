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

_Ledger empty._ Entries D-1 … D-26 (M0–M4) were reviewed and resolved into
API_v3.md as normative spec text, with the remaining code corrections tracked
under milestone **M4.5 — Faithfulness corrections** in IMPLEMENTATION_PLAN.md.
The full original entries remain in this repo's git history (see the commit that
reset this file). Add new entries below as future milestones surface fresh
ambiguities.
