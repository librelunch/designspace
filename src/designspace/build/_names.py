"""Name validation shared across the path grammar (API_v3.md, "Paths and Scoping").

Error-table row 5: names may not contain the path grammar's reserved
characters, regardless of syntactic route.
"""

from __future__ import annotations

from designspace.errors import ResolutionError

_FORBIDDEN = (".", "[", "]")


def check_name(name: str, *, what: str = "name") -> None:
    if any(ch in name for ch in _FORBIDDEN):
        raise ResolutionError(
            f"invalid {what} {name!r}: must not contain '.', '[', or ']' "
            "(reserved by the path grammar)"
        )
