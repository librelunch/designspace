"""The path grammar (API_v3.md, "Paths and Scoping").

```
path     := segment ("." segment)*
segment  := name ("[" i "]")*        # instance path
          | name ("[]")*             # definition path
```

One segment per param/variant/struct name; repeated brackets address nested
lift levels (`mask[2][3]`, `mask[][]`). No lift landed yet (M4), so no
config produced by M3 ever contains bracket syntax — this module exists
now, "multi-index ready," per IMPLEMENTATION_PLAN.md's M3 Build line, so
`validate_param` and the config utilities have one grammar to grow into
rather than a flat-name special case that needs revisiting at M4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from designspace.errors import ResolutionError

_SEGMENT_RE = re.compile(r"^([^.\[\]]+)((?:\[[^\[\]]*\])*)$")
_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")


@dataclass(frozen=True)
class Segment:
    """One dotted component of a path.

    `brackets` holds one entry per `[...]` group in declaration order:
    an `int` for an instance index (`[i]`), or `None` for a bare
    definition-path marker (`[]`). A segment's brackets are always uniformly
    one kind or the other (the grammar doesn't mix `[i]` and `[]` within a
    single segment).
    """

    name: str
    brackets: tuple[int | None, ...] = ()

    @property
    def is_definition(self) -> bool:
        return any(b is None for b in self.brackets)


def parse_path(path: str) -> tuple[Segment, ...]:
    if path == "":
        raise ResolutionError("invalid path '': path must not be empty")
    segments = []
    for raw in path.split("."):
        m = _SEGMENT_RE.match(raw)
        if m is None or not m.group(1):
            raise ResolutionError(f"invalid path {path!r}: malformed segment {raw!r}")
        name, bracket_part = m.group(1), m.group(2)
        brackets: list[int | None] = []
        for content in _BRACKET_RE.findall(bracket_part):
            if content == "":
                brackets.append(None)
            else:
                try:
                    brackets.append(int(content))
                except ValueError as exc:
                    raise ResolutionError(
                        f"invalid path {path!r}: non-integer index {content!r}"
                    ) from exc
        has_index = any(b is not None for b in brackets)
        has_definition = any(b is None for b in brackets)
        if has_index and has_definition:
            raise ResolutionError(
                f"invalid path {path!r}: segment {raw!r} mixes instance and "
                "definition brackets"
            )
        segments.append(Segment(name=name, brackets=tuple(brackets)))
    return tuple(segments)


def join_path(segments: tuple[Segment, ...]) -> str:
    parts = []
    for seg in segments:
        brackets = "".join("[]" if b is None else f"[{b}]" for b in seg.brackets)
        parts.append(f"{seg.name}{brackets}")
    return ".".join(parts)


def is_definition_path(path: str) -> bool:
    return any(seg.is_definition for seg in parse_path(path))
