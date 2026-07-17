"""eval: Kleene evaluation, activity, and margins (API_v3.md, "Expressions" >
"Three-valued semantics"; "Constraints and Feasibility" > "Margins").

Internal machinery consumed by validate/ and sample/ — not part of the
public surface (the public result types, `ConstraintEval`/`ValidationResult`,
live in ir/).
"""

from designspace.eval._constraint_eval import evaluate_constraint, is_violated
from designspace.eval._kleene import (
    UNKNOWN,
    Kleene,
    Unknown,
    compute_activity,
    evaluate_arith,
    evaluate_bool,
    topological_order,
)
from designspace.eval._margins import margin

__all__ = [
    "UNKNOWN",
    "Kleene",
    "Unknown",
    "compute_activity",
    "evaluate_arith",
    "evaluate_bool",
    "evaluate_constraint",
    "is_violated",
    "margin",
    "topological_order",
]
