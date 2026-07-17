"""config: nested phenotype <-> flat path-keyed dict, and choice-value
helpers (API_v3.md, "Config Utilities").

`flatten`/`unflatten`/`variant`/`payload`/`destructure` are M3's build
item; `config_hash`/`config_diff` join at M7.
"""

from designspace.config._flatten import flatten, flatten_with_errors
from designspace.config._helpers import destructure, payload, variant
from designspace.config._unflatten import unflatten

__all__ = [
    "destructure",
    "flatten",
    "flatten_with_errors",
    "payload",
    "unflatten",
    "variant",
]
