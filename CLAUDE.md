# designspace

Implementing **API_v3.md** per **IMPLEMENTATION_PLAN.md**. Read both fully before any change.

## Rules

- The spec (API_v3.md) is normative; the plan sequences it. Spec/plan conflicts and any spec ambiguity go into `DECISIONS.md` — never resolve silently, never weaken a stated law (conformance laws, error table, Kleene table, chart formulas).
- Current milestone: see `PROGRESS.md`. Work only within it; one milestone per branch/PR. Bootstrapping from the plan is already done — begin at M0.
- Laws-first: write the milestone's conformance-law tests before implementation; existing conformance tests are permanent and may never be deleted or loosened.
- No dead scaffolding: do not stub future milestones' public APIs. `src/designspace/__init__.py` exports exactly the spec surface implemented so far.
- Frozen after M7 ships: the JSON format and fingerprint preimage. Changes require the version-bump protocol in the plan (bump the shared integer, add — never replace — known-answer vectors).
- Out-of-scope list in the spec is binding even for "helpers": no search operators, no distances, no tree generators, no algebraic expression normalization, no clamping anywhere.
- All public objects immutable; RNG passed explicitly; error messages name the offending definition path(s).

## Commands

```
uv run ruff check
uv run mypy --strict src/
uv run pytest -q
```

All three green on every commit.

## Dependencies

`numpy` (core). `polars` enters at M10, `pydantic` only as an extra at M13. Anything else requires a `DECISIONS.md` entry.
