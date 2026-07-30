"""`ds.param_from_def` / `ds.space_from_ir` (API.md, "Space —
Metaprogramming"; DECISIONS.md D-41). `.map_params`/`.without_constraints`
sugar lives on `Space` (build/_space.py), both routed through
`space_from_ir`.

"The IR is bidirectional": `param_from_def` inverts one resolved `ParamDef`
back into the `TypedParamExpr` view the fluent builder would have produced,
via `resolve.param_def_to_view` — the reverse of `_emit`'s per-definition
half. `space_from_ir` goes the other way at space granularity: it takes an
already-flat IR (exactly the shape `Space.params`/`.conditions`/
`.constraints` already have — no structural relocation, since that only
happens once, going from nested builder exprs to flat IR) and re-validates
it via `resolve.revalidate_space` ("resolution re-validates whatever comes
in") into a fresh `Space`.

A struct/choice-kind `ParamDef` cannot invert *alone* through
`param_from_def`: `_emit()` relocates its descendants into separate flat
`Space.params` entries (`"s.field"`, `"c.variant."`) that a single
`ParamDef` has no reference to. `space_from_ir` has no such gap — every
descendant is already its own entry in the `params` it receives — so
`param_def_to_view`'s payload-less struct/choice view is exactly right
there, and only `param_from_def` need reject the two container kinds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

from designspace.build._space import Space
from designspace.build._views import TypedParamExpr
from designspace.errors import ResolutionError
from designspace.ir import Condition, Constraint, ListDomain, ParamDef
from designspace.resolve import param_def_to_view, rebuild_charts, revalidate_space
from designspace.resolve._anchors import add_anchors

_NO_SINGLE_DEF_INVERSE = (
    "param_from_def(): {path!r} {detail} — its descendants live as separate "
    "flat ParamDefs elsewhere in the space and cannot be recovered from this "
    "ParamDef alone; feed the whole flat IR to space_from_ir() instead"
)


def param_from_def(pd: ParamDef) -> TypedParamExpr:
    if pd.type_kind in ("space", "choice"):
        raise TypeError(
            _NO_SINGLE_DEF_INVERSE.format(path=pd.path, detail=f"is a {pd.type_kind!r} container")
        )
    if pd.type_kind == "list":
        assert isinstance(pd.domain, ListDomain)
        elem_kind = _innermost_element_kind(pd.domain)
        if elem_kind in ("space", "choice"):
            raise TypeError(
                _NO_SINGLE_DEF_INVERSE.format(
                    path=pd.path, detail=f"repeats a {elem_kind!r} container element"
                )
            )
    view = param_def_to_view(pd)
    assert isinstance(view, TypedParamExpr)
    return view


def _innermost_element_kind(domain: ListDomain) -> str:
    while domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        domain = domain.element_domain
    return domain.element_kind


def _build_space_from_ir(
    params: Mapping[str, ParamDef] | Iterable[ParamDef],
    conditions: Iterable[Condition],
    constraints: Iterable[Constraint],
    anchors: dict[str, dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> Space:
    """The un-validated-anchors core of `space_from_ir` — accepts `anchors`
    as-is, with no row-22 check. `space_from_ir` (below) is the public,
    strict entry point for a caller with no anchor-validation strategy of
    its own; `ops/_structural.py`'s `.select()`/`.freeze()`/`.slice()` call
    *this* instead, since each already applies its own — hard-fail
    (`_revalidate_anchors_unchanged_shape`) or warn-and-drop
    (`_drop_invalid_anchors`) — immediately afterward, and a validating
    rebuild here would raise before either gets the chance to run."""
    pd_list = list(params.values()) if isinstance(params, Mapping) else list(params)
    rebuilt: dict[str, ParamDef] = {}
    for pd in pd_list:
        if pd.path in rebuilt:
            raise ResolutionError(f"duplicate param path {pd.path!r} in space_from_ir()")
        rebuilt[pd.path] = rebuild_charts(pd)
    space = Space(
        params=MappingProxyType(rebuilt),
        conditions=tuple(conditions),
        constraints=tuple(constraints),
        anchors=MappingProxyType(dict(anchors or {})),
        meta_map=MappingProxyType(dict(meta or {})),
    )
    return revalidate_space(space)


def space_from_ir(
    params: Mapping[str, ParamDef] | Iterable[ParamDef],
    conditions: Iterable[Condition],
    constraints: Iterable[Constraint],
    anchors: dict[str, dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> Space:
    space = _build_space_from_ir(params, conditions, constraints, meta=meta)
    if anchors:
        # M10.5 item 8: routed through the same `add_anchors` a builder's
        # `.anchor()` uses, so an anchor invalid against the space raises
        # row 22 here too — this path used to accept it silently, since
        # neither `revalidate_space` nor `_build_space_from_ir` above checks
        # anchors at all (deliberately, for the internal callers above).
        space = add_anchors(space, anchors)
    return space
