"""config: nested phenotype to flat path-keyed dict, and choice helpers.

See API.md, "Config Utilities". `flatten`, `unflatten`, `variant`, `payload`,
`destructure` and `config_diff` live here. `config_hash` lives in
`identity/`, which owns the canonical-encoding machinery it is built on.
"""

from designspace.config._diff import config_diff
from designspace.config._flatten import flatten, flatten_with_errors
from designspace.config._helpers import destructure, payload, variant
from designspace.config._unflatten import unflatten

__all__ = [
    "config_diff",
    "destructure",
    "flatten",
    "flatten_with_errors",
    "payload",
    "unflatten",
    "variant",
]
