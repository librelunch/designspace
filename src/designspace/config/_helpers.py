"""`ds.variant()` / `ds.payload()` / `ds.destructure()` (API.md, "Config
Utilities"). Choice values are self-contained, so unlike `flatten`/
`unflatten` these need no `Space` — the shape (bare string vs. single-key
dict) is self-describing; `param_path` addresses a nested slot by walking
the path grammar's segments, exactly matching definition/instance paths
(struct namespaces and chosen variant names are plain dict keys in the
canonical nested config, and `[k]` indexes into a lifted-choice list —
`variant(config, "pipeline[1]")`). Addressing a lifted choice by its bare
list path (`"pipeline"`) is a misuse error naming the indexed form (a list
has no single variant); the scalar return types are preserved.
"""

from __future__ import annotations

from typing import Any

from designspace.paths._grammar import parse_path


def _get_by_path(config: dict[str, Any], param_path: str) -> Any:
    node: Any = config
    for seg in parse_path(param_path):
        if not isinstance(node, dict) or seg.name not in node:
            raise KeyError(f"{param_path!r} not found in config")
        node = node[seg.name]
        for idx in seg.brackets:
            # An instance path's brackets are all concrete indices; a bare
            # definition marker (`[]`, `idx is None`) addresses no config value.
            if idx is None or not isinstance(node, list) or not 0 <= idx < len(node):
                raise KeyError(f"{param_path!r} not found in config")
            node = node[idx]
    return node


def _split(param_path: str, value: Any) -> tuple[str, dict[str, Any] | None]:
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict) and len(value) == 1:
        ((name, payload_value),) = value.items()
        return name, payload_value
    if isinstance(value, list):
        # A lifted-choice bare list path: a list has no single variant — name
        # the indexed form the caller meant (API.md, "Config Utilities").
        raise TypeError(
            f"{param_path!r} addresses a lifted-choice list, which has no single "
            f"variant; use an instance path like {param_path + '[0]'!r}"
        )
    raise ValueError(f"{param_path!r}: not a well-formed choice value: {value!r}")


def variant(config: dict[str, Any], param_path: str) -> str:
    name, _ = _split(param_path, _get_by_path(config, param_path))
    return name


def payload(config: dict[str, Any], param_path: str) -> dict[str, Any] | None:
    _, payload_value = _split(param_path, _get_by_path(config, param_path))
    return payload_value


def destructure(config: dict[str, Any], param_path: str) -> tuple[str, dict[str, Any] | None]:
    return _split(param_path, _get_by_path(config, param_path))
