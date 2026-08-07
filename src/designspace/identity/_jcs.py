"""RFC 8785 (JCS) canonical digest.

See API.md, "fingerprint()" and "config_hash". This is the single call site
around the `rfc8785` dependency. Everywhere else in `identity` and
`serialize` builds a tree that is already semantically canonical, with type
tags applied, `-0.0` folded to `0.0`, unordered collections sorted and
bound-origin polarity flipped. `rfc8785.dumps` supplies only the last step,
serializing that tree to deterministic bytes under RFC 8785, meaning sorted
object keys and the ES6 number-to-string rule. Those bytes are then
SHA-256'd.
"""

from __future__ import annotations

import hashlib
from typing import Any

import rfc8785


def canonical_digest(tree: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(tree)).hexdigest()
