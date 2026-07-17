"""charts: chart construction (API_v3.md, "Charts").

Internal machinery invoked by resolve/'s step 6 — charts are never
constructed directly by users (they only see `ParamDef.chart` after
resolution), so nothing here is re-exported from the top-level
`designspace` package.
"""

from designspace.charts._build import build_chart
from designspace.charts._grid import GridShape, build_grid_shape, floor_to_grid, grid_membership

__all__ = [
    "GridShape",
    "build_chart",
    "build_grid_shape",
    "floor_to_grid",
    "grid_membership",
]
