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
from typing import Any, cast

from designspace.build._paramexpr import ParamExpr
from designspace.errors import ResolutionError
from designspace.expr import ArithOp, Compare, Contains, Expr, PositionOf, Size, SumOver
from designspace.ir import OrdinalDomain, PermutationDomain, SubsetDomain


def iter_nodes(node: Expr) -> Iterator[Expr]:
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def _referenced_domain(node: Any, defs_by_path: Mapping[str, Any], *, context: str) -> Any:
    if not isinstance(node, ParamExpr):
        raise ResolutionError(
            f"{context}: expects a bare param reference, got {node.kind!r}"
        )
    return defs_by_path[node.path].domain


def _require_subset_domain(
    node: Any, defs_by_path: Mapping[str, Any], *, context: str, what: str
) -> SubsetDomain:
    domain = _referenced_domain(node, defs_by_path, context=context)
    if not isinstance(domain, SubsetDomain):
        raise ResolutionError(
            f"{context}: {what} on {node.path!r}, which is not a subset param"
        )
    return domain


def _require_permutation_domain(
    node: Any, defs_by_path: Mapping[str, Any], *, context: str
) -> PermutationDomain:
    domain = _referenced_domain(node, defs_by_path, context=context)
    if not isinstance(domain, PermutationDomain):
        raise ResolutionError(
            f"{context}: position_of() on {node.path!r}, which is not a permutation param"
        )
    return domain


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
        elif isinstance(node, Contains):
            _require_subset_domain(node.operand, defs_by_path, context=context, what="contains()")
        elif isinstance(node, Size):
            _require_subset_domain(node.operand, defs_by_path, context=context, what="size()")
        elif isinstance(node, SumOver):
            subset_domain = _require_subset_domain(
                node.operand, defs_by_path, context=context, what="sum_over()"
            )
            universe = set(subset_domain.items)
            bad_keys = sorted(set(node.mapping.keys()) - universe, key=repr)
            if bad_keys:
                operand_path = cast(ParamExpr, node.operand).path
                raise ResolutionError(
                    f"{context}: sum_over() mapping has keys {bad_keys!r} outside "
                    f"the item universe of {operand_path!r}"
                )
        elif isinstance(node, PositionOf):
            perm_domain = _require_permutation_domain(node.operand, defs_by_path, context=context)
            if node.item not in perm_domain.items:
                operand_path = cast(ParamExpr, node.operand).path
                raise ResolutionError(
                    f"{context}: position_of({node.item!r}) on {operand_path!r} "
                    "is not a declared member"
                )
