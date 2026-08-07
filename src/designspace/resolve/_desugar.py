"""Resolution step 3: desugar (API.md, "Resolution").

`implies` is the only construct this step rewrites. `expr.implies(other)`
builds a distinct `Implies` node and keeps it through construction, so that
`.kind` reports what the author wrote. This pass rewrites it to
`~expr | other`, after which the Kleene evaluator sees only `BoolOp` and
`Not`. `log_scale` leaves nothing to desugar, being applied as a prior at
the builder.

`Implies` nests only inside another `BoolExpr`, that is inside `BoolOp`,
`Not`, or an operand of `Count`. An `ArithExpr` tree never contains a
`BoolExpr` subterm, so walking the boolean trees reaches every occurrence.
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
