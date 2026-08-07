"""frame: `space.sample()`'s DataFrame output.

See API.md, "Config Representation" > "DataFrame output". This requires the
`designspace[polars]` extra. polars is imported lazily, only when
`sample_frame` runs; importing this module never touches it.
"""

from designspace.frame._frame import sample_frame

__all__ = ["sample_frame"]
