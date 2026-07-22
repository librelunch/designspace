"""`ParamType`: the open-world extension protocol (API.md, "Protocols";
"Extension"; M9).

**Required surface only.** `sample`, `cardinality`, `properties`/`extract`
are documented-optional capabilities a type may or may not implement
(DECISIONS.md D-45/D-46) — duck-typed via `hasattr` at each call site,
exactly like the existing external-`Prior` protocol's optional `.cdf()`
(`ir/_priors.py`, `charts/_external.py`): they are never part of this
`Protocol`'s static shape, so a type author is never forced to stub an
unsupported capability, and `isinstance`/structural checks on `ParamType`
itself only ever demand the required five.

**Value convention (DECISIONS.md D-46).** `validate`/`extract` (and a
`sample()`-supporting type's own internal use of its sampled value) operate
on the type's own *native* representation — whatever `sample()` returns.
`to_json`/`from_json` are the *only* bridge between that native form and the
JSON-safe **phenotype** form: every public, config-dict-shaped surface (a
config leaf, `.validate()`, `.freeze()`, `.default()`, `sample_one()`'s
return value) holds the phenotype form — `to_json(native)` — never the
native object directly. Core calls `to_json` once, immediately after
`sample()` produces a fresh native value, and calls `from_json` immediately
before it needs to call `validate`/`extract` on a config-sourced value. This
lets every existing generic value codec (`identity/_tags.py::
encode_default_value`, the config/flatten/hash machinery) treat a custom
leaf as an ordinary opaque JSON-shaped value, with no per-type special
casing anywhere outside this bridge.

The `.custom(sampler, validator)` shorthand has no `to_json`/`from_json` at
all (API.md: "Callback shorthand. Not serializable.") — for it, native and
phenotype coincide: `sampler(rng)`'s return value is used directly.
"""

from __future__ import annotations

from typing import Any, Protocol


class ParamType(Protocol):
    """The full `.custom(param_type)` protocol. Required: `type_key`,
    `validate`, `to_json`, `from_json`, `describe`.

    Optional capabilities (checked via `hasattr`, not declared in this
    Protocol's static shape — see module docstring):

    - `sample(self, rng) -> Any` — generative iff present; absent, the
      param is **non-generative** (API.md, "Sampling and Generativity":
      `sample()` raises `SamplingError` naming the param iff it must
      materialize a value — `.default()`/`freeze`/`slice`/inactivity all
      satisfy it instead).
    - `cardinality(self) -> int | None` — contributes a finite factor to
      `Space.cardinality()` iff present; absent, the whole space's
      cardinality is `None` whenever this param is included.
    - `properties(self) -> dict[str, type]` and `extract(self, value, prop)
      -> Any` — present *together*, they enable `.prop()` in expressions
      (row 16 governs misuse: undeclared property, non-scalar property
      type, comparison type mismatch).
    """

    @property
    def type_key(self) -> str: ...

    def validate(self, value: Any) -> bool: ...
    def to_json(self, value: Any) -> Any: ...
    def from_json(self, data: Any) -> Any: ...
    def describe(self) -> dict[str, Any]: ...


def is_generative(param_type: Any) -> bool:
    """Whether `param_type` declares `sample()` (API.md "Sampling and
    Generativity"; DECISIONS.md D-45/D-46)."""
    return hasattr(param_type, "sample")


def has_cardinality(param_type: Any) -> bool:
    return hasattr(param_type, "cardinality")


def has_properties(param_type: Any) -> bool:
    return hasattr(param_type, "properties") and hasattr(param_type, "extract")
