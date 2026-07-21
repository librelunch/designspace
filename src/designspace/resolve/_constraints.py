"""`.forbid()` / `.require()` / `.encourage()` / `.discourage()`: adding
constraints to an already-resolved `Space` (API.md, "Constraints and
Feasibility"). Two polarity pairs: hard `forbid`/`require` (affect
feasibility), soft `encourage`/`discourage` (declared, reported, never
affect feasibility).

Each positional condition becomes its own `Constraint` entry (sharing the
call's `tags`/`meta`) so `evaluate_constraints` reports a margin per
declared predicate rather than one folded blob. Validation reuses the same
row-6/row-14 checks conditions get (resolve/_expr_checks.py), against the
space's resolved `ParamDef`s rather than builder-time `ParamExpr`s, and
desugars `implies` (D-1) the same way step 3 does.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from designspace.build._names import check_meta_json_serializable
from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.errors import ResolutionError
from designspace.expr import BoolExpr, Compare
from designspace.ir import Constraint, ParamDef
from designspace.resolve._desugar import desugar_bool
from designspace.resolve._expr_checks import check_expr_types, check_refs_declared, iter_nodes


def add_constraints(
    space: Space,
    exprs: tuple[BoolExpr, ...],
    *,
    hard: bool,
    tags: tuple[str, ...],
    meta: dict[str, Any] | None,
    origin: str = "user",
) -> Space:
    # The four builder verbs are two polarity pairs — hard `forbid`/`require`
    # and soft `discourage`/`encourage` — distinguished by `(origin, hard)`.
    # `require`/`discourage` store the polarity-opposite predicate from their
    # sibling and carry a non-`user` origin; the feasibility flip and the
    # fingerprint canonicalization to forbidden-state form live downstream
    # (eval/_constraint_eval.py, identity/_ir_codec.py).
    call = {"require": "require()", "discourage": "discourage()"}.get(
        origin, "forbid()" if hard else "encourage()"
    )
    _check_tags_meta(call, tags, meta)
    meta_map = MappingProxyType(dict(meta or {}))
    tag_set = frozenset(tags)

    new_constraints = []
    for expr in exprs:
        if not isinstance(expr, BoolExpr):
            raise TypeError(f"{call} requires BoolExpr conditions, got {type(expr).__name__}")
        context = f"{call} condition {expr.kind!r}"
        check_refs_declared(expr, space.params, context=context)
        check_expr_types(expr, space.params, context=context)
        desugared = desugar_bool(expr)
        _warn_if_continuous_equality(desugared, space.params)
        new_constraints.append(
            Constraint(
                expr=desugared,
                hard=hard,
                origin=origin,
                tags=tag_set,
                meta=meta_map,
                params=desugared.params,
            )
        )
    return replace(space, constraints=space.constraints + tuple(new_constraints))


def _check_tags_meta(call: str, tags: tuple[str, ...], meta: dict[str, Any] | None) -> None:
    if "" in tags:
        raise ResolutionError(f"{call}: empty-string tags are not allowed")
    check_meta_json_serializable(meta or {}, what=call)


def _references_unquantized_real(node: Any, defs_by_path: Mapping[str, ParamDef]) -> bool:
    for n in iter_nodes(node):
        if isinstance(n, ParamExpr):
            d = defs_by_path[n.path]
            if d.type_kind == "real" and d.quantized is None:
                return True
    return False


def _warn_if_continuous_equality(expr: BoolExpr, defs_by_path: Mapping[str, ParamDef]) -> None:
    """Row 25 (warning): `==` over purely continuous, unquantized operands is
    measure-zero under sampling. "Purely continuous" is read as: no operand
    of a discrete type (categorical/ordinal/bool/integer) participates, and
    at least one unquantized real does (see DECISIONS.md).
    """
    for node in iter_nodes(expr):
        if not (isinstance(node, Compare) and node.op == "eq"):
            continue
        leaves = [n for n in iter_nodes(node) if isinstance(n, ParamExpr)]
        if not leaves:
            continue
        kinds = {defs_by_path[leaf.path].type_kind for leaf in leaves}
        if kinds & {"categorical", "ordinal", "bool", "integer"}:
            continue
        if _references_unquantized_real(node.left, defs_by_path) or _references_unquantized_real(
            node.right, defs_by_path
        ):
            paths = sorted({leaf.path for leaf in leaves})
            warnings.warn(
                f"`==` constraint over continuous, unquantized param(s) {paths} is "
                "measure-zero under sampling; consider generative reparameterization "
                "or .custom()",
                UserWarning,
                stacklevel=3,
            )
