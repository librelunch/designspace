"""`ds.unflatten()` (API.md, "Config Utilities"): the inverse of
`flatten` — flat, path-keyed dict -> nested canonical phenotype.

M4 adds list (lift) values, mirroring `_flatten.py`'s template/concrete
prefix pair (DECISIONS.md D-18): a lift's realized count lives at its own
flat key (`flat["dropout"] == 4`, `flat["edges"] == 2`); each instance's
value(s) live under `"[i]"`-indexed keys, reconstructed from the `"[]"`-
bracketed descendant *template* in `space.params`.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.config._flatten import _direct_children
from designspace.ir import ChoiceDomain, ListDomain


def _unflatten_level(
    flat: dict[str, Any], space: Space, template_prefix: str, concrete_prefix: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for template_path in _direct_children(space, template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        concrete_path = concrete_prefix + local_name
        if pd.type_kind == "space":
            children = _direct_children(space, f"{template_path}.")
            if not children:
                result[local_name] = {}
                continue
            nested = _unflatten_level(
                flat,
                space,
                template_prefix=f"{template_path}.",
                concrete_prefix=f"{concrete_path}.",
            )
            if nested:
                result[local_name] = nested
            # else: struct is inactive (no descendant present) -- omit.
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            value = _unflatten_choice(
                flat, pd.domain, space, template_path, concrete_path
            )
            if value is not None:
                result[local_name] = value
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            if concrete_path not in flat:
                continue
            n = flat[concrete_path]
            result[local_name] = [
                _unflatten_list_element(
                    flat,
                    pd.domain,
                    space,
                    template_prefix=f"{template_path}[].",
                    concrete_prefix=f"{concrete_path}[{i}].",
                )
                for i in range(n)
            ]
        elif concrete_path in flat:
            result[local_name] = flat[concrete_path]
    return result


def _unflatten_choice(
    flat: dict[str, Any],
    domain: ChoiceDomain,
    space: Space,
    template_path: str,
    concrete_path: str,
) -> Any | None:
    if concrete_path not in flat:
        return None
    variant_name = flat[concrete_path]
    if variant_name in domain.has_payload:
        nested = _unflatten_level(
            flat,
            space,
            template_prefix=f"{template_path}.{variant_name}.",
            concrete_prefix=f"{concrete_path}.{variant_name}.",
        )
        return {variant_name: nested}
    return variant_name


def _unflatten_list_element(
    flat: dict[str, Any],
    domain: ListDomain,
    space: Space,
    template_prefix: str,
    concrete_prefix: str,
) -> Any:
    concrete_path = concrete_prefix[:-1]
    if domain.element_kind == "space":
        return _unflatten_level(flat, space, template_prefix, concrete_prefix)
    if domain.element_kind == "choice":
        assert isinstance(domain.element_domain, ChoiceDomain)
        return _unflatten_choice(
            flat, domain.element_domain, space, template_prefix[:-1], concrete_path
        )
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        n = flat[concrete_path]
        return [
            _unflatten_list_element(
                flat,
                domain.element_domain,
                space,
                template_prefix=f"{template_prefix[:-1]}[].",
                concrete_prefix=f"{concrete_path}[{j}].",
            )
            for j in range(n)
        ]
    return flat[concrete_path]


def unflatten(flat: dict[str, Any], space: Space) -> dict[str, Any]:
    return _unflatten_level(flat, space, template_prefix="", concrete_prefix="")
