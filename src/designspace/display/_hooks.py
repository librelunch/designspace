"""The `displayable` class decorator (API.md, "Human-Readable Rendering").

Assigns `__str__`, `_repr_pretty_` (IPython), and `_repr_html_` (Jupyter).
`__repr__` is never touched: every displayable type keeps its
dataclass-generated, constructor-shaped repr.

`text` and `html` are dotted paths to the rendering functions, such as
`"designspace.display._domain.render_domain"`, resolved on first use and
cached rather than imported at class-definition time. The renderer modules
import `ir`, `expr`, `builder`, `paths`, and `program` freely to do their
isinstance dispatch, and those are exactly the modules whose classes this
decorator dresses, so a module-level import back into them here would
cycle. This mirrors the function-local import already used throughout
`builder/_space.py` for its own deferred dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any, TypeVar, cast

T = TypeVar("T")

_RESOLVED: dict[str, Callable[[Any], str]] = {}


def _resolve(path: str) -> Callable[[Any], str]:
    fn = _RESOLVED.get(path)
    if fn is None:
        module_name, _, fn_name = path.rpartition(".")
        fn = cast(Callable[[Any], str], getattr(import_module(module_name), fn_name))
        _RESOLVED[path] = fn
    return fn


def displayable(text: str, html: str | None = None) -> Callable[[type[T]], type[T]]:
    """Attach the display hooks to a class.

    Parameters
    ----------
    text : str
        Dotted path to a `(self) -> str` function, used for `__str__` and
        `_repr_pretty_`.
    html : str | None
        Dotted path to a `(self) -> str` function returning an HTML
        fragment, used for `_repr_html_`. Defaults to an escaped `<pre>`
        block around `text`'s output.
    """

    def decorate(cls: type[T]) -> type[T]:
        def __str__(self: T) -> str:
            return _resolve(text)(self)

        def _repr_pretty_(self: T, p: Any, cycle: bool) -> None:
            p.text(_resolve(text)(self))

        def _repr_html_(self: T) -> str:
            if html is not None:
                return _resolve(html)(self)
            from designspace.display._html import escape_block

            return escape_block(_resolve(text)(self))

        cls.__str__ = __str__  # type: ignore[method-assign, assignment]
        cls._repr_pretty_ = _repr_pretty_  # type: ignore[attr-defined]
        cls._repr_html_ = _repr_html_  # type: ignore[attr-defined]
        return cls

    return decorate
