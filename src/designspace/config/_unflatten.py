"""`ds.unflatten()`: flat, path-keyed dict to nested canonical phenotype.

The inverse of `flatten`; see API.md, "Config Utilities".

A lift's realized count lives at its own flat key, so `flat["dropout"] == 4`
and `flat["edges"] == 2`. Each instance's values live under `"[i]"`-indexed
keys, reconstructed from the `"[]"`-bracketed descendant template in
`space.params`. This mirrors `_flatten.py`'s template and concrete prefix
pair.

**The static-count fallback** (API.md, "The fixed leaf layout"). When the
bookkeeping key is absent and the `ListDomain`'s own count is a literal
`int`, that count recovers the length rather than the list being dropped.
This is what makes `ds.unflatten(dict(zip(space.coordinate_paths(), values)),
space)`, a flat dict carrying no bookkeeping keys at all, an inverse of
`flatten`.

A present bookkeeping key wins, being `flatten`'s own realized length, so
the fallback fires only on absence. A dynamic count that is absent is
unrecoverable, no `ListDomain` count existing to fall back to: the outer
level omits the list and a nested level raises `KeyError`. The spec
addresses the static case only.

**The emptiness check.** An absent bookkeeping key does not by itself
distinguish a full coordinate vector, every leaf present and no bookkeeping
key anywhere, from a list deliberately left implicit with no element
written. `apply_defaults` produces the second shape: API.md, "Defaults" >
"Counts and lifts" says that "otherwise the lift is left implicit". The
static fallback therefore requires at least one real leaf under the list's
own instance range before reconstructing anything, and omits the list when
it finds none, as an absent bookkeeping key on a dynamic count does.

Without the check, a scalar or custom leaf raises an uncaught `KeyError` and
a struct element, which unflattens absence to `{}` rather than raising,
silently yields `n` empty placeholders. Neither is the "omit if nothing
present" answer every other absent container gets.

The check is gated to a fully static count chain, meaning every nested
`.repeat()` level carries a literal `int`, which is the boundary
`coordinate_paths()` draws for a fixed layout. A mixed chain, a static outer
count over a dynamic inner one such as `.repeat(ds.param("n")).repeat(2)`,
falls under the unrecoverable case above: the inner count is never a literal
the fallback can use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from designspace.builder._space import Space
from designspace.expr import ArithExpr
from designspace.ir import ChoiceDomain, ListDomain
from designspace.paths import element_prefix, instance_prefix

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


def _is_fully_static(domain: ListDomain) -> bool:
    """Whether every level of a possibly nested lift has a literal `int` count.

    This is the boundary `coordinate_paths()` draws for a fixed layout. A
    struct or choice element is a recursion boundary, handled by its own
    `_unflatten_level` call, and is not inspected here.

    It gates the static-count fallback's emptiness check below. A mixed
    chain, a static outer count over a dynamic inner one such as
    `.repeat(ds.param("n")).repeat(2)`, is unrecoverable regardless of data
    and must keep raising.
    """
    if not isinstance(domain.count, int):
        return False
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _is_fully_static(domain.element_domain)
    return True


def _resolve_count(flat: dict[str, Any], concrete_path: str, count: int | ArithExpr) -> int | None:
    """The lift's realized length at `concrete_path`.

    The flat bookkeeping key wins when present. On absence a literal
    `ListDomain` count is used instead. The result is `None` when neither
    resolves, meaning a dynamic count that is absent.
    """
    if concrete_path in flat:
        return cast("int", flat[concrete_path])
    if isinstance(count, int):
        return count
    return None


def _unflatten_level(
    flat: dict[str, Any], space: Space, template_prefix: str, concrete_prefix: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for template_path in space._direct_children(template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        concrete_path = concrete_prefix + local_name
        if pd.type_kind == "space":
            children = space._direct_children(f"{template_path}.")
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
            # else the struct is inactive, no descendant being present, so omit it.
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            value = _unflatten_choice(flat, pd.domain, space, template_path, concrete_path)
            if value is not None:
                result[local_name] = value
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            bookkeeping_present = concrete_path in flat
            n = _resolve_count(flat, concrete_path, pd.domain.count)
            if n is None:
                continue
            if not bookkeeping_present and n > 0 and _is_fully_static(pd.domain):
                # A literal count needs no bookkeeping key to be
                # determined, so absence alone cannot distinguish a full
                # coordinate vector, every leaf present and no bookkeeping
                # key anywhere, from a list left implicit with nothing
                # written, as `apply_defaults` leaves a no-default lift or
                # an inactive list. An element kind that unflattens absence
                # to `{}` rather than raising, a struct with nothing
                # present, would then reconstruct `n` empty placeholders
                # instead of omitting the list. Check for at least one real
                # leaf under this instance range first. Gated to a fully
                # static chain; a mixed static and dynamic nested count
                # still raises.
                marker = f"{concrete_path}["
                if not any(k.startswith(marker) for k in flat):
                    continue
            result[local_name] = [
                _unflatten_list_element(
                    flat,
                    pd.domain,
                    space,
                    template_prefix=element_prefix(template_path),
                    concrete_prefix=instance_prefix(concrete_path, i),
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
        n = _resolve_count(flat, concrete_path, domain.element_domain.count)
        if n is None:
            raise KeyError(concrete_path)  # dynamic and absent: unrecoverable
        return [
            _unflatten_list_element(
                flat,
                domain.element_domain,
                space,
                template_prefix=element_prefix(template_prefix),
                concrete_prefix=instance_prefix(concrete_path, j),
            )
            for j in range(n)
        ]
    return flat[concrete_path]


def unflatten(flat: dict[str, Any], space: Space) -> dict[str, Any]:
    """Rebuild a nested configuration from one keyed by path.

    The inverse of `ds.flatten()`, and the way back from a solver's flat
    view to the shape `.validate()` and `.sample_one()` speak.

    Parameters
    ----------
    flat : dict[str, Any]
        A configuration keyed by path.
    space : Space
        The space it belongs to, which supplies the structure to rebuild.

    Returns
    -------
    dict[str, Any]
        The configuration in nested form.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("opt").choice(sgd=ds.space(ds.param("momentum").real(0, 1))),
    ...     ds.param("lr").real(0, 1),
    ... )
    >>> flat = {"opt": "sgd", "opt.sgd.momentum": 0.5, "lr": 0.1}
    >>> ds.unflatten(flat, s)
    {'opt': {'sgd': {'momentum': 0.5}}, 'lr': 0.1}
    """
    return _unflatten_level(flat, space, template_prefix="", concrete_prefix="")
