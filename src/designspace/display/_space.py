"""Rendering a `Space`, a `ParamDef`, and a `ParamExpr` (API.md,
"Human-Readable Rendering").

`_walk` recurses over the space's own declared structure the way
`config/_flatten.py` recurses over a config, but with no value to branch
on: a struct always descends, a choice descends into every payload-bearing
variant rather than one selected at a value, and a lift descends into its
element template. `Space._direct_children`, the traversal primitive every
space-guided walker already shares, drives it.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from designspace.display._columns import DEFAULT_SPACE_COLUMNS, SPACE_COLUMNS, resolve_columns
from designspace.display._domain import render_domain
from designspace.display._expr import render_expr
from designspace.display._values import WIDTH, render_elidable, render_value
from designspace.ir import ChoiceDomain, Condition, Constraint, ListDomain, ParamDef
from designspace.ir._priors import Log, Logit, Power, Weights
from designspace.paths._grammar import element_prefix
from designspace.resolve._relocate import element_paramdef

if TYPE_CHECKING:
    from designspace.builder._paramexpr import ParamExpr
    from designspace.builder._space import Space


def render_prior(prior: Any) -> str:
    if prior is None:
        return ""
    if isinstance(prior, Log):
        return "log"
    if isinstance(prior, Logit):
        return "logit"
    if isinstance(prior, Power):
        return f"power({render_value(prior.p)})"
    if isinstance(prior, Weights):
        return "weights" + render_elidable(
            [render_value(v) for v in prior.values], open="(", close=")"
        )
    return type(prior).__name__.lower()


def render_quantized(q: Any) -> str:
    if q.step is not None:
        inner = f"step={render_value(q.step)}"
    else:
        inner = f"factor={render_value(q.factor)}"
    if q.include_hi:
        inner += ", include_hi"
    return f"quantized({inner})"


def _quantized_tail(q: Any) -> str:
    if q.step is not None:
        return f"step={render_value(q.step)}"
    return f"factor={render_value(q.factor)}"


def _kind_label(type_kind: str | None) -> str:
    if type_kind is None:
        return "?"
    return "struct" if type_kind == "space" else type_kind


def _default_tail(default: Any, type_kind: str | None) -> str | None:
    if default is None:
        return None
    if type_kind in ("symbolic", "code"):
        return f"default=<{type_kind}>"
    text = render_value(default)
    if len(text) > 24:
        text = text[:21] + "\N{HORIZONTAL ELLIPSIS}"
    return f"default={text}"


def _modifiers(
    *,
    prior: Any,
    quantized: Any,
    periodic: bool,
    default: Any,
    type_kind: str | None,
    tags: frozenset[str] = frozenset(),
    columns: frozenset[str] = DEFAULT_SPACE_COLUMNS,
) -> list[str]:
    tokens = []
    if "prior" in columns:
        if prior is not None:
            tokens.append(render_prior(prior))
        if quantized is not None:
            tokens.append(_quantized_tail(quantized))
        if periodic:
            tokens.append("periodic")
    if "default" in columns:
        tail = _default_tail(default, type_kind)
        if tail is not None:
            tokens.append(tail)
    if "tags" in columns and tags:
        tokens.append("tags=" + render_elidable(sorted(tags), open="{", close="}"))
    return tokens


def render_param_def(
    pd: ParamDef, *, width: int = WIDTH, columns: str | Iterable[str] | None = None
) -> str:
    """A parameter definition on its own, outside a space's table."""
    cols = resolve_columns(columns, SPACE_COLUMNS, DEFAULT_SPACE_COLUMNS)
    parts = [f"{pd.path}:"]
    if "kind" in cols:
        parts.append(_kind_label(pd.type_kind))
    if "domain" in cols:
        parts.append(render_domain(pd.domain, budget=width))
    text = " ".join(parts)
    tokens = _modifiers(
        prior=pd.prior,
        quantized=pd.quantized,
        periodic=pd.periodic,
        default=pd.default,
        type_kind=pd.type_kind,
        tags=pd.tags,
        columns=cols,
    )
    if "when" in cols and pd.condition is not None:
        tokens.append(f"when {render_expr(pd.condition)}")
    return f"{text} {' '.join(tokens)}".rstrip() if tokens else text


def render_param_expr(
    pe: ParamExpr, *, width: int = WIDTH, columns: str | Iterable[str] | None = None
) -> str:
    """A parameter expression: its declaration if a type has been chosen,
    a bare reference otherwise."""
    if pe.domain is None:
        return f"param({pe.path!r})"
    cols = resolve_columns(columns, SPACE_COLUMNS, DEFAULT_SPACE_COLUMNS)
    parts = [f"param({pe.path!r}):"]
    if "kind" in cols:
        parts.append(_kind_label(pe.type_kind))
    if "domain" in cols:
        parts.append(render_domain(pe.domain, budget=width))
    text = " ".join(parts)
    tokens = _modifiers(
        prior=pe.prior_spec,
        quantized=pe.quantized_spec,
        periodic=pe.periodic,
        default=pe.default_value,
        type_kind=pe.type_kind,
        tags=pe.tags,
        columns=cols,
    )
    if "when" in cols and pe.condition is not None:
        tokens.append(f"when {render_expr(pe.condition)}")
    return f"{text} {' '.join(tokens)}".rstrip() if tokens else text


def render_condition(condition: Condition) -> str:
    return f"{condition.target} when {render_expr(condition.expr)}"


def render_constraint(constraint: Constraint) -> str:
    return f"{constraint.kind}  {render_expr(constraint.expr)}"


class _Row:
    __slots__ = ("domain", "kind", "label", "tokens", "when")

    def __init__(
        self,
        label: str,
        kind: str,
        domain: str = "",
        tokens: list[str] | None = None,
        when: str = "",
    ) -> None:
        self.label = label
        self.kind = kind
        self.domain = domain
        self.tokens = tokens or []
        self.when = when


def _walk(
    space: Space, prefix: str, depth: int, label_prefix: str, suppress: str | None
) -> Iterator[tuple[str, ParamDef, int, str, str | None]]:
    for path in space._direct_children(prefix):
        pd = space.params[path]
        local = path[len(prefix) :]
        yield path, pd, depth, label_prefix + local, suppress
        if pd.type_kind == "space":
            yield from _walk(space, f"{path}.", depth + 1, "", None)
        elif pd.type_kind == "choice" and isinstance(pd.domain, ChoiceDomain):
            for variant in pd.domain.variants:
                if variant not in pd.domain.has_payload:
                    continue
                yield from _walk(
                    space,
                    f"{path}.{variant}.",
                    depth + 1,
                    f"{variant}.",
                    f"{path} == {variant!r}",
                )
        elif pd.type_kind == "list":
            yield from _walk(space, element_prefix(path), depth + 1, "[].", None)
            # A lifted choice's payload fields are bucketed one level below
            # the element itself (`p[].mutation.rate`, not a child of
            # `p[].`), because the element's own `ParamDef` is synthesized
            # rather than stored: `space.params` never holds `p[]`. Descend
            # into it the same way a bare choice does, off the synthesized
            # element definition.
            if isinstance(pd.domain, ListDomain):
                element = element_paramdef(f"{path}[]", pd.domain)
                if element.type_kind == "choice" and isinstance(element.domain, ChoiceDomain):
                    for variant in element.domain.variants:
                        if variant not in element.domain.has_payload:
                            continue
                        yield from _walk(
                            space,
                            f"{path}[].{variant}.",
                            depth + 1,
                            f"[].{variant}.",
                            f"{path}[] == {variant!r}",
                        )


def _build_rows(space: Space, *, budget: int, columns: frozenset[str]) -> list[_Row]:
    """Every row, domain text included, elided to fit `budget`.

    Two passes over the same walk: the first collects everything that does
    not need a width decision (label, kind, tokens, `when`), sized from
    which is the lead and tail width every row's domain column has to fit
    around; the second renders each domain with the budget that leaves,
    so a param with a long path never starves one with a short path of
    room its own domain did not need. `_emit_rows` never truncates what
    comes out of this pass: elision happens once, here, with full
    knowledge of the surrounding columns.
    """
    partial: list[tuple[ParamDef, _Row, str]] = []
    for _path, pd, depth, label, suppress in _walk(space, "", 0, "", None):
        when = ""
        if "when" in columns and pd.condition is not None:
            rendered = render_expr(pd.condition)
            if rendered != suppress:
                when = f"when {rendered}"
        tokens = _modifiers(
            prior=pd.prior,
            quantized=pd.quantized,
            periodic=pd.periodic,
            default=pd.default,
            type_kind=pd.type_kind,
            tags=pd.tags,
            columns=columns,
        )
        kind_label = _kind_label(pd.type_kind)
        row = _Row(
            "  " * depth + label,
            kind_label if "kind" in columns else "",
            tokens=tokens,
            when=when,
        )
        partial.append((pd, row, kind_label))

    if not partial:
        return []
    w0 = max(len(row.label) for _pd, row, _kind in partial)
    w1 = max(len(row.kind) for _pd, row, _kind in partial)
    lead_width = 2 + w0 + 2 + w1 + 2
    # The domain's own line, alone, is the binding constraint: a row whose
    # tail does not fit next to it falls back to a continuation line
    # (`_emit_rows`), which only needs `lead_width + domain <= budget`.
    # Reserving room for the tail here as well would let one row's long
    # `when` starve every other row's domain of width it does not need.
    domain_budget = max(budget - lead_width, 18)

    for pd, row, kind_label in partial:
        # A struct's kind is already named, by the kind column when it is
        # shown and by the row's own tree position otherwise; StructDomain's
        # own rendering would just repeat "struct" in the domain column too.
        if "domain" not in columns or kind_label == "struct":
            row.domain = ""
        else:
            row.domain = render_domain(pd.domain, budget=domain_budget)
    return [row for _pd, row, _kind in partial]


def _emit_rows(rows: list[_Row], *, width: int) -> list[str]:
    if not rows:
        return []
    w0 = max(len(r.label) for r in rows)
    w1 = max(len(r.kind) for r in rows)
    lead_width = 2 + w0 + 2 + w1 + 2
    tails = ["  ".join(t for t in (" ".join(r.tokens), r.when) if t) for r in rows]

    lines = []
    for row, tail in zip(rows, tails, strict=True):
        lead = f"  {row.label:<{w0}}  {row.kind:<{w1}}  "
        if not tail:
            lines.append((lead + row.domain).rstrip())
        # Whether the tail fits is decided from this row's own domain
        # length, not a width shared across every row: one param with an
        # unusually wide domain must not push every other row's tail onto
        # a continuation line it never needed.
        elif lead_width + len(row.domain) + 2 + len(tail) <= width:
            lines.append(f"{lead}{row.domain}  {tail}")
        else:
            lines.append((lead + row.domain).rstrip())
            lines.append(" " * lead_width + tail)
    return lines


def _constraint_lines(
    constraint: Constraint, *, lead_width: int, width: int, indent: str = "  "
) -> list[str]:
    lead = f"{indent}{constraint.kind:<{lead_width}}  "
    body = render_expr(constraint.expr)
    if len(lead) + len(body) <= width:
        return [lead + body]
    wrapped = textwrap.wrap(
        body, width=max(width - len(lead), 20), break_long_words=False, break_on_hyphens=False
    )
    return [lead + wrapped[0], *(" " * len(lead) + w for w in wrapped[1:])]


def render_constraint_wrapped(constraint: Constraint, *, width: int = WIDTH) -> str:
    """A single constraint, standalone, wrapped to `width` past the point
    `render_constraint`'s own one-line form would overrun it. The one-line
    case is byte-identical to `render_constraint`, so `pretty` and `str`
    never disagree on a constraint that fits."""
    return "\n".join(
        _constraint_lines(constraint, lead_width=len(constraint.kind), width=width, indent="")
    )


def render_space(
    space: Space,
    *,
    width: int = WIDTH,
    max_rows: int = 40,
    max_constraints: int = 8,
    columns: str | Iterable[str] | None = None,
) -> str:
    """Render a space: one row per parameter, then its constraints."""
    cols = resolve_columns(columns, SPACE_COLUMNS, DEFAULT_SPACE_COLUMNS)
    n_cond = sum(1 for pd in space.params.values() if pd.condition is not None)
    header = (
        f"Space: {len(space.params)} params, {n_cond} conditional, "
        f"{len(space.constraints)} constraints"
    )

    rows = _build_rows(space, budget=width, columns=cols)
    shown, hidden = rows[:max_rows], rows[max_rows:]
    lines = [header, *_emit_rows(shown, width=width)]
    if hidden:
        lines.append(f"  ... and {len(hidden)} more")

    if space.constraints and "constraints" in cols:
        lines.append("")
        shown_c = space.constraints[:max_constraints]
        kw = max(len(c.kind) for c in shown_c)
        for c in shown_c:
            lines.extend(_constraint_lines(c, lead_width=kw, width=width))
        if len(space.constraints) > max_constraints:
            lines.append(f"  ... and {len(space.constraints) - max_constraints} more")

    if space.anchors:
        lines.append(f"  anchors: {', '.join(space.anchors)}")

    return "\n".join(lines)
