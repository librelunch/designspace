# Progress

Current milestone: **M8 — Structural operations and metaprogramming** (not started)

| Milestone | Completed | Tests | DECISIONS entries |
|---|---|---|---|
| M0 — Expression core | 2026-07-17 | 63 | D-1 |
| M1 — Builder, resolution skeleton, IR (flat scalar spaces) | 2026-07-17 | 126 | D-2, D-3 |
| M2 — Charts, Kleene, validation, sampler | 2026-07-17 | 259 | D-4, D-5, D-6, D-7, D-8, D-9, D-10 |
| M3 — Structure: choice, struct, subset, permutation, paths | 2026-07-17 | 369 | D-11, D-12, D-13, D-14, D-15, D-16, D-17 |
| M4 — Lifts and aggregates | 2026-07-18 | 449 | D-18, D-19, D-20, D-21, D-22, D-23, D-24, D-25 |
| M4.5 — Faithfulness corrections | 2026-07-18 | 475 | _none_ |
| M4.6 — Build-layer view types | 2026-07-18 | 509 | D-27, D-28 |
| M5 — Expression bounds | 2026-07-19 | 550 | D-29 |
| M6 — Defaults and partial-config API | 2026-07-19 | 622 | D-30 |
| M7 — Identity and serialization (internal v0.1) | 2026-07-20 | 781 | D-31, D-32, D-33, D-34, D-35, D-36, D-37 |

One row per completed milestone: date, total test count at completion, IDs of any DECISIONS entries created during it. Update the "Current milestone" line when a milestone's exit criteria pass.

The "DECISIONS entries" column above is a **historical** record. As of M5 those
entries (D-1 … D-29) were resolved into API.md (as normative spec text) or into
the plan, and `DECISIONS.md` was reset to an empty ledger for future use before M6
began. The original entries remain in this repo's git history. D-30 (M6) through
D-37 (M7) were folded into API.md on 2026-07-21 and `DECISIONS.md` reset again to
the empty ledger; those entries likewise remain in git history. Folded the same day
without new ledger entries (user-approved directly): four API changes — keeping
`to_json`/`from_json` (no rename), instance-path `variant`/`payload` on lifted
choices, the empty/non-existent-path `remaining_domain` `TypeError`, and the new
`space.require` (positive complement of `space.forbid`; spec only). Implementation of
these additions is scheduled as **milestone M7.5** (before M8) — see `PLAN.md`, which
records the freeze handling (additive `origin="require"`, no version bump) and the
`origin == "bound"` → `bound`-or-`require` code sites that must be generalized so the
spec's `require(e) ≡ forbid(~e)` equivalences don't silently break.
