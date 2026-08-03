"""The path grammar (API.md, "Paths and Scoping").

```
path     := segment ("." segment)*
segment  := name ("[" i "]")*        # instance path
          | name ("[]")*             # definition path
```

One segment per param/variant/struct name; repeated brackets address nested
lift levels (`mask[2][3]`, `mask[][]`). No lift landed yet (M4), so no
config produced by M3 ever contains bracket syntax — this module exists
now, "multi-index ready," per PLAN.md's M3 Build line, so
`validate_param` and the config utilities have one grammar to grow into
rather than a flat-name special case that needs revisiting at M4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from designspace.errors import ResolutionError

_SEGMENT_RE = re.compile(r"^([^.\[\]]+)((?:\[[^\[\]]*\])*)$")
_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")

# A cheap, non-raising alternative to `definition_form` for stripping concrete
# indices — `validate/_validate.py::_lookup_param_shape` and
# `ops/_structural.py::_definition_path_of`/`_governing_definition_path` share
# it rather than each compiling their own copy (M10.7: was independently
# defined in both, `import re` for no other reason in either file). Kept
# distinct from the parsing grammar above on purpose: both call sites accept
# a possibly-non-grammar path (a `.validate_param()`/`.remaining_domain()`
# argument, an anchor/constraint-param flat key) and must not raise on one,
# where `definition_form`/`parse_path` would.
_INDEX_RE = re.compile(r"\[\d+\]")


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
                f"invalid path {path!r}: segment {raw!r} mixes instance and definition brackets"
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


def split_instance_path(path: str) -> tuple[str, tuple[int | None, ...]] | None:
    """Splits a path into `(base_key, trailing_brackets)` — the general
    form of the "peel one trailing bracket group" resolution a
    single-level lift reference used to need (M10.5/D-72): `base_key` is
    the definition-form path backing the *final* dotted segment, and
    `trailing_brackets` is that segment's own bracket groups (possibly
    many, possibly negative concrete indices, or a bare `None` "`[]`"
    template marker — the virtual per-instance discriminator placeholder a
    lifted choice's variant-equality condition folds in, e.g. `"pipeline[]"`,
    DECISIONS.md D-18), meant to be consumed one at a time against that
    entry's own (possibly chained) lift domain by the caller — a caller
    that needs a *concrete* index (evaluation-time negative-index
    resolution) asserts none are `None`; one that only needs the *count*
    of brackets (declared-ness/type checks) does not care about the value.

    Every *earlier* segment contributes at most one bracket to `base_key`,
    collapsed to `"[]"` — a struct/choice lift crossing is capped at repeat
    depth 1 (API.md, M4.5), so only the *final* segment's own bracket chain
    can run arbitrarily deep (a scalar/subset/permutation nested lift, e.g.
    `g[0][1]`). `None` if an earlier segment carries more than one bracket
    group — no legally-resolved space can produce that, so it can only be a
    malformed reference (never silently mis-resolved).

    Shared by `resolve/_expr_checks.py` (declared-ness/type checks, row 6/12/
    14/18/29) and `eval/_kleene.py` (ordinal domain lookup, negative-index
    resolution) — the one walk both used to duplicate with a single-bracket
    assumption baked in.
    """
    segments = parse_path(path)
    if not segments:
        return None
    prefix_parts: list[str] = []
    for seg in segments[:-1]:
        if len(seg.brackets) > 1:
            return None
        prefix_parts.append(f"{seg.name}{'[]' if seg.brackets else ''}.")
    last = segments[-1]
    return "".join(prefix_parts) + last.name, last.brackets


def strip_last_index(path: str) -> str:
    """Peels one trailing `"[i]"` bracket group off an instance path,
    returning the base path one level up (`"stops[3]"` -> `"stops"`,
    `"stops[3][1]"` -> `"stops[3]"`) — the "which lift does this concrete
    sibling belong to" step, re-derived by hand (`path[: path.rindex("[")]`)
    in half a dozen modules before M10.7."""
    return path[: path.rindex("[")]


def element_prefix(base: str) -> str:
    """The lift's element-*template* prefix for `base`: a bare definition
    path (`"edges"` -> `"edges[]."`) or an existing `"[]."`/`"[i]."`-
    terminated prefix one level up, whose trailing dot is dropped before
    appending another bracket group (`"grid[]."` -> `"grid[][]."`, the
    depth-2 case a chained `.repeat().repeat()` produces). Compose with
    `strip_last_index` to go from a *concrete* instance path to its lift's
    template prefix (`element_prefix(strip_last_index("stops[3]"))` ->
    `"stops[]."`)."""
    if base.endswith("."):
        base = base[:-1]
    return f"{base}[]."


def instance_prefix(base: str, index: int) -> str:
    """The concrete per-instance prefix for lift element `index` of `base`
    (`"stops", 3` -> `"stops[3]."`)."""
    return f"{base}[{index}]."


def definition_form(path: str) -> str:
    """An instance path with every concrete index blanked to its `"[]"`
    template marker (`workers[0].timeout_s` -> `workers[].timeout_s`,
    `g[0][1]` -> `g[][]`) — the inverse direction from `split_instance_path`
    (which peels one trailing group), needed wherever concrete instances
    fold back onto the single definition-path key `space.params` declares
    them under (M10.6 `sampling_report`'s per-draw activity fold; M11's
    `decode` will need the identical normalization to look up an encoding).
    A path with no brackets is already its own definition form.
    """
    segments = parse_path(path)
    template = tuple(
        Segment(name=seg.name, brackets=tuple(None for _ in seg.brackets)) for seg in segments
    )
    return join_path(template)
