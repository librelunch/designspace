"""custom/: the `ParamType` protocol and capability detection (API.md,
"Protocols"; "Extension"; M9). The `from_json` registry (`type_key ->
factory`) is a caller-supplied mapping, not core state — "core defines the
protocol and a registry type keyed by `type_key`; core never populates the
registry" (API.md, "Transforms and Encodings").
"""

from designspace.custom._protocol import (
    ParamType,
    has_cardinality,
    has_properties,
    is_generative,
)

__all__ = ["ParamType", "has_cardinality", "has_properties", "is_generative"]
