"""Capability negotiation over a design space.

A solver defines the space it can work with. Base CMA-ES is R^n, variants add
integers and categoricals, and define-by-run frameworks add conditionals.
Pointing one at a space therefore begins by asking whether the space falls
inside that envelope.

This module reads the answer off the public representation alone: parameter
kinds, whether a parameter's activity is conditional, whether a list has a
variable length, and whether a scalar carries a chart. It decides nothing. A
backend states its own envelope, and this module reports by path where a space
leaves it, so a refusal names the parameter responsible rather than the space
as a whole.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import designspace as ds

__all__ = [
    "ParamProfile",
    "Rejection",
    "SpaceProfile",
    "UnsupportedSpace",
    "profile",
    "rejections",
    "require",
]


@dataclass(frozen=True)
class Rejection:
    """One reason a backend cannot accept a space, attributed to a parameter.

    Attributes
    ----------
    path : str
        The definition path of the offending parameter.
    kind : ds.TypeKind
        That parameter's kind, as `ParamDef.type_kind` reports it.
    reason : str
        What about the parameter puts it outside the backend's envelope.
    """

    path: str
    kind: ds.TypeKind
    reason: str


class UnsupportedSpace(ValueError):
    """A backend was pointed at a space it cannot represent.

    Attributes
    ----------
    backend : str
        The name of the refusing backend.
    rejections : tuple[Rejection, ...]
        Every reason found, in the space's topological order. The full set is
        reported at once so that a space is not fixed one parameter per run.
    """

    def __init__(self, backend: str, found: Sequence[Rejection]) -> None:
        self.backend = backend
        self.rejections = tuple(found)
        detail = "; ".join(f"{r.path} ({r.kind}): {r.reason}" for r in self.rejections)
        super().__init__(f"{backend} cannot search this space: {detail}")


@dataclass(frozen=True)
class ParamProfile:
    """What a backend needs to know about one parameter to place it.

    Attributes
    ----------
    path : str
        The parameter's definition path.
    kind : ds.TypeKind
        The parameter's kind.
    has_chart : bool
        Whether a static chart maps `[0, 1]` onto the domain. True for real and
        integer parameters. Every other kind needs an embedding the consumer
        supplies, which is the division the library draws deliberately.
    conditional : bool
        Whether the parameter is active only under a condition.
    variable_length : bool
        Whether the parameter is a list whose count is an expression rather
        than a static integer.
    """

    path: str
    kind: ds.TypeKind
    has_chart: bool
    conditional: bool
    variable_length: bool


@dataclass(frozen=True)
class SpaceProfile:
    """A whole space, reduced to what capability negotiation needs.

    Attributes
    ----------
    params : tuple[ParamProfile, ...]
        One entry per parameter, in the space's topological order.
    """

    params: tuple[ParamProfile, ...]

    def kinds(self) -> frozenset[str]:
        """Return every parameter kind the space uses.

        Returns
        -------
        frozenset[str]
            The distinct kinds present.

        Examples
        --------
        >>> import designspace as ds
        >>> from designspace_solvers import profile
        >>> s = ds.space(ds.param("lr").real(0.001, 1.0), ds.param("n").integer(1, 8))
        >>> sorted(profile(s).kinds())
        ['integer', 'real']
        """
        return frozenset(p.kind for p in self.params)


def _is_variable_length(defn: ds.ParamDef) -> bool:
    domain = defn.domain
    return isinstance(domain, ds.ListDomain) and not isinstance(domain.count, int)


def profile(space: ds.Space) -> SpaceProfile:
    """Reduce a space to the facts a backend negotiates over.

    Parameters
    ----------
    space : designspace.Space
        The space to inspect. It is read through its public representation
        only, so any resolved space works.

    Returns
    -------
    SpaceProfile
        One `ParamProfile` per parameter, in topological order.

    Examples
    --------
    >>> import designspace as ds
    >>> from designspace_solvers import profile
    >>> s = ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale())
    >>> entry = profile(s).params[0]
    >>> entry.path, entry.kind, entry.has_chart
    ('lr', 'real', True)
    """
    entries = []
    for path in space.topological_order:
        defn = space.params[path]
        entries.append(
            ParamProfile(
                path=path,
                kind=defn.type_kind,
                has_chart=defn.chart is not None,
                conditional=defn.condition is not None,
                variable_length=_is_variable_length(defn),
            )
        )
    return SpaceProfile(params=tuple(entries))


def rejections(
    space: ds.Space,
    *,
    kinds: Iterable[str],
    conditional: bool = True,
    variable_length: bool = True,
) -> tuple[Rejection, ...]:
    """Report every parameter that falls outside a stated envelope.

    Parameters
    ----------
    space : designspace.Space
        The space to check.
    kinds : Iterable[str]
        The parameter kinds the backend can place.
    conditional : bool, default True
        Whether the backend can handle a parameter whose activity depends on
        another parameter's value.
    variable_length : bool, default True
        Whether the backend can handle a list whose count is an expression.

    Returns
    -------
    tuple[Rejection, ...]
        Every reason found, in topological order. Empty when the space fits.

    Examples
    --------
    >>> import designspace as ds
    >>> from designspace_solvers import rejections
    >>> s = ds.space(ds.param("lr").real(0.001, 1.0), ds.param("opt").categorical("a", "b"))
    >>> [r.path for r in rejections(s, kinds={"real"})]
    ['opt']
    """
    supported = frozenset(kinds)
    found = []
    for entry in profile(space).params:
        if entry.kind not in supported:
            found.append(
                Rejection(
                    path=entry.path,
                    kind=entry.kind,
                    reason=f"kind is not one of {sorted(supported)}",
                )
            )
            continue
        if entry.conditional and not conditional:
            found.append(
                Rejection(
                    path=entry.path,
                    kind=entry.kind,
                    reason="active only under a condition, and this backend has no "
                    "representation for an absent parameter",
                )
            )
        if entry.variable_length and not variable_length:
            found.append(
                Rejection(
                    path=entry.path,
                    kind=entry.kind,
                    reason="length is an expression, and this backend needs a fixed width",
                )
            )
    return tuple(found)


def require(
    space: ds.Space,
    *,
    backend: str,
    kinds: Iterable[str],
    conditional: bool = True,
    variable_length: bool = True,
) -> None:
    """Raise unless a space falls inside a stated envelope.

    Parameters
    ----------
    space : designspace.Space
        The space to check.
    backend : str
        The name to attribute a refusal to.
    kinds : Iterable[str]
        The parameter kinds the backend can place.
    conditional : bool, default True
        Whether the backend can handle conditional activity.
    variable_length : bool, default True
        Whether the backend can handle a variable-length list.

    Raises
    ------
    UnsupportedSpace
        When any parameter falls outside the envelope. Every reason is
        reported at once.

    Examples
    --------
    >>> import designspace as ds
    >>> from designspace_solvers import UnsupportedSpace, require
    >>> s = ds.space(ds.param("opt").categorical("a", "b"))
    >>> try:
    ...     require(s, backend="demo", kinds={"real"})
    ... except UnsupportedSpace as exc:
    ...     print(exc)
    demo cannot search this space: opt (categorical): kind is not one of ['real']
    """
    found = rejections(space, kinds=kinds, conditional=conditional, variable_length=variable_length)
    if found:
        raise UnsupportedSpace(backend, found)
