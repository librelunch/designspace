"""`ds.unflatten()` (API_v3.md, "Config Utilities"): the inverse of
`flatten` — flat, path-keyed dict -> nested canonical phenotype.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.config._flatten import _direct_children
from designspace.ir import ChoiceDomain


def _unflatten_level(flat: dict[str, Any], space: Space, prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in _direct_children(space, prefix):
        pd = space.params[path]
        local_name = path[len(prefix) :]
        if pd.type_kind == "space":
            children = _direct_children(space, f"{path}.")
            if not children:
                result[local_name] = {}
                continue
            nested = _unflatten_level(flat, space, prefix=f"{path}.")
            if nested:
                result[local_name] = nested
            # else: struct is inactive (no descendant present) -- omit.
        elif pd.type_kind == "choice":
            if path not in flat:
                continue
            variant_name = flat[path]
            assert isinstance(pd.domain, ChoiceDomain)
            if variant_name in pd.domain.has_payload:
                nested = _unflatten_level(flat, space, prefix=f"{path}.{variant_name}.")
                result[local_name] = {variant_name: nested}
            else:
                result[local_name] = variant_name
        elif path in flat:
            result[local_name] = flat[path]
    return result


def unflatten(flat: dict[str, Any], space: Space) -> dict[str, Any]:
    return _unflatten_level(flat, space, prefix="")
