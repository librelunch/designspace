"""Rendering a configuration against its space (API.md, "Human-Readable
Rendering").

A configuration is a plain `dict`; no dunder can reach it. `render_config`
is the renderer behind `pretty(config, space)`, built entirely from
existing primitives: `Space.evaluate_partial` for the four-valued activity
status per instance path, `config/_flatten.py`'s `flatten_with_errors` for
the assigned values, `Space.validate` for the constraint verdicts, and
`display/_space.py`'s `_walk` for the same tree labels a `Space` table
already uses.

`evaluate_partial` and `validate` both raise `TypeError` on a value whose
type does not match its domain, exactly the config a printer gets reached
for. Both run behind a guard; on failure the affected accounting degrades
to `"unknown"` rather than propagating, which is what keeps `render_config`
from raising on a config a space itself would reject.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from designspace.config._flatten import flatten_with_errors
from designspace.display._columns import (
    CONFIG_COLUMNS,
    DEFAULT_CONFIG_COLUMNS,
    resolve_columns,
    resolve_show_hide,
)
from designspace.display._domain import render_domain
from designspace.display._expr import render_expr
from designspace.display._space import _walk
from designspace.display._values import WIDTH, render_value
from designspace.ir import ParamDef
from designspace.validate._validate import _lookup_param_shape

if TYPE_CHECKING:
    from designspace.builder._space import Space

_IDX_RE = re.compile(r"\[(\d+)\]")

#: `evaluate_partial`'s four internal words, spelled for a reader.
_STATUS_WORD = {"set": "set", "active_unset": "unset", "inactive": "inactive", "unknown": "unknown"}

#: A malformed value can fail activity or constraint evaluation in whichever
#: built-in way the wrong shape happens to trip: a numeric comparison
#: against a string raises `TypeError`, `position_of` against a
#: non-sequence raises `ValueError`, a non-integer lift count fails an
#: internal invariant and raises `AssertionError`, and so on through the
#: operators `eval/` implements. Printing a suspect config is exactly when
#: this guard earns its place, so it is not narrowed to one exception type.
_SHAPE_ERRORS: tuple[type[Exception], ...] = (
    TypeError,
    ValueError,
    AttributeError,
    IndexError,
    KeyError,
    AssertionError,
)


class _ConfigRow:
    __slots__ = ("body", "domain", "domain_of", "label", "when")

    def __init__(
        self,
        label: str,
        body: str = "",
        domain: str = "",
        when: str = "",
        domain_of: ParamDef | None = None,
    ) -> None:
        self.label = label  # already indented: "  " * depth + the tree label
        self.body = body
        self.domain = domain  # "" until `_size_domains` renders it
        self.when = when
        self.domain_of = domain_of  # the param whose domain still needs sizing


def _template_labels(space: Space) -> dict[str, tuple[int, str]]:
    return {
        path: (depth, label) for path, _pd, depth, label, _suppress in _walk(space, "", 0, "", None)
    }


def _indented_label(templates: dict[str, tuple[int, str]], path: str) -> str:
    """`path`'s tree label, indented by depth, with its template's `[]`
    markers replaced by the real indices `path` carries, deepest first."""
    guess = _IDX_RE.sub("[]", path)
    if guess in templates:
        depth, label = templates[guess]
        idxs = _IDX_RE.findall(path)
        n = label.count("[]")
        for idx in idxs[len(idxs) - n :] if n else ():
            label = label.replace("[]", f"[{idx}]", 1)
        return "  " * depth + label
    # A bare lift-element entry (`pipeline[0]`, `means[1]`): no row of its
    # own in the template walk, since a list only ever emits a row for its
    # element's *fields*, not the element itself. It inherits the list's
    # own row, one level deeper, labeled by its index alone.
    container, _, idx = path.rpartition("[")
    depth, _label = templates[container]
    return "  " * (depth + 1) + f"[{idx.rstrip(']')}]"


def _value_body(raw: Any) -> str:
    if isinstance(raw, Mapping) and "source" in raw:
        return f"= {raw['source']}"
    return f"= {render_value(raw)}"


def _container_body(pd: ParamDef, flat: Mapping[str, Any], path: str) -> str | None:
    """`None` for a leaf, or when a list's own count is not yet known; the
    container's own value-slot text otherwise."""
    if pd.type_kind == "space":
        return "struct"
    if pd.type_kind == "list":
        count = flat.get(path)
        return f"count {count}" if count is not None else None
    return None


def _size_domains(rows: list[_ConfigRow], *, width: int, label_width: int) -> None:
    """Render every row's deferred domain, budgeted from what its own
    label and value already spent, the same two-pass shape `_build_rows`
    uses for a `Space` table: a row with a short value gets more room for
    its domain than one whose value already fills most of the line."""
    lead_width = 2 + label_width
    for row in rows:
        if row.domain_of is None:
            continue
        prefix = lead_width + (2 + len(row.body) if row.body else 0) + len("in ")
        row.domain = f"in {render_domain(row.domain_of.domain, budget=max(width - prefix, 1))}"


def _emit_config_rows(rows: list[_ConfigRow], *, width: int, label_width: int) -> list[str]:
    if not rows:
        return []
    w0 = label_width
    lead_width = 2 + w0 + 2
    lines = []
    for r in rows:
        lead = f"  {r.label:<{w0}}"
        tail = "  ".join(t for t in (r.domain, r.when) if t)
        first = f"{lead}  {r.body}" if r.body else lead
        if not tail:
            lines.append(first.rstrip())
            continue
        line = f"{first}  {tail}" if r.body else f"{lead}  {tail}"
        # Whether the tail fits is decided from this row's own body, never
        # by truncating it: a value is exact (rule 2), so a row whose value
        # alone is wide overruns rather than losing a digit.
        if len(line) <= width:
            lines.append(line)
            continue
        lines.append(first.rstrip())
        combined = " " * lead_width + tail
        if len(combined) <= width:
            lines.append(combined)
        else:
            # Even domain and when together do not fit one continuation
            # line: each gets its own, rather than one overlong line no
            # narrower reflow could have avoided.
            if r.domain:
                lines.append(" " * lead_width + r.domain)
            if r.when:
                lines.append(" " * lead_width + r.when)
    return lines


def _constraint_lines(ce: Any, *, lead_width: int, width: int) -> list[str]:
    lead = f"  {ce.constraint.kind:<{lead_width}}  "
    body = render_expr(ce.constraint.expr)
    verdict = "n/a" if not ce.applicable else ("violated" if ce.violated else "ok")
    margin = "n/a" if ce.margin is None else f"{ce.margin:.3f}"
    tail = f"{verdict}  margin {margin}"
    one_line = f"{lead}{body}  {tail}"
    if len(one_line) <= width:
        return [one_line]
    if len(lead) + len(body) <= width:
        return [lead + body, " " * len(lead) + tail]
    wrapped = textwrap.wrap(
        body, width=max(width - len(lead), 20), break_long_words=False, break_on_hyphens=False
    )
    return [lead + wrapped[0], *(" " * len(lead) + w for w in wrapped[1:]), " " * len(lead) + tail]


def render_config(
    config: Mapping[str, Any],
    space: Space,
    *,
    width: int = WIDTH,
    columns: str | Iterable[str] | None = None,
    show: str | Iterable[str] | None = None,
    hide: str | Iterable[str] | None = None,
) -> str:
    """A configuration, read against the space that declares it."""
    cols = resolve_columns(columns, CONFIG_COLUMNS, DEFAULT_CONFIG_COLUMNS)
    keep = resolve_show_hide(show, hide)
    cfg = dict(config)
    flat, _shape_errors = flatten_with_errors(cfg, space)

    try:
        status: dict[str, str] | None = dict(space.evaluate_partial(cfg).param_status)
    except _SHAPE_ERRORS:
        status = None
    try:
        vres: Any = space.validate(cfg)
    except _SHAPE_ERRORS:
        vres = None

    templates = _template_labels(space)
    rows: list[tuple[str, _ConfigRow]] = []  # (display status word, row)

    if status is not None:
        for path, raw_status in status.items():
            word = _STATUS_WORD[raw_status]
            label = _indented_label(templates, path)
            pd = _lookup_param_shape(space, path)
            body = ""
            domain_of = None
            if word == "set":
                container = _container_body(pd, flat, path)
                if container is not None:
                    body = container
                elif path in flat:
                    body = _value_body(flat[path])
                    if "domain" in cols:
                        domain_of = pd
            if not body and word != "set" and "status" in cols:
                body = word
            when = ""
            if "when" in cols and pd.condition is not None:
                when = f"when {render_expr(pd.condition)}"
            rows.append((word, _ConfigRow(label, body, "", when, domain_of)))
        n_total = len(rows)
        n_set = sum(1 for word, _row in rows if word == "set")
        n_inactive = sum(1 for word, _row in rows if word == "inactive")
        validity = "not validated" if vres is None else ("valid" if vres.valid else "INVALID")
        header = f"Config: {n_total} params, {n_set} set, {n_inactive} inactive, {validity}"
    else:
        # Neither status nor per-instance structure narrows further than
        # the raw config itself; every row falls back to its declared
        # template, one row per parameter rather than one per instance.
        for path in space.params:
            depth_label = templates[path][1]
            label = "  " * templates[path][0] + depth_label
            pd = space.params[path]
            if path in flat:
                word = "set"
                container = _container_body(pd, flat, path)
                body = container if container is not None else _value_body(flat[path])
            else:
                word = "unknown"
                body = "unknown" if "status" in cols else ""
            when = ""
            if "when" in cols and pd.condition is not None:
                when = f"when {render_expr(pd.condition)}"
            rows.append((word, _ConfigRow(label, body, "", when)))
        n_total = len(rows)
        n_set = sum(1 for word, _row in rows if word == "set")
        header = f"Config: {n_total} params, {n_set} set, not validated"

    # Sized from every row, not just the kept ones: a filter selects rows,
    # and must not reflow the alignment of the rows it keeps by changing
    # which label is the widest.
    label_width = max((len(row.label) for _word, row in rows), default=0)
    _size_domains([row for _word, row in rows], width=width, label_width=label_width)
    kept = [row for word, row in rows if word in keep]
    hidden_counts: dict[str, int] = {}
    for word, _row in rows:
        if word not in keep:
            hidden_counts[word] = hidden_counts.get(word, 0) + 1

    lines = [header, *_emit_config_rows(kept, width=width, label_width=label_width)]
    for word in sorted(hidden_counts):
        lines.append(f"  ... {hidden_counts[word]} {word} not shown")

    if vres is not None and "constraints" in cols and vres.constraint_evals:
        lines.append("")
        kw = max(len(ce.constraint.kind) for ce in vres.constraint_evals)
        for ce in vres.constraint_evals:
            lines.extend(_constraint_lines(ce, lead_width=kw, width=width))

    return "\n".join(lines)
