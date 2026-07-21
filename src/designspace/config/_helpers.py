"""`ds.variant()` / `ds.payload()` / `ds.destructure()` (API.md, "Config
Utilities"). Choice values are self-contained, so unlike `flatten`/
`unflatten` these need no `Space` — the shape (bare string vs. single-key
dict) is self-describing; `param_path` just addresses a nested dict slot
by walking dot-separated segments, exactly matching definition paths
(struct namespaces and chosen variant names are both plain dict keys in
the canonical nested config).
"""

from __future__ import annotations

from typing import Any


def _get_by_path(config: dict[str, Any], param_path: str) -> Any:
    node: Any = config
    for segment in param_path.split("."):
        if not isinstance(node, dict) or segment not in node:
            raise KeyError(f"{param_path!r} not found in config")
        node = node[segment]
    return node


def _split(param_path: str, value: Any) -> tuple[str, dict[str, Any] | None]:
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict) and len(value) == 1:
        ((name, payload_value),) = value.items()
        return name, payload_value
    raise ValueError(f"{param_path!r}: not a well-formed choice value: {value!r}")


def variant(config: dict[str, Any], param_path: str) -> str:
    name, _ = _split(param_path, _get_by_path(config, param_path))
    return name


def payload(config: dict[str, Any], param_path: str) -> dict[str, Any] | None:
    _, payload_value = _split(param_path, _get_by_path(config, param_path))
    return payload_value


def destructure(config: dict[str, Any], param_path: str) -> tuple[str, dict[str, Any] | None]:
    return _split(param_path, _get_by_path(config, param_path))
