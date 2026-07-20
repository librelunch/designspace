"""Name and meta-value validation shared across construction/resolution
(API_v3.md, "Paths and Scoping"; "Identity and Serialization").

Error-table row 5: names may not contain the path grammar's reserved
characters, regardless of syntactic route.

`check_meta_json_serializable` backs row 23 (`.meta()`/`.forbid()`/
`.constrain()` tags and meta): the error table's own wording is
"non-JSON-serializable meta value" — a list/dict value passes that bar. The
Identity normalization pipeline's step 5 ("meta values encode as {"$t": ...,
"v": ...}") describes how a *scalar* leaf gets tagged, not a ceiling on
meta's shape — a nested list/dict meta value recurses through the same
generic codec used for `default`/`list_default`
(`identity/_tags.py::encode_default_value`), tagging each scalar leaf.
(DECISIONS.md D-36, corrected: an earlier draft tightened this to
scalar-only, which row 23's literal text does not support.)

This check walks the value itself rather than delegating to `json.dumps`:
`json.dumps` is *more* lenient than `encode_default_value` in ways that
would otherwise let something construct here and then either crash or
silently mis-round-trip later:

- a tuple (`json.dumps` encodes it as an array; `encode_default_value` has
  no tuple branch and raises);
- a non-string dict key (`json.dumps` coerces `1` to `"1"`; the encoded
  tree keeps the original key type, which then round-trips as a different
  value, or is rejected outright once handed to the JCS canonicalizer);
- a dict key starting with `"$"` (the tag micro-format's own key, `"$t"`)
  nested inside a meta value — `decode_default_value` treats *any* dict
  containing a `"$t"` key as a tagged scalar and looks for a sibling
  `"v"` key, so `{"cfg": {"$t": "oops"}}` encodes without error but raises
  a bare `KeyError` on decode. (A `"$"`-prefixed key at the *top level* of
  `meta` itself doesn't collide — only values are decoded through
  `decode_default_value`, never the enclosing dict's own keys — but the
  prefix is reserved everywhere in a meta key for a uniform, easier-to-state
  rule; unlike a `default`'s struct field names, which are already
  constrained by declared struct fields, meta keys are unconstrained user
  input, so the stricter rule collects nothing back later.)

This check therefore accepts exactly the shapes `encode_default_value`
round-trips faithfully: `None`/`bool`/`int`/finite `float`/`str`, or
`list`/`dict` (str-keyed, no key starting with `"$"`) thereof, recursively.
"""

from __future__ import annotations

import math
from typing import Any

from designspace.errors import ResolutionError

_FORBIDDEN = (".", "[", "]")
_META_SCALAR_TYPES = (bool, int, float, str, type(None))


def check_name(name: str, *, what: str = "name") -> None:
    if any(ch in name for ch in _FORBIDDEN):
        raise ResolutionError(
            f"invalid {what} {name!r}: must not contain '.', '[', or ']' "
            "(reserved by the path grammar)"
        )


def check_meta_json_serializable(meta: dict[str, Any], *, what: str) -> None:
    for key, value in meta.items():
        _check_meta_key(key, what=what)
        _check_meta_value(value, what=f"{what}: meta[{key!r}]")


def _check_meta_key(key: str, *, what: str) -> None:
    if key.startswith("$"):
        raise ResolutionError(
            f"{what}: meta key {key!r} starts with '$', reserved by the "
            'identity tag format ({"$t": ..., "v": ...})'
        )


def _check_meta_value(value: Any, *, what: str) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ResolutionError(f"{what}: dict meta keys must be strings, got {k!r}")
            _check_meta_key(k, what=what)
            _check_meta_value(v, what=what)
        return
    if isinstance(value, list):
        for item in value:
            _check_meta_value(item, what=what)
        return
    if isinstance(value, _META_SCALAR_TYPES):
        if isinstance(value, float) and not math.isfinite(value):
            raise ResolutionError(f"{what} = {value!r} must be finite (no NaN/Inf)")
        return
    raise ResolutionError(
        f"{what} = {value!r} is not JSON-serializable — expected bool/int/"
        "float/str/None, or a list/dict (string keys) thereof, got "
        f"{type(value).__name__}"
    )
