# Implementation plan

`API.md` defines the target. This file defines the current route toward it, and
holds only work that has not shipped. Keep exactly one milestone in progress.
Completed milestones are recorded in `PROGRESS.md`.

## Milestone protocol

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

**Gate:** `just gates` plus the docstring-coverage gates, all green;
pre-existing known-answer vectors byte-identical; every corpus fixture's
`to_json_schema()` output validates that fixture's own sampled configs;
`examples/README.md`'s "Not yet implemented" section, which currently names
exactly `.to_json_schema()`, is deleted. **Exit:** tag **v0.2**.

---

## Deferred questions

Raised by a milestone that has shipped and deliberately left unanswered. Each
is additive, so none blocks a release.

- **`assignable(config) -> dict[str, ParamDef]`**, raised at M13.11. The
  partial-config walk reports instance paths and `param_def` resolves each one,
  so pairing them is two lines at a call site. Whether that reads badly is a
  question the corpus can answer once the bindings have run on the fixed
  surface, rather than one to guess at now.

---

## Definition of done (per milestone)

1. All new conformance laws green; all prior laws untouched and green.
2. Corpus fixtures for the milestone added and passing end-to-end.
3. Error-table rows introduced by the milestone each have a message-content
   test.
4. `just gates` green.
5. `PROGRESS.md` updated; `DECISIONS.md` entries for anything the spec left
   open.
