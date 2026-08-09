"""Rendering a domain (API.md, "Human-Readable Rendering" and "IR").

One function per row of the type table, matched by `isinstance` against the
public `Domain` union. A bound that is an `ArithExpr` (an expression-bounded
real or integer domain) renders through `render_expr`, so `[1, n_stops]`
reads the same as any other reference.
"""

from __future__ import annotations

from typing import Any

from designspace.display._expr import render_expr
from designspace.display._values import WIDTH, render_elidable, render_value
from designspace.expr import Expr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    CodeDomain,
    CustomDomain,
    Domain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    PermutationDomain,
    RealDomain,
    StructDomain,
    SubsetDomain,
    SymbolicDomain,
)


def _bound(value: Any) -> str:
    return render_expr(value) if isinstance(value, Expr) else render_value(value)


def render_signature(sig: Any) -> str:
    if sig is None:
        return "()"
    args = ", ".join(f"{name}: {kind}" for name, kind in sig.args.items())
    return f"({args}) -> {sig.returns}"


def _primitive_name(p: Any) -> str:
    name = getattr(p, "name", None)
    return name if name is not None else str(p)


def _remaining(budget: int, *fixed_parts: str) -> int:
    """`budget` minus the literal template text already spent, floored so
    an elidable call is never handed a negative budget. Left tight rather
    than padded to some working minimum: `render_elidable` degrades
    gracefully to a bare `"+n more"` under a small budget, and padding
    here would just let that overflow the caller's own budget instead."""
    return max(budget - sum(len(p) for p in fixed_parts), 1)


def render_domain(domain: Domain, *, budget: int = WIDTH) -> str:
    """Render one domain's declared shape, without any value.

    Parameters
    ----------
    domain : Domain
        The domain to render.
    budget : int
        Column budget for the *whole* returned string, template text
        included: each branch below reserves room for its own wrapping
        text (`"subset of "`, `", size 1..4"`, and so on) before eliding
        the sequence inside it, so the returned string as a whole
        respects `budget` rather than only the elided part of it.
    """
    if isinstance(domain, RealDomain | IntegerDomain):
        return f"[{_bound(domain.lo)}, {_bound(domain.hi)}]"
    if isinstance(domain, CategoricalDomain):
        return render_elidable(
            [render_value(v) for v in domain.values], open="{", close="}", budget=budget
        )
    if isinstance(domain, OrdinalDomain):
        items = render_elidable(
            [render_value(v) for v in domain.values],
            open="",
            close="",
            budget=_remaining(budget, "()"),
            sep=" < ",
        )
        return f"({items})"
    if isinstance(domain, BoolDomain):
        return "{False, True}"
    if isinstance(domain, SubsetDomain):
        hi = domain.max_size if domain.max_size is not None else len(domain.items)
        tail = f", size {domain.min_size}..{hi}"
        items = render_elidable(
            [render_value(v) for v in domain.items],
            open="{",
            close="}",
            budget=_remaining(budget, "subset of ", tail),
        )
        return f"subset of {items}{tail}"
    if isinstance(domain, PermutationDomain):
        items = render_elidable(
            [render_value(v) for v in domain.items],
            open="{",
            close="}",
            budget=_remaining(budget, "ordering of "),
        )
        return f"ordering of {items}"
    if isinstance(domain, ChoiceDomain):
        labels = [f"{v}(...)" if v in domain.has_payload else v for v in domain.variants]
        variants = render_elidable(labels, open="", close="", budget=_remaining(budget, "one of "))
        return f"one of {variants}"
    if isinstance(domain, StructDomain):
        return "struct"
    if isinstance(domain, CustomDomain):
        if domain.param_type is not None:
            key = getattr(domain.param_type, "type_key", type(domain.param_type).__name__)
            try:
                described = domain.param_type.describe()
            except Exception:
                described = {}
            fields = render_elidable(
                [f"{k}={render_value(v)}" for k, v in described.items()],
                open="",
                close="",
                budget=_remaining(budget, str(key), "()"),
            )
            return f"{key}({fields})"
        return "custom(sampler)"
    if isinstance(domain, SymbolicDomain):
        sig = render_signature(domain.signature)
        depth = f", depth<={domain.max_depth}, "
        primitives = render_elidable(
            [_primitive_name(p) for p in domain.primitives],
            open="",
            close="",
            budget=_remaining(budget, sig, depth),
        )
        return f"{sig}{depth}{primitives}"
    if isinstance(domain, CodeDomain):
        return f"code {render_signature(domain.signature)}"
    if isinstance(domain, ListDomain):
        count = _bound(domain.count)
        element = "struct" if domain.element_kind == "space" else domain.element_kind
        head = f"count = {count}, of " + ("" if element == "struct" else f"{element} ")
        inner = render_domain(domain.element_domain, budget=_remaining(budget, head))
        return f"{head}{inner}"
    return type(domain).__name__
