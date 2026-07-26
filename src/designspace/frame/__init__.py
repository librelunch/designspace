"""frame: `space.sample()`'s DataFrame output (API.md, "Config
Representation" -> "DataFrame output"). Requires the `designspace[polars]`
extra — polars is imported lazily, only when `sample_frame` actually runs
(DECISIONS.md D-51); importing this module itself never touches polars.
"""

from designspace.frame._frame import sample_frame

__all__ = ["sample_frame"]
