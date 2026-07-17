"""Shared expression checks: row 6 (undeclared refs) and row 14 (arithmetic /
ordering type errors) — API_v3.md's error table.

Used both for `.when()` conditions (resolve/_pipeline.py, M1) and for
`.forbid()`/`.constrain()` expressions (resolve/_constraints.py, M2): both
walk a `BoolExpr`/`Expr` tree against a `path -> definition` mapping, where
the mapping may hold either builder-time `ParamExpr`s (fresh `ds.space()`)
or resolved `ParamDef`s (a constraint added to an already-resolved `Space`)
— both expose `.type_kind`/`.domain`, so the checks are identical either way.

`context` is a pre-formatted, already-quoted description of where the
expression came from — `"param 'x'"` for a condition, `"forbid()"` for a
feasibility constraint — prefixed onto each message.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from designspace.build._paramexpr import ParamExpr
from designspace.errors import ResolutionError
from designspace.expr import ArithOp, Compare, Expr
from designspace.ir import OrdinalDomain


def iter_nodes(node: Expr) -> Iterator[Expr]:
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def check_refs_declared(expr: Expr, defs_by_path: Mapping[str, Any], *, context: str) -> None:
    for path in expr.params:
        if path not in defs_by_path:
            raise ResolutionError(f"{context}: references undeclared param {path!r}")


def check_expr_types(expr: Expr, defs_by_path: Mapping[str, Any], *, context: str) -> None:
    for node in iter_nodes(expr):
        if isinstance(node, ArithOp):
            for path in node.params:
                kind = defs_by_path[path].type_kind
                if kind in ("categorical", "ordinal"):
                    raise ResolutionError(
                        f"{context}: performs arithmetic on {kind} "
                        f"param {path!r}, which supports comparison only"
                    )
        elif isinstance(node, Compare):
            if node.op in ("gt", "lt", "ge", "le"):
                for path in node.params:
                    kind = defs_by_path[path].type_kind
                    if kind == "categorical":
                        raise ResolutionError(
                            f"{context}: orders categorical param "
                            f"{path!r} (categoricals support only ==, !=, is_in)"
                        )
            left, right = node.left, node.right
            if (
                isinstance(left, ParamExpr)
                and isinstance(right, ParamExpr)
                and defs_by_path[left.path].type_kind == "ordinal"
                and defs_by_path[right.path].type_kind == "ordinal"
            ):
                left_domain = defs_by_path[left.path].domain
                right_domain = defs_by_path[right.path].domain
                if (
                    isinstance(left_domain, OrdinalDomain)
                    and isinstance(right_domain, OrdinalDomain)
                    and left_domain.values != right_domain.values
                ):
                    raise ResolutionError(
                        f"{context}: compares ordinals {left.path!r} and "
                        f"{right.path!r}, which declare different value sequences"
                    )
