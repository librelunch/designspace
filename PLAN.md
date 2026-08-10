# Implementation plan

`API.md` defines the target. This file defines the current route toward it, and
holds only work that has not shipped. Keep exactly one milestone in progress.
Completed milestones are recorded in `PROGRESS.md`.

## Source of truth and conflict handling

1. **API.md is normative.** This plan sequences it; it never overrides it.
2. If the spec and this plan conflict, the spec wins. Record the conflict in
   `DECISIONS.md`.
3. If the spec is ambiguous or silent, do not invent silently: choose the
   least-surprising behavior consistent with the spec's design principles and
   representation model, implement it, and record the question, the options, and
   the choice in `DECISIONS.md` under the current milestone. An agent's answer
   stays in `DECISIONS.md` for review and is not folded into `API.md`; a user's
   answer is folded in (see `CLAUDE.md`).
4. Never resolve an ambiguity by weakening a stated law (conformance laws, error
   table, Kleene table, chart formulas). Laws are frozen text.

## Working protocol

- **One milestone.** Do not start milestone N+1 while N's exit criteria fail.
- **Laws first.** At the start of each milestone, write that milestone's
  conformance-law tests, which will fail, then implement until green.
  Conformance tests are permanent. Never delete or loosen one; a milestone may
  only add.
- **Track progress in `PROGRESS.md`:** one line per completed milestone with
  date and test count. When a milestone's exit criteria pass, delete its section
  from this file and add its row there. `PROGRESS.md` is the record that it
  shipped; this file holds only unshipped work.
- **No dead scaffolding.** Do not stub future milestones' APIs. Unimplemented
  spec surface should not exist yet, so `from designspace import X` fails
  honestly.

## Global conventions

- Python >= 3.12
- Layout: `src/designspace/`, tests in `tests/`.
- Tooling: `uv` for env, `ruff` (lint and format), `mypy --strict`, `pytest`,
  `hypothesis` for property tests.
- All public objects are **immutable** (`@dataclass(frozen=True)` or
  equivalent); builders return new objects. No global mutable state; RNG passed
  explicitly.
- Exception taxonomy per spec: `DesignSpaceError` with `ResolutionError`,
  `SerializationError`, and `SamplingError` under it; misuse guards raise plain
  `TypeError`. Every `ResolutionError` message names the offending definition
  path or paths.
- Do not implement anything in the spec's **Out of scope** list, even as a
  helper: no search operators, no distances, no tree generators, no algebraic
  expression normalization, no clamping anywhere.

## Freeze discipline (the version-bump protocol)

The JSON document and the fingerprint preimage share **one integer format
version**, frozen at `1`. Every milestone works under this protocol:

1. **One counter, two surfaces.** `to_json`'s version and the preimage's version
   are the same number. `from_json` raises on an unknown one.
2. **Additive changes need no bump** during the pre-release span ("<0.1"): a new
   `origin` value, a new expression node kind, a new entry in the
   non-serializable set, anything no shipped document or committed vector
   depends on.
3. **Add, never replace, known-answer vectors.** A milestone that touches the
   format adds vectors for the new construct and must show **every pre-existing
   vector byte-identical**. This is the gate that enforces the freeze; the
   version integer alone would not.
4. **Any non-additive change bumps the integer** and requires user approval. It
   is a compatibility break, not an implementation detail.
5. **`rfc8785` is pinned exactly.** Bumping that pin is an act under this
   protocol rather than a routine dependency update: a transitive change to
   number formatting would silently shift every committed digest.

## Module map (stable across milestones)

```
src/designspace/
  __init__.py      # public surface only; re-exports
  expr/            # M0  AST nodes, operators, guardrails, all_/any_/count
  builder/         # M1  ds.param / ds.space builders, modifiers, layering
  ir/              # M1  ParamDef, Domain, Constraint, Condition, results
  resolve/         # M1+ pass pipeline, error table, desugaring; M5 envelopes
  charts/          # M2  chart families, integers, grids, periodic, truncation
  eval/            # M2  Kleene engine, activity, margins; M4 aggregates
  validate/        # M2  validate / is_feasible / evaluate_constraints
  sample/          # M2  reference sampler, rejection, retries
  paths/           # M3  grammar, parsing, scoping walk
  config/          # M3  flatten/unflatten/variant/payload/destructure; M7 hash/diff
  defaults/        # M6  apply_defaults cascade
  partial/         # M6  evaluate_partial, remaining_domain, next_assignable
  identity/        # M7  canonical encoding, config_hash, fingerprint
  serialize/       # M7  to_json/from_json, versioning; M15 to_json_schema
  ops/             # M8  slice/freeze/select/filter/extend/active_subspace
  meta/            # M8  space_from_ir, param_from_def, map_params, ...
  custom/          # M9  ParamType protocol, registry, prop()
  frame/           # M10 polars output
  represent/       # M11 Encoding, Representation, transport, the induced chart representation
  program/         # M12 symbolic/code types
tests/
  unit/            # per-module
  conformance/     # the laws; known-answer vectors in tests/conformance/vectors/
  corpus/          # integration spaces (below), exercised end-to-end
```

## Integration corpus

Each fixture is a real space from the spec's design history. Add each at the
milestone tagged; from then on it runs in every end-to-end suite (resolve,
sample 200, validate all, round-trip once serialization exists).

| Fixture | Exercises | Added at |
|---|---|---|
| `flat_hpo` | reals/ints/categorical, log_scale, quantized, `when`, forbid margins | M2 |
| `greenhouse` | choice, nested values, defaults cascade | M3 (defaults asserts at M6) |
| `flow_chemistry` | subset inclusion priors, `contains`, `sum_over`, implications | M3 |
| `job_shop` | permutation, `position_of` | M3 |
| `sat_solver` | choice+ordinal, anchors, ordinal comparisons | M3 (freeze asserts at M8) |
| `wind_farm_grid` | subset + machine-generated pairwise forbids (static unrolling) | M3 |
| `delivery_routes` | struct lifts, instance paths, per-instance constraints, aggregates | M4 |
| `solver_portfolio` | bool+`count`, `if_inactive`, inactive-vs-empty | M4 |
| `memetic_pipeline` | lifted choice, `count_of`, list element forms | M4 |
| `firmware_buffers` | expression bounds, envelopes, bound-origin margins | M5 |
| `pump_configurator` | driver loop: `next_assignable` + `remaining_domain` | M6 |
| `compiler_pipeline` | registry-driven generation, `all_`, degenerate arities, map_params | M8 |
| `vi_family` | custom type, `describe` round-trip, `prop()` constraints | M9 |
| `mixture_stickbreaking` | representation morphism, mixed genotypes, custom-to-u-space bridge | M11 |
| `annealing_schedule` | `.symbolic()` definition + validation (no generation) | M12 |

---

## Milestones

### M13.11: Solver socket prototype (pre-v0.1)

**Spec:** no core runtime surface. A sibling distribution,
`designspace-solvers`, lands as a uv workspace member under `packages/`, with
one extra per backend and bindings for Optuna and cmaes. Core ships no adapter
and takes no dependency, per `API.md`'s *Solver Integration* section, so the
package exists to prove the public representation is a sufficient socket and to
find where it is not. It is not published; its version stays `0.0.0`.

**Build:** done. `[tool.uv.workspace]` at the root, the member's own
`pyproject.toml`, and a seventh gate recipe, `solvers`, inside `just gates`, so
a change to the representation breaks its consumer on the day it lands rather
than at release. The workspace shares one environment and one tool
configuration, so lint and type strictness cannot drift between the two
packages. The bindings run against the existing corpus fixtures rather than
spaces written to make them pass, and the two runnable examples under
`examples/` are executed by the package's own tests, so neither the bindings
nor what a reader is shown of them can rot quietly.

**Findings.** The prototype's deliverable. Three defects in shipped behaviour,
two gaps in the published surface, and one imprecision. Each needs a decision
before v0.1 tags, because every one of them is visible to a consumer.

**All five findings are fixed.** Each landed with its own conformance tests,
written first, except F5, which is specification text with no behaviour behind
it.

**F1. A factor-quantized real chart loses a grid step under round trip.**
*Fixed.*
`Chart.from_unit(chart.to_unit(v)) != v` for a real parameter with a
multiplicative grid, landing on the adjacent grid point. For
`real(1e-6, 1e-2).log_scale().quantized(factor=10)`, two of the five grid
points come back a full decade low, a ratio of `0.100`. `to_unit(1e-5)` returns
`0.19999999999999996`, just under the bucket boundary, and `from_unit` floors
it into the bucket below. The grid itself is built as `9.999999999999999e-06`
rather than `1e-05`, so the value an expert writes is not the value the chart
holds. Scope: multiplicative grids on reals only. Additive `step=` grids on
reals and integers, and multiplicative grids on integers, all round-trip
exactly. `Chart`'s own docstring promises this round trip holds for a
quantizing chart, and `API.md`'s *Solver Integration* section directs solvers
to embed through charts, so this is the operation a warm start runs: seeding an
optimizer from a known-good configuration silently moves a learning rate by a
decade. Fixed by recovering the grid index with the `_K_EPS` tolerance
`build_grid_shape` already floors with, the two directions of one piece of
arithmetic having disagreed on it. Known-answer vectors are byte-identical.

**F2. `validate` rejects the configuration the assignment protocol produces.**
For a lift whose count resolves to zero while its condition holds,
`next_assignable` returns `[]`, `is_complete` returns `True` and
`missing_params` returns `[]`, while `validate` reports the parameter missing.
A driver loop that follows the documented protocol therefore halts on a
configuration that does not validate. Reproduced on `solver_portfolio`, whose
own comments show the active-empty case was intended.

The three partial-config predicates are right and `validate` is the outlier.
*Space: Partial Configs* fixes all three: a list container is "`set`,
`unknown`, or `inactive`, never `active_unset`", `next_assignable` and
completeness coincide by stated law, and the loop assigns "a lift's count param
and its instance leaves, never the container". Under those rules the loop can
only produce the configuration it produces, and it is complete. The container's
status is `set` because its count is determined, and the justification given
for a container never needing a pending status of its own, that its instance
leaves carry one, holds for every count except zero.

Everything canonical disagrees with the loop, not with `validate`: the
reference sampler emits `items: []`, `apply_defaults` fills it in, and
`config_hash` gives the two spellings different hashes, so a tuning loop keyed
on one cannot recognize the other.

This was a specification gap rather than a bug: *Space: Partial Configs* did
not say whether a determined count of zero makes the container's own key
required, and both readings satisfied its text. *Fixed*, the user having
resolved it that presence marks activity without exception. An active lift is
present whatever its count, carrying `[]` when that count is zero, so absence
marks inactivity and nothing else. A zero-count container is `active_unset`
until its key is written and `next_assignable` reports it, which is the one
case where a container is assigned directly. `validate` was already correct and
is unchanged, and an absent key is now an incomplete config rather than a second
spelling of a complete one, so `config_hash` and the frozen format are
untouched and no vector changes. Recorded in `DECISIONS.md` and folded into
`API.md`.

**F3. `Space.next_assignable` reports paths its own configuration cannot
hold.** *Fixed.* Its docstring calls it the driver of an interactive loop. Under a
`.repeat()` lift it reports instance paths such as `workers[0].timeout_s`,
while the configuration it consumes is nested. Assigning the key it just
reported does not register, and the loop repeats that path forever. Routing
through `flatten` and `unflatten` does not rescue it either: `unflatten` needs
the lift's own count key, which is not among the reported paths, and without it
discards the element values silently rather than failing. Route: user
decision. Fixed by having the surface accept what it reports: every
partial-config surface now takes a config in either form and reads the same
answer from both, so a loop accumulates its answers at the paths it was given.
`flatten` refuses an already-flat config rather than dropping its lifts, with
`ds.is_flat` reporting that condition so a caller tests it instead of catching
it, and
`unflatten` takes a dynamic lift's length from the element keys it already
holds, so what the loop builds round-trips without a bookkeeping key the loop is
never told to write. Recorded in `DECISIONS.md` and folded into `API.md`.

**F4. The instance-to-definition path mapping is not published.** *Fixed.* Resolving
`workers[0].timeout_s` to the `workers[].timeout_s` key of `Space.params`, which
a consumer must do to learn the domain it is assigning, is performed by
`designspace.paths.definition_form`. That module appears in no `__all__`, in
`docs/reference.md`, or in `docs/api/`. The binding reimplements it against the
path grammar. Fixed by `Space.param_def(path)`, which takes either form and
returns the definition, joining `param_constraints` and `param_conditions`,
which already accepted both. One accessor rather than a richer walker: four
surfaces report instance paths that `params` cannot hold, and enriching
`next_assignable` alone would have served one of them while breaking the law
that its emptiness coincides with completeness.

**F5. Charts cover two kinds, not every generative one.** *Fixed.* `API.md`'s *Design
Principles* say every generative param resolves to a chart. The *Charts*
section says every generative *scalar* param does, and the IR comment says
`None for non-chart kinds`. Only real and integer carry one; bool, ordinal,
categorical, subset and permutation do not. The narrower reading is the
implemented one and is the right one, ordinal and bool being the only arguable
cases. Both sentences overstated, as it turned out, not just the informative
one: the *Scalar* table groups `bool`, `categorical` and `ordinal` with `real`
and `integer`, so "every generative scalar param" names five kinds where two
carry a chart. Both now name the two kinds and say why the rest carry none.

**What the socket got right**, recorded because it is load-bearing and was not
obvious in advance: `ConstraintEval.margin` with `Constraint.feasible_when_satisfied`
yields a graded, correctly oriented penalty rather than a flag, which is what a
constrained sampler can descend; `coordinate_paths()` refuses a conditional
space rather than quietly padding it; `Representation.decode(encode(config))`
is exact, and `config_hash` survives the round trip, so warm start and
observation identity both work; reading a scalar's bounds off its chart rather
than its domain sidesteps expression bounds entirely; and a lifted element's
`ParamDef` carries its own chart, so the element-chart indirection never has to
be walked.

**A declared prior reaches a solver that has somewhere to put it**, the
discrete kinds included. A real or integer parameter's prior travels in its
chart, so it arrives with the coordinate whichever backend is driving.
`CatCMAwM` holds one categorical distribution per variable and adapts it as the
run proceeds, and takes its starting point as `cat_param`, so `Weights` on a
`categorical`, `bool` or `subset` param normalizes into that argument and the
run begins where the space says the good values are, rather than starting
uniform and being corrected afterwards by the consumer. The exception is
`ordinal`, which the binding places in the solver's integer block, where the
solver holds a Gaussian rather than a distribution over levels: nothing there
takes weights, and summarizing them as a mean index would substitute a point
for a distribution. That is a limit of the solver's model rather than of the
representation, so it is documented and left.

**Gate:** the seven commit gates green, `solvers` among them.

**Exit:** met. All five findings resolved, two as out-of-band fixes, two as a
user-resolved specification gap, and one as a specification correction.

**Still open.** Whether the walk deserves a convenience method, `assignable(config) ->
dict[str, ParamDef]`, deferred deliberately: it is additive, and the bindings
now run on the fixed surface, so whether the two-line form reads badly is a
question the corpus can answer rather than one to guess at.

### M14: v0.1 release

**Spec:** no new runtime surface; release packaging only. `pyproject.toml` gains
`version = "0.1.0"`, `license`, `authors`, `classifiers`, and `[project.urls]`,
and the `LICENSE` file lands here. A real `README.md` (install, a short
quickstart, feature summary, links to the docs site and `API.md`, project
status) replaces today's three-line stub. New `CHANGELOG.md`.

**Gate:** `uv build` emits a wheel containing `py.typed`; a clean-venv install
of that wheel imports `designspace` and type-checks correctly from a consumer's
perspective, which proves `py.typed` took effect rather than merely being
present in the archive.

**Exit:** the first public release. With the full feature set, the user docs,
and release packaging in place, tag **v0.1**. The wire format ships as
format-version `1`, unchanged and vector-tested byte-identical. `to_json_schema`
ships with M15 rather than v0.1, at the user's direction, so `API.md`'s
*Staging* section governs it until then. This is the first artifact intended for
public consumption; everything before M14 was a pre-release checkpoint.

### M15: Optional extras and `to_json_schema` (v0.2, post-release)

**Spec:** the `[pydantic]` extra with `to_pydantic_model`; `to_dataclass() ->
type` and `to_python_source()`; `from_callable` and `Annotated` domain literals
as `designspace.contrib.signatures`; and `Space.to_json_schema() -> dict`.
`to_json_schema` needs no optional dependency, staying dependency-free per the
spec, so it is *build*-deferred here rather than demoted to an install-time
extra. `API.md`'s *Staging* section is revised to say so when this milestone
opens.

**`API.md` currently underspecifies `to_json_schema`'s output contract:** a
signature line and a nine-word comment, with no JSON Schema draft, no per-kind
mapping, and no statement on conditions, constraints, or opaque params. Resolve
this with the user before writing code and record the answer in `DECISIONS.md`
at that point. The other three extras are purely additive, being new methods, a
new subpackage, and new optional extras, with no IR, format, or fingerprint
impact, so no version bump and no vector churn. `to_json_schema` likewise adds
no wire format, being a new method only.

**Build:** the three extras as scoped in `API.md`'s *Staging* section, plus
`serialize/_jsonschema.py` for `to_json_schema`, mirroring the domain walk
already in `serialize/_tojson.py` and `identity/_ir_codec.py`'s `encode_domain`
rather than writing a third walker, wired onto `Space` via a deferred import
matching the existing `builder/_space.py` pattern. New
`tests/conformance/test_json_schema.py`, laws first per the usual protocol. This
milestone writes its own user-facing docstrings, under the same coverage gates,
before merging.

**Gate:** the six commit gates plus the docstring-coverage gates, all green;
pre-existing known-answer vectors byte-identical; every corpus fixture's
`to_json_schema()` output validates that fixture's own sampled configs;
`examples/README.md`'s "Not yet implemented" section, which currently names
exactly `.to_json_schema()`, is deleted. **Exit:** tag **v0.2**.

---

## Definition of done (per milestone)

1. All new conformance laws green; all prior laws untouched and green.
2. Corpus fixtures for the milestone added and passing end-to-end.
3. Error-table rows introduced by the milestone each have a message-content
   test.
4. The six commit gates in `CLAUDE.md` green.
5. `PROGRESS.md` updated; `DECISIONS.md` entries for anything the spec left
   open.
6. Public `__init__.py` exports exactly the spec surface implemented so far,
   nothing speculative.
