"""`ds.config_diff` (API_v3.md, "Config Utilities"): structural, no
magnitude.

Built entirely on `flatten()` — a variant switch "decomposes into the
discriminator diff... plus newly-inactive/newly-active payload diffs" and a
"repeat length change aligns positionally" fall out for free from how
`flatten` already keys a choice (discriminator string at the choice's own
path, payload leaves nested under `path.variant.*`, only for whichever
variant is active) and a lift (positionally-indexed `path[i].*` leaves): a
plain key-set diff over the two flattened dicts reproduces exactly those
two rules without any choice/lift-specific code here.

Equality is plain Python `==` on flattened leaf values, not the type-tagged
comparison `config_hash`/`fingerprint` use — DECISIONS.md D-35.
"""

from __future__ import annotations

from typing import Any

from designspace.build._space import Space
from designspace.config._flatten import flatten
from designspace.ir import ParamDiff


def config_diff(a: dict[str, Any], b: dict[str, Any], space: Space) -> list[ParamDiff]:
    flat_a = flatten(a, space)
    flat_b = flatten(b, space)
    diffs: list[ParamDiff] = []
    seen: set[str] = set()
    for key, va in flat_a.items():
        seen.add(key)
        if key not in flat_b:
            diffs.append(ParamDiff(param=key, old=va, new=None))
        elif va != flat_b[key]:
            diffs.append(ParamDiff(param=key, old=va, new=flat_b[key]))
    for key, vb in flat_b.items():
        if key not in seen:
            diffs.append(ParamDiff(param=key, old=None, new=vb))
    return diffs
