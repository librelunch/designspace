"""`pretty`'s dispatch (API.md, "Human-Readable Rendering").

A dunder takes no arguments, so it can reach neither a configuration, which
needs the space it is read against, nor a caller's width and column
choices. `pretty` is the one function that can: a config dispatches to
`display/_config.py`; anything else dispatches to whichever renderer its
own `__str__` already calls, with `width` and `columns` threaded through
where that renderer accepts them. `str(x) == pretty(x)` at `pretty`'s
defaults for every displayable `x`, since both paths end at the same
renderer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from designspace.display._values import WIDTH


def pretty(
    obj: Any,
    space: Any = None,
    *,
    width: int = WIDTH,
    columns: str | Iterable[str] | None = None,
    show: str | Iterable[str] | None = None,
    hide: str | Iterable[str] | None = None,
) -> str:
    """Render `obj` for a person to read.

    A plain `dict` needs `space`, the declaration it is read against;
    anything else, a `Space`, a `ParamDef`, a `ParamExpr`, a domain, a
    result, is read on its own and `space` is omitted. `columns` narrows
    which facts a row carries; `show` and `hide` narrow a configuration's
    rows by status and apply only there, together with `space`.

    Parameters
    ----------
    obj : Any
        A configuration (with `space`), or any object this package
        renders for display.
    space : Space | None
        The space `obj` is read against, when `obj` is a configuration.
        Omitted otherwise.
    width : int
        The column budget a rendered line targets.
    columns : str | Iterable[str] | None
        The facts a row carries. Unset keeps the default selection for
        whatever `obj` is.
    show : str | Iterable[str] | None
        For a configuration, the row statuses to keep. Mutually exclusive
        with `hide`.
    hide : str | Iterable[str] | None
        For a configuration, the row statuses to omit. Mutually exclusive
        with `show`.

    Returns
    -------
    str
        The rendered text.

    Raises
    ------
    TypeError
        `obj` and `space` do not pair into a configuration and its space,
        `show` and `hide` are both given, either is given without `space`,
        or `columns` names something outside the vocabulary that applies.

    Examples
    --------
    >>> import designspace as ds
    >>> space = ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale())
    >>> config = {"lr": 0.01}
    >>> print(ds.pretty(config, space))
    Config: 1 params, 1 set, 0 inactive, valid
      lr  = 0.01  in [0.0001, 0.1]
    >>> ds.pretty(space) == str(space)
    True
    """
    if space is not None:
        if not isinstance(obj, Mapping):
            raise TypeError(
                f"pretty() was given a space, so obj must be a configuration "
                f"(a Mapping), not {type(obj).__name__}"
            )
        from designspace.display._config import render_config

        return render_config(obj, space, width=width, columns=columns, show=show, hide=hide)

    if show is not None or hide is not None:
        raise TypeError("show and hide apply only to a configuration, together with its space")
    if isinstance(obj, Mapping):
        raise TypeError("a configuration needs the space it is read against: pretty(config, space)")

    # `display` sits at the leaf of the import graph; importing `builder`
    # and `ir` here rather than at module scope keeps `_pretty.py` safe to
    # import from anywhere they in turn import `display` from.
    from designspace.builder._space import Space

    if isinstance(obj, Space):
        from designspace.display._space import render_space

        return render_space(obj, width=width, columns=columns)

    from designspace.builder._paramexpr import ParamExpr

    if isinstance(obj, ParamExpr):
        from designspace.display._space import render_param_expr

        return render_param_expr(obj, width=width, columns=columns)

    from designspace.ir import Constraint, ParamDef

    if isinstance(obj, ParamDef):
        from designspace.display._space import render_param_def

        return render_param_def(obj, width=width, columns=columns)

    if isinstance(obj, Constraint):
        # `render_constraint`, a bare Constraint's own `__str__`, never
        # wraps: the width discipline only applies once a constraint sits
        # inside a table (`render_space`'s own block) or a caller asks for
        # it explicitly here. At the ambient default this is the same
        # choice `str` already makes, so the two never disagree unless a
        # caller names a width of their own.
        from designspace.display._space import render_constraint, render_constraint_wrapped

        if width == WIDTH:
            return render_constraint(obj)
        return render_constraint_wrapped(obj, width=width)

    if not hasattr(obj, "_repr_pretty_"):
        raise TypeError(f"pretty() does not know how to render {type(obj).__name__!r}")

    # Every other displayable type, an IR domain, a prior, a result or
    # report dataclass, a program support type, has no columns of its own
    # to select and is read whole: `columns` is ignored where it does not
    # apply, per the same rule a `Space`'s own columns follow.
    return str(obj)
