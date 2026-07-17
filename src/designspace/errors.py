"""Exception taxonomy (API_v3.md, "Errors, Concurrency").

`ResolutionError` covers every R-tagged row of the spec's error table.
`SerializationError` is added when serialize/ (M7) exists to raise it.
"""

from __future__ import annotations


class DesignSpaceError(Exception):
    """Base of the designspace exception taxonomy."""


class ResolutionError(DesignSpaceError):
    """Raised by the resolve/ pass pipeline; message names the offending path(s)."""


class SamplingError(DesignSpaceError):
    """Raised by sample/: retry exhaustion (row 26) or non-generative materialization."""
