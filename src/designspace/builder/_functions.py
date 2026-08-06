"""`ds.param` / `ds.space` (API.md, "Construction")."""

from __future__ import annotations

from typing import TYPE_CHECKING

from designspace.builder._paramexpr import ParamExpr
from designspace.builder._space import Space
from designspace.builder._views import FreshParamExpr
from designspace.resolve import resolve_space

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401


def param(name: str) -> FreshParamExpr:
    """Begin declaring a parameter called `name`.

    This is the entry point for every parameter in a design space. The
    returned object is a builder: call exactly one *type* method on it
    (`.real()`, `.integer()`, `.categorical()`, ...) to say what kind of
    value the parameter holds, then chain any number of *modifiers*
    (`.prior()`, `.default()`, `.when()`, `.repeat()`, ...). Each call
    returns a new object, so a builder can be safely shared and branched.

    The same call is also how you *refer* to an already-declared parameter
    inside an expression, so `ds.param("x") < ds.param("y")` builds a
    comparison, it does not redeclare anything. Which reading applies is
    positional: a builder passed to `ds.space()` declares, one used in a
    constraint refers.

    Parameters
    ----------
    name : str
        The parameter's name, or a path into a nested structure
        (`"optimizer.lr"`, `"stops[].dwell"`). See API.md, "Paths and
        Scoping" for the grammar.

    Returns
    -------
    FreshParamExpr
        A builder with no type chosen yet. Choosing a second type is an
        error, and the view types make it a static one too.

    Examples
    --------
    >>> lr = ds.param("lr").real(1e-4, 1e-1).log_scale()
    >>> depth = ds.param("depth").integer(1, 8)
    >>> s = ds.space(lr, depth)
    >>> s.n_params
    2

    The second reading, referring rather than declaring:

    >>> s = ds.space(
    ...     ds.param("lo").integer(0, 10),
    ...     ds.param("hi").integer(0, 10),
    ... ).require(ds.param("lo") < ds.param("hi"))
    >>> s.is_feasible({"lo": 2, "hi": 7})
    True
    >>> s.is_feasible({"lo": 7, "hi": 2})
    False
    """
    return FreshParamExpr(path=name)


def space(*exprs: ParamExpr) -> Space:
    """Resolve parameter builders into a `Space`.

    Resolution is where declarations become a checked, immutable object:
    names are validated, references are bound, the dependency graph is
    built and cycle-checked, expression types are checked, and charts are
    constructed. Anything wrong with the declarations raises a
    `ResolutionError` here rather than later during sampling, and the
    message names the offending path.

    Parameters
    ----------
    *exprs : ParamExpr
        The parameter builders to include. Declaration order is preserved
        in `Space.params` and is part of the space's identity: permuting
        two parameters yields a different fingerprint.

    Returns
    -------
    Space
        The resolved space. Immutable: `.forbid()`, `.freeze()`, and the
        other operations return a new `Space` rather than mutating this one.

    Raises
    ------
    ResolutionError
        If any declaration is invalid: a duplicate or malformed name, a
        reference to an undeclared parameter, a dependency cycle, a
        type-incorrect expression, or a degenerate domain.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("algorithm").categorical("greedy", "exact"),
    ...     ds.param("timeout").real(0.1, 60.0).log_scale(),
    ... )
    >>> list(s.params)
    ['algorithm', 'timeout']

    A bad declaration fails here, naming the path:

    >>> ds.space(ds.param("k").integer(10, 1))
    Traceback (most recent call last):
        ...
    designspace.errors.ResolutionError: param 'k': lo=10 > hi=1
    """
    return resolve_space(exprs)
