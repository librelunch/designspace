"""Polars dtype schema derived from `Space.params` (API.md, "Config
Representation" > "DataFrame output" dtype table). It reads no draw data
and is built once per `.sample()` call. It mirrors `config/_flatten.py`'s
`_direct_children`-driven traversal, dispatching to a polars dtype rather
than copying a value; `_rows.py` is the per-draw counterpart.

A `choice` expands into sibling schema entries at its own level, a `Utf8`
discriminator plus one `Struct` per parameterized variant, named `<local>`
and `<local>.<variant>`, rather than into one nested dtype, matching
the table's "Utf8 discriminator at the param path + one Struct per
parameterized variant at `param.variant`" literally. A lifted choice
(the list *element itself* is a choice) has no enclosing sibling scope to
expand into, so it collapses to a single `Struct` whose own fields are
named `variant` / `<variant>`, matching the table's
`List(Struct{variant: Utf8, <variant>: Struct | null, ...})` row exactly.
"""

from __future__ import annotations

from typing import Any, Literal

from designspace.builder._space import Space
from designspace.expr import ArithExpr
from designspace.ir import ChoiceDomain, ListDomain, PermutationDomain, SubsetDomain
from designspace.paths import element_prefix

_ScalarKind = Literal[
    "real",
    "integer",
    "categorical",
    "ordinal",
    "bool",
    "subset",
    "permutation",
    "symbolic",
    "code",
    "custom",
]
"""Every kind but the three container kinds.

`space`, `choice` and `list` each expand into further schema entries and are
dispatched by the two traversals below before a dtype is asked for. Naming
the remainder is what lets `_scalar_dtype` be checked as total: its callers
reach it only where the type checker has already ruled the containers out,
so a kind added to `TypeKind` and forgotten here fails at both ends.
"""


def build_schema(space: Space, pl: Any) -> dict[str, Any]:
    return _level_schema(space, "", pl)


def _level_schema(space: Space, template_prefix: str, pl: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for template_path in space._direct_children(template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        if pd.type_kind == "space":
            out[local_name] = pl.Struct(_level_schema(space, f"{template_path}.", pl))
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            out[local_name] = pl.Utf8
            for variant in pd.domain.has_payload:
                out[f"{local_name}.{variant}"] = pl.Struct(
                    _level_schema(space, f"{template_path}.{variant}.", pl)
                )
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            out[local_name] = _list_dtype(space, pd.domain, element_prefix(template_path), pl)
        else:
            out[local_name] = _scalar_dtype(pd.type_kind, pd.domain, pl)
    return out


def _list_dtype(space: Space, domain: ListDomain, elem_template_prefix: str, pl: Any) -> Any:
    inner = _element_dtype(space, domain, elem_template_prefix, pl)
    if isinstance(domain.count, ArithExpr):
        return pl.List(inner)
    return pl.Array(inner, domain.count)


def _element_dtype(space: Space, domain: ListDomain, elem_template_prefix: str, pl: Any) -> Any:
    if domain.element_kind == "space":
        return pl.Struct(_level_schema(space, elem_template_prefix, pl))
    if domain.element_kind == "choice":
        assert isinstance(domain.element_domain, ChoiceDomain)
        choice_domain = domain.element_domain
        fields: dict[str, Any] = {"variant": pl.Utf8}
        for variant in choice_domain.has_payload:
            fields[variant] = pl.Struct(
                _level_schema(space, f"{elem_template_prefix}{variant}.", pl)
            )
        return pl.Struct(fields)
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _list_dtype(space, domain.element_domain, element_prefix(elem_template_prefix), pl)
    return _scalar_dtype(domain.element_kind, domain.element_domain, pl)


def _scalar_dtype(type_kind: _ScalarKind, domain: Any, pl: Any) -> Any:
    if type_kind == "real":
        return pl.Float64
    if type_kind == "integer":
        return pl.Int64
    if type_kind in ("categorical", "ordinal"):
        return pl.Utf8
    if type_kind == "bool":
        return pl.Boolean
    if type_kind == "subset":
        assert isinstance(domain, SubsetDomain)
        return pl.List(_item_dtype(domain.items, pl))
    if type_kind == "permutation":
        assert isinstance(domain, PermutationDomain)
        return pl.List(_item_dtype(domain.items, pl))
    if type_kind in ("symbolic", "code", "custom"):
        return pl.Utf8
    # Not `assert_never`: the branches above are grouped as API.md's dtype
    # table groups them, and a membership test narrows only the branch it
    # takes, so what reaches here is the grouped kinds rather than `Never`.
    # Splitting the groups to buy the proof would stop the dispatch mirroring
    # the table it implements. `_ScalarKind` still bounds what can arrive.
    raise AssertionError(f"unhandled type_kind {type_kind!r}")


def _item_dtype(items: tuple[Any, ...], pl: Any) -> Any:
    return pl.Series(list(items)).dtype
