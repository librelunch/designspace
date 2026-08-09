"""Rendering literal Python values (API.md, "Human-Readable Rendering").

`render_value` covers the scalar and simple-container values that appear as
domain members, literal operands, and declared metadata: what API.md's row
4 already keeps unambiguous by forbidding two declared categorical values
that share a string image. `render_elidable` implements the
`display_elides_without_truncating` law: where a sequence is too long for
the width budget, it is cut to a `"+k more"` count, never to a severed
token.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: The column budget every rendered line targets, per API.md's
#: "Human-Readable Rendering" section. 88 rather than the 80 columns
#: authored prose wraps at: a rendered block is a code block, and 80
#: pushed several corpus fixtures' `when`/`default` tails onto a
#: continuation line that 88 keeps inline.
WIDTH = 88


def render_value(value: Any) -> str:
    """Render one literal value: `repr()`, recursing into containers."""
    if isinstance(value, Mapping):
        inner = ", ".join(f"{k}: {render_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, frozenset | set):
        return "{" + ", ".join(render_value(v) for v in sorted(value, key=repr)) + "}"
    if isinstance(value, tuple):
        return "(" + ", ".join(render_value(v) for v in value) + ")"
    if isinstance(value, list):
        return "[" + ", ".join(render_value(v) for v in value) + "]"
    return repr(value)


def render_elidable(
    items: Sequence[str], *, open: str, close: str, budget: int = WIDTH, sep: str = ", "
) -> str:
    """Join `items` inside `open`/`close`, eliding to a `"+k more"` count
    when the whole sequence would not fit `budget`.

    Every kept item is rendered whole; an item is never cut mid-token. The
    reserved room for the eventual `"+k more"` suffix is accounted for
    before an item is admitted, so the result never overflows the budget by
    growing the suffix itself. A budget too tight for even one item falls
    back to a bare `"+n more"`, shorter than any single kept item plus that
    same suffix would be.
    """
    if not items:
        return open + close
    kept: list[str] = []
    width = len(open) + len(close)
    for i, item in enumerate(items):
        remaining_after = len(items) - i - 1
        piece = (sep if kept else "") + item
        reserve = len(f"{sep}+{remaining_after} more") if remaining_after else 0
        if width + len(piece) + reserve > budget:
            break
        kept.append(item)
        width += len(piece)
    left = len(items) - len(kept)
    if left == 0:
        return open + sep.join(kept) + close
    if not kept:
        return open + f"+{left} more" + close
    return open + sep.join(kept) + f"{sep}+{left} more" + close


def render_seq(
    values: Iterable[Any], *, open: str = "{", close: str = "}", budget: int = WIDTH
) -> str:
    """`render_elidable` over a sequence of literal values."""
    return render_elidable([render_value(v) for v in values], open=open, close=close, budget=budget)
