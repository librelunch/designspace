"""RFC 8785 (JCS) canonical digest (API.md, "fingerprint()" /
"config_hash"; DECISIONS.md D-32).

A single call site around the `rfc8785` dependency: everywhere else in
`identity`/`serialize` builds an already-semantically-canonical tree (type
tags applied, `-0.0 -> 0.0`, unordered collections sorted, bound-origin
polarity flipped) — `rfc8785.dumps` only replaces the last step, serializing
that tree to deterministic bytes per RFC 8785 (sorted object keys, the ES6
number-to-string rule), which are then SHA-256'd.
"""

from __future__ import annotations

import hashlib
from typing import Any

import rfc8785


def canonical_digest(tree: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(tree)).hexdigest()
