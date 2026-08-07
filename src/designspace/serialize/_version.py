"""The shared format-version integer (API.md, "to_json / from_json" /
"fingerprint()"): "The JSON document carries a single integer format
version... Output: preimage-format version (shared with to_json's version
counter)..." One counter, bumped deliberately under the freeze
discipline's version-bump protocol.
"""

from __future__ import annotations

FORMAT_VERSION = 1
