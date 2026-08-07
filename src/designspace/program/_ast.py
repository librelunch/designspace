"""AST structural validation for `.symbolic()`.

See API.md, "Parameter Types" > "Program".

Checks *value* membership of one AST node against a `SymbolicDomain`'s
declaration:

    node ::= {"op": name, "args": [node, ...]}   # primitive application
           | {"var": name}                       # name in signature.args
           | {"const": number}                   # within a declared literal's bounds

Five things are checked: vocabulary, admitting only a name this param
declared; arity, where a `Primitive` declares one; variable names; literal
bounds; and tree depth, a leaf being depth 1.

A tree is never evaluated, no evaluator shipping. Vocabulary checking here
is structural membership alone, the value-time counterpart of the open
declaration-time vocabulary row 15 permits.
"""

from __future__ import annotations

from typing import Any

from designspace.ir import SymbolicDomain
from designspace.program._support import FloatLiteral, IntLiteral, Primitive


def _find_primitive(primitives: Any, op: str) -> str | Primitive | None:
    for p in primitives:
        if isinstance(p, str) and p == op:
            return p
        if isinstance(p, Primitive) and p.name == op:
            return p
    return None


def _within_any_literal(primitives: Any, value: Any) -> bool:
    for p in primitives:
        if isinstance(p, FloatLiteral) and p.lo <= value <= p.hi:
            return True
        if (
            isinstance(p, IntLiteral)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and p.lo <= value <= p.hi
        ):
            return True
    return False


def ast_error(domain: SymbolicDomain, node: Any, *, depth: int = 1) -> str | None:
    """A `validate()`-style reason string (`"wrong_type"` for a malformed
    shape, `"out_of_bounds"` for a declared-vocabulary/arity/literal/depth
    violation) or `None` when `node` is valid against `domain`."""
    if not isinstance(node, dict):
        return "wrong_type"
    if depth > domain.max_depth:
        return "out_of_bounds"
    if "op" in node:
        op = node["op"]
        args = node.get("args")
        if not isinstance(op, str) or not isinstance(args, list):
            return "wrong_type"
        declared = _find_primitive(domain.primitives, op)
        if declared is None:
            return "out_of_bounds"
        if isinstance(declared, Primitive):
            lo, hi = declared.arity_range
            n = len(args)
            if n < lo or (hi is not None and n > hi):
                return "out_of_bounds"
        for arg in args:
            reason = ast_error(domain, arg, depth=depth + 1)
            if reason is not None:
                return reason
        return None
    if "var" in node:
        name = node["var"]
        if not isinstance(name, str):
            return "wrong_type"
        if name not in domain.signature.args:
            return "out_of_bounds"
        return None
    if "const" in node:
        value = node["const"]
        if not isinstance(value, int | float) or isinstance(value, bool):
            return "wrong_type"
        if not _within_any_literal(domain.primitives, value):
            return "out_of_bounds"
        return None
    return "wrong_type"
