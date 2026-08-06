"""`ds.unflatten()` (API.md, "Config Utilities"): the inverse of
`flatten` — flat, path-keyed dict -> nested canonical phenotype.

M4 adds list (lift) values, mirroring `_flatten.py`'s template/concrete
prefix pair (DECISIONS.md D-18): a lift's realized count lives at its own
flat key (`flat["dropout"] == 4`, `flat["edges"] == 2`); each instance's
value(s) live under `"[i]"`-indexed keys, reconstructed from the `"[]"`-
bracketed descendant *template* in `space.params`.

M10.7 adds the **static-count fallback** (API.md, "The fixed leaf layout"):
when the bookkeeping key is absent and the `ListDomain`'s own count is a
literal `int`, that count recovers the length instead of silently dropping
the list — this is what makes `ds.unflatten(dict(zip(space.coordinate_paths(),
values)), space)` (a flat dict with no bookkeeping keys at all) an inverse of
`flatten`. A *present* bookkeeping key still wins (it is `flatten`'s own
realized length); the fallback fires only on absence. A *dynamic* and absent
count stays exactly as before — unrecoverable, since no `ListDomain` count
exists to fall back to: the outer level omits the list (as it already did),
the nested level still raises `KeyError` (as it already did) — noted, not
changed; the spec addresses only the static case.

**Bug fix (post-M10.7):** the static-count fallback originally assumed an
absent bookkeeping key always meant "a full coordinate vector was supplied,
recover the length" — but `apply_defaults` also calls this same `unflatten`
on a `flat` dict where a literal-count list was deliberately left implicit
(API.md, "Defaults" > "Counts and lifts": "otherwise the lift is left
implicit") with *no* element ever written, and the fallback then tried to
reconstruct elements that were never there. For a scalar/custom leaf that
raised an uncaught `KeyError`; for a struct element (which unflattens
absence to `{}` rather than raising, mirroring the omission convention just
above) it instead silently produced `n` empty placeholders — either way,
not the "omit if nothing present" answer every other absent container
already gets. The static (non-zero-count) fallback branch now checks for at
least one real leaf under the list's own instance range before committing
to reconstruct anything; finding none, it omits the list instead, exactly
like an absent bookkeeping key on a dynamic count already did. A present
bookkeeping key skips this check entirely (unaffected, exactly as before),
and the fully-supplied coordinate-vector round trip (no bookkeeping keys
anywhere, but every leaf present) always finds its own first leaf and so is
unaffected too.

This check is gated to a **fully static** count chain (`_is_fully_static`,
every nested `.repeat()` level a literal `int` — the identical boundary
`coordinate_paths()` itself draws for "fixed layout"). A *mixed* chain — a
static outer count over a dynamic inner one, e.g.
`.repeat(ds.param("n")).repeat(2)` — is the separate, already-documented
case just above: unrecoverable regardless of data, because the *inner*
count is never a literal the fallback can use, so it still raises exactly
as before this fix.
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
    """`True` iff every level of a (possibly nested-list) lift has a
    literal `int` count -- the same boundary `coordinate_paths()` itself
    draws for a "fixed layout" (a struct/choice element is a recursion
    boundary handled by its own independent `_unflatten_level` call, not
    inspected here). Gates the static-count-fallback safety check below: a
    *mixed* chain (a static outer count over a dynamic inner one, e.g.
    `.repeat(ds.param("n")).repeat(2)`) is a different, already-documented
    "unrecoverable regardless of data" case (M10.7's own "nested level
    still raises `KeyError`" note) that this fix must not touch.
    """
    if not isinstance(domain.count, int):
        return False
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _is_fully_static(domain.element_domain)
    return True


def _resolve_count(flat: dict[str, Any], concrete_path: str, count: int | ArithExpr) -> int | None:
    """The lift's realized length at `concrete_path`. Prefers the flat
    bookkeeping key when present; falls back to a literal `ListDomain` count
    on absence; `None` when neither resolves (a dynamic count, absent)."""
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
            # else: struct is inactive (no descendant present) -- omit.
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
                # Static-count fallback (D-75): a literal count needs no
                # bookkeeping key to be "determined", so its absence alone
                # can't distinguish a full coordinate vector (every leaf
                # present, no bookkeeping keys anywhere -- the round-trip
                # this fallback exists for) from a list left implicit with
                # nothing written at all (`apply_defaults` leaving a
                # no-default lift unfilled, or an inactive list) -- an
                # element kind that unflattens absence to `{}` rather than
                # raising (a struct with nothing present) would otherwise
                # "reconstruct" `n` empty placeholders instead of omitting
                # the list, so check for at least one real leaf under this
                # instance range before committing to any of it. Gated to a
                # *fully* static chain -- a mixed static/dynamic nested
                # count is the separate, unchanged "still raises" case.
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
            raise KeyError(concrete_path)  # dynamic and absent -- unrecoverable, unchanged
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
