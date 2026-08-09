"""Human-readable rendering for the public surface (API.md, "Human-Readable
Rendering").

`display/` sits at a leaf of the import graph: its submodules import `ir`,
`expr`, `builder`, `paths`, and `program` freely to do their isinstance
dispatch. Every displayable class elsewhere is dressed with `_hooks.py`'s
`displayable` decorator, which resolves its renderer lazily by dotted path
rather than importing it at class-definition time, so decorating a type in
`ir/_domain.py` never creates a cycle back into this package.

`pretty` is the one name re-exported here, since it is itself a public
export of `designspace`. Its own module, `_pretty.py`, has no module-level
import of `ir`, `builder`, or any other package this decorates, only
function-local ones, so re-exporting it creates no cycle. Every other
submodule stays private: import it directly, as `designspace.display._space`.
"""

from __future__ import annotations

from designspace.display._pretty import pretty

__all__ = ["pretty"]
