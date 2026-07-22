"""`ds.config_hash` (API.md, "config_hash"): SHA-256 over the canonical
config encoding. Does **not** embed the space fingerprint — "the globally
unique observation key is the pair `(space.fingerprint(), ds.config_hash
(config, space))`", so the two are combined by the caller, not here.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.identity._config_encode import encode_config
from designspace.identity._jcs import canonical_digest


def config_hash(config: dict[str, Any], space: Space) -> str:
    return canonical_digest(encode_config(config, space))
