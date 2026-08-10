# Agent instructions

These instructions govern all work in this repository.

## The documents

Before editing code, read:

1. `API.md`, the normative product and semantic specification. It defines what
   the library is.
2. `DECISIONS.md`, the interpretation ledger. It governs what counts as a
   specification gap and who may resolve one.
3. `PLAN.md`, the route toward the specification. It governs the milestone
   protocol and holds the work that has not shipped.

`PROGRESS.md` records the milestones that have shipped. Each rule of this
repository is stated in exactly one of these files, the one whose subject it is.

## Precedence

A direct user instruction overrides these documents. Otherwise `API.md` is
normative: `PLAN.md` sequences it and never overrides it, and no requirement in
it is silently reinterpreted.

A stated law is frozen text. Conformance laws, the error table, the Kleene table
and the chart formulas are never weakened, and an ambiguity is never resolved by
weakening one.

A clear specification that is inconvenient to implement is not ambiguous. An
implementation that contradicts it is a bug, not a decision.

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
5. **A reference resolves for its reader.** Maintainer-facing text, meaning
   private modules, comments and everything under `tests/`, may cite `API.md`,
   its sections and its error-table rows. User-facing text, meaning runtime
   messages, the docstrings of exported objects and their public members, and
   everything under `docs/`, states the thing: it names no repository-only
   document, no error-table row, and no private module.

Prose laws in `tests/test_docs_site.py` enforce what is mechanically checkable.
Read a failure from that file as a rule, not as a lint to satisfy narrowly.

## Standing rules

- All public objects immutable; RNG passed explicitly; error messages name the
  offending definition path or paths.
- The specification's *Out of Scope* section is binding as written, including
  for anything offered as a helper. Read it there rather than from a copy.
- Keep the public surface small; internal structure is not automatically public
  API.
- Add a dependency only when the open milestone needs it.
- Prefer small, reviewable changes that preserve storage compatibility during
  extraction.
- Do not commit or tag until the milestone is explicitly approved.
- Do not open any PRs or push to remotes unless explicitly requested.

## Commits

Run `just gates` from the repository root before every commit. The `justfile` is
the one definition of what that runs, and no other file lists or counts the
gates. `just check` is the fast subset the pre-commit hook runs; the full set
runs before a push. CI calls the same recipes, so a gate cannot differ between a
working copy and CI. Do not skip a gate, weaken strictness, add a broad ignore,
hide a failure, or change a recipe to make a commit pass.

A subject is `type(scope): what changed` (Conventional Commits style).

- Types: `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `chore`.
- Scope is optional and names the package directory or the document the change
  touches. It is read off the tree rather than from a list kept here.
- The subject states what changed, in the plain register the prose standard
  sets, under 72 characters, lower case after the colon, no trailing period.
- Milestone numbers stay in `PLAN.md` and `PROGRESS.md`. A commit that closes a
  milestone says what it recorded, not which number it was.
- Name a decision in words rather than by ledger number, for the reason
  `DECISIONS.md` gives.

Bodies come in two sizes, wrapped at 72 columns.

- A routine commit gets at most three lines, and none at all where the subject
  is enough. Use them for why the change was made, where the subject cannot
  carry it.
- A milestone commit, or one of comparable reach, gets at most three short
  paragraphs: what shipped, what it cost, what it left open.

No body walks the diff file by file, narrates how the work went, or restates
what `API.md`, `DECISIONS.md`, `PLAN.md` or `PROGRESS.md` already record. It
names those documents instead.
