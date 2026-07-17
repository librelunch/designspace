"""Resolution step 3: desugar (API_v3.md, "Resolution").

Only `implies` needs a rewrite pass in the flat-scalar/Kleene world M2 adds:
`expr.implies(other)` was preserved as a distinct `Implies` node through
construction (DECISIONS.md D-1) and is rewritten here to `~expr | other` so
the Kleene evaluator (eval/) only ever sees `BoolOp`/`Not`. `log_scale`
already resolved eagerly at the builder (D-2); layer folding arrives with
`.repeat()` (M4).

`Implies` can only nest inside other `BoolExpr` trees (`BoolOp`, `Not`,
`Count`'s operands) — `ArithExpr` trees (`Compare`/`IsIn` operands, `ArithOp`)
can never contain a `BoolExpr` subterm, so only `BoolExpr` trees need walking.
"""

from __future__ import annotations

from designspace.expr import BoolExpr, BoolOp, Implies, Not


def desugar_bool(expr: BoolExpr) -> BoolExpr:
    if isinstance(expr, Implies):
        return BoolOp("or", Not(desugar_bool(expr.left)), desugar_bool(expr.right))
    if isinstance(expr, BoolOp):
        return BoolOp(expr.op, desugar_bool(expr.left), desugar_bool(expr.right))
    if isinstance(expr, Not):
        return Not(desugar_bool(expr.operand))
    return expr
