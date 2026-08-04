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

from typing import TYPE_CHECKING, Any

from designspace.paths._grammar import parse_path

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


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
    """Which variant a choice parameter selected.

    A choice value is either a bare name, when the variant has no
    parameters of its own, or a single-key dict when it does. This reads
    the name either way, so callers need not branch on the shape.

    Parameters
    ----------
    config : dict[str, Any]
        A configuration, in nested form.
    param_path : str
        Path of the choice parameter. Use an instance path such as
        `"pipeline[0]"` to address one element of a lifted choice.

    Returns
    -------
    str
        The selected variant's name.

    Examples
    --------
    >>> config = {"opt": {"sgd": {"momentum": 0.5}}}
    >>> ds.variant(config, "opt")
    'sgd'
    >>> ds.variant({"opt": "adagrad"}, "opt")
    'adagrad'
    """
    name, _ = _split(param_path, _get_by_path(config, param_path))
    return name


def payload(config: dict[str, Any], param_path: str) -> dict[str, Any] | None:
    """The parameters carried by a choice parameter's selected variant.

    Parameters
    ----------
    config : dict[str, Any]
        A configuration, in nested form.
    param_path : str
        Path of the choice parameter.

    Returns
    -------
    dict[str, Any] | None
        The variant's own parameters, or `None` when the selected variant
        carries none.

    Examples
    --------
    >>> ds.payload({"opt": {"sgd": {"momentum": 0.5}}}, "opt")
    {'momentum': 0.5}
    >>> ds.payload({"opt": "adagrad"}, "opt") is None
    True
    """
    _, payload_value = _split(param_path, _get_by_path(config, param_path))
    return payload_value


def destructure(config: dict[str, Any], param_path: str) -> tuple[str, dict[str, Any] | None]:
    """Both the variant name and its payload, in one call.

    Equivalent to `ds.variant()` and `ds.payload()` together, and the
    natural way to unpack a choice.

    Parameters
    ----------
    config : dict[str, Any]
        A configuration, in nested form.
    param_path : str
        Path of the choice parameter.

    Returns
    -------
    tuple[str, dict[str, Any] | None]
        The variant name and its payload, the latter `None` when the
        variant carries no parameters.

    Examples
    --------
    >>> name, params = ds.destructure({"opt": {"sgd": {"momentum": 0.5}}}, "opt")
    >>> name, params
    ('sgd', {'momentum': 0.5})
    >>> ds.destructure({"opt": "adagrad"}, "opt")
    ('adagrad', None)
    """
    return _split(param_path, _get_by_path(config, param_path))
