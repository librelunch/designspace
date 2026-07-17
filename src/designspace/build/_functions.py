"""`ds.param` / `ds.space` (API_v3.md, "Construction")."""

from __future__ import annotations

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.resolve import resolve_space


def param(name: str) -> ParamExpr:
    return ParamExpr(path=name)


def space(*exprs: ParamExpr) -> Space:
    return resolve_space(exprs)
