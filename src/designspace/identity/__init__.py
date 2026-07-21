"""identity: canonical encoding, `config_hash`, `fingerprint` (API.md,
"Identity and Serialization"; "config_hash"). Shared with `serialize/`, which
reuses the same IR codec (`identity/_ir_codec.py`) for `to_json`/`from_json`.
"""

from designspace.identity._config_hash import config_hash
from designspace.identity._fingerprint import fingerprint

__all__ = ["config_hash", "fingerprint"]
