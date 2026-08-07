"""The path grammar (API.md, "Paths and Scoping").

```
path     := segment ("." segment)*
segment  := name ("[" i "]")*        # instance path
          | name ("[]")*             # definition path
```

One segment names a param, a variant or a struct field. Repeated brackets
address nested lift levels, as in `mask[2][3]` and `mask[][]`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from designspace.errors import ResolutionError

_SEGMENT_RE = re.compile(r"^([^.\[\]]+)((?:\[[^\[\]]*\])*)$")
_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")

# A cheap, non-raising alternative to `definition_form` for stripping
# concrete indices. `_lookup_param_shape` in `validate/_validate.py` and
# `_definition_path_of` and `_governing_definition_path` in
# `ops/_structural.py` share it rather than each compiling their own copy.
#
# It is kept distinct from the parsing grammar above deliberately. Those
# call sites accept a possibly non-grammar path, such as a
# `.validate_param()` or `.remaining_domain()` argument or an anchor or
# constraint-param flat key, and must not raise on one, where
# `definition_form` and `parse_path` would.
_INDEX_RE = re.compile(r"\[\d+\]")


@dataclass(frozen=True)
class Segment:
    """One dotted component of a path.

    `brackets` holds one entry per `[...]` group, in declaration order: an
    `int` for an instance index `[i]`, or `None` for a bare definition-path
    marker `[]`. A segment's brackets are uniformly one kind or the other,
    the grammar never mixing `[i]` with `[]` within one segment.
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
    """Split a path into `(base_key, trailing_brackets)`.

    `base_key` is the definition-form path backing the final dotted segment.
    `trailing_brackets` holds that segment's own bracket groups: possibly
    many, possibly negative concrete indices, or a bare `None` marking a
    `"[]"` template. That template is the virtual per-instance discriminator
    placeholder a lifted choice's variant-equality condition folds in, as in
    `"pipeline[]"`.

    The caller consumes the brackets one at a time against that entry's own,
    possibly chained, lift domain. A caller needing a concrete index, as
    evaluation-time negative-index resolution does, asserts that none is
    `None`. A caller needing only the number of brackets, as the
    declaredness and type checks do, ignores the values.

    Every earlier segment contributes at most one bracket to `base_key`,
    collapsed to `"[]"`. A struct or choice lift crossing is capped at
    repeat depth 1, so only the final segment's own bracket chain can run
    arbitrarily deep, as a scalar, subset or permutation nested lift such as
    `g[0][1]` does. The result is `None` when an earlier segment carries more
    than one bracket group: no legally resolved space produces that, so it
    can only be a malformed reference, and is never silently mis-resolved.

    Shared by `resolve/_expr_checks.py`, for the declaredness and type
    checks of rows 6, 12, 14, 18 and 29, and by `eval/_kleene.py`, for
    ordinal domain lookup and negative-index resolution.
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
    """Peel one trailing `"[i]"` bracket group off an instance path.

    Returns the base path one level up: `"stops[3]"` gives `"stops"`, and
    `"stops[3][1]"` gives `"stops[3]"`. This is the step that answers which
    lift a concrete sibling belongs to.
    """
    return path[: path.rindex("[")]


def element_prefix(base: str) -> str:
    """The lift's element-template prefix for `base`.

    A bare definition path gives `"edges"` to `"edges[]."`. An existing
    prefix ending in `"[]."` or `"[i]."` has its trailing dot dropped before
    another bracket group is appended, so `"grid[]."` gives `"grid[][]."`,
    the depth-2 case a chained `.repeat().repeat()` produces.

    Compose with `strip_last_index` to go from a concrete instance path to
    its lift's template prefix: `element_prefix(strip_last_index("stops[3]"))`
    gives `"stops[]."`.
    """
    if base.endswith("."):
        base = base[:-1]
    return f"{base}[]."


def instance_prefix(base: str, index: int) -> str:
    """The concrete per-instance prefix for lift element `index` of `base`.

    `("stops", 3)` gives `"stops[3]."`.
    """
    return f"{base}[{index}]."


def definition_form(path: str) -> str:
    """An instance path with every concrete index blanked to `"[]"`.

    `workers[0].timeout_s` gives `workers[].timeout_s`, and `g[0][1]` gives
    `g[][]`. This is the opposite direction from `split_instance_path`,
    which peels one trailing group.

    It is needed wherever concrete instances fold back onto the single
    definition-path key `space.params` declares them under, as
    `sampling_report`'s per-draw activity fold does. A path with no brackets
    is already its own definition form.
    """
    segments = parse_path(path)
    template = tuple(
        Segment(name=seg.name, brackets=tuple(None for _ in seg.brackets)) for seg in segments
    )
    return join_path(template)
