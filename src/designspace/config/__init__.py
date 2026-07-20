"""config: nested phenotype <-> flat path-keyed dict, and choice-value
helpers (API_v3.md, "Config Utilities").

`flatten`/`unflatten`/`variant`/`payload`/`destructure` are M3's build
item; `config_diff` joins at M7 (`config_hash` lives in `identity/`, which
owns the shared canonical-encoding machinery it's built on).
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
