"""custom: the `ParamType` protocol and its capability detection.

See API.md, "Protocols" and "Extension". The `from_json` registry, mapping
`type_key` to a factory, is a caller-supplied mapping rather than core
state: API.md, "Identity and Serialization" says `from_json` "requires a
`custom_types` registry entry mapping `type_key -> factory` where
`factory(describe_dict)` reconstructs the instance".
"""

from designspace.custom._protocol import (
    ParamType,
    has_cardinality,
    has_properties,
    is_generative,
)

__all__ = ["ParamType", "has_cardinality", "has_properties", "is_generative"]
