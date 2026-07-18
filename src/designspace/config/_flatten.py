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

M4 adds list (lift) values. A lift's *descendant* template (struct/choice
element fields) lives in `space.params` under a `"[]"`-bracketed prefix
(`"edges[].src"`, DECISIONS.md D-18) — one definition, shared by every
instance — so the traversal here carries two prefixes side by side: a
`template_prefix` used to look up param defs (always `"[]"`-bracketed for
lift descendants) and a `concrete_prefix` used to write output keys
(`"[i]"`-indexed). Everywhere prior to M4, the two coincide.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.ir import ChoiceDomain, ListDomain, ParamError


def _direct_children(space: Space, prefix: str) -> list[str]:
    """Full (template) paths that are one segment below `prefix` ("" for
    root, `"algo.svm."` inside a chosen variant, or `"edges[]."` inside a
    lift's element template)."""
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
    template_prefix: str,
    concrete_prefix: str,
    out: dict[str, Any],
    errors: list[ParamError] | None,
) -> None:
    if not isinstance(nested, dict):
        return
    for template_path in _direct_children(space, template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        if local_name not in nested:
            continue
        value = nested[local_name]
        concrete_path = concrete_prefix + local_name
        if pd.type_kind == "space":
            if isinstance(value, dict):
                _flatten_level(
                    value,
                    space,
                    template_prefix=f"{template_path}.",
                    concrete_prefix=f"{concrete_path}.",
                    out=out,
                    errors=errors,
                )
            elif errors is not None:
                errors.append(ParamError(param=concrete_path, reason="wrong_type", value=value))
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            _flatten_choice_value(
                value, pd.domain, space, template_path, concrete_path, out, errors
            )
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            if not isinstance(value, list):
                if errors is not None:
                    errors.append(
                        ParamError(param=concrete_path, reason="wrong_type", value=value)
                    )
                continue
            out[concrete_path] = len(value)
            for i, item in enumerate(value):
                _flatten_list_element(
                    item,
                    pd.domain,
                    space,
                    template_prefix=f"{template_path}[].",
                    concrete_prefix=f"{concrete_path}[{i}].",
                    out=out,
                    errors=errors,
                )
        else:
            out[concrete_path] = value


def _flatten_choice_value(
    value: Any,
    domain: ChoiceDomain,
    space: Space,
    template_path: str,
    concrete_path: str,
    out: dict[str, Any],
    errors: list[ParamError] | None,
) -> None:
    variant_name, payload_value, well_formed = _split_choice_value(value)
    if not well_formed:
        if errors is not None:
            errors.append(ParamError(param=concrete_path, reason="wrong_type", value=value))
        return
    assert variant_name is not None
    if variant_name not in domain.variants:
        if errors is not None:
            errors.append(
                ParamError(param=concrete_path, reason="out_of_bounds", value=variant_name)
            )
        return
    has_payload = variant_name in domain.has_payload
    if has_payload != (payload_value is not None):
        if errors is not None:
            errors.append(ParamError(param=concrete_path, reason="wrong_type", value=value))
        out[concrete_path] = variant_name
        return
    out[concrete_path] = variant_name
    if has_payload:
        assert payload_value is not None
        _flatten_level(
            payload_value,
            space,
            template_prefix=f"{template_path}.{variant_name}.",
            concrete_prefix=f"{concrete_path}.{variant_name}.",
            out=out,
            errors=errors,
        )


def _flatten_list_element(
    item: Any,
    domain: ListDomain,
    space: Space,
    template_prefix: str,
    concrete_prefix: str,
    out: dict[str, Any],
    errors: list[ParamError] | None,
) -> None:
    """One lift instance's value — `template_prefix`/`concrete_prefix` both
    end in `"."` (e.g. `"edges[]."` / `"edges[3]."`); `concrete_path` (no
    trailing dot) is the instance's own leaf key when the element has no
    descendants of its own (scalar/subset/permutation)."""
    concrete_path = concrete_prefix[:-1]
    if domain.element_kind == "space":
        if isinstance(item, dict):
            _flatten_level(item, space, template_prefix, concrete_prefix, out, errors)
        elif errors is not None:
            errors.append(ParamError(param=concrete_path, reason="wrong_type", value=item))
    elif domain.element_kind == "choice":
        assert isinstance(domain.element_domain, ChoiceDomain)
        _flatten_choice_value(
            item,
            domain.element_domain,
            space,
            template_prefix[:-1],
            concrete_path,
            out,
            errors,
        )
    elif domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        if not isinstance(item, list):
            if errors is not None:
                errors.append(ParamError(param=concrete_path, reason="wrong_type", value=item))
            return
        out[concrete_path] = len(item)
        for j, subitem in enumerate(item):
            _flatten_list_element(
                subitem,
                domain.element_domain,
                space,
                template_prefix=f"{template_prefix[:-1]}[].",
                concrete_prefix=f"{concrete_path}[{j}].",
                out=out,
                errors=errors,
            )
    else:
        out[concrete_path] = item


def flatten(config: dict[str, Any], space: Space) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _flatten_level(config, space, template_prefix="", concrete_prefix="", out=out, errors=None)
    return out


def flatten_with_errors(
    config: dict[str, Any], space: Space
) -> tuple[dict[str, Any], list[ParamError]]:
    out: dict[str, Any] = {}
    errors: list[ParamError] = []
    _flatten_level(config, space, template_prefix="", concrete_prefix="", out=out, errors=errors)
    return out, errors
