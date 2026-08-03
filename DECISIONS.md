# Decisions

This file is an interpretation log for genuine gaps in `API.md`. It is not a general ADR
diary, progress log, or place to justify divergence from a clear requirement.

When a question is resolved, update `API.md` so future work no longer depends on reading
the historical entry. Keep the entry here to preserve why the answer was chosen.

## D-91 — `to_json_schema`'s output contract

- Status: Open
- Date: 2026-08-03
- Spec section: API.md §Identity and Serialization ("to_json / from_json"); §Staging
- Decided by: Pending

### Question

`Space.to_json_schema() -> dict` is API.md's last unimplemented core surface (M13). The spec gives
it exactly two mentions: the signature line itself, annotated only `# oneOf per choice;
dependency-free`, and the Staging note that it "stays core (dependency-free; cheap under nested
choice)." Neither says which JSON Schema draft, what each of the 13 domain kinds maps to, whether
conditions/constraints appear in the emitted schema at all, what happens at a non-serializable or
opaque param, or whether the output is config-shaped or flat. All five are genuine gaps: nothing
in the surrounding prose, the Kleene semantics, or the `to_json` precedent settles them, and the
answer changes public API — per `CLAUDE.md`, an agent may not resolve this alone.

### Why the specification is insufficient

`to_json_schema` is mentioned nowhere else in the document — no worked example, no error-table row,
no conformance-law bullet. The `to_json`/`fingerprint` sections it sits beside are exhaustive about
draft/format choices (RFC 8785, SHA-256, an explicit version integer); `to_json_schema` has no
equivalent. The one substantive hint — "`oneOf` per choice" — fixes how a `choice` param's variants
are expressed but says nothing about the other twelve domain kinds (real/integer under
`log_scale`/`quantized`/`periodic`, categorical, ordinal, bool, subset, permutation, struct,
list/lift, custom, symbolic, code).

### Possibilities considered

1. **JSON Schema draft.** 2020-12 is the current stable draft and the obvious default; older drafts
   (Draft-07) have wider tooling support in some ecosystems but lack `unevaluatedProperties` and the
   vocabulary system a struct/lift mapping would benefit from.
2. **Per-kind mapping.** Each of the 13 domain kinds needs a concrete schema shape. The two
   sub-questions with real design weight: whether `log_scale`/`quantized`/`periodic` reals are
   expressed as annotations (`x-designspace-log-scale`, vendor extension keys) or collapse to a
   plain `number` with only `minimum`/`maximum`, since JSON Schema has no native log/quantization
   vocabulary; and whether `choice`'s `oneOf` branches are tagged by variant name (a `const`
   discriminator field) or left structurally distinct with no explicit tag.
3. **Conditions and constraints.** *Shape-only* (the schema validates structural well-formedness —
   types, ranges, required keys — and says nothing about `.when()`/`.forbid()`/`.require()`) versus
   *maximal* (attempt `if`/`then`/`dependentSchemas` for at least the simple per-param conditions).
   Shape-only is simpler and honest about what JSON Schema *can't* express (arbitrary Kleene
   expressions, cross-param aggregates); maximal captures more but partially — a schema that encodes
   some constraints and silently drops others is arguably more misleading than one that encodes
   none, since a consumer has no way to tell which case they're in from the schema alone.
4. **Non-serializable / opaque params.** `to_json` has `on_unserializable="raise"|"mark"|"drop"`
   for exactly this case. `to_json_schema` could take the same parameter (with `"mark"`/`"drop"`
   meaning "describe the field as accepting-anything" or "omit the field"), or it could simply raise
   unconditionally, on the reasoning that a schema is a static contract with no such thing as a
   partial-manifest — unlike `to_json`, which still emits a document with the offending sites
   noted, `to_json_schema` has no values to emit, only shape, so there may be nothing sensible for
   `"mark"` to describe beyond "any JSON value."
5. **Config-shaped vs. flat.** Config-shaped (nested, matching `to_json`'s config form and what
   `space.validate()` accepts) is the natural reading of "schema for this space's configs"; flat
   (`flatten`-keyed, matching the DataFrame/path-grammar surface) would instead validate the
   flattened representation, which is a different and less obviously useful contract — `validate()`
   never accepts a flat dict, so a flat schema would validate something no public method consumes.

### Answer

Pending.

### Reasoning

Pending — recommendation leans 2020-12 draft, vendor-extension annotations for
`log_scale`/`quantized`/`periodic`, shape-only (no conditions/constraints), raise-only for opaque
params (no `on_unserializable` parameter), and config-shaped output, but this is the user's call to
make at M13's open, not a default to implement silently.

### Specification update

Pending.

---

## Entry template

Copy this template for each genuine specification gap.

```markdown
## D-NN — Short title

- Status: Open | Resolved
- Date: YYYY-MM-DD
- Spec section: API.md §...
- Decided by: User | Agent | Pending

### Question

The exact question that the specification does not answer.

### Why the specification is insufficient

The conflicting readings or missing information that prevent a justified answer.

### Possibilities considered

1. **Possibility A.** Observable consequences and trade-offs.
2. **Possibility B.** Observable consequences and trade-offs.

### Answer

The selected interpretation, or `Pending` while the entry remains open.

### Reasoning

Why this answer best fits the stated scope and invariants.

### Specification update

The `API.md` section changed after resolution, or `Pending`.
```

---

_Ledger tail._ D-1 through D-90 were resolved into `API.md` and their entries removed here
(preserved in git history: D-1 through D-70 folded before M10.5 opened; D-71 through D-90 —
M10.5, M10.6, M10.7, M10.8, M11, M12 — folded on the 2026-08-03 documentation pass). D-91 is open
above; continue with D-92.
