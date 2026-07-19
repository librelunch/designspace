"""defaults: `.apply_defaults()` cascade (API_v3.md, "Defaults").

Internal machinery invoked by `build/_space.py`'s `Space.apply_defaults` —
not part of the public surface (users only ever see the plain `dict` it
returns).
"""

from designspace.defaults._defaults import apply_defaults

__all__ = ["apply_defaults"]
