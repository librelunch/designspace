"""One DataFrame row from a flat sampler draw (API.md, "Config
Representation" -> "DataFrame output"). Mirrors `config/_unflatten.py`'s
`(template_prefix, concrete_prefix)`-threaded traversal, with two
deltas relative to it. An inactive path becomes `None`, a DataFrame column
always existing where a dict key need not, so `unflatten` omits and this
nulls. A choice becomes a Utf8-discriminator-plus-variant-Struct sibling
pair, `<name>` and `<name>.<variant>`, rather than a nested
`{variant: payload}` dict, matching `_schema.py`'s column layout.

Every definition path's activity is read from `activity` (`sample_flat`'s
flat per-draw pair) rather than inferred from `config`-presence: a struct
path never gets a `config` entry at all (API.md: "a struct... produces no
value of its own"), so `activity` is the only signal for whether a
`Struct` column should be `null`.

One path kind has no `activity` entry of its own: a nested lift level, from
`.repeat().repeat()` chaining. It needs none. A lift has no per-position
deactivation, so reaching a nested instance at all, through its enclosing
`range(n)`, already means it is present. `_element_row`'s "list" branch
reads `config` directly for that reason.
"""

from __future__ import annotations

import json
from typing import Any

from designspace.builder._space import Space
from designspace.ir import ChoiceDomain, ListDomain
from designspace.paths import element_prefix, instance_prefix


def build_row(space: Space, config: dict[str, Any], activity: dict[str, bool]) -> dict[str, Any]:
    return _level_row(space, "", "", config, activity)


def _level_row(
    space: Space,
    template_prefix: str,
    concrete_prefix: str,
    config: dict[str, Any],
    activity: dict[str, bool],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for template_path in space._direct_children(template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        concrete_path = concrete_prefix + local_name
        if pd.type_kind == "space":
            out[local_name] = (
                _level_row(space, f"{template_path}.", f"{concrete_path}.", config, activity)
                if activity.get(concrete_path, False)
                else None
            )
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            active = activity.get(concrete_path, False)
            variant = config.get(concrete_path) if active else None
            out[local_name] = variant
            for v in pd.domain.has_payload:
                out[f"{local_name}.{v}"] = (
                    _level_row(
                        space, f"{template_path}.{v}.", f"{concrete_path}.{v}.", config, activity
                    )
                    if variant == v
                    else None
                )
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            if not activity.get(concrete_path, False):
                out[local_name] = None
            else:
                n = config[concrete_path]
                out[local_name] = [
                    _element_row(
                        space,
                        pd.domain,
                        element_prefix(template_path),
                        instance_prefix(concrete_path, i),
                        config,
                        activity,
                    )
                    for i in range(n)
                ]
        else:
            out[local_name] = _scalar_value(pd.type_kind, concrete_path, config, activity)
    return out


def _element_row(
    space: Space,
    domain: ListDomain,
    elem_template_prefix: str,
    elem_concrete_prefix: str,
    config: dict[str, Any],
    activity: dict[str, bool],
) -> Any:
    if domain.element_kind == "space":
        return _level_row(space, elem_template_prefix, elem_concrete_prefix, config, activity)
    concrete_path = elem_concrete_prefix[:-1]
    if domain.element_kind == "choice":
        assert isinstance(domain.element_domain, ChoiceDomain)
        variant = config[concrete_path]
        row: dict[str, Any] = {"variant": variant}
        for v in domain.element_domain.has_payload:
            row[v] = (
                _level_row(
                    space,
                    f"{elem_template_prefix}{v}.",
                    f"{elem_concrete_prefix}{v}.",
                    config,
                    activity,
                )
                if variant == v
                else None
            )
        return row
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        n = config[concrete_path]
        return [
            _element_row(
                space,
                domain.element_domain,
                element_prefix(elem_template_prefix),
                instance_prefix(concrete_path, j),
                config,
                activity,
            )
            for j in range(n)
        ]
    return _scalar_value(domain.element_kind, concrete_path, config, activity)


def _scalar_value(
    type_kind: str, concrete_path: str, config: dict[str, Any], activity: dict[str, bool]
) -> Any:
    if not activity.get(concrete_path, False):
        return None
    raw = config[concrete_path]
    if type_kind in ("symbolic", "code", "custom"):
        return json.dumps(raw)
    if type_kind in ("subset", "permutation"):
        return list(raw)
    return raw
