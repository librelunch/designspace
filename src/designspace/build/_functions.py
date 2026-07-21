"""`ds.param` / `ds.space` (API.md, "Construction")."""

from __future__ import annotations

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.build._views import FreshParamExpr
from designspace.resolve import resolve_space


def param(name: str) -> FreshParamExpr:
    return FreshParamExpr(path=name)


def space(*exprs: ParamExpr) -> Space:
    return resolve_space(exprs)
