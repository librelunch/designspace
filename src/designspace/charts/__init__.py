"""charts: chart construction (API.md, "Charts").

Internal machinery invoked by `resolve/`'s step 6. A user never constructs
a chart directly, seeing only `ParamDef.chart` after resolution, so nothing
here is re-exported from the top-level `designspace` package.
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
