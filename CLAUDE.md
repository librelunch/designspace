# Agent instructions

These instructions govern all work in this repository.

## Read order

Before editing code, read:

1. `API.md` — the normative product and semantic specification.
2. `DECISIONS.md` — the history of genuine specification gaps and their resolutions.
3. `PLAN.md` — the current implementation milestone and acceptance criteria.

A direct user instruction overrides these repository documents. Otherwise, do not
silently reinterpret a clear requirement in `API.md`.

## Specification gaps

Use `DECISIONS.md` only when `API.md` is genuinely imprecise or incomplete and an
answer is required to proceed.

- State the exact question.
- Explain why the specification does not answer it.
- Compare the plausible answers and their consequences.
- Record the chosen answer and reasoning.
- Update `API.md` once the question is resolved.

A clear specification that is inconvenient to implement is not ambiguous. An
implementation that contradicts it is a bug, not a decision. Routine implementation
details do not belong in `DECISIONS.md`.

Ask the user before resolving a gap that changes public API,
compatibility, scope, or mathematical meaning. An agent may resolve a low-risk,
reversible implementation gap, but must still record it if it affects the contract.

## Work discipline

- Work only on the current `PLAN.md` milestone (see `PROGRESS.md`) and keep its acceptance criteria current.
- Prefer small, reviewable changes that preserve storage compatibility during extraction.
- Add dependencies only when the active milestone needs them.
- Keep the public surface small; internal structure is not automatically public API.
- Do not commit or tag until the milestone is explicitly approved.

## Commit gates

Before every commit, run these exact commands from the repository root:

```console
uv run ruff check
uv run mypy --strict src/
uv run pytest -q
```

All three must pass. Do not skip a gate, weaken strictness, add broad ignores, hide a
failure, or change these commands to make a commit pass. The same commands must run in
CI.


## Additional instructions

- Never weaken a stated law from `API.md` (conformance laws, error table, Kleene table, chart formulas).
- Laws-first: write the milestone's conformance-law tests before implementation; existing conformance tests are 
  permanent and may never be deleted or loosened.
- No dead scaffolding: do not stub future milestones' public APIs. `src/designspace/__init__.py` exports exactly  
  the spec surface implemented so far.
- Frozen after M7 ships: the JSON format and fingerprint preimage. Changes require the version-bump protocol in
  the plan (bump the shared integer, add — never replace — known-answer vectors).
- Out-of-scope list in the spec is binding even for "helpers": no search operators, no distances, no tree generators,
  no algebraic expression normalization, no clamping anywhere.
- All public objects immutable; RNG passed explicitly; error messages name the offending definition path(s).
