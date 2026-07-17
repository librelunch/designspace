"""Exception taxonomy (API_v3.md, "Errors, Concurrency").

`ResolutionError` covers every R-tagged row of the spec's error table.
`SerializationError`/`SamplingError` are added when serialize/ (M7) and
sample/ (M2) exist to raise them.
"""

from __future__ import annotations


class DesignSpaceError(Exception):
    """Base of the designspace exception taxonomy."""


class ResolutionError(DesignSpaceError):
    """Raised by the resolve/ pass pipeline; message names the offending path(s)."""
