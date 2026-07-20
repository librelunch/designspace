"""Canonical **config** encoding (API_v3.md, "config_hash"): "type tags,
float rules, grid canonicalization; subsets sorted, inactive stripped."

Mirrors `config/_flatten.py`'s space-guided recursive traversal (same
`template_prefix`/local-name walk over `space.params`) but builds a nested
canonical *tree* instead of a flat dict, applying per-leaf canonicalization
along the way. "Inactive stripped" needs no extra code: the dict-config
representation already omits inactive params (they are simply absent keys),
and this walker only ever visits keys present in the input.

Non-validating, like `flatten()` — a malformed config passes through
best-effort rather than raising a `ParamError` list; `config_hash` is not a
validator.

Whether a leaf value needs a `$t` type tag follows the same boundary as the
domain codec (`identity/_ir_codec.py`, DECISIONS.md D-34): categorical/
ordinal values and subset/permutation items are `Any`-typed declared data and
get tagged; real/integer/bool values are never ambiguous given the param's
own `type_kind` and stay bare.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.charts._grid import build_grid_shape, grid_membership
from designspace.config._flatten import _direct_children, _split_choice_value
from designspace.errors import SerializationError
from designspace.identity._tags import sort_key, tag_value
from designspace.ir import (
    ChoiceDomain,
    Domain,
    IntegerDomain,
    ListDomain,
    QuantizedSpec,
    RealDomain,
)


def _canonical_grid(
    domain: Domain, quantized: QuantizedSpec | None, value: Any
) -> Any:
    if quantized is None:
        return value
    assert isinstance(domain, RealDomain | IntegerDomain)
    # Resolved bounds are always plain numbers by this point (charts/_build.py
    # relies on the same post-resolution guarantee).
    assert isinstance(domain.lo, int | float) and isinstance(domain.hi, int | float)
    lo, hi = float(domain.lo), float(domain.hi)
    shape = build_grid_shape(lo, hi, quantized.step, quantized.factor, quantized.include_hi)
    canon = grid_membership(shape, float(value))
    return canon if canon is not None else value


def _encode_scalar_value(
    kind: str, domain: Domain, quantized: QuantizedSpec | None, value: Any
) -> Any:
    if kind == "real":
        return _canonical_grid(domain, quantized, float(value))
    if kind == "integer":
        return _canonical_grid(domain, quantized, value)
    if kind in ("categorical", "ordinal"):
        return tag_value(value)
    if kind == "bool":
        return bool(value)
    if kind == "subset":
        return sorted((tag_value(v) for v in value), key=sort_key)
    if kind == "permutation":  # order is the payload — never sorted
        return [tag_value(v) for v in value]
    raise SerializationError(f"config encoding: unsupported scalar kind {kind!r}")


def _encode_level(nested: Any, space: Space, template_prefix: str) -> Any:
    if not isinstance(nested, dict):
        return nested
    result: dict[str, Any] = {}
    for template_path in _direct_children(space, template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        if local_name not in nested:
            continue
        value = nested[local_name]
        if pd.type_kind == "space":
            result[local_name] = _encode_level(value, space, f"{template_path}.")
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            result[local_name] = _encode_choice_value(value, space, template_path)
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            if not isinstance(value, list):
                result[local_name] = value
                continue
            result[local_name] = [
                _encode_list_element(item, pd.domain, space, f"{template_path}[].")
                for item in value
            ]
        else:
            result[local_name] = _encode_scalar_value(pd.type_kind, pd.domain, pd.quantized, value)
    return result


def _encode_choice_value(value: Any, space: Space, template_path: str) -> Any:
    variant_name, payload_value, well_formed = _split_choice_value(value)
    if not well_formed or variant_name is None:
        return value
    if payload_value is None:
        return variant_name
    return {variant_name: _encode_level(payload_value, space, f"{template_path}.{variant_name}.")}


def _encode_list_element(item: Any, domain: ListDomain, space: Space, template_prefix: str) -> Any:
    if domain.element_kind == "space":
        return _encode_level(item, space, template_prefix)
    if domain.element_kind == "choice":
        assert isinstance(domain.element_domain, ChoiceDomain)
        return _encode_choice_value(item, space, template_prefix[:-1])
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        if not isinstance(item, list):
            return item
        return [
            _encode_list_element(sub, domain.element_domain, space, f"{template_prefix[:-1]}[].")
            for sub in item
        ]
    return _encode_scalar_value(
        domain.element_kind, domain.element_domain, domain.element_quantized, item
    )


def encode_config(config: dict[str, Any], space: Space) -> Any:
    return _encode_level(config, space, template_prefix="")
