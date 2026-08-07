"""defaults: `.apply_defaults()` cascade (API.md, "Defaults").

Internal machinery invoked by `Space.apply_defaults` in
`builder/_space.py`, and not part of the public surface. A user sees only
the plain `dict` it returns.
"""

from designspace.defaults._defaults import apply_defaults

__all__ = ["apply_defaults"]
