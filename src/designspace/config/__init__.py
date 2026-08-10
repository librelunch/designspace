"""config: nested phenotype to flat path-keyed dict, and choice helpers.

See API.md, "Config Utilities". `flatten`, `is_flat`, `unflatten`, `variant`,
`payload`, `destructure` and `config_diff` live here. `config_hash` lives in
`identity/`, which owns the canonical-encoding machinery it is built on.
"""

from designspace.config._diff import config_diff
from designspace.config._flatten import as_flat, flatten, flatten_with_errors, is_flat
from designspace.config._helpers import destructure, payload, variant
from designspace.config._unflatten import as_nested, unflatten

__all__ = [
    "as_flat",
    "as_nested",
    "config_diff",
    "destructure",
    "flatten",
    "flatten_with_errors",
    "is_flat",
    "payload",
    "unflatten",
    "variant",
]
