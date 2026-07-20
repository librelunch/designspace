"""The shared format-version integer (API_v3.md, "to_json / from_json" /
"fingerprint()"): "The JSON document carries a single integer format
version... Output: preimage-format version (shared with to_json's version
counter)..." One counter, bumped deliberately per the freeze-discipline
version-bump protocol (IMPLEMENTATION_PLAN.md) — never on a whim.
"""

from __future__ import annotations

FORMAT_VERSION = 1
