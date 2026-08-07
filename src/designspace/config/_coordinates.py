"""`Space.coordinate_paths()`: the fixed leaf layout.

See API.md, "Config Utilities" > "The fixed leaf layout", and error-table
row 33.

The layout is the ordered instance paths of a space's leaf entries,
excluding the lift-length entries `flatten` emits as structural
bookkeeping. It is what a consumer needs to pack a config into a positional
container, such as a solver's parameter vector.

It requires every `.repeat()` count to be a literal integer and no param to
carry a condition. Either makes the key set config-dependent, so no
positional layout exists, which is row 33.

The walk below mirrors `_flatten_level` and `_flatten_list_element` in
`config/_flatten.py`: the same `_direct_children`-driven descent, the same
`template_prefix` and `concrete_prefix` pair, and the same struct, choice
and list dispatch. It differs in being driven by the space alone, with no
config and no gate, and in never writing a list's own bookkeeping count.

A payload-bearing choice never reaches the walk. `resolve/_pipeline.py`
folds the discriminator-equality condition into every variant descendant's
`.condition`, so the row-33 sweep below raises before descent could matter.
A choice with bare variants only contributes one coordinate, its
discriminator.
"""

from __future__ import annotations

from designspace.builder._space import Space, _has_dynamic_count
from designspace.errors import ResolutionError
from designspace.ir import ListDomain
from designspace.paths import element_prefix, instance_prefix


def _check_fixed_layout(space: Space) -> None:
    for path, pd in space.params.items():
        if pd.condition is not None:
            raise ResolutionError(
                f"coordinate_paths(): {path!r} carries a condition, so the "
                "space has no fixed layout (row 33)"
            )
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            if _has_dynamic_count(pd.domain):
                raise ResolutionError(
                    f"coordinate_paths(): {path!r} has a dynamic repeat() "
                    "count, so the space has no fixed layout (row 33)"
                )


def coordinate_paths(space: Space) -> tuple[str, ...]:
    from designspace.resolve._pipeline import check_fully_resolved

    check_fully_resolved(space)
    _check_fixed_layout(space)
    out: list[str] = []
    _walk_level(space, "", "", out)
    return tuple(out)


def _walk_level(space: Space, template_prefix: str, concrete_prefix: str, out: list[str]) -> None:
    for template_path in space._direct_children(template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        concrete_path = concrete_prefix + local_name
        if pd.type_kind == "space":
            _walk_level(space, f"{template_path}.", f"{concrete_path}.", out)
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            count = pd.domain.count
            assert isinstance(count, int)  # _check_fixed_layout already ensured static
            for i in range(count):
                _walk_list_element(
                    space,
                    pd.domain,
                    element_prefix(template_path),
                    instance_prefix(concrete_path, i),
                    out,
                )
        else:
            # A choice, always with bare variants only here since a
            # payload-bearing variant's descendant already raised above, and
            # every scalar, subset, permutation and custom leaf: one
            # coordinate each.
            out.append(concrete_path)


def _walk_list_element(
    space: Space, domain: ListDomain, template_prefix: str, concrete_prefix: str, out: list[str]
) -> None:
    concrete_path = concrete_prefix[:-1]
    if domain.element_kind == "space":
        _walk_level(space, template_prefix, concrete_prefix, out)
    elif domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        inner = domain.element_domain
        count = inner.count
        assert isinstance(count, int)
        for j in range(count):
            _walk_list_element(
                space,
                inner,
                element_prefix(template_prefix),
                instance_prefix(concrete_path, j),
                out,
            )
    else:
        # A choice element, with bare variants only, and every scalar,
        # subset, permutation and custom element: one coordinate each.
        out.append(concrete_path)
