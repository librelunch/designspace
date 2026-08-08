"""Exception taxonomy (API.md, "Errors and Concurrency").

`ResolutionError` covers every R-tagged row of the spec's error table.
`SerializationError` covers the non-serializable sites `serialize/` and
`identity/` raise on, and `SamplingError` the two failures sampling
reports.
"""

from __future__ import annotations


class DesignSpaceError(Exception):
    """Base of the designspace exception taxonomy."""


class ResolutionError(DesignSpaceError):
    """Raised when a declaration cannot be resolved into a space.

    The message names the offending definition path or paths.
    """


class SamplingError(DesignSpaceError):
    """Raised when a draw cannot be produced.

    Either rejection sampling exhausted its retries, or a non-generative
    parameter had no `.default()` to materialize a value from.
    """


class SerializationError(DesignSpaceError):
    """Raised when a space cannot be written out or read back.

    An unknown format version, a non-serializable site under
    `on_unserializable="raise"` (the default), or a malformed `to_json`
    document passed to `from_json`.
    """
