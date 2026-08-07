"""`ds.flatten()`: nested canonical phenotype to flat, path-keyed dict.

See API.md, "Config Utilities". `flatten` is structural and non-validating,
in the spec's own words.

`flatten_with_errors` walks the same space-guided recursion and additionally
collects a `ParamError` for each malformed shape: a choice value that is
neither a bare variant string nor a single-key dict, an unknown variant
name, or a struct value that is not a dict. `validate/` uses it, having to
catch what `flatten` is allowed to let through. One traversal with two
behaviours keeps the two from drifting apart on what counts as structurally
present.

A lift's descendant template, meaning a struct or choice element's fields,
lives in `space.params` under a `"[]"`-bracketed prefix such as
`"edges[].src"`. That is one definition shared by every instance, so the
traversal carries two prefixes side by side: `template_prefix`, used to look
up param definitions and always `"[]"`-bracketed for a lift descendant, and
`concrete_prefix`, used to write output keys and `"[i]"`-indexed. Outside a
lift the two coincide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from designspace.builder._space import Space
from designspace.ir import ChoiceDomain, ListDomain, ParamError
from designspace.paths import element_prefix, instance_prefix

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


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
    for template_path in space._direct_children(template_prefix):
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
                    errors.append(ParamError(param=concrete_path, reason="wrong_type", value=value))
                continue
            out[concrete_path] = len(value)
            for i, item in enumerate(value):
                _flatten_list_element(
                    item,
                    pd.domain,
                    space,
                    template_prefix=element_prefix(template_path),
                    concrete_prefix=instance_prefix(concrete_path, i),
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
    """Flatten one lift instance's value.

    `template_prefix` and `concrete_prefix` both end in `"."`, as in
    `"edges[]."` and `"edges[3]."`. `concrete_path`, without the trailing
    dot, is the instance's own leaf key when the element has no descendants
    of its own, as a scalar, subset or permutation element does not.
    """
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
                template_prefix=element_prefix(template_prefix),
                concrete_prefix=instance_prefix(concrete_path, j),
                out=out,
                errors=errors,
            )
    else:
        out[concrete_path] = item


def flatten(config: dict[str, Any], space: Space) -> dict[str, Any]:
    """Turn a nested configuration into one keyed by path.

    Configurations nest: a struct is a dict, a choice with a payload is a
    single-key dict, while `Space.params` is flat. This bridges the two,
    producing keys in the path grammar, which are also the DataFrame column
    names. `ds.unflatten()` reverses it.

    A choice contributes both its discriminator and its payload's
    parameters, so no information is lost.

    Parameters
    ----------
    config : dict[str, Any]
        A configuration in nested form.
    space : Space
        The space it belongs to, which supplies the structure to walk.

    Returns
    -------
    dict[str, Any]
        The configuration keyed by path.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("opt").choice(sgd=ds.space(ds.param("momentum").real(0, 1))),
    ...     ds.param("lr").real(0, 1),
    ... )
    >>> config = {"opt": {"sgd": {"momentum": 0.5}}, "lr": 0.1}
    >>> ds.flatten(config, s)
    {'opt': 'sgd', 'opt.sgd.momentum': 0.5, 'lr': 0.1}
    >>> ds.unflatten(ds.flatten(config, s), s) == config
    True
    """
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
