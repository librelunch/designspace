"""paths: the path grammar (API.md, "Paths and Scoping").

Internal machinery consumed by config/ and resolve/ — not part of the
public surface (users see paths as plain strings everywhere: `.params`
keys, `validate_param`, `flatten`/`unflatten` keys).
"""

from designspace.paths._grammar import (
    Segment,
    is_definition_path,
    join_path,
    parse_path,
    split_instance_path,
)

__all__ = [
    "Segment",
    "is_definition_path",
    "join_path",
    "parse_path",
    "split_instance_path",
]
