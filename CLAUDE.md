# Agent instructions

These instructions govern all work in this repository.

## Read order

Before editing code, read:

1. `API.md`, the normative product and semantic specification.
2. `DECISIONS.md`, the record of genuine specification gaps and their
   resolutions.
3. `PLAN.md`, the current implementation milestone and acceptance criteria.

A direct user instruction overrides these repository documents. Otherwise, do
not silently reinterpret a clear requirement in `API.md`.

## Specification gaps

Use `DECISIONS.md` only when `API.md` is genuinely imprecise or incomplete and
an answer is required to proceed.

- State the exact question.
- Explain why the specification does not answer it.
- Compare the plausible answers and their consequences.
- Record the chosen answer and reasoning.

A clear specification that is inconvenient to implement is not ambiguous. An
implementation that contradicts it is a bug, not a decision. Routine
implementation details do not belong in `DECISIONS.md`.

Ask the user before resolving a gap that changes public API, compatibility,
scope, or mathematical meaning. An agent may resolve a low-risk, reversible
implementation gap, but must still record it if it affects the contract.

Who decided determines what happens to `API.md`. A gap the **user** resolves is
folded into `API.md`, and its `DECISIONS.md` entry stays for reference. A gap an
**agent** resolves is recorded in `DECISIONS.md` and is never folded into
`API.md` on the agent's own authority. There the entry is the request for
review, and `API.md` changes once the user has reviewed it.

## Prose standards

These govern every authored document, docstring, and comment in the repository.

1. **Write about the subject.** Not about the document, how it was produced, or
   what it used to say.
2. **Normative text states requirements.** Reasoning belongs in `DECISIONS.md`;
   argument written for a reader belongs in `docs/design-notes/` (latter
   requires user approval).
3. **Plain declarative prose, one claim per sentence.** The register of the
   NumPy and SciPy reference documentation.
4. **Wrap authored markdown prose at 80 columns.** Tables and code blocks are
   exempt.

Prose laws in `tests/test_docs_site.py` enforce what is mechanically checkable.
Read a failure from that file as a rule, not as a lint to satisfy narrowly.

## Work discipline

- Work only on the current `PLAN.md` milestone (see `PROGRESS.md`) and keep its
  acceptance criteria current.
- When a milestone's exit criteria pass, delete its section from `PLAN.md` and
  add its row to `PROGRESS.md`. `PLAN.md` holds only unshipped work;
  `PROGRESS.md` is the record that a milestone shipped.
- Prefer small, reviewable changes that preserve storage compatibility during
  extraction.
- Add dependencies only when the active milestone needs them.
- Keep the public surface small; internal structure is not automatically public
  API.
- Do not commit or tag until the milestone is explicitly approved.
- Do not open any PRs or push to remotes unless explicitly requested.

## Commit gates

Before every commit, run these exact commands from the repository root:

```console
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/
uv run pytest -q
uv run pytest -q --doctest-modules --doctest-glob='*.md' src docs
uv run --extra docs sphinx-build -b html -W docs docs/_build
```

All six must pass. Do not skip a gate, weaken strictness, add broad ignores,
hide a failure, or change these commands to make a commit pass. The same
commands must run in CI.


## Additional instructions

- Never weaken a stated law from `API.md` (conformance laws, error table, Kleene
  table, chart formulas).
- Laws-first: write the milestone's conformance-law tests before implementation;
  existing conformance tests are permanent and may never be deleted or loosened.
- No dead scaffolding: do not stub future milestones' public APIs.
  `src/designspace/__init__.py` exports exactly the spec surface implemented so
  far.
- Out-of-scope list in the spec is binding even for "helpers": no search
  operators, no distances, no tree generators, no algebraic expression
  normalization, no clamping anywhere.
- All public objects immutable; RNG passed explicitly; error messages name the
  offending definition path(s).
