"""`Space.subspaces` / `Space.dependency_graph` (API.md, "Space —
Introspection"; DECISIONS.md D-43 — neither's exact shape is otherwise
specified). Shared with `ops/_structural.py`'s `.select()`: "prefix subtree"
selection is exactly a lookup into `subspaces()`.
"""

from __future__ import annotations

from designspace.builder._paramexpr import ParamExpr
from designspace.builder._space import Space
from designspace.expr import ArithExpr, BoolExpr, Compare, Literal
from designspace.ir import ChoiceDomain, ListDomain, SubspaceInfo


def subspaces(space: Space) -> dict[str, SubspaceInfo]:
    """One entry per struct param and per payload-bearing choice variant,
    keyed by its relocation prefix — the same prefix
    `resolve/_relocate.py::relocate_child` reprefixed that payload's
    descendants under. `condition` reconstructs the activation condition
    `_relocate_choice_variants` folds into each descendant (own condition
    AND, for a variant, the discriminator equality) as a single value.
    """
    result: dict[str, SubspaceInfo] = {}
    for path, pd in space.params.items():
        if pd.type_kind == "space":
            prefix = f"{path}."
            result[prefix] = SubspaceInfo(
                prefix=prefix,
                kind="struct",
                member_paths=tuple(sorted(p for p in space.params if p.startswith(prefix))),
                condition=pd.condition,
            )
        elif pd.type_kind == "choice":
            assert isinstance(pd.domain, ChoiceDomain)
            for variant in pd.domain.variants:
                if variant not in pd.domain.has_payload:
                    continue
                prefix = f"{path}.{variant}."
                discriminator_eq: BoolExpr = Compare("eq", ParamExpr(path=path), Literal(variant))
                condition = (
                    discriminator_eq if pd.condition is None else pd.condition & discriminator_eq
                )
                result[prefix] = SubspaceInfo(
                    prefix=prefix,
                    kind="variant",
                    member_paths=tuple(sorted(p for p in space.params if p.startswith(prefix))),
                    condition=condition,
                    variant_name=variant,
                )
    return result


def dependency_graph(space: Space) -> dict[str, frozenset[str]]:
    """Each definition path's condition + constraint + repeat-count
    dependencies (API.md, "Space: Introspection"): a param's own
    condition (if any) contributes its referenced params; every constraint
    couples all the params it mentions together (added symmetrically, since
    a plain constraint has no distinguished target — unlike a condition,
    which does); a `.repeat()`-closed param's (possibly chained) count
    contributes whatever it references. Every path in `space.params` gets
    an entry, including lift-descendant templates (`"[]"`), matching
    `.params`'s own unfiltered transparency — unlike `topological_order`
    (`partial/_partial.py`), which filters those out for its own,
    execution-order-specific purpose.
    """
    deps: dict[str, set[str]] = {path: set() for path in space.params}
    for cond in space.conditions:
        deps[cond.target] |= cond.params - {cond.target}
    for c in space.constraints:
        for p in c.params:
            if p in deps:
                deps[p] |= c.params - {p}
    for path, pd in space.params.items():
        if pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            deps[path] |= _list_count_deps(pd.domain)
    return {k: frozenset(v) for k, v in deps.items()}


def _list_count_deps(domain: ListDomain) -> frozenset[str]:
    deps: set[str] = set(domain.count.params) if isinstance(domain.count, ArithExpr) else set()
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        deps |= _list_count_deps(domain.element_domain)
    return frozenset(deps)
