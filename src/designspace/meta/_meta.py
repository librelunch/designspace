"""`ds.param_from_def` and `ds.space_from_ir` (API.md, "Space:
Metaprogramming").

The `.map_params` and `.without_constraints` sugar lives on `Space`, in
`builder/_space.py`, and both route through `space_from_ir`.

"The IR is bidirectional". `param_from_def` inverts one resolved `ParamDef`
into the `TypedParamExpr` view the fluent builder would have produced,
through `resolve.param_def_to_view`, the reverse of `_emit`'s per-definition
half.

`space_from_ir` goes the other way at space granularity. It takes an
already-flat IR, exactly the shape `Space.params`, `.conditions` and
`.constraints` have, and re-validates it into a fresh `Space` through
`resolve.revalidate_space`, since "resolution re-validates whatever comes
in". No structural relocation happens, that occurring once only, going from
nested builder expressions to flat IR.

A struct- or choice-kind `ParamDef` cannot invert alone through
`param_from_def`. `_emit()` relocates its descendants into separate flat
`Space.params` entries, such as `"s.field"` and `"c.variant."`, that a
single `ParamDef` has no reference to. `space_from_ir` has no such gap,
every descendant already being its own entry in the `params` it receives, so
`param_def_to_view`'s payload-less struct and choice view is right there and
only `param_from_def` need reject the two container kinds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from designspace.builder._space import Space
from designspace.builder._views import TypedParamExpr
from designspace.errors import ResolutionError
from designspace.ir import Condition, Constraint, ListDomain, ParamDef
from designspace.resolve import param_def_to_view, rebuild_charts, revalidate_space
from designspace.resolve._anchors import add_anchors

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)

_NO_SINGLE_DEF_INVERSE = (
    "param_from_def(): {path!r} {detail}; its descendants live as separate "
    "flat ParamDefs elsewhere in the space and cannot be recovered from this "
    "ParamDef alone; feed the whole flat IR to space_from_ir() instead"
)


def param_from_def(pd: ParamDef) -> TypedParamExpr:
    """Turn a resolved parameter back into a builder.

    The inverse of declaring one, and half of what makes the IR
    bidirectional: read a space, adjust a parameter, rebuild. Useful when
    generating spaces from a registry or a catalogue rather than writing
    them out by hand.

    Parameters
    ----------
    pd : ParamDef
        A resolved parameter, typically from `Space.params`.

    Returns
    -------
    TypedParamExpr
        A builder equivalent to the original declaration.

    Raises
    ------
    TypeError
        If the parameter is a struct or choice, or a `.repeat()` of one.
        Such a parameter's contents live in other `ParamDef` entries and
        cannot be recovered from this one alone; pass the whole IR to
        `ds.space_from_ir()` instead.

    Examples
    --------
    >>> s = ds.space(ds.param("depth").integer(1, 8))
    >>> rebuilt = ds.space(ds.param_from_def(s.params["depth"]))
    >>> rebuilt.fingerprint() == s.fingerprint()
    True
    """
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
    """`space_from_ir`'s core, accepting `anchors` with no row-22 check.

    `space_from_ir` below is the public, strict entry point, for a caller
    with no anchor-validation strategy of its own. `.select()`, `.freeze()`
    and `.slice()` in `ops/_structural.py` call this instead, each applying
    its own strategy immediately afterward: `_revalidate_anchors_unchanged_shape`
    hard-fails and `_drop_invalid_anchors` warns and drops. A validating
    rebuild here would raise before either could run.
    """
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
    """Build a `Space` directly from IR, bypassing the builders.

    The other half of the bidirectional IR: `Space.to_json()` and
    `Space.params` read it out, this puts it back. Whatever you supply is
    re-resolved and re-validated exactly like a hand-written declaration,
    so a programmatically assembled space is checked as thoroughly as any
    other. This is also what `Space.map_params()` uses internally.

    It is the route to spaces the fluent API cannot express directly, and
    the supported way to write a structural `Representation`.

    Parameters
    ----------
    params : Mapping[str, ParamDef] | Iterable[ParamDef]
        The parameters, keyed by path or in declaration order.
    conditions : Iterable[Condition]
        Activity conditions.
    constraints : Iterable[Constraint]
        Constraints of any kind.
    anchors : dict[str, dict[str, Any]] | None
        Named reference configurations, validated against the new space.
    meta : dict[str, Any] | None
        Space-level metadata.

    Returns
    -------
    Space
        The rebuilt space.

    Raises
    ------
    ResolutionError
        If the supplied IR does not form a valid space: a duplicate path,
        a dangling reference, an anchor that does not validate.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("algo").categorical("greedy", "exact"),
    ...     ds.param("depth").integer(1, 4),
    ... )
    >>> rebuilt = ds.space_from_ir(s.params, s.conditions, s.constraints)
    >>> rebuilt.fingerprint() == s.fingerprint()
    True
    """
    space = _build_space_from_ir(params, conditions, constraints, meta=meta)
    if anchors:
        # Routed through the same `add_anchors` a builder's
        # `.anchor()` uses, so an anchor invalid against the space raises
        # row 22 here too. Neither `revalidate_space` nor
        # `_build_space_from_ir` checks anchors at all, deliberately, for
        # the internal callers above.
        space = add_anchors(space, anchors)
    return space
