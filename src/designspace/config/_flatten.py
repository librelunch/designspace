"""`ds.flatten()` (API_v3.md, "Config Utilities"): nested canonical phenotype
-> flat, path-keyed dict.

`flatten` itself is structural and non-validating (spec: "flatten is
structural and non-validating" — Transforms section, which this shares its
traversal shape with). `flatten_with_errors` walks the exact same
space-guided recursion but also collects `ParamError`s for malformed shapes
(a choice value that's neither a bare variant string nor a single-key
dict, an unknown variant name, a struct value that isn't a dict) — used by
validate/, which must catch what `flatten` is allowed to let through (see
DECISIONS.md). One traversal, two behaviors, so the two can never drift
apart on what counts as "structurally present."
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.ir import ChoiceDomain, ParamError


def _direct_children(space: Space, prefix: str) -> list[str]:
    """Full paths that are one segment below `prefix` ("" for root, or
    e.g. `"algo.svm."` inside a chosen variant's namespace)."""
    result = []
    for path in space.params:
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        if remainder and "." not in remainder:
            result.append(path)
    return result


def _split_choice_value(value: Any) -> tuple[str | None, dict[str, Any] | None, bool]:
    """`(variant_name, payload_dict, well_formed)`. A bare string is a
    parameterless variant (`payload_dict=None`); a single-key dict whose
    value is itself a dict is a parameterized variant. Anything else
    (wrong arity, non-dict payload, non-str/dict value) is malformed."""
    if isinstance(value, str):
        return value, None, True
    if isinstance(value, dict) and len(value) == 1:
        ((name, payload_value),) = value.items()
        if isinstance(payload_value, dict):
            return name, payload_value, True
        return name, None, False
    return None, None, False


def _flatten_level(
    nested: Any,
    space: Space,
    prefix: str,
    out: dict[str, Any],
    errors: list[ParamError] | None,
) -> None:
    if not isinstance(nested, dict):
        return
    for path in _direct_children(space, prefix):
        pd = space.params[path]
        local_name = path[len(prefix) :]
        if local_name not in nested:
            continue
        value = nested[local_name]
        if pd.type_kind == "space":
            if isinstance(value, dict):
                _flatten_level(value, space, prefix=f"{path}.", out=out, errors=errors)
            elif errors is not None:
                errors.append(ParamError(param=path, reason="wrong_type", value=value))
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            variant_name, payload_value, well_formed = _split_choice_value(value)
            if not well_formed:
                if errors is not None:
                    errors.append(ParamError(param=path, reason="wrong_type", value=value))
                continue
            assert variant_name is not None
            if variant_name not in pd.domain.variants:
                if errors is not None:
                    errors.append(
                        ParamError(param=path, reason="out_of_bounds", value=variant_name)
                    )
                continue
            has_payload = variant_name in pd.domain.has_payload
            if has_payload != (payload_value is not None):
                if errors is not None:
                    errors.append(ParamError(param=path, reason="wrong_type", value=value))
                out[path] = variant_name
                continue
            out[path] = variant_name
            if has_payload:
                assert payload_value is not None
                _flatten_level(
                    payload_value,
                    space,
                    prefix=f"{path}.{variant_name}.",
                    out=out,
                    errors=errors,
                )
        else:
            out[path] = value


def flatten(config: dict[str, Any], space: Space) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _flatten_level(config, space, prefix="", out=out, errors=None)
    return out


def flatten_with_errors(
    config: dict[str, Any], space: Space
) -> tuple[dict[str, Any], list[ParamError]]:
    out: dict[str, Any] = {}
    errors: list[ParamError] = []
    _flatten_level(config, space, prefix="", out=out, errors=errors)
    return out, errors
