"""Rendering for the Jupyter display hook (API.md, "Human-Readable
Rendering").

`escape_block` is the default every `displayable` type gets: an escaped
`<pre>` wrapping the same text `str()` produces. `render_space_html` is the
one bespoke table, `Space` being the type a notebook session prints most and
the one whose plain-text row-and-column shape maps directly onto `<table>`.
Every cell is escaped, guarding `display_escapes_html` against a categorical
value or a param path containing `<`, `>`, or `&`.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from designspace.display._columns import DEFAULT_SPACE_COLUMNS
from designspace.display._expr import render_expr
from designspace.display._space import _build_rows

if TYPE_CHECKING:
    from designspace.builder._space import Space


def escape_block(text: str) -> str:
    return f"<pre>{escape(text)}</pre>"


def render_space_html(space: Space) -> str:
    n_cond = sum(1 for pd in space.params.values() if pd.condition is not None)
    header = (
        f"<p><b>Space</b>: {len(space.params)} params, {n_cond} conditional, "
        f"{len(space.constraints)} constraints</p>"
    )
    rows = _build_rows(space, budget=200, columns=DEFAULT_SPACE_COLUMNS)
    body_rows = []
    for row in rows:
        tail = " ".join(t for t in (*row.tokens, row.when) if t)
        body_rows.append(
            "<tr>"
            f"<td>{escape(row.label)}</td>"
            f"<td>{escape(row.kind)}</td>"
            f"<td>{escape(row.domain)}</td>"
            f"<td>{escape(tail)}</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr><th>path</th><th>kind</th><th>domain</th>"
        "<th></th></tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )
    constraints = ""
    if space.constraints:
        c_rows = "".join(
            f"<tr><td>{escape(c.kind)}</td><td>{escape(render_expr(c.expr))}</td></tr>"
            for c in space.constraints
        )
        constraints = f"<table><tbody>{c_rows}</tbody></table>"
    return header + table + constraints
